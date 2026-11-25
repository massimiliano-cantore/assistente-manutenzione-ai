"""Costruisce o aggiorna l'indice di ricerca di tutti i documenti dei prodotti.

    python -m scripts.indicizza_documenti CARTELLA_DOCUMENTI [CARTELLA_PRODUZIONE1]

CARTELLA_DOCUMENTI è la cartella in cui cercare (es. "Documenti condivisi", anche su un disco di rete); se si
indica anche Produzione1, l'indice va lì (accanto a prodotti.yaml) e gli schemi riconosciuti dallo scanner
sono marcati come schemi. Se in Produzione1 c'è cartelle_da_indicizzare.txt, si leggono solo le
sottocartelle elencate lì (una per riga). La prima volta legge tutti i file (può richiedere parecchi minuti), poi solo
quelli nuovi o modificati. L'indice va in <Produzione1>\\indice_documenti.db; si consulta dalla pagina /documenti.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from app.documenti.indice import IndiceDocumenti, leggi_elenco_cartelle, schemi_da_prodotti_yaml


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    radice = Path(sys.argv[1])
    produzione = Path(sys.argv[2]) if len(sys.argv) > 2 else radice
    if not radice.is_dir():
        sys.exit(f"Cartella non trovata: {radice}")
    elenco = produzione / "cartelle_da_indicizzare.txt"
    cartelle = None
    if elenco.exists():
        cartelle = leggi_elenco_cartelle(elenco, radice)
        print(f"Cartelle da indicizzare ({elenco.name}): {len(cartelle)}", flush=True)
        for c in cartelle:
            print(f"  - {c or '(tutta la cartella)'}", flush=True)
        if not cartelle:
            sys.exit(f"Nessuna cartella valida in {elenco}: i nomi devono essere sottocartelle di {radice} "
                     "(oppure scrivi il percorso completo). Controlla anche DOCUMENTI in prepara_opera.bat.")
    inizio = time.time()
    indice = IndiceDocumenti(produzione / "indice_documenti.db", radice)
    print(f"Indicizzo {radice} ...", flush=True)
    r = indice.aggiorna(schemi_da_prodotti_yaml(produzione, radice),
                        avanzamento=lambda n: print(f"  ... {n} documenti letti", flush=True), cartelle=cartelle)
    st = indice.statistiche()
    print(f"Indice documenti: {r['documenti']} file ({st.get('istruzioni', 0)} istruzioni, {st.get('schemi', 0)} "
          f"schemi, {st.get('altri', 0)} altri); letti ora {r['indicizzati_ora']}, rimossi {r['rimossi']}, "
          f"non leggibili {r['errori']} - {time.time() - inizio:.0f} s")


if __name__ == "__main__":
    main()
