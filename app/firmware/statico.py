"""Analisi statica del firmware per microcontrollori a 8 bit: PIC16 (midrange classico), PIC18 e AVR (ATmega).

Si scorre il codice istruzione per istruzione seguendo i valori caricati nei registri di lavoro (W per i PIC,
R0-R31 per gli AVR) e si registra cosa viene scritto nei registri di configurazione dei pin (TRIS / DDR) e delle
uscite (PORT / LAT), oltre ai registri delle periferiche toccati. È un'analisi lineare: non esegue il programma,
quindi il risultato dice quali pin il firmware configura e in che modo almeno una volta, non lo stato in un momento
preciso.
"""
from __future__ import annotations

import re
from collections import defaultdict

from intelhex import IntelHex

# --- risultato comune -----------------------------------------------------------------------------------------

class Registri:
    """Raccoglie le scritture: per ogni indirizzo i bit messi a 1, a 0 e se è stato scritto con valore ignoto."""

    def __init__(self):
        self.uno = defaultdict(int)
        self.zero = defaultdict(int)
        self.ignoto = set()
        self.toccati = set()

    def scrivi(self, ind: int, valore: int | None, larghezza: int = 8):
        self.toccati.add(ind)
        if valore is None:
            self.ignoto.add(ind)
            return
        m = (1 << larghezza) - 1
        self.uno[ind] |= valore & m
        self.zero[ind] |= ~valore & m

    def bit(self, ind: int, b: int, v: int):
        self.toccati.add(ind)
        (self.uno if v else self.zero)[ind] |= 1 << b


def _pin_da_tris(reg: Registri, porte: dict[str, tuple[int, int, int | None]], prefisso: str,
                 uscita_se_zero: bool, pull: dict[str, int] | None = None) -> list[dict]:
    """porte: lettera -> (indirizzo direzione, indirizzo uscita/latch, indirizzo latch alternativo o None)."""
    pin = []
    for lettera, (dir_, out, lat) in porte.items():
        if dir_ not in reg.toccati:            # direzione di reset (ingresso) ma pull-up attivato
            for n in range(8):
                if pull and pull.get(lettera, 0) >> n & 1 and not uscita_se_zero:
                    pin.append({"pin": f"{prefisso}{lettera}{n}", "modo": "ingresso", "pull": "pull-up"})
            continue
        verso_uscita = reg.zero[dir_] if uscita_se_zero else reg.uno[dir_]
        verso_ingresso = reg.uno[dir_] if uscita_se_zero else reg.zero[dir_]
        alto = reg.uno.get(out, 0) | (reg.uno.get(lat, 0) if lat else 0)
        basso = reg.zero.get(out, 0) | (reg.zero.get(lat, 0) if lat else 0)
        for n in range(8):
            nome = f"{prefisso}{lettera}{n}"
            if verso_uscita >> n & 1:
                voce = {"pin": nome, "modo": "uscita"}
                if verso_ingresso >> n & 1:
                    voce["nota"] = "configurato sia come uscita sia come ingresso in punti diversi del programma"
                if alto >> n & 1 or basso >> n & 1:
                    livelli = (("alto", alto >> n & 1), ("basso", basso >> n & 1))
                    voce["livelli_scritti"] = "/".join(x for x, c in livelli if c)
                pin.append(voce)
            elif verso_ingresso >> n & 1:
                voce = {"pin": nome, "modo": "ingresso"}
                if pull and lettera in pull and pull[lettera] >> n & 1:
                    voce["pull"] = "pull-up"
                pin.append(voce)
        if dir_ in reg.ignoto:
            pin.append({"pin": f"{prefisso}{lettera}*", "modo": "direzione scritta con un valore calcolato",
                        "nota": "il programma imposta la direzione della porta con un valore non costante"})
    return pin


def _periferiche(reg: Registri, nomi: dict[int, str]) -> list[str]:
    return sorted({nomi[a] for a in reg.toccati if a in nomi})


def _parole(ih: IntelHex, fine_byte: int) -> list[tuple[int, int]]:
    """(indirizzo in byte, parola a 16 bit little-endian) delle zone di programma presenti nel file."""
    out = []
    for inizio, fine in ih.segments():
        for a in range(inizio & ~1, min(fine, fine_byte), 2):
            out.append((a, ih[a] | ih[a + 1] << 8))
    return out


