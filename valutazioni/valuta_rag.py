"""Valutazione del recupero: hit@k e MRR sulle domande di valuta/domande_rag.yaml.

Non usa l'LLM: è deterministica, veloce e gratuita, quindi gira a ogni push nella CI.
Uso: python -m valutazioni.valuta_rag            (embedder dalla configurazione)
     EMBEDDER=tfidf python -m valutazioni.valuta_rag
"""
from __future__ import annotations

from pathlib import Path

import yaml

from app.config import carica_config
from app.dati import ArchivioResi
from app.rag.indice import KnowledgeBase
from valutazioni.comune import salva_report, verifica_soglia


def main() -> None:
    cfg = carica_config()
    kb = KnowledgeBase(cfg, ArchivioResi(cfg.db_resi))
    domande = yaml.safe_load((Path(__file__).parent / "domande_rag.yaml").read_text(encoding="utf-8"))
    k, colpi, rr, dettaglio = cfg.top_k, 0, 0.0, []
    for d in domande:
        trovati = [r["id"] for r in kb.cerca_manuali(d["domanda"], k=k)]
        pos = trovati.index(d["attesa"]) + 1 if d["attesa"] in trovati else None
        colpi += pos is not None
        rr += 1 / pos if pos else 0
        dettaglio.append({**d, "trovati": trovati, "posizione": pos})
        print(f"{'OK' if pos else 'NO'} [{pos or '-'}] {d['domanda']}")
    hit, mrr = colpi / len(domande), rr / len(domande)
    firma = {**cfg.firma(), "embedder_effettivo": kb.embedder.nome}
    p = salva_report(f"rag_{kb.embedder.nome.split(':')[0]}", firma,
                     {"domande": len(domande), f"hit@{k}": round(hit, 3), "mrr": round(mrr, 3)}, dettaglio)
    print(f"\nhit@{k} = {hit:.3f}   MRR = {mrr:.3f}   report: {p}")
    verifica_soglia(f"RAG hit@{k} ({kb.embedder.nome})", hit, cfg.soglia_rag)


if __name__ == "__main__":
    main()
