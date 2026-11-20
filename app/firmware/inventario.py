"""Inventario del firmware: riconosce i file, legge gli indirizzi dei .hex e trova il microcontrollore sugli schemi.
Non disassembla niente: serve a capire che materiale c'è e a quale scheda appartiene."""
from __future__ import annotations

import re
from pathlib import Path

BINARI = {".hex": "hex", ".ihx": "hex", ".elf": "elf", ".axf": "elf", ".out": "elf", ".bin": "bin", ".s19": "srec",
          ".srec": "srec", ".mot": "srec"}
SORGENTI = {".c": "c", ".h": "c", ".cpp": "c++", ".hpp": "c++", ".cc": "c++", ".asm": "assembly", ".s": "assembly",
            ".inc": "assembly", ".py": "python", ".ino": "arduino"}
PROGETTI = {".mcp": "MPLAB 8", ".mcw": "MPLAB 8", ".uvproj": "Keil", ".uvprojx": "Keil", ".ewp": "IAR",
            ".ioc": "STM32CubeMX", ".cproject": "Eclipse/STM32CubeIDE", ".atsln": "Atmel Studio", ".cydsn": "PSoC"}
CARTELLE_PROGETTO = {"nbproject": "MPLAB X"}

# famiglie di microcontrollori riconoscibili dal valore o dalla descrizione del componente
MCU = re.compile(r"(?i)\b(STM32[A-Z]\d{2,3}\w*|STM8\w+|PIC\d{2}[A-Z]{1,2}\d+\w*|dsPIC\w+|AT(?:mega|tiny|xmega)\w+|"
                 r"ATSAM\w+|SAM[DLE]\d\w+|MSP430\w+|nRF5\d\w+|ESP32\w*|ESP8266\w*|LPC\d{3,4}\w*|MK[LEV]?\d\w+|"
                 r"EFM32\w+|EFR32\w+|R5F\w+|CC\d{4}\w*|AVR\w+|RP2040)\b")


def tipo(f: Path) -> tuple[str, str] | None:
    """('binario'|'sorgente'|'progetto', formato) oppure None."""
    s = f.suffix.lower()
    if s in BINARI:
        return "binario", BINARI[s]
    if s in SORGENTI:
        return "sorgente", SORGENTI[s]
    if s in PROGETTI:
        return "progetto", PROGETTI[s]
    return None


def info_hex(f: Path) -> dict:
    """Intervalli di indirizzi e byte di dati di un file Intel HEX."""
    base, blocchi, totale, errori = 0, [], 0, 0
    for riga in f.read_text(errors="replace").splitlines():
        riga = riga.strip()
        if not riga.startswith(":") or len(riga) < 11:
            continue
        try:
            n, ind, t = int(riga[1:3], 16), int(riga[3:7], 16), int(riga[7:9], 16)
            dati = bytes.fromhex(riga[9:9 + 2 * n])
            if (sum(bytes.fromhex(riga[1:])) & 0xFF) != 0:
                errori += 1
        except ValueError:
            errori += 1
            continue
        if t == 0:
            a = base + ind
            if blocchi and blocchi[-1][1] == a:
                blocchi[-1][1] = a + len(dati)
            else:
                blocchi.append([a, a + len(dati)])
            totale += len(dati)
        elif t == 2:
            base = int.from_bytes(dati, "big") << 4
        elif t == 4:
            base = int.from_bytes(dati, "big") << 16
    blocchi.sort()
    uniti = []
    for a, b in blocchi:
        if uniti and a <= uniti[-1][1] + 16:
            uniti[-1][1] = max(uniti[-1][1], b)
        else:
            uniti.append([a, b])
    return {"byte": totale, "intervalli": [f"0x{a:08X}-0x{b - 1:08X}" for a, b in uniti[:6]],
            "piu_intervalli": len(uniti) > 6, "errori_checksum": errori, "famiglia_probabile": _famiglia(uniti)}


def _famiglia(intervalli: list) -> str:
    """Indizio dall'indirizzo di partenza: è solo un suggerimento."""
    if not intervalli:
        return ""
    a = intervalli[0][0]
    if 0x08000000 <= a < 0x08200000:
        return "probabile STM32 (flash a 0x08000000)"
    if any(0x300000 <= x < 0x300010 for x, _ in intervalli):
        return "probabile PIC18 (bit di configurazione a 0x300000)"
    if any(0x400E <= x <= 0x4010 for x, _ in intervalli) or any(0x2007 <= x <= 0x2008 for x, _ in intervalli):
        return "probabile PIC16/PIC12 (configurazione)"
    if any(0x1FC00000 <= x < 0x1FC03000 or 0x1D000000 <= x < 0x1D200000 for x, _ in intervalli):
        return "probabile PIC32"
    if a == 0 and intervalli[-1][1] <= 0x40000:
        return "parte da 0 (AVR, PIC, 8051, MSP430 o ARM senza offset: da verificare con lo schema)"
    return ""


def mcu_della_scheda(scheda) -> list[tuple[str, str]]:
    """[(designator, codice)] dei microcontrollori trovati sullo schema."""
    out = []
    for d, c in scheda.componenti.items():
        m = MCU.search(" ".join([c.valore, c.codice_produttore, c.descrizione]))
        if m:
            out.append((d, m.group(1).upper()))
    return out


def associa(f: Path, schede: dict[str, list[str]], radice: Path) -> str | None:
    """Scheda a cui appartiene il file: codice della scheda nel percorso, altrimenti unica scheda con MCU."""
    testo = str(f.relative_to(radice)).upper()
    for codice in sorted(schede, key=len, reverse=True):
        nome = codice.split("_", 1)[-1].upper() if "_" in codice else codice.upper()
        if len(nome) >= 4 and (codice.upper() in testo or nome in testo):
            return codice
    con_mcu = [c for c, m in schede.items() if m]
    return con_mcu[0] if len(con_mcu) == 1 else None
