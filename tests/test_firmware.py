from pathlib import Path

from app.elettrico.modello import Componente, Scheda
from app.firmware import inventario as fw


def _riga(n_ind: int, tipo: int, dati: bytes) -> str:
    corpo = bytes([len(dati), n_ind >> 8, n_ind & 0xFF, tipo]) + dati
    return ":" + (corpo + bytes([(-sum(corpo)) & 0xFF])).hex().upper()


def test_info_hex_stm32(tmp_path: Path):
    f = tmp_path / "app.hex"
    f.write_text("\n".join([_riga(0, 4, b"\x08\x00"), _riga(0, 0, b"\x01" * 16), _riga(16, 0, b"\x02" * 16),
                            _riga(0, 1, b"")]))
    i = fw.info_hex(f)
    assert i["byte"] == 32 and i["intervalli"] == ["0x08000000-0x0800001F"]
    assert "STM32" in i["famiglia_probabile"] and i["errori_checksum"] == 0


def test_tipo_e_mcu():
    assert fw.tipo(Path("a.HEX")) == ("binario", "hex")
    assert fw.tipo(Path("main.c")) == ("sorgente", "c")
    assert fw.tipo(Path("x.uvprojx")) == ("progetto", "Keil")
    assert fw.tipo(Path("note.txt")) is None
    s = Scheda(codice="MADRE", componenti={"U3": Componente("U3", valore="PIC18F46K22-I/PT"),
                                            "R1": Componente("R1", valore="10K")})
    assert fw.mcu_della_scheda(s) == [("U3", "PIC18F46K22")]


def test_associa(tmp_path: Path):
    f = tmp_path / "firmware" / "MADRE_v2.hex"
    f.parent.mkdir()
    f.write_text("")
    assert fw.associa(f, {"MADRE": [], "RADIO": [("U1", "NRF52832")]}, tmp_path) == "MADRE"
    g = tmp_path / "firmware" / "release.hex"
    g.write_text("")
    assert fw.associa(g, {"MADRE": [], "RADIO": [("U1", "NRF52832")]}, tmp_path) == "RADIO"
