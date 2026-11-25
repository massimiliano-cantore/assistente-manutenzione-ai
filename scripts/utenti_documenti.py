"""Utenti della ricerca documenti per i colleghi (accesso dagli altri PC della rete).

    python -m scripts.utenti_documenti C:\\percorso\\Produzione1 aggiungi NOME   (chiede la password)
    python -m scripts.utenti_documenti C:\\percorso\\Produzione1 togli NOME
    python -m scripts.utenti_documenti C:\\percorso\\Produzione1 elenco

Aggiungere un nome che c'è già serve a cambiargli la password.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

from app.documenti.accesso import imposta_utente, leggi_utenti, togli_utente


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[2] not in ("aggiungi", "togli", "elenco"):
        print(__doc__)
        sys.exit(1)
    file = Path(sys.argv[1]) / "utenti_documenti.txt"
    azione = sys.argv[2]
    if azione == "elenco":
        utenti = sorted(leggi_utenti(file))
        print("\n".join(utenti) if utenti else "Nessun utente.")
        return
    if len(sys.argv) < 4 or ":" in sys.argv[3]:
        sys.exit("Indica il nome (senza ':').")
    nome = sys.argv[3]
    if azione == "togli":
        print(f"Tolto {nome}." if togli_utente(file, nome) else f"{nome} non c'è.")
        return
    p1 = getpass.getpass(f"Password per {nome} (non si vede mentre scrivi): ")
    if len(p1) < 8:
        sys.exit("La password deve avere almeno 8 caratteri.")
    if getpass.getpass("Ripetila: ") != p1:
        sys.exit("Le due password non coincidono.")
    imposta_utente(file, nome, p1)
    print(f"Utente {nome} salvato.")


if __name__ == "__main__":
    main()
