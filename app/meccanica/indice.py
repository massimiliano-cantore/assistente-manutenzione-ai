"""Indice meccanico degli articoli costruito dai file SolidWorks del PDM.

Per ogni codice (assieme, tavola, particolare): denominazione, date, stato, categoria (dalla cartella del PDM),
file, distinta (righe della tavola con la descrizione), sottogruppi e gruppi che lo contengono, codici articolo
di prodotto citati nella denominazione (es. "Gruppo elettropistone Prima 2460030 – 2560030"), immagini
(esploso della tavola, vista 3D).

Si salva in <Produzione1>/meccanica/indice.json; le immagini in <Produzione1>/meccanica/img/.
La lettura è incrementale: si rileggono solo i file nuovi o modificati (cache.json).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.meccanica.solidworks import CATEGORIE_PDM, ESTENSIONI, leggi

log = logging.getLogger(__name__)

CARTELLE_SALTATE = re.compile(r"(^|[\\/])(x_[^\\/]*|9\.[^\\/]*prova[^\\/]*|old|vecchi|obsoleti)([\\/]|$)", re.I)
ARTICOLO = re.compile(r"\b(\d{7})\b")
# parti elettriche riconosciute dall'inizio della descrizione ("Bobina Prima" sì, "Nucleo ... bobina" no)
PAROLE_ELETTRICHE = re.compile(r"^\s*(bobin|elettromagnet|circuit|scheda|sensor|reed|micro ?switch|microinterr|"
                               r"motor|cavo|cablaggio|led\b|alimentator|connettor|trasformator|finecorsa|"
                               r"interruttor|pulsant|elettronic)", re.I)


def _categoria(file: Path, radice: Path) -> str:
    try:
        prima = file.relative_to(radice).parts[0]
    except ValueError:
        return ""
    m = re.match(r"([A-Z])_", prima, re.I)
    return CATEGORIE_PDM.get(m[1].upper(), "") if m else ""


class IndiceMeccanico:
    def __init__(self, cartella_dati: Path):
        self.cartella = Path(cartella_dati) / "meccanica"
        self.articoli: dict[str, dict] = {}
        f = self.cartella / "indice.json"
        if f.exists():
            self.articoli = json.loads(f.read_text(encoding="utf-8"))
        self._per_prodotto: dict[str, list[str]] = {}
        self._padri: dict[str, list[str]] = {}       # anche per i codici senza file proprio nel PDM
        for cod, a in self.articoli.items():
            for r in a.get("distinta", []):
                self._padri.setdefault(r["codice"], []).append(cod)
            for p in a.get("prodotti", []):
                self._per_prodotto.setdefault(p, []).append(cod)

    # --- costruzione --------------------------------------------------------------------------------------------

    def aggiorna(self, pdm: Path, avanzamento=None) -> dict:
        pdm = Path(pdm)
        self.cartella.mkdir(parents=True, exist_ok=True)
        (self.cartella / "img").mkdir(exist_ok=True)
        f_cache = self.cartella / "cache.json"
        cache = json.loads(f_cache.read_text(encoding="utf-8")) if f_cache.exists() else {}
        nuova, letti, errori = {}, 0, 0
        for f in sorted(pdm.rglob("*")):
            if f.suffix.lower() not in ESTENSIONI or f.name.startswith("~$"):
                continue
            rel = f.relative_to(pdm)
            if CARTELLE_SALTATE.search(str(rel.parent)):
                continue
            chiave = str(rel)
            st = f.stat()
            vecchio = cache.get(chiave)
            if vecchio and vecchio["firma"] == [st.st_size, st.st_mtime]:
                nuova[chiave] = vecchio
                continue
            try:
                sw = leggi(f)
            except Exception as e:  # noqa: BLE001 - un file rovinato non ferma la scansione
                errori += 1
                log.warning("file SolidWorks non letto %s: %s", rel, e)
                continue
            immagini = []
            for k, png in enumerate(sw.anteprime[:2]):
                nome = f"{sw.codice}_{sw.tipo}_{k}.png".replace("/", "-")
                (self.cartella / "img" / nome).write_bytes(png)
                immagini.append(nome)
            nuova[chiave] = {"firma": [st.st_size, st.st_mtime], "tipo": sw.tipo, "codice": sw.codice,
                             "proprieta": sw.proprieta, "distinta": sw.distinta, "descrizioni": sw.descrizioni,
                             "componenti": sw.componenti, "immagini": immagini,
                             "categoria": _categoria(f, pdm), "percorso": str(f)}
            letti += 1
            if avanzamento and letti % 100 == 0:
                avanzamento(letti)
        f_cache.write_text(json.dumps(nuova, ensure_ascii=False), encoding="utf-8")
        self.articoli = self._componi(nuova)
        (self.cartella / "indice.json").write_text(json.dumps(self.articoli, ensure_ascii=False, indent=1),
                                                   encoding="utf-8")
        self.__init__(self.cartella.parent)
        n_assiemi = sum(1 for a in self.articoli.values() if a["distinta"])
        return {"file": len(nuova), "letti_ora": letti, "errori": errori, "codici": len(self.articoli),
                "con_distinta": n_assiemi}

    @staticmethod
    def _componi(file: dict) -> dict:
        art: dict[str, dict] = {}

        def voce(cod: str) -> dict:
            return art.setdefault(cod.upper(), {"codice": cod.upper(), "denominazione": "", "tipo": "", "categoria": "",
                                               "data": "", "stato": "", "autore": "", "file": {}, "distinta": [],
                                               "fonte_distinta": "", "immagini": {}, "prodotti": [], "padri": []})
        # prima parti e assiemi, poi tavole (la tavola ha la distinta "ufficiale")
        for d in sorted(file.values(), key=lambda d: {"parte": 0, "assieme": 1, "tavola": 2}[d["tipo"]]):
            a = voce(d["codice"])
            pr = d["proprieta"]
            a["denominazione"] = pr.get("DENOMINAZIONE") or a["denominazione"]
            a["data"] = pr.get("DATA") or a["data"]
            a["approvazione"] = pr.get("APPROVAZIONE_DATA") or a.get("approvazione", "")
            a["stato"] = pr.get("STATO") or a["stato"]
            a["autore"] = pr.get("COMPILATO_DA") or a["autore"]
            if pr.get("MATERIALE"):
                a["materiale"] = pr["MATERIALE"]
            if pr.get("TRATTAMENTO"):
                a["trattamento"] = pr["TRATTAMENTO"]
            a["categoria"] = a["categoria"] or d["categoria"]
            if d["tipo"] != "tavola" or not a["tipo"]:
                a["tipo"] = {"parte": "particolare", "assieme": "gruppo"}.get(d["tipo"], a["tipo"] or "tavola")
            a["file"][d["tipo"]] = d["percorso"]
            for img in d["immagini"]:
                a["immagini"].setdefault("tavola" if d["tipo"] == "tavola" else "3d", img)
            if d["tipo"] == "tavola" and d["distinta"]:
                descr = d["descrizioni"] if len(d["descrizioni"]) == len(d["distinta"]) else []
                a["distinta"] = [{"codice": c.upper(), "descrizione": descr[i] if descr else ""}
                                 for i, c in enumerate(d["distinta"])]
                a["fonte_distinta"] = "tavola"
            elif d["tipo"] == "assieme" and not a["distinta"]:
                a["_componenti_assieme"] = d["componenti"]
        noti = set(art)
        for a in art.values():      # assieme senza tavola: componenti che esistono nel PDM
            comp = a.pop("_componenti_assieme", None)
            if comp and not a["distinta"]:
                a["distinta"] = [{"codice": c.upper(), "descrizione": ""} for c in comp if c.upper() in noti]
                a["fonte_distinta"] = "assieme (riferimenti del file: da verificare)"
        for a in art.values():
            for r in a["distinta"]:
                figlio = art.get(r["codice"])
                if figlio:
                    r["descrizione"] = r["descrizione"] or figlio["denominazione"]
                    r["categoria"] = figlio["categoria"]
                    if a["codice"] not in figlio["padri"]:
                        figlio["padri"].append(a["codice"])
                r["elettrico"] = bool(r.get("categoria") == "elettronica"
                                      or PAROLE_ELETTRICHE.search(r["descrizione"]))
            a["prodotti"] = sorted(set(ARTICOLO.findall(a["denominazione"])))
        return art

    # --- consultazione ------------------------------------------------------------------------------------------

    def trova(self, testo: str) -> list[str]:
        """Codici che corrispondono a un codice disegno, a un articolo di prodotto o a parole della denominazione."""
        t = testo.strip().upper()
        if t in self.articoli or t in self._padri:
            return [t]
        if t in self._per_prodotto:
            return self._per_prodotto[t]
        parole = [w for w in re.findall(r"\w+", testo.lower()) if len(w) > 2]
        trovati = [c for c, a in self.articoli.items()
                   if parole and all(w in (a["denominazione"] + " " + c).lower() for w in parole)]
        return sorted(trovati, key=lambda c: (-len(self.articoli[c]["distinta"]), c))[:10]

    def radici(self, codice: str) -> list[str]:
        """Gruppi più in alto che contengono il codice."""
        visti, coda, out = set(), [codice], []
        while coda:
            c = coda.pop()
            if c in visti:
                continue
            visti.add(c)
            padri = self._padri.get(c, [])
            if not padri:
                out.append(c)
            coda += padri
        return out

    def esplodi(self, codice: str, livelli: int = 3) -> list[dict]:
        """Distinta su più livelli: [{livello, codice, descrizione, categoria, elettrico}]."""
        out = []

        def giu(c, liv, visti):
            for r in self.articoli.get(c, {}).get("distinta", []):
                out.append({"livello": liv, **r})
                if liv < livelli and r["codice"] not in visti:
                    giu(r["codice"], liv + 1, visti | {r["codice"]})
        giu(codice, 1, {codice})
        return out
