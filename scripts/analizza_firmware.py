"""Scheda funzionale di un firmware STM32 da riga di comando, senza avviare l'assistente.

    python -m scripts.analizza_firmware percorso\\file.hex [--mcu STM32G031G8U6] [--json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.firmware import stm32


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("file", type=Path)
    a.add_argument("--mcu", default="", help="codice del microcontrollore, per scegliere la famiglia giusta")
    a.add_argument("--json", action="store_true", help="stampa il risultato completo in JSON")
    a.add_argument("--disassembla", type=lambda x: int(x, 0), metavar="INDIRIZZO",
                   help="stampa 80 istruzioni a partire da un indirizzo (es. 0x08000164)")
    arg = a.parse_args()
    if arg.disassembla is not None:
        base, img = stm32.leggi_immagine(arg.file)
        print("\n".join(stm32.disassembla(base, img, arg.disassembla)))
        return
    r = stm32.analizza(arg.file, mcu=arg.mcu)
    if arg.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    print(f"{r['file']}: {r['byte']} byte da {r['indirizzo']}, GPIO famiglia {r['famiglia_gpio'] or '?'}")
    for p in r["pin"]:
        extra = ", ".join(str(p[k]) for k in ("uscita", "pull", "funzione_alternativa", "ultimo_comando") if k in p)
        print(f"  {p['pin']:<5} {p['modo']}" + (f" ({extra})" if extra else ""))
    print("periferiche:", ", ".join(r["periferiche_configurate"]) or "-")
    print("moduli:", ", ".join(r["moduli_sorgente"]) or "-")
    if r["testi"]:
        print("testi:", " | ".join(r["testi"][:15]))
    print("nota:", r["limiti"])


if __name__ == "__main__":
    main()
