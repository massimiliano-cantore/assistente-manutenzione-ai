"""Punto unico per analizzare un firmware: sceglie il metodo in base al microcontrollore.

- STM32 (ARM Cortex-M): emulazione (app.firmware.stm32)
- PIC16, PIC18, AVR: analisi statica (app.firmware.statico)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from intelhex import IntelHex

from app.firmware import inventario, statico, stm32


def architettura(f: Path, mcu: str = "") -> str:
    """'stm32', 'pic16', 'pic18', 'avr' o '' se non si capisce."""
    m = (mcu or "").upper()
    if m.startswith("STM32"):
        return "stm32"
    if m.startswith(("PIC18", "18F")):
        return "pic18"
    if m.startswith(("PIC16", "PIC12", "16F", "12F")):
        return "pic16"
    if m.startswith(("ATMEGA", "ATTINY", "ATXMEGA")):
        return "avr"
    if f.suffix.lower() in (".bin", ".elf", ".axf", ".out"):
        return "stm32"
    try:
        info = inventario.info_hex(f)
    except Exception:  # noqa: BLE001
        return ""
    return {"STM32": "stm32", "PIC18": "pic18", "PIC16": "pic16"}.get(info["famiglia"], "")


def analizza(f: Path, cache: Path | None = None, mcu: str = "") -> dict:
    f = Path(f)
    arch = architettura(f, mcu)
    if arch == "stm32":
        return stm32.analizza(f, cache=cache, mcu=mcu)
    if not arch:
        raise stm32.FirmwareNonSupportato(
            "microcontrollore non riconosciuto dal file: indicare il codice del micro (es. ATMEGA324A) nella "
            "scheda in prodotti.yaml ('mcu') o con --mcu")
    impronta = hashlib.sha1(f.read_bytes()).hexdigest()[:16]
    fc = Path(cache) / f"{impronta}_{mcu or arch}.json" if cache else None
    if fc and fc.exists():
        return json.loads(fc.read_text(encoding="utf-8"))
    ih = IntelHex(str(f))
    if ih.minaddr() is None:
        raise stm32.FirmwareNonSupportato("il file non contiene dati di programma")
    r = {"pic16": statico.analizza_pic16, "pic18": statico.analizza_pic18, "avr": statico.analizza_avr}[arch](ih, mcu)
    img = ih.tobinstr(start=ih.minaddr(), end=min(ih.maxaddr(), 0x3FFFF))
    r.update({"file": f.name, "sha1": impronta, "mcu": mcu or None, "byte": len(img),
              "moduli_sorgente": stm32.moduli_sorgente(img), "testi": stm32.testi(img),
              "limiti": statico.LIMITI_STATICI})
    if fc:
        fc.parent.mkdir(parents=True, exist_ok=True)
        fc.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return r
