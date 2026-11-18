"""API REST del finto CMMS. Gira come servizio separato (uvicorn app.cmms.api:app):
l'agente lo usa via HTTP, come farebbe con un CMMS vero."""
from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.cmms.store import CMMSStore
from app.config import carica_config


class NuovoOrdine(BaseModel):
    impianto_id: str = Field(examples=["IMP-00042"])
    descrizione: str = Field(min_length=5, max_length=500)
    priorita: Literal["bassa", "media", "alta"] = "media"
    ricambi: list[str] = []
    creato_da: str = "assistente-ai"


def crea_app(store: CMMSStore | None = None) -> FastAPI:
    if store is None:
        cfg = carica_config()
        store = CMMSStore(cfg.db_resi, cfg.db_cmms)
    app = FastAPI(title="KYROS CMMS (finto)", version="1.0")
    app.state.store = store

    @app.get("/health")
    def salute():
        return {"stato": "ok"}

    @app.get("/api/impianti")
    def cerca_impianti(cliente: str = "", seriale: str = "", articolo: str = "", limite: int = 20):
        return store.cerca_impianti(cliente, seriale, articolo, min(limite, 50))

    @app.get("/api/impianti/{impianto_id}")
    def impianto(impianto_id: str):
        r = store.impianto(impianto_id)
        if not r:
            raise HTTPException(404, f"impianto {impianto_id} non trovato")
        return {**r, "ordini": store.ordini(impianto_id=impianto_id)}

    @app.get("/api/ricambi/{codice}")
    def ricambio(codice: str):
        r = store.ricambio(codice)
        if not r:
            raise HTTPException(404, f"ricambio {codice} non trovato")
        return r

    @app.get("/api/ordini")
    def ordini(stato: str = "", impianto_id: str = ""):
        return store.ordini(stato, impianto_id)

    @app.post("/api/ordini", status_code=201)
    def crea_ordine(o: NuovoOrdine):
        try:
            return store.crea_ordine(o.impianto_id, o.descrizione, o.priorita, o.ricambi, o.creato_da)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    return app


# avvio: uvicorn app.cmms.api:crea_app --factory --port 8001
def main():  # pragma: no cover
    import uvicorn

    uvicorn.run("app.cmms.api:crea_app", factory=True, host="0.0.0.0", port=8001)


if __name__ == "__main__":  # pragma: no cover
    main()