# --- PIC16 midrange classico (16F6xx, 16F8xx, 12F6xx) ------------------------------------------------------------

PIC16_SFR = {0x01: "TMR0", 0x0B: "INTCON", 0x0C: "PIR1", 0x10: "T1CON", 0x12: "T2CON", 0x14: "SSPCON",
             0x15: "CCPR1L", 0x17: "CCP1CON", 0x18: "RCSTA", 0x19: "TXREG", 0x1D: "CCP2CON", 0x1F: "CMCON/ADCON0",
             0x81: "OPTION_REG", 0x8C: "PIE1", 0x92: "PR2", 0x93: "SSPADD", 0x95: "WPU/WPUB", 0x96: "IOC/IOCB",
             0x98: "TXSTA", 0x99: "SPBRG", 0x9B: "ANSEL", 0x9C: "CMCON (16F88x)", 0x9F: "ADCON1/ANSEL",
             0x10C: "EEDATA", 0x10D: "EEADR", 0x18C: "EECON1", 0x188: "ANSEL (16F88x)", 0x189: "ANSELH"}
PIC16_FUNZIONI = {"TXSTA": "seriale (USART)", "RCSTA": "seriale (USART)", "SSPCON": "SPI/I2C (MSSP)",
                  "CCP1CON": "PWM/cattura (CCP1)", "CCP2CON": "PWM/cattura (CCP2)", "T1CON": "timer 1",
                  "T2CON": "timer 2", "ADCON1/ANSEL": "convertitore A/D o ingressi analogici",
                  "CMCON/ADCON0": "comparatore o convertitore A/D", "EECON1": "EEPROM interna"}


def analizza_pic16(ih: IntelHex, mcu: str = "") -> dict:
    reg = Registri()
    w, banco = None, 0
    for _a, parola in _parole(ih, 0x4000):
        p = parola & 0x3FFF
        if p & 0x3C00 == 0x3000:                    # movlw k
            w = p & 0xFF
        elif p & 0x3F00 == 0x3800:                  # iorlw
            w = None if w is None else w | p & 0xFF
        elif p & 0x3F00 == 0x3900:                  # andlw
            w = None if w is None else w & p & 0xFF
        elif p & 0x3F00 == 0x3A00:                  # xorlw
            w = None if w is None else w ^ p & 0xFF
        elif p & 0x3F80 == 0x0080:                  # movwf f
            f = p & 0x7F
            reg.scrivi(_ind16(f, banco), w)
        elif p & 0x3F80 == 0x0180:                  # clrf f
            reg.scrivi(_ind16(p & 0x7F, banco), 0)
        elif p & 0x3800 == 0x1000:                  # bcf/bsf f,b
            f, b, v = p & 0x7F, p >> 7 & 7, p >> 10 & 1
            if f == 0x03 and b in (5, 6):           # STATUS: RP0 / RP1 cambiano banco
                banco = banco | 1 << (b - 5) if v else banco & ~(1 << (b - 5))
            else:
                reg.bit(_ind16(f, banco), b, v)
        elif p & 0x3000 == 0x2000:                  # call / goto: W e banco non più certi dopo una call
            if not p & 0x0800:
                w = None
        elif p & 0x3000 == 0x0000 and p & 0x0080 == 0 and p not in (0, 0x0008, 0x0009, 0x0062, 0x0063, 0x0064):
            w = None                                # operazione con risultato in W
    gp = (mcu or "").upper().startswith(("PIC12", "12F"))
    porte = {"A": (0x85, 0x05, None), "B": (0x86, 0x06, None), "C": (0x87, 0x07, None), "D": (0x88, 0x08, None),
             "E": (0x89, 0x09, None)}
    if gp:
        porte = {"": (0x85, 0x05, None)}
    pull = {}
    if 0x81 in reg.zero and reg.zero[0x81] & 0x80:   # OPTION_REG.nRBPU = 0: pull-up deboli su PORTB
        pull["A" if gp else "B"] = 0xFF
    pin = _pin_da_tris(reg, porte, "GP" if gp else "R", uscita_se_zero=True, pull=pull)
    per = _periferiche(reg, PIC16_SFR)
    return {"architettura": "PIC16 (midrange)", "pin": pin, "registri_periferiche": per,
            "periferiche_configurate": sorted({PIC16_FUNZIONI[p] for p in per if p in PIC16_FUNZIONI})}


