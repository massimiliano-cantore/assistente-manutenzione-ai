"""Knowledge base su Qdrant: due collezioni, manuali tecnici (chunk per sezione) e profili dei casi storici.

Qdrant gira in tre modi, scelti dalla configurazione:
- server (QDRANT_URL)       -> docker compose
- locale su disco (cartella) -> immagine Docker: l'indice è costruito durante la build
- in memoria                -> test e sviluppo
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchAny, PointStruct, VectorParams

from app.config import Config
from app.dati import ArchivioResi, sezioni_manuali
from app.rag.embedder import Embedder, crea_embedder

log = logging.getLogger(__name__)
MANUALI, CASI = "manuali", "casi"


class KnowledgeBase:
    def __init__(self, cfg: Config, archivio: ArchivioResi | None, embedder: Embedder | None = None,
                 cartella_manuali: Path | None = None):
        self.cfg = cfg
        self.sezioni = sezioni_manuali(cartella_manuali or cfg.cartella_manuali)
        self.profili = archivio.profili_casi() if archivio else []   # senza archivio: nessun caso simile
        self.embedder = embedder or crea_embedder(cfg.embedder, cfg.modello_embedding)
        if cfg.qdrant_url:
            self.client = QdrantClient(url=cfg.qdrant_url)
        elif cfg.cartella_indice:
            Path(cfg.cartella_indice).mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=cfg.cartella_indice)
        else:
            self.client = QdrantClient(":memory:")
        self._prepara()

    # --- costruzione ---------------------------------------------------------------------------------
    def _firma(self) -> str:
        h = hashlib.sha256(self.embedder.nome.encode())
        for d in self.sezioni + self.profili:
            h.update(d["testo"].encode())
        return h.hexdigest()[:16]

    def _file_firma(self) -> Path | None:
        if self.cfg.qdrant_url or not self.cfg.cartella_indice:   # col server Qdrant conta il contenuto del server
            return None
        return Path(self.cfg.cartella_indice) / "firma.json"

    def _prepara(self) -> None:
        firma, f = self._firma(), self._file_firma()
        # l'embedder TF-IDF va adattato ogni volta: solo i modelli pre-addestrati riusano l'indice salvato
        riusabile = self.embedder.nome.startswith("fastembed")
        if riusabile and f and f.exists() and json.loads(f.read_text()).get("firma") == firma:
            log.info("indice già costruito (firma %s): riuso", firma)
            return
        if riusabile and self.cfg.qdrant_url and self._gia_presente():
            log.info("indice già presente sul server Qdrant: riuso")
            return
        self.costruisci()
        if f:
            f.write_text(json.dumps({"firma": firma, "embedder": self.embedder.nome}))

    def _gia_presente(self) -> bool:
        try:
            return all(self.client.count(c).count > 0 for c in (MANUALI, CASI))
        except Exception:
            return False

    def costruisci(self) -> None:
        testi = [d["testo"] for d in self.sezioni + self.profili]
        if len(testi) >= 2:
            self.embedder.adatta(testi)
        for nome, docs in ((MANUALI, self.sezioni), (CASI, self.profili)):
            if self.client.collection_exists(nome):
                self.client.delete_collection(nome)
            if not docs:            # es. azienda senza archivio storico: la collezione resta vuota
                continue
            self.client.create_collection(nome, vectors_config=VectorParams(size=self.embedder.dim,
                                                                            distance=Distance.COSINE))
            vettori = self.embedder.documenti([d["testo"] for d in docs])
            self.client.upsert(nome, points=[PointStruct(id=i, vector=v, payload=d)
                                             for i, (v, d) in enumerate(zip(vettori, docs, strict=False))])
        log.info("indice costruito: %d sezioni di manuale, %d profili di casi", len(self.sezioni), len(self.profili))

    # --- ricerca ---------------------------------------------------------------------------------------
    def _cerca(self, collezione: str, testo: str, famiglia: str | None, k: int) -> list[dict]:
        if not self.client.collection_exists(collezione):
            return []
        filtro = None
        if famiglia:
            valori = [famiglia, "generale"] if collezione == MANUALI else [famiglia]
            filtro = Filter(must=[FieldCondition(key="famiglia", match=MatchAny(any=valori))])
        r = self.client.query_points(collezione, query=self.embedder.query(testo), limit=k, query_filter=filtro)
        return [{**p.payload, "punteggio": round(p.score, 3)} for p in r.points]

    def cerca_manuali(self, testo: str, famiglia: str | None = None, k: int | None = None) -> list[dict]:
        return self._cerca(MANUALI, testo, famiglia, k or self.cfg.top_k)

    def cerca_casi(self, testo: str, famiglia: str | None = None, k: int | None = None) -> list[dict]:
        return self._cerca(CASI, testo, famiglia, k or self.cfg.top_k)
