"""Ricerca datasheet ed estrazione della piedinatura, con fonti e download finti (nessuna rete)."""
import pytest

from app.agente.strumenti_elettrici import crea_strumenti_elettrici
from app.datasheet.fonti import FonteMouser, varianti
from app.datasheet.servizio import Piedinatura, Pin, ServizioDatasheet, confronta_con_netlist, pagine_con_pin
from app.elettrico.catalogo import Catalogo
from tests.dati_elettrici import cartella_azienda


class FonteFinta:
    nome, disponibile = "finta", True

    def __init__(self, conosciuti):
        self.conosciuti, self.cercati = conosciuti, []

    def cerca(self, codice):
        self.cercati.append(codice)
        return [{"codice": codice, "produttore": "Nordic", "descrizione": "", "url": f"https://x.com/{codice}.pdf",
                 "fonte": self.nome, "ufficiale": True}] if codice in self.conosciuti else []


def estrattore_finto(testo, codice, n_pin, package):
    assert "Pin description" in testo
    return Piedinatura(package="QFN6", pin=[
        Pin(numero="1", nome="MISO", tipo="uscita", funzione="dati SPI verso l'MCU"),
        Pin(numero="2", nome="CSN", tipo="ingresso", funzione="chip select SPI, attivo basso"),
        Pin(numero="3", nome="VDD", tipo="alimentazione", funzione="alimentazione 1,9-3,6 V"),
        Pin(numero="4", nome="VSS", tipo="massa", funzione="massa"),
        Pin(numero="5", nome="XC1", tipo="clock", funzione="ingresso del quarzo"),
        Pin(numero="9", nome="NC", tipo="non collegato", funzione="")])


@pytest.fixture
def servizio(tmp_path, monkeypatch):
    s = ServizioDatasheet(tmp_path / "cache", fonti=[FonteFinta({"NRF905", "STM32F401"})],
                          estrattore=estrattore_finto)
    monkeypatch.setattr(s, "scarica", lambda url: b"%PDF finto")
    monkeypatch.setattr("app.datasheet.servizio.testo_pagine",
                        lambda pdf: ["Introduzione", "Pin description\n1 MISO\n2 CSN\n3 VDD", "Fine"])
    return s


def test_varianti_per_compatibili():
    assert varianti("STM32F401VDT6") == ["STM32F401VDT", "STM32F401"]
    assert varianti("SIM800C S2-108K7-Z1L1D")[0] == "SIM800C"
    assert varianti("NRF905") == []


def test_trova_esatto_e_compatibile(servizio):
    assert servizio.trova("NRF905")["compatibile"] is False
    t = servizio.trova("STM32F401VDT6")
    assert t["compatibile"] is True and t["trovato_con"] == "STM32F401"


def test_piedinatura_e_cache(servizio):
    p = servizio.piedinatura("NRF905", n_pin=6)
    assert p["da_cache"] is False and p["pin"][4]["nome"] == "XC1"
    assert servizio.piedinatura("NRF905")["da_cache"] is True              # la seconda volta non si cerca più
    c = confronta_con_netlist(p, {"1", "2", "3", "4", "5", "6"})
    assert c["pin_senza_descrizione"] == ["6"] and c["pin_del_datasheet_non_presenti"] == ["9"]


def test_pagine_con_pin():
    pagine = ["Descrizione generale", "Table 3. Pin description\n1 TRX_CE\n2 PWR_UP\n3 uPCLK", "Elettriche"]
    assert "pagina 2" in pagine_con_pin(pagine)


def test_strumento_piedinatura_unisce_datasheet_e_netlist(servizio, tmp_path):
    catalogo = Catalogo.carica(cartella_azienda(tmp_path))
    strumenti = {t.name: t for t in crea_strumenti_elettrici(catalogo, servizio, tmp_path / "img")}
    r = strumenti["piedinatura_componente"].invoke({"scheda": "RADIO", "designator": "U1"})
    xc1 = next(p for p in r["pin"] if p["nome"] == "XC1")
    assert xc1["net"] == "NetY1_1" and set(xc1["collegato_a"]) == {"Y1-1", "R4-1"}
    cs = next(p for p in r["pin"] if p["nome"] == "CSN")
    assert cs["verso_altra_scheda"] == "RADIO:J1-2" or cs["net"] == "CS_TRX"
    assert r["copertura"] == pytest.approx(0.83, abs=0.01) and r["avviso"] is None


def test_senza_chiavi_lo_dice(tmp_path, monkeypatch):
    monkeypatch.delenv("MOUSER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    s = ServizioDatasheet(tmp_path, estrattore=estrattore_finto)
    with pytest.raises(RuntimeError, match="MOUSER_API_KEY"):
        s.trova("NRF905")


def test_mouser_legge_la_risposta():
    class Http:
        def post(self, url, params, json):
            class R:
                def raise_for_status(self): ...
                def json(self):
                    return {"Errors": [], "SearchResults": {"Parts": [{"ManufacturerPartNumber": "NRF905-REEL",
                            "Manufacturer": "Nordic", "Description": "RF Transceiver",
                            "DataSheetUrl": "https://www.mouser.com/datasheet/nrf905.pdf"}]}}
            return R()
    r = FonteMouser(chiave="k", http=Http()).cerca("NRF905")
    assert r[0]["url"].endswith("nrf905.pdf") and r[0]["ufficiale"]
