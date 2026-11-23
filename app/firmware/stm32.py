"""Analisi del firmware STM32 (Cortex-M) a partire dal binario (.hex, .bin, .elf), senza il codice sorgente.

Il codice viene eseguito in un emulatore (Unicorn) dall'avvio per un numero limitato di istruzioni: si registra
cosa scrive nei registri delle periferiche. Dai registri GPIO si ricava come è configurato ogni pin (ingresso,
uscita, funzione alternativa, pull-up...), dagli altri indirizzi quali periferiche usa. Funziona con HAL, LL e codice
scritto a registri, perché guarda l'effetto e non la libreria.

Limiti dichiarati nel risultato: un pin impostato come analogico non si distingue da uno lasciato al valore di
reset; le configurazioni fatte dopo l'inizio del ciclo principale o dentro un interrupt possono mancare.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

FLASH = 0x08000000

# basi GPIO per famiglia (passo 0x400 tra le porte): A, B, C...
BASI_GPIO = {
    0x50000000: "G0/C0/L0/U0",
    0x48000000: "F0/F3/G4/L4/L5/WB",
    0x40020000: "F2/F4/F7/L1",
}
BASE_GPIO_F1 = 0x40010800     # F1: registri CRL/CRH diversi
PORTE = "ABCDEFGHIJK"

# nomi indicativi delle periferiche più comuni (gli indirizzi coincidono nella maggior parte delle famiglie)
PERIFERICHE = {
    0x40012C00: "TIM1", 0x40000000: "TIM2", 0x40000400: "TIM3", 0x40000800: "TIM4", 0x40000C00: "TIM5",
    0x40001000: "TIM6", 0x40001400: "TIM7", 0x40002000: "TIM14", 0x40014000: "TIM15", 0x40014400: "TIM16",
    0x40014800: "TIM17", 0x40010000: "TIM1 (F4)", 0x40013800: "USART1", 0x40004400: "USART2",
    0x40004800: "USART3", 0x40004C00: "UART4", 0x40005000: "UART5", 0x40008000: "LPUART1", 0x40011000: "USART1 (F4)",
    0x40011400: "USART6 (F4)", 0x40013000: "SPI1", 0x40003800: "SPI2", 0x40003C00: "SPI3", 0x40005400: "I2C1",
    0x40005800: "I2C2", 0x40005C00: "I2C3", 0x40012400: "ADC (G0/F0)", 0x40012000: "ADC1 (F4/L1)",
    0x50040000: "ADC (G4/L4)", 0x40007400: "DAC", 0x40002800: "RTC", 0x40003000: "IWDG", 0x40002C00: "WWDG",
    0x40006400: "CAN/FDCAN",
    0x40021000: "RCC", 0x40023800: "RCC (F4)", 0x40022000: "FLASH", 0x40023C00: "FLASH (F4)", 0x40007000: "PWR",
    0x40010400: "EXTI", 0x40021800: "EXTI (G0)", 0x40013C00: "EXTI (F4)",
}
MODI = {0: "ingresso", 1: "uscita", 2: "funzione alternativa", 3: "analogico"}
PULL = {0: "", 1: "pull-up", 2: "pull-down"}


class FirmwareNonSupportato(Exception):
    pass


def leggi_immagine(f: Path) -> tuple[int, bytes]:
    """(indirizzo di partenza, byte) da .hex, .bin o .elf."""
    s = f.suffix.lower()
    if s in (".hex", ".ihx"):
        from intelhex import IntelHex
        ih = IntelHex(str(f))
        if ih.minaddr() is None:
            raise FirmwareNonSupportato("il file non contiene dati di programma")
        return ih.minaddr(), ih.tobinstr(start=ih.minaddr(), end=ih.maxaddr())
    if s == ".bin":
        return FLASH, f.read_bytes()
    if s in (".elf", ".axf", ".out"):
        from elftools.elf.elffile import ELFFile
        with f.open("rb") as h:
            elf = ELFFile(h)
            seg = [p for p in elf.iter_segments() if p["p_type"] == "PT_LOAD" and p["p_filesz"]]
            if not seg:
                raise FirmwareNonSupportato("ELF senza segmenti da caricare")
            inizio = min(p["p_paddr"] for p in seg)
            fine = max(p["p_paddr"] + p["p_filesz"] for p in seg)
            buf = bytearray(b"\xff" * (fine - inizio))
            for p in seg:
                buf[p["p_paddr"] - inizio: p["p_paddr"] - inizio + p["p_filesz"]] = p.data()
            return inizio, bytes(buf)
    raise FirmwareNonSupportato(f"formato {s} non gestito")


def e_cortex_m(base: int, img: bytes) -> bool:
    if len(img) < 8 or not (FLASH <= base < FLASH + 0x200000 or base == 0):
        return False
    sp, reset = struct.unpack("<II", img[:8])
    return 0x10000000 <= sp <= 0x20100000 and reset & 1 and base <= reset < base + len(img) + 0x08000000 * (base == 0)


def moduli_sorgente(img: bytes) -> list[str]:
    """Nomi dei file .c rimasti nel binario (di solito da assert o messaggi di errore)."""
    return sorted({m.group().decode() for m in re.finditer(rb"[A-Za-z_][A-Za-z0-9_]{1,40}\.c(?![A-Za-z0-9])", img)})


def testi(img: bytes, minimo: int = 6) -> list[str]:
    """Stringhe leggibili (messaggi, comandi AT, nomi): solo quelle con parole vere, non frammenti di codice."""
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minimo, img):
        t = m.group().decode().strip()
        parole = re.findall(r"[A-Za-z]{4,}", t)
        vere = [w for w in parole if w.islower() or w.isupper() or (w[0].isupper() and w[1:].islower())]
        ammessi = sum(c.isalnum() or c in " .,:;%-_=+/()!?#" for c in t) / max(len(t), 1)
        if vere and ammessi > 0.95 and sum(map(len, vere)) >= len(t.replace(" ", "")) * 0.5:
            out.append(t)
    return list(dict.fromkeys(out))[:80]


def disassembla(base: int, img: bytes, inizio: int | None = None, quante: int = 80) -> list[str]:
    from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    md.skipdata = True
    da = (inizio or struct.unpack("<I", img[4:8])[0]) & ~1
    off = da - base
    return [f"0x{i.address:08X}  {i.mnemonic} {i.op_str}" for i in md.disasm(img[off:off + quante * 4], da)][:quante]


def _emula(base: int, img: bytes, max_istruzioni: int) -> tuple[dict, dict, set, int]:
    from unicorn import (
        UC_ARCH_ARM,
        UC_HOOK_MEM_READ,
        UC_HOOK_MEM_UNMAPPED,
        UC_HOOK_MEM_WRITE,
        UC_MODE_THUMB,
        Uc,
        UcError,
    )
    from unicorn.arm_const import UC_ARM_REG_SP

    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    flash = base if base else FLASH
    dim = (len(img) + 0xFFFF) & ~0xFFFF
    for a in {flash, 0}:                       # all'avvio la flash è vista anche a 0
        uc.mem_map(a, max(dim, 0x10000))
        uc.mem_write(a, img)
    uc.mem_map(0x20000000, 0x80000)
    uc.mem_map(0x10000000, 0x10000)
    uc.mem_map(0x40000000, 0x20000000)         # periferiche
    uc.mem_map(0xE0000000, 0x100000)           # SysTick, NVIC, SCB
    # valori di reset dei GPIO: tutto analogico (0xFFFFFFFF) così un pin messo in ingresso (00) si vede
    for b in BASI_GPIO:
        for i in range(len(PORTE)):
            uc.mem_write(b + 0x400 * i, b"\xff\xff\xff\xff")
    for i in range(len(PORTE)):
        uc.mem_write(BASE_GPIO_F1 + 0x400 * i, struct.pack("<II", 0x44444444, 0x44444444))

    scritture: dict[int, int] = {}            # ultimo valore scritto per indirizzo
    bsrr: dict[int, dict[int, int]] = {}      # porta -> pin -> ultimo stato comandato
    toccati: set[int] = set()
    letture = {"ind": None, "n": 0}

    def scrive(uc, _acc, ind, dim_, val, _):
        if dim_ < 4:                           # scrittura a byte o mezza parola: ricompone il registro
            vecchio = struct.unpack("<I", uc.mem_read(ind & ~3, 4))[0]
            sh = (ind & 3) * 8
            maschera = ((1 << (dim_ * 8)) - 1) << sh
            val = (vecchio & ~maschera) | ((val << sh) & maschera)
            ind &= ~3
        scritture[ind] = val & 0xFFFFFFFF
        toccati.add(ind & ~0x3FF)
        off = ind & 0x3FF
        porta_base = ind & ~0x3FF
        if off == 0x18:                        # BSRR: bit 0-15 accendono, 16-31 spengono
            for b in range(16):
                if val >> (b + 16) & 1:
                    bsrr.setdefault(porta_base, {})[b] = 0
                if val >> b & 1:
                    bsrr.setdefault(porta_base, {})[b] = 1
        elif off == 0x28:                      # BRR
            for b in range(16):
                if val >> b & 1:
                    bsrr.setdefault(porta_base, {})[b] = 0

    def legge(uc, _acc, ind, dim_, _val, _):
        # Attese su un flag ("aspetta che il clock sia pronto"): l'hardware non c'è, quindi dopo molte letture
        # dello stesso registro si provano valori plausibili. Nei registri di stato degli STM32 il bit "pronto" o
        # il campo di stato sta poco sopra il bit di comando (HSION->HSIRDY, PLLON->PLLRDY, SW->SWS): si prova
        # l'ultimo valore scritto sommato a sé stesso spostato di 1, 2 o 3 bit, poi tutti 1 e tutti 0.
        if letture["ind"] == ind:
            letture["n"] += 1
            if letture["n"] % 30 == 0:
                a = ind & ~3
                w = scritture.get(a, struct.unpack("<I", uc.mem_read(a, 4))[0])
                prove = [w | w << 1, w | w << 2, w | w << 3, w | w << 1 | w << 2, 0xFFFFFFFF, 0, ~w]
                v = prove[(letture["n"] // 30 - 1) % len(prove)] & 0xFFFFFFFF
                uc.mem_write(a, struct.pack("<I", v))
        else:
            letture["ind"], letture["n"] = ind, 0

    def non_mappata(uc, _acc, ind, *_):
        try:
            uc.mem_map(ind & ~0xFFF, 0x1000)
            return True
        except UcError:
            return False

    uc.hook_add(UC_HOOK_MEM_WRITE, scrive, begin=0x40000000, end=0x5FFFFFFF)
    uc.hook_add(UC_HOOK_MEM_READ, legge, begin=0x40000000, end=0x5FFFFFFF)
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, non_mappata)
    sp, reset = struct.unpack("<II", img[:8])
    uc.reg_write(UC_ARM_REG_SP, sp)
    eseguite = 0
    try:
        uc.emu_start(reset | 1, 0xFFFFFFFE, count=max_istruzioni)
        eseguite = max_istruzioni
    except UcError:
        eseguite = -1                          # si è fermato su un'istruzione non emulabile: si usa quanto raccolto
    return scritture, bsrr, toccati, eseguite


def famiglia_da_mcu(mcu: str) -> int | str | None:
    """Base GPIO attesa dal codice del microcontrollore (es. 'STM32G031G8U6' -> 0x50000000)."""
    m = re.match(r"STM32([A-Z])(\d)", (mcu or "").upper())
    if not m:
        return None
    serie = m.group(1) + m.group(2)
    if serie in ("G0", "C0", "L0", "U0"):
        return 0x50000000
    if serie in ("F0", "F3", "G4", "L4", "L5", "WB", "U5", "H5"):
        return 0x48000000
    if serie == "F1":
        return "F1"
    if serie in ("F2", "F4", "F7", "L1"):
        return 0x40020000
    return None


def _scegli_base(scritture: dict, mcu: str = "") -> int | str | None:
    """Una sola famiglia: gli indirizzi GPIO di una famiglia coincidono con altre periferiche in un'altra."""
    attesa = famiglia_da_mcu(mcu)
    if attesa is not None:
        return attesa
    for b in (0x50000000, 0x48000000):
        if any(b + 0x400 * i in scritture for i in range(len(PORTE))):
            return b
    if any(0x40020000 + 0x400 * i in scritture for i in range(len(PORTE))):
        return 0x40020000
    if any(BASE_GPIO_F1 + 0x400 * i + o in scritture for i in range(len(PORTE)) for o in (0, 4)):
        return "F1"
    return None


