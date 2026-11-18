"""Assemblaggio dei componenti, condiviso da API, script di valutazione e test."""
from __future__ import annotations

from dataclasses import dataclass

from app.agente.grafo import crea_grafo, crea_llm
from app.agente.servizio import Assistente
from app.agente.strumenti import crea_strumenti
from app.cmms.api import crea_app as crea_app_cmms
from app.cmms.client import ClienteCMMS
from app.cmms.store import CMMSStore
from app.config import Config, carica_config
from app.dati import ArchivioResi
from app.rag.indice import KnowledgeBase


@dataclass
class Componenti:
    cfg: Config
    archivio: ArchivioResi
    kb: KnowledgeBase
    cmms: ClienteCMMS
    strumenti: list
    assistente: Assistente | None


def costruisci(cfg: Config | None = None, llm=None, con_agente: bool = True, kb: KnowledgeBase | None = None,
               archivio: ArchivioResi | None = None) -> Componenti:
    cfg = cfg or carica_config()
    archivio = archivio or ArchivioResi(cfg.db_resi)
    kb = kb or KnowledgeBase(cfg, archivio)
    if cfg.cmms_url:
        cmms = ClienteCMMS(base_url=cfg.cmms_url)
    else:  # CMMS in-process: stessa API HTTP, senza un servizio separato
        cmms = ClienteCMMS(app=crea_app_cmms(CMMSStore(cfg.db_resi, cfg.db_cmms)))
    strumenti = crea_strumenti(archivio, kb, cmms)
    assistente = None
    if con_agente:
        llm = llm or crea_llm(cfg, strumenti)
        grafo = crea_grafo(llm, strumenti, cfg.prompt_sistema())
        assistente = Assistente(grafo, cfg.max_passi, cfg.firma())
    return Componenti(cfg, archivio, kb, cmms, strumenti, assistente)
