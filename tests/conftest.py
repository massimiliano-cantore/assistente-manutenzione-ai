import dataclasses
import os

import pytest

os.environ.setdefault("EMBEDDER", "tfidf")   # nei test: nessun download di modelli

from app.cmms.api import crea_app as crea_app_cmms  # noqa: E402
from app.cmms.client import ClienteCMMS  # noqa: E402
from app.cmms.store import CMMSStore  # noqa: E402
from app.config import carica_config  # noqa: E402
from app.dati import ArchivioResi  # noqa: E402
from app.rag.indice import KnowledgeBase  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    c = carica_config()
    return dataclasses.replace(c, embedder="tfidf", qdrant_url=None, cartella_indice=None, cmms_url=None)


@pytest.fixture(scope="session")
def archivio(cfg):
    return ArchivioResi(cfg.db_resi)


@pytest.fixture(scope="session")
def kb(cfg, archivio):
    return KnowledgeBase(cfg, archivio)


@pytest.fixture
def store(cfg):
    return CMMSStore(cfg.db_resi)


@pytest.fixture
def cmms(store):
    return ClienteCMMS(app=crea_app_cmms(store))
