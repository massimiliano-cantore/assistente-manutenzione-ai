"""Fonti dei datasheet: prima l'API ufficiale di Mouser, poi una ricerca web (Tavily) come ripiego.

Ogni fonte restituisce candidati {codice, produttore, descrizione, url, fonte, ufficiale}.
A internet arrivano solo codici di componenti, mai schemi o altri documenti dell'azienda.
"""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

# siti dei produttori e dei distributori: un datasheet da qui è considerato ufficiale
DOMINI_UFFICIALI = ("st.com", "ti.com", "nordicsemi.com", "analog.com", "microchip.com", "nxp.com", "infineon.com",
                    "onsemi.com", "vishay.com", "rohm.com", "renesas.com", "diodes.com", "murata.com", "we-online.com",
                    "simcom.com", "mouser.com", "mouser.it", "digikey.com", "farnell.com", "rs-online.com",
                    "lcsc.com", "silabs.com", "espressif.com", "maxlinear.com", "toshiba", "panasonic", "kemet.com",
                    "yageo.com", "littelfuse.com", "bourns.com", "molex.com", "te.com", "hirose.com", "amphenol")


def ufficiale(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(d in host for d in DOMINI_UFFICIALI)


class FonteMouser:
    nome = "mouser"
    URL = "https://api.mouser.com/api/v1/search"

    def __init__(self, chiave: str | None = None, http: httpx.Client | None = None):
        self.chiave = chiave or os.getenv("MOUSER_API_KEY")
        self.http = http or httpx.Client(timeout=20)

    @property
    def disponibile(self) -> bool:
        return bool(self.chiave)

    def _parti(self, percorso: str, corpo: dict) -> list[dict]:
        r = self.http.post(f"{self.URL}/{percorso}", params={"apiKey": self.chiave}, json=corpo)
        r.raise_for_status()
        dati = r.json() or {}
        if dati.get("Errors"):
            log.warning("Mouser: %s", dati["Errors"])
        return ((dati.get("SearchResults") or {}).get("Parts")) or []

    def cerca(self, codice: str) -> list[dict]:
        parti = self._parti("partnumber", {"SearchByPartRequest": {"mouserPartNumber": codice,
                                                                   "partSearchOptions": "None"}})
        if not parti:
            parti = self._parti("keyword", {"SearchByKeywordRequest": {"keyword": codice, "records": 5,
                                                                       "startingRecord": 0}})
        out = []
        for p in parti:
            url = (p.get("DataSheetUrl") or "").strip()
            if url:
                out.append({"codice": p.get("ManufacturerPartNumber") or codice,
                            "produttore": p.get("Manufacturer") or "", "descrizione": p.get("Description") or "",
                            "url": url, "fonte": self.nome, "ufficiale": True})
        return out


class FonteWeb:
    """Ricerca web tramite l'API di Tavily (piano gratuito): solo quando Mouser non trova nulla."""
    nome = "web"
    URL = "https://api.tavily.com/search"

    def __init__(self, chiave: str | None = None, http: httpx.Client | None = None):
        self.chiave = chiave or os.getenv("TAVILY_API_KEY")
        self.http = http or httpx.Client(timeout=30)

    @property
    def disponibile(self) -> bool:
        return bool(self.chiave)

    def cerca(self, codice: str) -> list[dict]:
        r = self.http.post(self.URL, headers={"Authorization": f"Bearer {self.chiave}"},
                           json={"query": f"{codice} datasheet pdf pin description", "max_results": 8})
        r.raise_for_status()
        risultati = (r.json() or {}).get("results") or []
        candidati = []
        for x in risultati:
            url = x.get("url") or ""
            testo = f"{x.get('title', '')} {url}".lower()
            if codice.lower()[:6] not in testo.replace("-", "").lower() and codice.lower()[:6] not in testo:
                continue
            punteggio = (2 if url.lower().endswith(".pdf") else 0) + (2 if ufficiale(url) else 0) + \
                        (1 if "datasheet" in testo else 0)
            candidati.append((punteggio, {"codice": codice, "produttore": "", "descrizione": x.get("title", ""),
                                          "url": url, "fonte": self.nome, "ufficiale": ufficiale(url)}))
        return [c for _, c in sorted(candidati, key=lambda t: -t[0])]


def varianti(codice: str) -> list[str]:
    """Codici più generici per trovare un datasheet compatibile: 'STM32F401VDT6' -> 'STM32F401VDT', 'STM32F401'.
    Si taglia ai cambi lettera/cifra, si tolgono i suffissi di confezionamento (TR, REEL, ...) e ci si ferma
    prima di diventare troppo generici (almeno 3 cifre e 6 caratteri)."""
    base = codice.strip().upper()
    c = base.split()[0] if " " in base else base          # 'SIM800C S2-108K7' -> 'SIM800C'
    c = re.sub(r"(-?(TR|REEL|T&R|TAPE)|#PBF|/TR|-ND)$", "", c)
    out, attuale = ([c] if c != base else []), c
    while len(attuale) > 5:
        tagli = [i for i in range(len(attuale) - 1, 4, -1)
                 if attuale[i - 1].isdigit() != attuale[i].isdigit() or attuale[i] in "-/_."]
        if not tagli:
            break
        attuale = attuale[:tagli[0]].rstrip("-/_.")
        if len(attuale) >= 6 and sum(ch.isdigit() for ch in attuale) >= 3 and attuale not in out:
            out.append(attuale)
    return out