def _decodifica_gpio(scritture: dict, bsrr: dict, mcu: str = "") -> tuple[str, list[dict]]:
    pin = []
    famiglia = ""
    scelta = _scegli_base(scritture, mcu)
    for b, fam in BASI_GPIO.items():
        if b != scelta:
            continue
        for i, lettera in enumerate(PORTE):
            pb = b + 0x400 * i
            moder = scritture.get(pb)
            if moder is None:
                continue
            famiglia = fam
            otyper = scritture.get(pb + 0x04, 0)
            pupdr = scritture.get(pb + 0x0C, 0)
            afr = scritture.get(pb + 0x20, 0) | scritture.get(pb + 0x24, 0) << 32
            for n in range(16):
                modo = moder >> (2 * n) & 3
                if modo == 3:
                    continue                   # analogico o non configurato: non distinguibili
                voce = {"pin": f"P{lettera}{n}", "modo": MODI[modo]}
                if modo in (1, 2):
                    voce["uscita"] = "open-drain" if otyper >> n & 1 else "push-pull"
                p = PULL.get(pupdr >> (2 * n) & 3, "")
                if p:
                    voce["pull"] = p
                if modo == 2:
                    voce["funzione_alternativa"] = f"AF{afr >> (4 * n) & 0xF}"
                if modo == 1 and n in bsrr.get(pb, {}):
                    voce["ultimo_comando"] = "alto" if bsrr[pb][n] else "basso"
                pin.append(voce)
    for i, lettera in enumerate(PORTE if scelta == "F1" else ""):        # F1
        pb = BASE_GPIO_F1 + 0x400 * i
        if pb not in scritture and pb + 4 not in scritture:
            continue
        famiglia = "F1"
        cr = scritture.get(pb, 0x44444444) | scritture.get(pb + 4, 0x44444444) << 32
        odr = scritture.get(pb + 0x0C, 0)
        for n in range(16):
            c = cr >> (4 * n) & 0xF
            mode, cnf = c & 3, c >> 2
            if c == 0x4:
                continue                       # ingresso flottante di reset
            if mode == 0:
                voce = {"pin": f"P{lettera}{n}", "modo": ["analogico", "ingresso", "ingresso", "?"][cnf]}
                if cnf == 2:
                    voce["pull"] = "pull-up" if odr >> n & 1 else "pull-down"
            else:
                voce = {"pin": f"P{lettera}{n}", "modo": "funzione alternativa" if cnf & 2 else "uscita",
                        "uscita": "open-drain" if cnf & 1 else "push-pull"}
            pin.append(voce)
    return famiglia, pin


