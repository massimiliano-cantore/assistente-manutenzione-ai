import struct
from pathlib import Path

from intelhex import IntelHex

from app.firmware import analisi


def _hex(tmp: Path, parole: list[int], nome: str) -> Path:
    ih = IntelHex()
    ih.frombytes(struct.pack(f"<{len(parole)}H", *parole), offset=0)
    f = tmp / nome
    ih.write_hex_file(str(f))
    return f


def _pin(r):
    return {p["pin"]: p for p in r["pin"]}


def test_pic16(tmp_path: Path):
    # bsf STATUS,RP0 ; movlw 0xF0 ; movwf TRISB ; bcf OPTION_REG,7 ; bcf STATUS,RP0 ; bsf PORTB,0 ; goto $
    f = _hex(tmp_path, [0x1683, 0x30F0, 0x0086, 0x1381, 0x1283, 0x1406, 0x2806], "pic16.hex")
    r = analisi.analizza(f, mcu="PIC16F628A")
    p = _pin(r)
    assert r["architettura"].startswith("PIC16")
    assert p["RB0"]["modo"] == "uscita" and p["RB0"]["livelli_scritti"] == "alto"
    assert p["RB3"]["modo"] == "uscita"
    assert p["RB5"] == {"pin": "RB5", "modo": "ingresso", "pull": "pull-up"}
    assert "OPTION_REG" in r["registri_periferiche"]


def test_pic18(tmp_path: Path):
    # movlw 0x0F ; movwf TRISC ; bsf LATC,4 ; movlw 0x24 ; movwf TXSTA ; bra $
    f = _hex(tmp_path, [0x0E0F, 0x6E94, 0x888B, 0x0E24, 0x6EAC, 0xD7FF], "pic18.hex")
    r = analisi.analizza(f, mcu="PIC18F2520")
    p = _pin(r)
    assert p["RC4"]["modo"] == "uscita" and p["RC4"]["livelli_scritti"] == "alto"
    assert p["RC0"]["modo"] == "ingresso"
    assert "seriale (EUSART)" in r["periferiche_configurate"]


def test_avr(tmp_path: Path):
    # ldi r24,0x0F ; out DDRB,r24 ; sbi PORTB,5 ; sbi PORTD,2 ; ldi r24,0x18 ; sts UCSR0B,r24 ; rjmp .-2
    f = _hex(tmp_path, [0xE08F, 0xB984, 0x9A2D, 0x9A5A, 0xE188, 0x9380, 0x00C1, 0xCFFF], "avr.hex")
    r = analisi.analizza(f, mcu="ATMEGA324A")
    p = _pin(r)
    assert all(p[f"PB{n}"]["modo"] == "uscita" for n in range(4))
    assert p["PB5"] == {"pin": "PB5", "modo": "ingresso", "pull": "pull-up"}
    assert p["PD2"]["pull"] == "pull-up"
    assert "seriale USART0" in r["periferiche_configurate"]