def _ind16(f: int, banco: int) -> int:
    return f if 0x70 <= f <= 0x7F else banco * 0x80 + f


# --- PIC18 ------------------------------------------------------------------------------------------------------

PIC18_SFR = {0xF92: "TRISA", 0xF93: "TRISB", 0xF94: "TRISC", 0xF95: "TRISD", 0xF96: "TRISE", 0xFF1: "INTCON2",
             0xFF2: "INTCON", 0xFC1: "ADCON1", 0xFC2: "ADCON0", 0xFC0: "ADCON2", 0xFAC: "TXSTA", 0xFAB: "RCSTA",
             0xFAF: "SPBRG", 0xFB8: "BAUDCON", 0xFD5: "T0CON", 0xFCD: "T1CON", 0xFCA: "T2CON", 0xFCB: "PR2",
             0xFBD: "CCP1CON", 0xFBA: "CCP2CON", 0xFC6: "SSPCON1", 0xFC5: "SSPCON2", 0xFB4: "CMCON", 0xFA6: "EECON1",
             0xF9D: "PIE1", 0xF38: "ANSELA", 0xF39: "ANSELB", 0xF3A: "ANSELC", 0xF7E: "ANSEL/ANSELH", 0xF85: "WPUB",
             0xF7F: "ANSELH"}
PIC18_FUNZIONI = {"TXSTA": "seriale (EUSART)", "RCSTA": "seriale (EUSART)", "BAUDCON": "seriale (EUSART)",
                  "SSPCON1": "SPI/I2C (MSSP)", "SSPCON2": "I2C (MSSP)", "CCP1CON": "PWM/cattura (CCP1)",
                  "CCP2CON": "PWM/cattura (CCP2)", "T0CON": "timer 0", "T1CON": "timer 1", "T2CON": "timer 2",
                  "ADCON0": "convertitore A/D", "ADCON1": "convertitore A/D o ingressi analogici",
                  "CMCON": "comparatore", "EECON1": "EEPROM interna", "ANSELA": "ingressi analogici",
                  "ANSELB": "ingressi analogici", "ANSELC": "ingressi analogici", "ANSEL/ANSELH": "ingressi analogici",
                  "WPUB": "pull-up su PORTB"}


def analizza_pic18(ih: IntelHex, mcu: str = "") -> dict:
    reg = Registri()
    parole = _parole(ih, 0x200000)
    w, bsr = None, 0
    i = 0
    while i < len(parole):
        a, p = parole[i]
        hi = p >> 8
        if hi == 0x0E:                               # movlw
            w = p & 0xFF
        elif hi == 0x09:
            w = None if w is None else w | p & 0xFF  # iorlw
        elif hi == 0x0B:
            w = None if w is None else w & p & 0xFF  # andlw
        elif hi == 0x0A:
            w = None if w is None else w ^ p & 0xFF  # xorlw
        elif p & 0xFFF0 == 0x0100:                   # movlb
            bsr = p & 0xF
        elif hi in (0x6E, 0x6F):                     # movwf f,a
            reg.scrivi(_ind18(p & 0xFF, hi & 1, bsr), w)
        elif hi in (0x6A, 0x6B):                     # clrf
            reg.scrivi(_ind18(p & 0xFF, hi & 1, bsr), 0)
        elif hi in (0x68, 0x69):                     # setf
            reg.scrivi(_ind18(p & 0xFF, hi & 1, bsr), 0xFF)
        elif 0x80 <= hi <= 0x9F:                     # bsf (1000) / bcf (1001) f,b,a
            reg.bit(_ind18(p & 0xFF, hi & 1, bsr), hi >> 1 & 7, 1 if hi < 0x90 else 0)
        elif p & 0xF000 == 0xC000 and i + 1 < len(parole) and parole[i + 1][1] & 0xF000 == 0xF000:   # movff
            reg.scrivi(parole[i + 1][1] & 0xFFF, None)
            i += 1
        elif p & 0xFF00 == 0xEC00 or p & 0xF800 == 0xD800:   # call / rcall
            w = None
        elif hi in (0x50, 0x51) or (hi & 0xFC) in (0x24, 0x28, 0x14, 0x10, 0x18, 0x1C, 0x04, 0x34, 0x30, 0x38):
            w = None                                 # movf / addwf / incf / andwf / iorwf ... con risultato in W
        i += 1
    porte = {lettera: (0xF92 + k, 0xF80 + k, 0xF89 + k) for k, lettera in enumerate("ABCDE")}
    pull = {}
    if reg.zero.get(0xFF1, 0) & 0x80:                # INTCON2.nRBPU = 0
        pull["B"] = 0xFF
    if 0xF85 in reg.toccati:
        pull["B"] = reg.uno.get(0xF85, 0xFF)
    pin = _pin_da_tris(reg, porte, "R", uscita_se_zero=True, pull=pull)
    per = _periferiche(reg, PIC18_SFR)
    return {"architettura": "PIC18", "pin": pin, "registri_periferiche": [p for p in per if not p.startswith("TRIS")],
            "periferiche_configurate": sorted({PIC18_FUNZIONI[p] for p in per if p in PIC18_FUNZIONI})}


