"""Servizio datasheet: trova il PDF (anche di un compatibile), estrae la piedinatura e la tiene in cache.

Piedinatura = per ogni pin: numero, nome, tipo (alimentazione, massa, ingresso, uscita, I/O, analogico, RF, clock,
non collegato) e funzione con il segnale atteso. Viene verificata contro la netlist: se il datasheet descrive pin
che il componente non ha, o ne manca qualcuno, lo si dice nella risposta.
"""
from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pypdfium2 as pdfium
from pydantic import BaseModel, Field

from app.datasheet.fonti import FonteMouser, FonteWeb, varianti

log = logging.getLogger(__name__)
MAX_PDF = 30 * 1024 * 1024
PAROLE_PIN = ("pin description", "pin descriptions", "pin function", "pin assignment", "pinout", "pin configuration",
              "pin no", "pin name", "pin #", "terminal functions", "pin definitions", "descrizione dei pin")
TIPI = ("alimentazione", "massa", "ingresso", "uscita", "ingresso/uscita", "analogico", "rf", "clock",
        "non collegato", "altro")


class Pin(BaseModel):
    numero: str = Field(description="numero del pin nel package indicato, come stringa (es. '14' o 'A3')")
    nome: str = Field(description="nome del pin nel datasheet (es. 'XC1', 'PA5', 'VDD')")
    tipo: str = Field(description=f"uno tra: {', '.join(TIPI)}")
    funzione: str = Field(description="funzione in italiano, breve, con il segnale atteso (tensione, frequenza, "
                                      "livello logico o protocollo) quando il datasheet lo indica")


class Piedinatura(BaseModel):
    package: str = Field(description="package a cui si riferiscono i numeri dei pin (es. 'QFN32', 'LQFP100')")
    pin: list[Pin]


Estrattore = Callable[[str, str, int | None, str], Piedinatura]


def estrattore_llm(llm) -> Estrattore:
    """Estrazione strutturata con il modello linguistico (lo stesso dell'agente o uno locale)."""
    # Claude: uscita con schema JSON (la chiamata forzata a uno strumento non è supportata dai modelli recenti)
    metodo = "json_schema" if type(llm).__name__ == "ChatAnthropic" else "function_calling"
    strutturato = llm.with_structured_output(Piedinatura, method=metodo)

    def estrai(testo: str, codice: str, n_pin: int | None, package: str) -> Piedinatura:
        richiesta = (f"Questo è un estratto del datasheet di {codice}. Estrai la tabella dei pin "
                     f"{'per il package ' + package + ' ' if package else ''}"
                     f"{'(il componente montato ha ' + str(n_pin) + ' pin) ' if n_pin else ''}"
                     "con numero, nome, tipo e funzione in italiano. Se il datasheet ha più package, usa i numeri "
                     "di quello indicato. Non inventare: se un dato non c'è, lascia la funzione breve e generica.\n\n"
                     + testo)
        return strutturato.invoke(richiesta)
    return estrai


def testo_pagine(pdf: bytes) -> list[str]:
    doc = pdfium.PdfDocument(io.BytesIO(pdf))
    try:
        return [p.get_textpage().get_text_range() for p in doc]
    finally:
        doc.close()


def pagine_con_pin(pagine: list[str], massimo_caratteri: int = 60000) -> str:
    """Pagine con la tabella dei pin: parole chiave + molte righe che iniziano con un numero di pin."""
    punteggi = []
    for i, t in enumerate(pagine):
        tl = t.lower()
        righe_pin = len(re.findall(r"(?m)^\s*\d{1,3}\s+[A-Z][A-Z0-9_/]+", t))
        punteggi.append((sum(3 for k in PAROLE_PIN if k in tl) + min(righe_pin, 40) / 4, i))
    scelte = sorted(i for p, i in sorted(punteggi, reverse=True)[:6] if p > 0)
    # le tabelle dei pin continuano spesso nella pagina dopo
    estese = sorted({j for i in scelte for j in (i, i + 1) if j < len(pagine)})
    testo = ""
    for i in estese:
        blocco = f"\n--- pagina {i + 1} ---\n{pagine[i]}"
        if len(testo) + len(blocco) > massimo_caratteri:
            break
        testo += blocco
    return testo


