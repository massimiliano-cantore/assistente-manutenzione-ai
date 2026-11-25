"""Accesso dei colleghi dalla rete aziendale: solo la ricerca documenti, con nome e password, e registro accessi.

- Dal PC dove gira il server (127.0.0.1) tutto è libero, come prima.
- Dagli altri PC si vedono solo /documenti e /api/documenti/*, dopo l'accesso; il resto (chat) risponde 403.
- Utenti in <Produzione1>/utenti_documenti.txt (nome:sale:hash), gestiti con scripts.utenti_documenti.
- Registro in <Produzione1>/accessi_documenti.csv: data e ora, utente, IP, azione, dettaglio (si apre con Excel).
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import html
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

LOCALI = {"127.0.0.1", "::1", "localhost"}
PERMESSI_REMOTI = ("/documenti", "/api/documenti/")
DURATA_SESSIONE = 12 * 3600
TENTATIVI_MAX, BLOCCO_S = 5, 300
COOKIE = "sessione_documenti"
_blocco = threading.Lock()


# --- utenti --------------------------------------------------------------------------------------------------------

def _hash(password: str, sale: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(sale), 200_000).hex()


def leggi_utenti(file: Path) -> dict[str, tuple[str, str]]:
    if not file.exists():
        return {}
    out = {}
    for riga in file.read_text(encoding="utf-8").splitlines():
        parti = riga.strip().split(":")
        if len(parti) == 3 and not riga.startswith("#"):
            out[parti[0].lower()] = (parti[1], parti[2])
    return out


def imposta_utente(file: Path, nome: str, password: str) -> None:
    utenti = leggi_utenti(file)
    sale = secrets.token_hex(16)
    utenti[nome.lower()] = (sale, _hash(password, sale))
    righe = ["# utenti della ricerca documenti: nome:sale:hash (NON modificare a mano, usa scripts.utenti_documenti)"]
    righe += [f"{n}:{s}:{h}" for n, (s, h) in sorted(utenti.items())]
    file.write_text("\n".join(righe) + "\n", encoding="utf-8")


def togli_utente(file: Path, nome: str) -> bool:
    utenti = leggi_utenti(file)
    if utenti.pop(nome.lower(), None) is None:
        return False
    righe = ["# utenti della ricerca documenti: nome:sale:hash (NON modificare a mano, usa scripts.utenti_documenti)"]
    righe += [f"{n}:{s}:{h}" for n, (s, h) in sorted(utenti.items())]
    file.write_text("\n".join(righe) + "\n", encoding="utf-8")
    return True


def verifica(file: Path, nome: str, password: str) -> bool:
    u = leggi_utenti(file).get(nome.strip().lower())
    return bool(u) and hmac.compare_digest(_hash(password, u[0]), u[1])


# --- registro ------------------------------------------------------------------------------------------------------

def registra(file: Path, utente: str, ip: str, azione: str, dettaglio: str = "") -> None:
    nuovo = not file.exists()
    with _blocco, file.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if nuovo:
            w.writerow(["data e ora", "utente", "IP", "azione", "dettaglio"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), utente, ip, azione, dettaglio[:300]])


# --- middleware ----------------------------------------------------------------------------------------------------

PAGINA_ACCESSO = """<!doctype html><html lang="it"><head><meta charset="utf-8"><title>Accesso</title>
<style>body{font-family:system-ui,sans-serif;background:#f6f7f9;display:flex;justify-content:center;padding-top:12vh}
form{background:#fff;padding:28px 32px;border-radius:10px;box-shadow:0 2px 10px #0001;width:300px}
h1{font-size:20px;margin:0 0 18px}input{width:100%;box-sizing:border-box;padding:10px;margin:6px 0 14px;
border:1px solid #ccc;border-radius:6px;font-size:15px}button{width:100%;padding:10px;border:0;border-radius:6px;
background:#1a73e8;color:#fff;font-size:15px;cursor:pointer}.err{color:#c5221f;font-size:14px;margin-bottom:10px}</style>
</head><body><form method="post" action="/accesso"><h1>Ricerca documenti</h1>{errore}
<label>Nome<input name="nome" autofocus autocomplete="username"></label>
<label>Password<input name="password" type="password" autocomplete="current-password"></label>
<input type="hidden" name="vai" value="{vai}"><button>Entra</button></form></body></html>"""


class AccessoDocumenti(BaseHTTPMiddleware):
    def __init__(self, app, cartella: Path):
        super().__init__(app)
        self.utenti = cartella / "utenti_documenti.txt"
        self.registro = cartella / "accessi_documenti.csv"
        f_segreto = cartella / ".segreto_sessioni"
        if not f_segreto.exists():
            f_segreto.write_text(secrets.token_hex(32), encoding="utf-8")
        self.segreto = bytes.fromhex(f_segreto.read_text(encoding="utf-8").strip())
        self.falliti: dict[str, list[float]] = {}

    def _firma(self, testo: str) -> str:
        return hmac.new(self.segreto, testo.encode(), hashlib.sha256).hexdigest()

    def _utente(self, request: Request) -> str | None:
        c = request.cookies.get(COOKIE, "")
        try:
            nome, scade, firma = c.rsplit("|", 2)
        except ValueError:
            return None
        if not hmac.compare_digest(firma, self._firma(f"{nome}|{scade}")) or float(scade) < time.time():
            return None
        return nome if nome in leggi_utenti(self.utenti) else None   # utente tolto: sessione non più valida

    def _pagina(self, vai: str, errore: str = "", stato: int = 200):
        e = f'<div class="err">{html.escape(errore)}</div>' if errore else ""
        return HTMLResponse(PAGINA_ACCESSO.replace("{errore}", e).replace("{vai}", html.escape(vai)), stato)

    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "?"
        if ip in LOCALI:
            return await call_next(request)
        percorso = request.url.path
        if percorso == "/accesso" and request.method == "POST":
            return await self._accedi(request, ip)
        if percorso == "/esci":
            r = RedirectResponse("/documenti", 303)
            r.delete_cookie(COOKIE)
            if u := self._utente(request):
                registra(self.registro, u, ip, "uscita")
            return r
        if not percorso.startswith(PERMESSI_REMOTI):
            return JSONResponse({"detail": "dagli altri PC è disponibile solo la ricerca documenti"}, 403)
        utente = self._utente(request)
        if not utente:
            if percorso.startswith("/api/"):
                return JSONResponse({"detail": "accesso richiesto"}, 401)
            return self._pagina(str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""))
        if percorso == "/api/documenti/cerca":
            registra(self.registro, utente, ip, "ricerca", request.query_params.get("q", ""))
        elif percorso == "/api/documenti/apri":
            registra(self.registro, utente, ip, "apertura", request.query_params.get("p", ""))
        return await call_next(request)

    async def _accedi(self, request: Request, ip: str):
        dati = {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8", "replace")).items()}
        nome, vai = dati.get("nome", "").strip().lower(), dati.get("vai", "/documenti")
        if not vai.startswith("/documenti"):
            vai = "/documenti"
        ora = time.time()
        recenti = [t for t in self.falliti.get(ip, []) if ora - t < BLOCCO_S]
        if len(recenti) >= TENTATIVI_MAX:
            registra(self.registro, nome, ip, "accesso bloccato", "troppi tentativi")
            return self._pagina(vai, "Troppi tentativi: riprova tra qualche minuto.", 429)
        if not verifica(self.utenti, nome, dati.get("password", "")):
            self.falliti[ip] = recenti + [ora]
            registra(self.registro, nome, ip, "accesso fallito")
            return self._pagina(vai, "Nome o password non corretti.", 401)
        self.falliti.pop(ip, None)
        registra(self.registro, nome, ip, "accesso")
        scade = str(int(ora + DURATA_SESSIONE))
        r = RedirectResponse(quote(vai, safe="/?=&%"), 303)
        r.set_cookie(COOKIE, f"{nome}|{scade}|{self._firma(f'{nome}|{scade}')}", max_age=DURATA_SESSIONE,
                     httponly=True, samesite="lax")
        return r
