"""Strumenti dell'agente sullo storico delle riparazioni (schede lette con Document AI)."""
from __future__ import annotations

from langchain_core.tools import tool

from app.storico import Storico


def crea_strumenti_storico(storico: Storico) -> list:
    @tool
    def storico_riparazioni(sintomo: str = "", prodotto: str = "", articolo: str = "", seriale: str = "") -> dict:
        """Riparazioni già fatte e registrate (schede di riparazione) simili al guasto descritto: per ognuna data,
        articolo, seriale, firmware, note del tecnico e componenti sostituiti con l'intervento. prodotto: nome
        del prodotto (anche parziale) o codice articolo; seriale: per vedere la storia di un apparecchio preciso
        (se è già tornato). Usalo all'inizio di una diagnosi: i guasti già visti sono le cause più probabili."""
        casi = storico.cerca(sintomo, prodotto, articolo, seriale)
        if not casi:
            return {"casi": [], "nota": "nessuna riparazione simile registrata con questi filtri"}
        return {"casi": casi}

    @tool
    def statistiche_guasti(prodotto: str = "", articolo: str = "") -> dict:
        """Statistiche dei guasti di un prodotto dallo storico delle riparazioni: componenti più sostituiti, cause
        annotate (es. BRUCIATO, ROTTO), riferimenti dello schema citati, versioni firmware, seriali tornati più
        volte, tempo medio. Utile per dire al tecnico da dove partire."""
        return storico.statistiche(prodotto, articolo)

    return [storico_riparazioni, statistiche_guasti]


def crea_strumento_prodotto(storico: Storico) -> list:
    @tool
    def cerca_prodotto(testo: str) -> dict:
        """Trova il prodotto della documentazione (e le sue schede) da un codice articolo (es. '40810N',
        '2480035') o da parte del nome (es. 'elettropistone', 'arca'). Usalo per primo quando il tecnico
        indica un codice articolo o un nome commerciale."""
        return storico.prodotto_per(testo)

    return [cerca_prodotto]