def _ind18(f: int, a: int, bsr: int) -> int:
    if a == 0:
        return 0xF00 + f if f >= 0x60 else f
    return bsr << 8 | f


# --- AVR (ATmega) -----------------------------------------------------------------------------------------------

# indirizzi I/O (come in OUT/SBI) di PIN, DDR, PORT. Gli ATmega recenti hanno A..D a partire da 0x00;
# quelli vecchi (ATmega8/16/32/8535/162) da PORTA=0x1B in giù.
AVR_PORTE_NUOVI = {"A": 0x00, "B": 0x03, "C": 0x06, "D": 0x09}
AVR_PORTE_VECCHI = {"A": 0x19, "B": 0x16, "C": 0x13, "D": 0x10}
AVR_NUOVI_SFR = {0x44 - 0x20: "TCCR0A", 0x45 - 0x20: "TCCR0B", 0x80: "TCCR1A", 0x81: "TCCR1B", 0xB0: "TCCR2A",
                 0xB1: "TCCR2B", 0xC1: "UCSR0B", 0xC2: "UCSR0C", 0xC4: "UBRR0L", 0xC9: "UCSR1B", 0xCA: "UCSR1C",
                 0xCC: "UBRR1L", 0x4C - 0x20: "SPCR", 0xBC: "TWCR", 0xB8: "TWBR", 0x7A: "ADCSRA", 0x7C: "ADMUX",
                 0x7E: "DIDR0", 0x69: "EICRA", 0x68: "PCICR", 0x60: "WDTCSR", 0x3F - 0x20: "EECR", 0x6E: "TIMSK0",
                 0x6F: "TIMSK1"}
AVR_VECCHI_SFR = {0x0A: "UCSRB", 0x09: "UBRRL", 0x0D: "SPCR", 0x36 + 0x20: "TWCR", 0x06: "ADCSRA", 0x07: "ADMUX",
                  0x33: "TCCR0", 0x2F: "TCCR1A", 0x2E: "TCCR1B", 0x25: "TCCR2", 0x35: "MCUCR", 0x3B: "GICR",
                  0x21: "WDTCR", 0x1C: "EECR", 0x39: "TIMSK"}
AVR_FUNZIONI = {"UCSR0B": "seriale USART0", "UCSR1B": "seriale USART1", "UCSRB": "seriale USART", "SPCR": "SPI",
                "TWCR": "I2C (TWI)", "ADCSRA": "convertitore A/D", "ADMUX": "convertitore A/D",
                "TCCR0A": "timer 0", "TCCR0B": "timer 0", "TCCR0": "timer 0", "TCCR1A": "timer 1 (PWM?)",
                "TCCR1B": "timer 1", "TCCR2A": "timer 2", "TCCR2B": "timer 2", "TCCR2": "timer 2",
                "WDTCSR": "watchdog", "WDTCR": "watchdog", "EECR": "EEPROM interna", "EICRA": "interrupt esterni",
                "PCICR": "interrupt su cambio pin", "GICR": "interrupt esterni"}


