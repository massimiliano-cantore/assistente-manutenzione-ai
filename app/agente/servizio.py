"""Servizio dell'assistente: un turno di conversazione, la conferma delle azioni e la raccolta dei passi.

Restituisce sempre, oltre alla risposta, i passi eseguiti (strumenti, argomenti, esiti): l'interfaccia li mostra
sotto ogni risposta, così il tecnico vede da dove vengono i dati.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.osservabilita import CONFERME, RICHIESTE, STRUMENTI, TOKEN, Cronometro, callback_tracciamento

log = logging.getLogger("assistente")


@dataclass
class Risposta:
    thread_id: str
    testo: str
    passi: list[dict] = field(default_factory=list)
    in_attesa_di_conferma: dict | None = None
    secondi: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _contenuto(m: ToolMessage):
    try:
        return json.loads(m.content)
    except (TypeError, json.JSONDecodeError):
        return m.content


class Assistente:
    def __init__(self, grafo, max_passi: int = 8, firma: dict | None = None):
        self.grafo = grafo
        self.limite = 2 * max_passi + 1   # ogni passo = nodo agente + nodo strumenti
        self.firma = firma or {}

    def _config(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": self.limite,
                "callbacks": callback_tracciamento(), "metadata": {"thread_id": thread_id, **self.firma}}

    def chiedi(self, messaggio: str, thread_id: str | None = None) -> Risposta:
        thread_id = thread_id or uuid.uuid4().hex
        if self.in_attesa(thread_id):
            # una nuova domanda mentre un'azione aspetta conferma vale come rifiuto dell'azione
            return self._esegui(Command(resume={"approvato": False}), thread_id,
                                dopo=lambda: self._esegui({"messages": [HumanMessage(messaggio)]}, thread_id))
        return self._esegui({"messages": [HumanMessage(messaggio)]}, thread_id)

    def conferma(self, thread_id: str, approvato: bool) -> Risposta:
        if not self.in_attesa(thread_id):
            return Risposta(thread_id, "Non c'è nessuna azione in attesa di conferma.")
        CONFERME.labels("approvata" if approvato else "rifiutata").inc()
        return self._esegui(Command(resume={"approvato": approvato}), thread_id)

    def in_attesa(self, thread_id: str) -> dict | None:
        stato = self.grafo.get_state({"configurable": {"thread_id": thread_id}})
        for t in stato.tasks or ():
            for i in t.interrupts or ():
                return i.value
        return None

    def _esegui(self, ingresso, thread_id: str, dopo=None) -> Risposta:
        cfg = self._config(thread_id)
        prima = len(self.grafo.get_state(cfg).values.get("messages", []))
        try:
            with Cronometro() as c:
                self.grafo.invoke(ingresso, cfg)
        except Exception as e:
            RICHIESTE.labels("errore").inc()
            log.exception("turno fallito", extra={"evento": {"thread_id": thread_id, "errore": str(e)[:300]}})
            return Risposta(thread_id, "Si è verificato un errore nel servizio. Riprova tra poco.",
                            secondi=round(c.secondi, 2) if hasattr(c, "secondi") else 0.0)
        if dopo:
            return dopo()
        nuovi = self.grafo.get_state(cfg).values.get("messages", [])[prima:]
        passi, testo = self._passi(nuovi)
        attesa = self.in_attesa(thread_id)
        RICHIESTE.labels("in_attesa" if attesa else "ok").inc()
        r = Risposta(thread_id, testo if not attesa else "", passi, attesa, round(c.secondi, 2))
        log.info("turno completato", extra={"evento": {
            "thread_id": thread_id, "secondi": r.secondi, "strumenti": [p["strumento"] for p in passi],
            "in_attesa": bool(attesa), **self.firma}})
        return r

    @staticmethod
    def _passi(messaggi) -> tuple[list[dict], str]:
        passi, chiamate, testo = [], {}, ""
        for m in messaggi:
            if isinstance(m, AIMessage):
                if m.usage_metadata:
                    TOKEN.labels("input").inc(m.usage_metadata.get("input_tokens", 0))
                    TOKEN.labels("output").inc(m.usage_metadata.get("output_tokens", 0))
                for tc in m.tool_calls:
                    chiamate[tc["id"]] = tc
                if m.content and not m.tool_calls:
                    testo = m.content if isinstance(m.content, str) else str(m.content)
            elif isinstance(m, ToolMessage):
                tc = chiamate.get(m.tool_call_id, {})
                errore = m.status == "error"
                STRUMENTI.labels(m.name or "?", "errore" if errore else "ok").inc()
                passi.append({"strumento": m.name, "argomenti": tc.get("args", {}), "esito": _contenuto(m),
                              "errore": errore})
        return passi, testo
