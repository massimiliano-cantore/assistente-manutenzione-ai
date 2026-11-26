"""Strumento dell'agente sulla parte meccanica: distinta, gerarchia, funzionamento e aggancio all'elettrico."""
from __future__ import annotations

import re

from langchain_core.tools import tool

from app.meccanica import funzionamento as fz
from app.meccanica.indice import IndiceMeccanico


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def crea_strumenti_meccanica(indice: IndiceMeccanico, cartella_dati, catalogo=None) -> list:
    schede = list(getattr(catalogo, "schede", {}) or {})

    def schede_elettriche(codice: str) -> list[str]:
        n = _norm(codice)
        return [s for s in schede if n and (n in _norm(s) or _norm(s) in n)]

    @tool
    def scheda_meccanica(articolo: str) -> dict:
        """Parte meccanica di un articolo: distinta (con sottogruppi), parti elettriche e schede collegate,
        gruppi che lo contengono e funzionamento meccanico (catena e guasti tipici). Accetta il codice disegno
        (es. 01542L00), il codice articolo di prodotto (es. 2560030) o parole della denominazione.
        Usala per i guasti di articoli con meccanica, insieme agli strumenti elettrici."""
        trovati = indice.trova(articolo)
        if not trovati:
            return {"errore": f"nessun assieme o particolare trovato per '{articolo}'"}
        funz = fz.carica(cartella_dati)
        # dal particolare si sale al gruppo più in alto: è lì che si capisce il funzionamento
        principale = trovati[0]
        radici = [r for r in indice.radici(principale) if r != principale]
        descr = next((r["descrizione"] for c in indice._padri.get(principale, [])
                      for r in indice.articoli[c]["distinta"] if r["codice"] == principale), "")
        a = indice.articoli.get(principale) or {"denominazione": descr, "prodotti": [], "stato": "", "data": "",
                                                 "fonte_distinta": "particolare senza file proprio nel PDM"}
        distinta = indice.esplodi(principale)
        elettrici = [{"codice": r["codice"], "descrizione": r["descrizione"],
                      "schede_schema": schede_elettriche(r["codice"])} for r in distinta if r.get("elettrico")]
        out = {"codice": principale, "denominazione": a["denominazione"], "articoli_prodotto": a["prodotti"],
               "stato": a["stato"], "data": a["data"], "fonte_distinta": a["fonte_distinta"],
               "distinta": [f"{'  ' * (r['livello'] - 1)}{r['codice']} {r['descrizione']}" for r in distinta][:60],
               "parti_elettriche": elettrici, "contenuto_in": radici,
               "altri_trovati": trovati[1:6]}
        for c in [principale] + radici:
            if c in funz:
                out["funzionamento"] = {"di": c, **funz[c]}
                if funz[c].get("stato") != "confermato":
                    out["funzionamento"]["nota"] = "proposto dall'AI, non ancora confermato dal tecnico"
                break
        return out

    return [scheda_meccanica]