def analizza_avr(ih: IntelHex, mcu: str = "") -> dict:
    vecchio = bool(re.match(r"(?i)ATMEGA(8|16|32|64|128|8535|162|8515)(A|L)?$", (mcu or "").upper().split("-")[0]))
    reg = Registri()
    r: list[int | None] = [None] * 32
    io_valore: dict[int, int | None] = {}
    parole = _parole(ih, 0x40000)
    i = 0
    while i < len(parole):
        _, p = parole[i]
        due = p & 0xFE0F in (0x9000, 0x9200) or p & 0xFE0E in (0x940C, 0x940E)   # lds/sts/jmp/call: 2 parole
        if p & 0xF000 == 0xE000:                                 # ldi Rd,K
            r[16 + (p >> 4 & 0xF)] = (p >> 4 & 0xF0) | (p & 0xF)
        elif p & 0xF000 == 0x6000:                               # ori
            d = 16 + (p >> 4 & 0xF)
            r[d] = None if r[d] is None else r[d] | ((p >> 4 & 0xF0) | (p & 0xF))
        elif p & 0xF000 == 0x7000:                               # andi
            d = 16 + (p >> 4 & 0xF)
            r[d] = None if r[d] is None else r[d] & ((p >> 4 & 0xF0) | (p & 0xF))
        elif p & 0xFC00 == 0x2400:                               # eor (clr se Rd==Rr)
            d, rr = p >> 4 & 0x1F, (p & 0xF) | (p >> 5 & 0x10)
            r[d] = 0 if d == rr else None
        elif p & 0xFC00 == 0x2C00:                               # mov
            r[p >> 4 & 0x1F] = r[(p & 0xF) | (p >> 5 & 0x10)]
        elif p & 0xF800 == 0xB800:                               # out A,Rr
            ind = (p & 0xF) | (p >> 5 & 0x30)
            v = r[p >> 4 & 0x1F]
            reg.scrivi(ind, v)
            io_valore[ind] = v
        elif p & 0xF800 == 0xB000:                               # in Rd,A
            r[p >> 4 & 0x1F] = io_valore.get((p & 0xF) | (p >> 5 & 0x30))
        elif p & 0xFE0F == 0x9200 and i + 1 < len(parole):       # sts k,Rr (indirizzo di memoria)
            k = parole[i + 1][1]
            reg.scrivi(k - 0x20 if 0x20 <= k < 0x60 else k, r[p >> 4 & 0x1F])
        elif p & 0xFE0F == 0x9000:                               # lds
            r[p >> 4 & 0x1F] = None
        elif p & 0xFD00 == 0x9800:                               # cbi (0x98) / sbi (0x9A) A,b
            reg.bit(p >> 3 & 0x1F, p & 7, 1 if p & 0x0200 else 0)
        elif p & 0xFE0E in (0x940E,) or p & 0xF000 == 0xD000:   # call / rcall
            r = [None] * 32
        elif p & 0xFC00 in (0x0C00, 0x1C00, 0x1800, 0x0800, 0x2000, 0x2800, 0x9400) or p & 0xF000 in (0x5000,
                                                                                                    0x4000, 0x8000,
                                                                                                    0xA000):
            if p & 0xF000 in (0x8000, 0xA000) or p & 0xFC00 != 0x9400:
                r[p >> 4 & 0x1F] = None                          # aritmetica / carichi da memoria: valore ignoto
        i += 2 if due else 1
    tabella = AVR_PORTE_VECCHI if vecchio else AVR_PORTE_NUOVI
    porte = {lettera: (b + 1, b + 2, None) for lettera, b in tabella.items()}
    pull = {lettera: reg.uno.get(b + 2, 0) for lettera, b in tabella.items()}
    pin = _pin_da_tris(reg, porte, "P", uscita_se_zero=False, pull=pull)
    nomi = AVR_VECCHI_SFR if vecchio else AVR_NUOVI_SFR
    per = _periferiche(reg, nomi)
    return {"architettura": "AVR (ATmega)" + (" serie vecchia" if vecchio else ""), "pin": pin,
            "registri_periferiche": per,
            "periferiche_configurate": sorted({AVR_FUNZIONI[p] for p in per if p in AVR_FUNZIONI})}


LIMITI_STATICI = ("Analisi statica: dice quali pin il firmware configura come uscita o ingresso in almeno un punto "
                  "del programma e quali periferiche imposta; non lo stato in un momento preciso. Un pin lasciato "
                  "come al reset (ingresso) non compare. Le funzioni speciali dei pin (seriale, PWM, A/D) dipendono "
                  "dalle periferiche attive: verificarle con la piedinatura del datasheet.")