class ServizioDatasheet:
    def __init__(self, cartella_cache: str | Path, fonti: list | None = None, estrattore: Estrattore | None = None,
                 http: httpx.Client | None = None):
        self.cache = Path(cartella_cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.fonti = [f for f in (fonti if fonti is not None else [FonteMouser(), FonteWeb()]) if f.disponibile]
        self.estrattore = estrattore
        self.http = http or httpx.Client(timeout=60, follow_redirects=True,
                                         headers={"User-Agent": "Mozilla/5.0 (assistente-manutenzione)"})

    def _file_cache(self, codice: str) -> Path:
        return self.cache / (re.sub(r"[^A-Za-z0-9._-]+", "_", codice.upper()) + ".json")

    def trova(self, codice: str) -> dict | None:
        """Datasheet del codice esatto; se non c'è, di un codice più generico (compatibile)."""
        if not self.fonti:
            raise RuntimeError("nessuna fonte di datasheet configurata: imposta MOUSER_API_KEY e/o TAVILY_API_KEY")
        for tentativo, compatibile in [(codice, False)] + [(v, True) for v in varianti(codice)]:
            for fonte in self.fonti:
                try:
                    candidati = fonte.cerca(tentativo)
                except Exception as e:
                    log.warning("ricerca %s su %s fallita: %s", tentativo, fonte.nome, e)
                    continue
                if candidati:
                    return {**candidati[0], "cercato": codice, "trovato_con": tentativo, "compatibile": compatibile}
        return None

    def scarica(self, url: str) -> bytes:
        if not url.startswith("http"):
            url = "https:" + url if url.startswith("//") else "https://" + url
        r = self.http.get(url)
        r.raise_for_status()
        dati = r.content
        if len(dati) > MAX_PDF or not dati.startswith(b"%PDF"):
            raise ValueError(f"il link non porta a un PDF utilizzabile: {url}")
        return dati

    def piedinatura(self, codice: str, n_pin: int | None = None, package: str = "", aggiorna: bool = False) -> dict:
        file = self._file_cache(codice)
        if file.exists() and not aggiorna:
            return json.loads(file.read_text(encoding="utf-8")) | {"da_cache": True}
        if self.estrattore is None:
            raise RuntimeError("estrattore della piedinatura non configurato")
        trovato = self.trova(codice)
        if not trovato:
            return {"codice": codice, "errore": "datasheet non trovato, nemmeno per un compatibile"}
        pdf = self.scarica(trovato["url"])
        testo = pagine_con_pin(testo_pagine(pdf))
        if not testo:
            return {"codice": codice, **trovato, "errore": "nel datasheet non ho trovato la tabella dei pin"}
        tabella = self.estrattore(testo, trovato.get("codice") or codice, n_pin, package)
        risultato = {"codice": codice, "fonte": trovato["fonte"], "url": trovato["url"],
                     "datasheet_di": trovato.get("codice"), "produttore": trovato.get("produttore", ""),
                     "compatibile": trovato["compatibile"], "ufficiale": trovato.get("ufficiale", False),
                     "package": tabella.package, "pin": [p.model_dump() for p in tabella.pin],
                     "estratto_il": datetime.now(UTC).isoformat(timespec="seconds")}
        file.write_text(json.dumps(risultato, ensure_ascii=False, indent=1), encoding="utf-8")
        return risultato | {"da_cache": False}


def confronta_con_netlist(piedinatura: dict, pin_montati: set[str]) -> dict:
    """Quanto la piedinatura estratta corrisponde ai pin reali del componente sulla scheda."""
    nel_datasheet = {str(p["numero"]).strip() for p in piedinatura.get("pin", [])}
    mancanti = sorted(pin_montati - nel_datasheet, key=lambda x: (len(x), x))
    in_piu = sorted(nel_datasheet - pin_montati, key=lambda x: (len(x), x))
    copertura = 1 - len(mancanti) / len(pin_montati) if pin_montati else 0
    return {"copertura": round(copertura, 2), "pin_senza_descrizione": mancanti[:20],
            "pin_del_datasheet_non_presenti": in_piu[:20]}
