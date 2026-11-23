import struct
from pathlib import Path

import pytest

pytest.importorskip("unicorn")
pytest.importorskip("capstone")
from intelhex import IntelHex  # noqa: E402

from app.agente.strumenti_firmware import crea_strumenti_firmware, scegli_file  # noqa: E402
from app.elettrico.catalogo import Catalogo  # noqa: E402
from app.elettrico.modello import Componente, Scheda  # noqa: E402
from app.firmware import stm32  # noqa: E402

# Firmware minimo per STM32G0: PA2 in uscita (MODER), poi PA2 alto (BSRR), poi ciclo infinito
CODICE = struct.pack("<II", 0x20001000, 0x08000009) + struct.pack(
    "<HHHHHH", 0x4802, 0x4903, 0x6001, 0x2204, 0x6182, 0xE7FE) + struct.pack("<II", 0x50000000, 0xFFFFFFDF)


def _hex(cartella: Path, nome: str = "app_v1.hex") -> Path:
    ih = IntelHex()
    ih.frombytes(CODICE, offset=0x08000000)
    f = cartella / nome
    ih.write_hex_file(str(f))
    return f


def test_analizza_pin(tmp_path: Path):
    r = stm32.analizza(_hex(tmp_path), cache=tmp_path / "c")
    assert r["famiglia_gpio"].startswith("G0")
    assert r["pin"] == [{"pin": "PA2", "modo": "uscita", "uscita": "push-pull", "ultimo_comando": "alto"}]
    assert list((tmp_path / "c").glob("*.json"))          # in cache


def test_non_arm(tmp_path: Path):
    f = tmp_path / "pic.hex"
    ih = IntelHex()
    ih.frombytes(b"\x01\x02" * 64, offset=0)
    ih.write_hex_file(str(f))
    with pytest.raises(stm32.FirmwareNonSupportato):
        stm32.analizza(f)


def test_strumento_incrocia_schema(tmp_path: Path):
    (tmp_path / "fw").mkdir()
    _hex(tmp_path, "fw/app_v1.hex")
    _hex(tmp_path, "fw/app_v2.hex")
    s = Scheda(codice="MAIN", componenti={"U1": Componente("U1", valore="STM32G031G8U6", pin={"8"}),
                                         "R5": Componente("R5", pin={"1", "2"})},
               nets={"RELE": {"U1-8", "R5-1"}})
    cat = Catalogo({"MAIN": s}, [], tmp_path,
                   firmware={"MAIN": [{"file": "fw/app_v1.hex", "formato": "hex", "famiglia": "STM32"},
                                      {"file": "fw/app_v2.hex", "formato": "hex", "famiglia": "STM32"}]},
                   extra={"MAIN": {"piedinatura_mcu": {"PA2": 8}}})
    firmware_scheda = {t.name: t for t in crea_strumenti_firmware(cat, None)}["firmware_scheda"]
    r = firmware_scheda.invoke({"scheda": "MAIN"})
    assert r["file"] == "app_v2.hex" and r["microcontrollore"] == "U1 STM32G031G8U6"
    assert r["pin"][0]["pin_componente"] == "U1-8" and r["pin"][0]["net"] == "RELE"
    assert r["pin"][0]["collegato_a"] == ["R5-1"]


def test_scegli_versione_piu_recente():
    f = [{"file": "a/x_v00_00_9.hex", "famiglia": "STM32"}, {"file": "a/x_v00_00_10.hex", "famiglia": "STM32"}]
    assert scegli_file(f)["file"].endswith("_10.hex")
    assert scegli_file(f, "00_9")["file"].endswith("_9.hex")
