"""Legge i file SolidWorks del PDM (assiemi, tavole, particolari) e costruisce l'indice meccanico.

    python -m scripts.scansiona_meccanica C:\\OPERA_PDM C:\\percorso\\Produzione1
    python -m scripts.scansiona_meccanica C:\\OPERA_PDM C:\\percorso\\Produzione1 --descrivi 20

--descrivi N: per N assiemi non ancora descritti chiede all'AI (Claude, dal .env) il funzionamento meccanico
e lo scrive in Produzione1\\meccanica\\funzionamento.yaml come 'da_confermare' (circa 0,03 $ ad assieme).
Non serve SolidWorks. Le cartelle X_ (progettazione), di prova e "old" si saltano.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from app.meccanica import funzionamento as fz
from app.meccanica.indice import IndiceMeccanico


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdm")
    ap.add_argument("dati")
    ap.add_argument("--descrivi", type=int, default=0, metavar="N")
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    pdm, dati = Path(a.pdm), Path(a.dati)
    if not pdm.is_dir():
        raise SystemExit(f"Cartella PDM non trovata: {pdm}")
    t = time.time()
    indice = IndiceMeccanico(dati)
    r = indice.aggiorna(pdm, avanzamento=lambda n: print(f"  ... {n} file letti", flush=True))
    print(f"MECCANICA: {r['file']} file SolidWorks ({r['letti_ora']} letti ora, {r['errori']} non leggibili), "
          f"{r['codici']} codici, {r['con_distinta']} con distinta - {time.time() - t:.0f} s")
    gia = fz.carica(dati)
    print(f"Funzionamento: {sum(1 for v in gia.values() if v.get('stato') == 'confermato')} confermati, "
          f"{sum(1 for v in gia.values() if v.get('stato') != 'confermato')} da confermare")
    if a.descrivi:
        from app.agente.grafo import crea_llm_semplice
        from app.config import carica_config
        llm = crea_llm_semplice(carica_config())
        coda = fz.da_descrivere(indice, gia)[:a.descrivi]
        print(f"Descrivo {len(coda)} assiemi con l'AI...")
        for c in coda:
            try:
                gia[c] = fz.genera(indice, c, llm)
                fz.salva(dati, gia)
                print(f"  {c} {indice.articoli[c]['denominazione']}: fatto")
            except Exception as e:  # noqa: BLE001
                print(f"  {c}: non riuscito ({e})")
        print(f"Controlla e conferma in {fz.file_funzionamento(dati)}")


if __name__ == "__main__":
    main()
