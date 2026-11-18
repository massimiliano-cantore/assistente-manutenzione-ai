"""Monitoraggio: metriche Prometheus, log strutturati JSON e (opzionale) tracciamento con Langfuse.

- /metrics espone latenza, richieste, chiamate agli strumenti, token ed errori: si collega a Prometheus/Grafana
  o a Google Cloud Monitoring.
- Ogni turno di conversazione produce una riga di log JSON (leggibile da Cloud Logging / ELK).
- Se sono impostate LANGFUSE_PUBLIC_KEY e LANGFUSE_SECRET_KEY, ogni esecuzione dell'agente viene tracciata
  passo per passo su Langfuse (prompt, chiamate agli strumenti, costi).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRO = CollectorRegistry()
RICHIESTE = Counter("assistente_richieste_totali", "Turni di conversazione", ["esito"], registry=REGISTRO)
LATENZA = Histogram("assistente_latenza_secondi", "Durata di un turno", registry=REGISTRO,
                    buckets=(0.5, 1, 2, 4, 8, 15, 30, 60))
STRUMENTI = Counter("assistente_chiamate_strumenti_totali", "Chiamate agli strumenti", ["strumento", "esito"],
                    registry=REGISTRO)
TOKEN = Counter("assistente_token_totali", "Token consumati", ["tipo"], registry=REGISTRO)
CONFERME = Counter("assistente_conferme_totali", "Decisioni umane sulle azioni proposte", ["decisione"],
                   registry=REGISTRO)


class FormatoJSON(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        base = {"ts": round(r.created, 3), "livello": r.levelname, "logger": r.name, "msg": r.getMessage()}
        if isinstance(getattr(r, "evento", None), dict):
            base.update(r.evento)
        return json.dumps(base, ensure_ascii=False, default=str)


def configura_log() -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(FormatoJSON())
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), handlers=[h], force=True)


def callback_tracciamento() -> list:
    """Callback Langfuse se configurato, altrimenti nessuno. Un errore qui non deve mai fermare l'agente."""
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return []
    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception as e:  # pragma: no cover
        logging.getLogger(__name__).warning("Langfuse non disponibile: %s", e)
        return []


class Cronometro:
    def __enter__(self):
        self.inizio = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.secondi = time.perf_counter() - self.inizio
        LATENZA.observe(self.secondi)
