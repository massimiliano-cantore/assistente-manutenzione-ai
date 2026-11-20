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
                 r"EFM32\w+|EFR32\w+|R5F\w+|CC\d{4}\w*|AVR\w+|RP2040|1[268]L?F\d{2,5}[A-Z]?)\b")


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
            "piu_intervalli": len(uniti) > 6, "errori_checksum": errori, "famiglia_probabile": _famiglia(uniti),
            "famiglia": famiglia_hex(uniti)}


def _sovrappone(intervalli: list, da: int, a: int) -> bool:
    return any(x <= a and y > da for x, y in intervalli)


def famiglia_hex(intervalli: list) -> str:
    """Famiglia probabile dagli indirizzi: 'STM32', 'PIC18', 'PIC16', 'PIC32', 'AVR/altro' o ''."""
    if not intervalli:
        return ""
    if 0x08000000 <= intervalli[0][0] < 0x08200000:
        return "STM32"
    if _sovrappone(intervalli, 0x300000, 0x30000F) or _sovrappone(intervalli, 0xF00000, 0xF003FF):
        return "PIC18"
    if _sovrappone(intervalli, 0x1FC00000, 0x1FC02FFF) or _sovrappone(intervalli, 0x1D000000, 0x1D1FFFFF):
        return "PIC32"
    if _sovrappone(intervalli, 0x400E, 0x4011) or _sovrappone(intervalli, 0x4200, 0x43FF):
        return "PIC16"          # configurazione a 0x2007 (byte 0x400E) ed EEPROM a 0x2100 (byte 0x4200)
    if intervalli[0][0] == 0 and intervalli[-1][1] <= 0x40000:
        return "AVR/altro"
    return ""


SPIEGAZIONE = {"STM32": "probabile STM32 (flash a 0x08000000)",
               "PIC18": "probabile PIC18 (configurazione a 0x300000 / EEPROM a 0xF00000)",
               "PIC16": "probabile PIC16/PIC12 (configurazione a 0x400E / EEPROM a 0x4200)",
               "PIC32": "probabile PIC32",
               "AVR/altro": "parte da 0: AVR, 8051, MSP430 o ARM senza offset (da verificare con lo schema)"}


def _famiglia(intervalli: list) -> str:
    return SPIEGAZIONE.get(famiglia_hex(intervalli), "")


def famiglia_mcu(codice: str) -> str:
    c = codice.upper()
    for pref, fam in (("STM32", "STM32"), ("PIC18", "PIC18"), ("PIC16", "PIC16"), ("PIC12", "PIC16"),
                      ("PIC32", "PIC32"), ("ATMEGA", "AVR/altro"), ("ATTINY", "AVR/altro"), ("ATXMEGA", "AVR/altro"),
                      ("MSP430", "AVR/altro")):
        if c.startswith(pref):
            return fam
    return ""


def compatibile(fam_hex: str, mcu: list[tuple[str, str]]) -> bool:
    """Un .hex può appartenere alla scheda? Se non sappiamo, sì."""
    fam = {famiglia_mcu(m) for _, m in mcu} - {""}
    return not fam_hex or not fam or fam_hex in fam


def mcu_della_scheda(scheda) -> list[tuple[str, str]]:
    """[(designator, codice)] dei microcontrollori trovati sullo schema."""
    out = []
    for d, c in scheda.componenti.items():
        m = MCU.search(" ".join([c.valore, c.codice_produttore, c.descrizione]))
        if m:
            codice = m.group(1).upper()
            out.append((d, "PIC" + codice if codice[:2] in ("12", "16", "18") else codice))
    return out


def associa(f: Path, schede: dict[str, list], radice: Path, alias: dict[str, set[str]] | None = None,
            fam_hex: str = "") -> str | None:
    """Scheda a cui appartiene il file: codice della scheda (o un suo alias, es. il numero di circuito '01180' preso
    dal nome della BOM) nel percorso; altrimenti l'unica scheda con un microcontrollore compatibile."""
    testo = str(f.relative_to(radice)).upper()
    alias = alias or {}
    candidati = []
    for codice in schede:
        nomi = {codice.upper(), codice.split("_", 1)[-1].upper()} | {a.upper() for a in alias.get(codice, ())}
        for nome in nomi:
            if len(nome) >= 4 and re.search(rf"(?<![A-Z0-9]){re.escape(nome)}(?![0-9])", testo):
                candidati.append((len(nome), codice))
    for _, codice in sorted(candidati, reverse=True):
        if compatibile(fam_hex, schede[codice]):
            return codice
    con_mcu = [c for c, m in schede.items() if m and compatibile(fam_hex, m)]
    return con_mcu[0] if len(con_mcu) == 1 else None
