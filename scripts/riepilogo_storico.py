"""Riepilogo dello storico delle riparazioni (schede esportate da Document AI) e del collegamento ai prodotti.

    python -m scripts.riepilogo_storico C:\\percorso\\produzione1

Legge i JSON in <cartella>\\storico, li collega ai prodotti di prodotti.yaml e scrive storico_report.txt.
Gli articoli non riconosciuti si associano a mano in <cartella>\\storico\\storico.yaml:

    articoli:
      "40806": "Elettromaniglie - seriale 03 000"
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.elettrico.catalogo import Catalogo
from app.storico import Storico


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    radice = Path(sys.argv[1])
    cartella = radice / "storico"
    if not cartella.exists():
        print(f"manca la cartella {cartella}: esporta lì le schede confermate da Document AI "
              "(app, Esporta, 'Prepara lo zip JSON', oppure elabora.py --esporta-json)")
        sys.exit(1)
    s = Storico.carica(cartella)
    catalogo = Catalogo.carica(radice) if (radice / "prodotti.yaml").exists() else None
    c = s.collega(catalogo, radice / "prodotti.yaml")
    r = s.riepilogo()
    righe = [f"STORICO: {r['riparazioni']} riparazioni dal {r['dal']} al {r['al']}, "
             f"{c['collegate_a_prodotto']} collegate a un prodotto della documentazione", ""]
    righe.append("Per prodotto:")
    righe += [f"  {n:5d}  {p}" for p, n in r["per_prodotto"]]
    if c["articoli_non_riconosciuti"]:
        righe += ["", "Articoli non riconosciuti (associali a mano in storico/storico.yaml, voce 'articoli'):"]
        righe += [f"  {a}: {n} riparazioni" for a, n in c["articoli_non_riconosciuti"].items()]
    for prodotto, _ in r["per_prodotto"][:10]:
        if prodotto.startswith("(articolo"):
            continue
        st = s.statistiche(prodotto)
        righe += ["", f"== {prodotto}: {st['riparazioni']} riparazioni, tempo medio {st['tempo_medio_minuti']} min"]
        righe.append("  più sostituiti: " + "; ".join(f"{k} ({n})" for k, n in st["componenti_piu_sostituiti"][:6]))
        if st["riferimenti_schema_citati"]:
            righe.append("  componenti dello schema citati: " + ", ".join(f"{k} ({n})"
                                                                          for k, n in st["riferimenti_schema_citati"]))
        if st["seriali_tornati_piu_volte"]:
            righe.append("  seriali tornati più volte: " + ", ".join(f"{k} ({n})"
                                                                     for k, n in st["seriali_tornati_piu_volte"]))
    testo = "\n".join(righe)
    (radice / "storico_report.txt").write_text(testo, encoding="utf-8")
    print(testo)


if __name__ == "__main__":
    main()
