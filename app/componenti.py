"""Assemblaggio dei componenti, condiviso da API, script di valutazione e test.

Due modalità, stesso codice:
- demo:    azienda fittizia KYROS (archivio resi sintetico, manuali di esempio, CMMS finto);
- azienda: documentazione reale nella cartella DATI_AZIENDA (schede, BOM, istruzioni), che non sta nel repository.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.agente.grafo import crea_grafo, crea_llm
from app.agente.servizio import Assistente
from app.agente.strumenti import crea_strumenti
from app.agente.strumenti_elettrici import crea_strumenti_elettrici
from app.agente.strumenti_firmware import crea_strumenti_firmware
from app.agente.strumenti_storico import crea_strumenti_storico, crea_strumento_prodotto
from app.cmms.api import crea_app as crea_app_cmms
from app.cmms.client import ClienteCMMS
from app.cmms.store import CMMSStore
from app.config import Config, carica_config
from app.dati import ArchivioResi
from app.rag.indice import KnowledgeBase


@dataclass
class Componenti:
    cfg: Config
    archivio: ArchivioResi | None
    kb: KnowledgeBase
    cmms: ClienteCMMS | None
    strumenti: list
    assistente: Assistente | None
    catalogo: object | None = None
    datasheet: object | None = None
    extra: dict = field(default_factory=dict)


def _componenti_azienda(cfg: Config, llm, kb, catalogo, datasheet) -> Componenti:
    from app.datasheet.servizio import ServizioDatasheet, estrattore_llm
    from app.elettrico.catalogo import Catalogo

    catalogo = catalogo or Catalogo.carica(cfg.dati_azienda)
    if kb is None:
        from app.dati import sezioni_manuali
        from app.rag.embedder import TfidfEmbedder
        documenti = cfg.dati_azienda / "documenti"
        # senza manuali da indicizzare non serve scaricare il modello di embedding
        vuota = not documenti.exists() or not sezioni_manuali(documenti)
        kb = KnowledgeBase(cfg, None, embedder=TfidfEmbedder() if vuota else None, cartella_manuali=documenti)
    if datasheet is None:
        try:
            datasheet = ServizioDatasheet(cfg.dati_azienda / "datasheet")
        except Exception:
            datasheet = None
    strumenti = crea_strumenti_elettrici(catalogo, datasheet, cfg.cartella_immagini) + \
        crea_strumenti_firmware(catalogo, datasheet)
    if kb.sezioni:   # istruzioni e manuali dell'azienda, se presenti nella cartella documenti/
        strumenti = [s for s in crea_strumenti(None, kb, None) if s.name == "cerca_manuale"] + strumenti
    extra = {"estrattore": estrattore_llm}
    from app.storico import Storico
    cartella_storico = cfg.dati_azienda / "storico"
    # anche senza schede di riparazione serve per ritrovare un prodotto dal codice articolo (storico.yaml)
    storico = Storico.carica(cartella_storico) if cartella_storico.exists() else Storico([])
    collegamento = storico.collega(catalogo, cfg.dati_azienda / "prodotti.yaml")
    strumenti = crea_strumento_prodotto(storico) + strumenti
    if storico.riparazioni:   # schede di riparazione esportate da Document AI
        extra["storico"] = storico
        extra["storico_collegamento"] = collegamento
        strumenti = crea_strumenti_storico(storico) + strumenti
    from app.agente.limiti import limita
    return Componenti(cfg, None, kb, None, limita(strumenti), None, catalogo, datasheet, extra)


def costruisci(cfg: Config | None = None, llm=None, con_agente: bool = True, kb: KnowledgeBase | None = None,
               archivio: ArchivioResi | None = None, catalogo=None, datasheet=None) -> Componenti:
    cfg = cfg or carica_config()
    if cfg.modalita == "azienda":
        c = _componenti_azienda(cfg, llm, kb, catalogo, datasheet)
    else:
        archivio = archivio or ArchivioResi(cfg.db_resi)
        kb = kb or KnowledgeBase(cfg, archivio)
        if cfg.cmms_url:
            cmms = ClienteCMMS(base_url=cfg.cmms_url)
        else:  # CMMS in-process: stessa API HTTP, senza un servizio separato
            cmms = ClienteCMMS(app=crea_app_cmms(CMMSStore(cfg.db_resi, cfg.db_cmms)))
        c = Componenti(cfg, archivio, kb, cmms, crea_strumenti(archivio, kb, cmms), None)
    if con_agente:
        llm = llm or crea_llm(cfg, c.strumenti)
        if c.datasheet is not None and c.datasheet.estrattore is None and "estrattore" in c.extra:
            try:   # la piedinatura si estrae con lo stesso modello (senza strumenti collegati)
                from app.agente.grafo import crea_llm_semplice
                c.datasheet.estrattore = c.extra["estrattore"](crea_llm_semplice(cfg))
            except Exception:
                pass
        grafo = crea_grafo(llm, c.strumenti, cfg.prompt_sistema())
        c.assistente = Assistente(grafo, cfg.max_passi, cfg.firma())
    return c
