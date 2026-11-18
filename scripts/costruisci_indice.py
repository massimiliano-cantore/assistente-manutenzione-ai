"""Costruisce l'indice Qdrant su disco (usato nella build Docker: l'immagine parte con l'indice già pronto).

Uso: CARTELLA_INDICE=indice python -m scripts.costruisci_indice
"""
import logging
import sys

from app.config import carica_config
from app.dati import ArchivioResi
from app.rag.indice import KnowledgeBase


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = carica_config()
    if not (cfg.cartella_indice or cfg.qdrant_url):
        sys.exit("imposta CARTELLA_INDICE (indice su disco) oppure QDRANT_URL (server)")
    kb = KnowledgeBase(cfg, ArchivioResi(cfg.db_resi))
    print(f"indice pronto in {cfg.cartella_indice or cfg.qdrant_url}: {len(kb.sezioni)} sezioni, "
          f"{len(kb.profili)} profili, embedder {kb.embedder.nome}")
    kb.client.close()


if __name__ == "__main__":
    main()
