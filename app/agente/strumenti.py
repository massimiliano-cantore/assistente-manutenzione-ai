"""Strumenti dell'agente: knowledge base (RAG), archivio storico (SQL in sola lettura) e CMMS (HTTP).

L'unico strumento che scrive, `apri_ordine_di_lavoro`, si ferma con `interrupt` di LangGraph e aspetta
la conferma dell'utente: nessuna azione sui sistemi aziendali parte senza approvazione umana.
"""
from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool
from langgraph.types import interrupt

from app.cmms.client import ClienteCMMS, ErroreCMMS
from app.dati import ArchivioResi
from app.rag.indice import KnowledgeBase

Famiglia = Literal["", "serratura", "cilindro", "centralina", "lettore", "tastiera"]
STRUMENTI_SCRITTURA = {"apri_ordine_di_lavoro"}


def _risultati(righe: list[dict], se_vuoto: str = "nessun risultato") -> dict:
    """Gli strumenti restituiscono sempre un oggetto, mai una lista: una lista vuota diventerebbe un messaggio
    vuoto, che alcune API (es. Groq) rifiutano con errore 400. E il modello deve sapere che non c'è nulla."""
    return {"risultati": righe, "trovati": len(righe)} if righe else {"risultati": [], "trovati": 0, "nota": se_vuoto}


def crea_strumenti(archivio: ArchivioResi, kb: KnowledgeBase, cmms: ClienteCMMS) -> list:
    @tool
    def cerca_manuale(domanda: str, famiglia: Famiglia = "") -> dict:
        """Cerca nei manuali di assistenza le procedure di diagnosi e riparazione.
        famiglia: limita la ricerca a una famiglia di prodotto ('' = tutte). Restituisce le sezioni più pertinenti."""
        return _risultati([{"sezione": r["id"], "titolo": r["titolo"], "testo": r["testo"][:900],
                            "punteggio": r["punteggio"]} for r in kb.cerca_manuali(domanda, famiglia or None)])

    @tool
    def casi_simili(sintomo: str, famiglia: Famiglia = "") -> dict:
        """Cerca nello storico delle riparazioni i casi con una diagnosi simile al sintomo descritto.
        Per ogni gruppo di casi restituisce numero di casi, pezzi sostituiti più spesso, esiti
        e numeri di riparazione d'esempio."""
        return _risultati([{k: r[k] for k in ("diagnosi", "famiglia", "casi", "pezzi_frequenti", "esiti",
                                              "giorni_mediani", "esempi", "punteggio")}
                           for r in kb.cerca_casi(sintomo, famiglia or None)])

    @tool
    def interroga_archivio(query: str) -> dict:
        """Esegue UNA query SQLite di sola lettura (SELECT o WITH) sull'archivio resi (tabelle rientri e pezzi)
        e restituisce al massimo 50 righe. Usa GROUP BY, COUNT, ORDER BY, LIMIT per riassumere."""
        return archivio.sql(query)

    @tool
    def cerca_impianto(cliente: str = "", seriale: str = "", articolo: str = "") -> dict:
        """Cerca nel CMMS gli impianti installati presso i clienti, per nome cliente (anche parziale),
        numero di serie o codice articolo. Restituisce id impianto, articolo, seriale e rientri negli ultimi 6 mesi."""
        if not (cliente or seriale or articolo):
            return {"errore": "indica almeno cliente, seriale o articolo"}
        return _risultati(cmms.cerca_impianti(cliente, seriale, articolo),
                          "nessun impianto trovato: riprova con una parte del nome cliente o con il seriale")

    @tool
    def verifica_ricambio(codice: str) -> dict:
        """Verifica nel CMMS giacenza, scorta minima e prezzo di un ricambio (es. 'SCB1180')."""
        return cmms.ricambio(codice) or {"errore": f"ricambio {codice} non trovato"}

    @tool
    def apri_ordine_di_lavoro(impianto_id: str, descrizione: str,
                              priorita: Literal["bassa", "media", "alta"] = "media",
                              ricambi: list[str] | None = None) -> dict:
        """Apre un ordine di lavoro nel CMMS per un intervento presso il cliente.
        Chiede automaticamente la conferma all'utente prima di scrivere."""
        proposta = {"azione": "apri_ordine_di_lavoro", "impianto_id": impianto_id, "descrizione": descrizione,
                    "priorita": priorita, "ricambi": ricambi or []}
        decisione = interrupt(proposta)          # il grafo si ferma qui finché l'utente non risponde
        if not (isinstance(decisione, dict) and decisione.get("approvato")):
            return {"esito": "annullato", "motivo": "l'utente non ha confermato l'apertura dell'ordine"}
        try:
            return {"esito": "creato", "ordine": cmms.crea_ordine(impianto_id, descrizione, priorita, ricambi or [])}
        except ErroreCMMS as e:
            return {"esito": "errore", "dettaglio": str(e)}

    return [cerca_manuale, casi_simili, interroga_archivio, cerca_impianto, verifica_ricambio, apri_ordine_di_lavoro]
