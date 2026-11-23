"""Scheda funzionale del firmware da riga di comando, senza avviare l'assistente (STM32, PIC16, PIC18, AVR).

    python -m scripts.analizza_firmware percorso\\file.hex [--mcu STM32G031G8U6] [--json]
    python -m scripts.analizza_firmware --tutti C:\\percorso\\produzione1     (rapporto su tutti i prodotti)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from app.agente.strumenti_firmware import scheda_funzionale
from app.elettrico.catalogo import Catalogo
from app.firmware import analisi, stm32


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("file", type=Path, nargs="?")
    a.add_argument("--tutti", type=Path, metavar="CARTELLA",
                   help="analizza il firmware di tutti i prodotti di prodotti.yaml e scrive firmware_report.txt")
    a.add_argument("--mcu", default="", help="codice del microcontrollore, per scegliere la famiglia giusta")
    a.add_argument("--json", action="store_true", help="stampa il risultato completo in JSON")
    a.add_argument("--disassembla", type=lambda x: int(x, 0), metavar="INDIRIZZO",
                   help="stampa 80 istruzioni a partire da un indirizzo (es. 0x08000164)")
    arg = a.parse_args()
    if arg.tutti:
        rapporto_completo(arg.tutti)
        return
    if not arg.file:
        a.error("indicare un file o --tutti CARTELLA")
    if arg.disassembla is not None:
        base, img = stm32.leggi_immagine(arg.file)
        print("\n".join(stm32.disassembla(base, img, arg.disassembla)))
        return
    r = analisi.analizza(arg.file, mcu=arg.mcu)
    if arg.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    print("\n".join(_righe(r)))
    print("nota:", r["limiti"])


CHIAVI = ("uscita", "pull", "funzione_alternativa", "ultimo_comando", "livelli_scritti", "pin_componente", "net")


def _righe(r: dict, rientro: str = "  ") -> list[str]:
    arch = r.get("architettura") or f"STM32, GPIO {r.get('famiglia_gpio') or '?'}"
    out = [f"{r['file']}: {arch}"]
    for p in r.get("pin", []):
        extra = ", ".join(str(p[k]) for k in CHIAVI if p.get(k))
        out.append(f"{rientro}{p['pin']:<5} {p['modo']}" + (f" ({extra})" if extra else ""))
    out.append(f"{rientro}periferiche: " + (", ".join(r.get("periferiche_configurate", [])) or "-"))
    if r.get("moduli_sorgente"):
        out.append(f"{rientro}moduli: " + ", ".join(r["moduli_sorgente"]))
    if r.get("testi"):
        out.append(f"{rientro}testi: " + " | ".join(r["testi"][:10]))
    for d in r.get("da_verificare", []):
        out.append(f"{rientro}DA VERIFICARE: {d}")
    if r.get("avviso"):
        out.append(f"{rientro}nota: {r['avviso']}")
    return out


def _serie(nome: str) -> str:
    """'57512RFv00_01_12.hex' -> '57512RF': raggruppa le versioni dello stesso firmware."""
    return re.split(r"(?i)[ _-]?v?\d+([._]\d+)+|[ _-]?rev", Path(nome).stem)[0] or Path(nome).stem


def rapporto_completo(cartella: Path) -> None:
    cat = Catalogo.carica(cartella)
    conf = yaml.safe_load((cartella / "prodotti.yaml").read_text(encoding="utf-8"))
    righe, tot = [], {"schede": 0, "file": 0, "errori": 0}
    for prodotto in conf.get("prodotti", []):
        binari = (prodotto.get("firmware") or {}).get("binari", [])
        if not binari:
            continue
        righe.append(f"\n== {prodotto['nome']}")
        for codice in prodotto.get("schede", []):
            if not cat.firmware.get(codice):
                continue
            tot["schede"] += 1
            r = scheda_funzionale(cat, None, codice)
            if "errore" in r:
                tot["errori"] += 1
                righe.append(f"  {codice}: {r.get('file', '')} {r['errore']}")
                continue
            righe.append(f"  [{codice}] microcontrollore {r['microcontrollore'] or '?'}, "
                         f"{r['versioni_disponibili']} versioni, analizzata la più recente:")
            righe += _righe(r, "     ")
        # firmware senza scheda: una riga per serie, sulla versione più recente
        liberi = [b for b in binari if not b.get("scheda") and b.get("formato") == "hex" and b.get("byte")]
        serie: dict[str, list] = {}
        for b in liberi:
            serie.setdefault(_serie(b["file"]), []).append(b)
        for _nome, gruppo in sorted(serie.items()):
            b = max(gruppo, key=lambda x: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", x["file"])])
            tot["file"] += 1
            try:
                r = analisi.analizza(cartella / b["file"], cache=cartella / "firmware_analisi")
            except Exception as e:  # noqa: BLE001
                tot["errori"] += 1
                righe.append(f"  {Path(b['file']).name} (senza scheda): {e}")
                continue
            uscite = [p["pin"] for p in r["pin"] if p["modo"] == "uscita"]
            ingressi = [p["pin"] + ("↑" if p.get("pull") else "") for p in r["pin"] if p["modo"] == "ingresso"]
            righe.append(f"  {Path(b['file']).name} (senza scheda, {len(gruppo)} versioni) "
                         f"{r.get('architettura') or 'STM32'}: uscite {', '.join(uscite) or '-'}; "
                         f"ingressi {', '.join(ingressi) or '-'}; periferiche "
                         f"{', '.join(r.get('periferiche_configurate', [])) or '-'}")
        print(f"{prodotto['nome']}: fatto", file=sys.stderr)
    righe.insert(0, f"FIRMWARE: {tot['schede']} schede analizzate, {tot['file']} firmware senza scheda, "
                    f"{tot['errori']} non analizzabili  (↑ = pull-up)")
    (cartella / "firmware_report.txt").write_text("\n".join(righe), encoding="utf-8")
    print(f"scritto {cartella / 'firmware_report.txt'}")


if __name__ == "__main__":
    main()