def analizza(f: Path, cache: Path | None = None, mcu: str = "", max_istruzioni: int = 3_000_000) -> dict:
    """Scheda funzionale del firmware: pin configurati, periferiche usate, moduli e testi. Risultato in cache."""
    f = Path(f)
    dati = f.read_bytes()
    impronta = hashlib.sha1(dati).hexdigest()[:16]
    if cache:
        fc = Path(cache) / f"{impronta}_{mcu or 'x'}.json"
        if fc.exists():
            return json.loads(fc.read_text(encoding="utf-8"))
    base, img = leggi_immagine(f)
    if not e_cortex_m(base, img):
        raise FirmwareNonSupportato("non sembra un firmware ARM Cortex-M (STM32): per PIC e AVR serve un "
                                    "disassemblatore diverso, non ancora disponibile")
    scritture, bsrr, toccati, eseguite = _emula(base, img, max_istruzioni)
    famiglia, pin = _decodifica_gpio(scritture, bsrr, mcu)
    periferiche = sorted({PERIFERICHE[t] for t in toccati if t in PERIFERICHE})
    risultato = {
        "file": f.name, "sha1": impronta, "mcu": mcu or None, "indirizzo": f"0x{base:08X}", "byte": len(img),
        "famiglia_gpio": famiglia, "pin": pin, "periferiche_configurate": periferiche,
        "moduli_sorgente": moduli_sorgente(img), "testi": testi(img),
        "emulazione": "completata fino al limite di istruzioni" if eseguite > 0 else
                      "interrotta su un'istruzione non emulabile: i dati raccolti fino a quel punto sono validi",
        "limiti": "'ultimo_comando' è l'ultimo livello scritto su un'uscita durante l'emulazione, non lo stato a "
                  "regime. Un pin analogico (es. ingresso ADC) non si distingue da uno non usato; configurazioni fatte "
                  "più tardi nel ciclo principale o negli interrupt possono mancare. I nomi delle periferiche sono "
                  "indicativi: verificare con il manuale della famiglia.",
    }
    if cache:
        Path(cache).mkdir(parents=True, exist_ok=True)
        (Path(cache) / f"{impronta}_{mcu or 'x'}.json").write_text(json.dumps(risultato, ensure_ascii=False, indent=1),
                                                      encoding="utf-8")
    return risultato


def nome_pin_a_numero(piedinatura: dict | None) -> dict[str, str]:
    """Da una piedinatura del datasheet ({'pin': [{'numero','nome'}]}) la mappa 'PA2' -> '8'."""
    out = {}
    for p in (piedinatura or {}).get("pin", []):
        for nome in re.findall(r"P[A-K]\d{1,2}", str(p.get("nome", "")).upper()):
            out.setdefault(nome, str(p["numero"]))
    return out
