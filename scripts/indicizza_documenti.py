"""Costruisce o aggiorna l'indice di ricerca di tutti i documenti dei prodotti.

    python -m scripts.indicizza_documenti C:\\percorso\\Produzione1

La prima volta legge tutti i file (può richiedere parecchi minuti); le volte successive solo quelli nuovi o
modificati. L'indice va in <cartella>\\indice_documenti.db e si consulta dalla pagina /documenti dell'assistente.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from app.documenti.indice import IndiceDocumenti, schemi_da_prodotti_yaml


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    radice = Path(sys.argv[1])
    inizio = time.time()
    indice = IndiceDocumenti(radice / "indice_documenti.db", radice)
    r = indice.aggiorna(schemi_da_prodotti_yaml(radice),
                        avanzamento=lambda n: print(f"  ... {n} documenti letti", flush=True))
    st = indice.statistiche()
    print(f"Indice documenti: {r['documenti']} file ({st.get('istruzioni', 0)} istruzioni, {st.get('schemi', 0)} "
          f"schemi, {st.get('altri', 0)} altri); letti ora {r['indicizzati_ora']}, rimossi {r['rimossi']}, "
          f"non leggibili {r['errori']} - {time.time() - inizio:.0f} s")


if __name__ == "__main__":
    main()
