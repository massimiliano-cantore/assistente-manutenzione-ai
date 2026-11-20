"""Lettura della documentazione elettronica e operazioni sul circuito, su dati finti (mai documenti reali)."""
import pytest

from app.elettrico import altium_pdf, bom
from app.elettrico.catalogo import Catalogo
from app.elettrico.evidenzia import evidenzia
from tests.dati_elettrici import cartella_azienda


@pytest.fixture(scope="module")
def cartella(tmp_path_factory):
    return cartella_azienda(tmp_path_factory.mktemp("azienda"))


@pytest.fixture(scope="module")
def catalogo(cartella):
    return Catalogo.carica(cartella)


def test_importa_pdf_altium(cartella):
    s = altium_pdf.importa(cartella / "RADIO.pdf", "RADIO")
    assert set(s.componenti) == {"U1", "J1", "Y1", "R4"} and s.componenti["U1"].pin == {"1", "2", "3", "4", "5", "6"}
    assert s.nets["NetY1_1"] == {"U1-5", "Y1-1", "R4-1"} and s.net_del_pin("J1-2") == "CS_TRX"
    assert any("THD to SMD" in n for n in s.note)                      # note di revisione dal cartiglio
    assert altium_pdf.posizioni(cartella / "RADIO.pdf", ["Y1", "ZZ9"]).keys() == {"Y1"}


def test_bom(cartella):
    assert bom.espandi_designator("R1, R2, R5-R7") == ["R1", "R2", "R5", "R6", "R7"]
    comp = {c.designator: c for c in bom.leggi(cartella / "bom_madre.csv")}
    assert comp["U3"].valore == "STM32F401VDT6" and comp["U3"].footprint == "LQFP-100"
    assert comp["C1"].montato is False and comp["R10"].montato is True


def test_catalogo_e_integrazioni(catalogo):
    p = catalogo.panoramica()
    assert p["prodotti"][0]["collegamenti"] == ["MADRE.J4 <-> RADIO.J1"]
    assert catalogo.info_componente("radio", "U1")["valore"] == "NRF905"      # integrazione a mano nel yaml
    assert catalogo.cerca_componenti("transceiver")[0]["designator"] == "U1"


def test_collegamenti_oltre_il_connettore(catalogo):
    c = catalogo.collegati("RADIO", "J1-3")
    assert c["net"] == "+3V3" and c["su_altre_schede"][0]["tramite"] == "RADIO:J1-3 -> MADRE:J4-3"
    info = catalogo.info_componente("MADRE", "J4")
    assert {x["pin"]: x["verso_altra_scheda"] for x in info["pin"]}["2"] == "RADIO:J1-2"


def test_percorso_tra_schede_attraverso_resistenza(catalogo):
    p = catalogo.percorso("MADRE", "U3-1", "RADIO", "U1-1")
    assert p["trovato"] and p["componenti_attraversati"] == ["R10"]
    assert any(x["come"] == "connettore verso la scheda RADIO" for x in p["passi"])
    assert not catalogo.percorso("MADRE", "U3-1", "RADIO", "U1-5")["trovato"]


def test_sottocircuito_esclude_alimentazioni(catalogo):
    s = catalogo.sottocircuito("RADIO", "U1")
    assert {v["designator"] for v in s["vicini"]} == {"J1", "Y1", "R4"}
    assert s["alimentazioni"] == ["+3V3", "GND"]


def test_evidenzia(cartella, tmp_path):
    r = evidenzia(str(cartella / "RADIO.pdf"), ["Y1", "R4", "NONCE"], tmp_path)
    assert (tmp_path / r["immagine"]).stat().st_size > 1000 and r["non_trovati"] == ["NONCE"]
