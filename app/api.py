"""API dell'assistente (FastAPI). Avvio: uvicorn app.api:crea_app --factory --port 8000

POST /api/chat       un turno di conversazione
POST /api/conferma   approva o rifiuta l'azione proposta dall'agente
GET  /api/salute     stato e versione (modello, prompt, embedder)
GET  /metrics        metriche Prometheus
/                    interfaccia web (frontend TypeScript compilato), se presente
"""
from __future__ import annotations

import mimetypes
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.componenti import Componenti, costruisci
from app.config import RADICE
from app.osservabilita import REGISTRO, configura_log

FRONTEND = RADICE / "frontend" / "dist"


class Domanda(BaseModel):
    messaggio: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = None


class Decisione(BaseModel):
    thread_id: str
    approvato: bool


def crea_app(componenti: Componenti | None = None, frontend: Path | None = FRONTEND) -> FastAPI:
    @asynccontextmanager
    async def ciclo_vita(app: FastAPI):
        configura_log()
        app.state.c = componenti or await run_in_threadpool(costruisci)
        yield

    app = FastAPI(title="Assistente tecnico KYROS", version="1.0", lifespan=ciclo_vita)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"],
                       allow_headers=["*"])

    @app.post("/api/chat")
    async def chat(d: Domanda):
        r = await run_in_threadpool(app.state.c.assistente.chiedi, d.messaggio, d.thread_id)
        return r.to_dict()

    @app.post("/api/conferma")
    async def conferma(d: Decisione):
        r = await run_in_threadpool(app.state.c.assistente.conferma, d.thread_id, d.approvato)
        return r.to_dict()

    @app.get("/api/salute")
    def salute():
        c: Componenti = app.state.c
        return {"stato": "ok", **c.cfg.firma(), "sezioni_manuali": len(c.kb.sezioni),
                "profili_casi": len(c.kb.profili), "schede": len(c.catalogo.schede) if c.catalogo else 0,
                "riparazioni_storico": len(c.extra["storico"].riparazioni) if "storico" in c.extra else 0}

    @app.get("/api/immagini/{nome}")
    def immagine(nome: str):
        """Disegni con i componenti evidenziati dall'agente."""
        if not re.fullmatch(r"[a-f0-9]{12}\.png", nome):
            raise HTTPException(404)
        f = app.state.c.cfg.cartella_immagini / nome
        if not f.exists():
            raise HTTPException(404)
        return FileResponse(f, media_type="image/png")

    # --- ricerca nei documenti dei prodotti (solo versione azienda) ---------------------------------------
    def _indice():
        c: Componenti = app.state.c
        if not c.cfg.dati_azienda:
            raise HTTPException(404, "ricerca documenti disponibile solo con la documentazione aziendale")
        if "indice_documenti" not in c.extra:
            from app.documenti.indice import IndiceDocumenti
            f = c.cfg.dati_azienda / "indice_documenti.db"
            if not f.exists():
                raise HTTPException(503, "indice dei documenti non ancora costruito: lancia "
                                         "'python -m scripts.indicizza_documenti' o prepara_opera.bat")
            c.extra["indice_documenti"] = IndiceDocumenti(f)   # cartella registrata nell'indice
        return c.extra["indice_documenti"]

    @app.get("/documenti")
    def pagina_documenti():
        return FileResponse(Path(__file__).parent / "documenti" / "pagina.html", media_type="text/html")

    @app.get("/api/documenti/cerca")
    def cerca_documenti(q: str):
        return _indice().cerca(q[:200])

    @app.get("/api/documenti/apri")
    def apri_documento(p: str):
        radice = _indice().radice.resolve()
        f = (radice / p).resolve()
        if not f.is_file() or radice not in f.parents:   # solo file dentro la cartella dei documenti
            raise HTTPException(404)
        tipo = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        intestazioni = {"Content-Disposition": f'inline; filename="{f.name.encode("ascii", "replace").decode()}"'}
        return FileResponse(f, media_type=tipo, headers=intestazioni)

    @app.get("/metrics")
    def metriche():
        return Response(generate_latest(REGISTRO), media_type=CONTENT_TYPE_LATEST)

    if frontend and frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:   # interfaccia React non compilata (serve Node.js): pagina semplice incorporata
        @app.get("/")
        def pagina_base():
            return FileResponse(Path(__file__).parent / "pagina_base.html", media_type="text/html")
    return app
