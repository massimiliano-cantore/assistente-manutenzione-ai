"""Client HTTP del CMMS usato dagli strumenti dell'agente.

In produzione punta all'URL del servizio CMMS; nei test e in sviluppo può parlare con l'app FastAPI
in-process (stessa API HTTP, nessuna rete)."""
from __future__ import annotations

import httpx


class ErroreCMMS(Exception):
    pass


class ClienteCMMS:
    def __init__(self, base_url: str | None = None, app=None, timeout: float = 10.0):
        if app is not None:
            from fastapi.testclient import TestClient

            self._http = TestClient(app)
        elif base_url:
            self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        else:
            raise ValueError("serve base_url oppure app")

    def _get(self, percorso: str, **params):
        r = self._http.get(percorso, params={k: v for k, v in params.items() if v})
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise ErroreCMMS(f"CMMS {r.status_code}: {r.text[:200]}")
        return r.json()

    def cerca_impianti(self, cliente: str = "", seriale: str = "", articolo: str = "") -> list[dict]:
        return self._get("/api/impianti", cliente=cliente, seriale=seriale, articolo=articolo, limite=10) or []

    def impianto(self, impianto_id: str) -> dict | None:
        return self._get(f"/api/impianti/{impianto_id}")

    def ricambio(self, codice: str) -> dict | None:
        return self._get(f"/api/ricambi/{codice}")

    def crea_ordine(self, impianto_id: str, descrizione: str, priorita: str, ricambi: list[str]) -> dict:
        r = self._http.post("/api/ordini", json={"impianto_id": impianto_id, "descrizione": descrizione,
                                                 "priorita": priorita, "ricambi": ricambi})
        if r.status_code >= 400:
            raise ErroreCMMS(f"CMMS {r.status_code}: {r.json().get('detail', r.text)}")
        return r.json()
