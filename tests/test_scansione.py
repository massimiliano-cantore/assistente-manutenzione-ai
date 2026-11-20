"""La scansione di una cartella con una sottocartella per prodotto prepara prodotti.yaml da sola."""
import shutil

import yaml

from app.elettrico.catalogo import Catalogo
from scripts.scansiona_documenti import scansiona
from tests.dati_elettrici import MADRE, RADIO, pdf_altium


def test_scansione_e_collegamento_suggerito(tmp_path):
    prodotto = tmp_path / "CentralinaProva"
    (prodotto / "radio").mkdir(parents=True)
    # nomi di segnale uguali sui pin dei connettori: lo script deve proporre il collegamento J4 <-> J1
    madre = {"componenti": MADRE["componenti"], "nets": {**MADRE["nets"], "TRX_CE": ["J4-1"]}}
    madre["nets"].pop("NetJ4_1")
    madre["nets"]["SPI_MISO"] = ["U3-1", "R10-1"]
    madre["nets"]["MISO_LINE"] = ["R10-2", "J4-1"]
    madre["nets"].pop("TRX_CE")
    madre["nets"]["CS_TRX"] = madre["nets"].pop("SPI_CS")
    radio = {"componenti": RADIO["componenti"], "nets": {**RADIO["nets"], "MISO_LINE": RADIO["nets"]["MISO"]}}
    radio["nets"].pop("MISO")
    madre["nets"]["AUX_LINE"] = []
    pdf_altium(prodotto / "SCH_MADRE_v1.0.pdf", {"componenti": madre["componenti"],
                                                 "nets": {k: v for k, v in madre["nets"].items() if v}})
    pdf_altium(prodotto / "radio" / "SCH_RADIO.pdf", radio)
    conf, rapporto = scansiona(tmp_path)
    assert {s["codice"] for s in conf["schede"]} == {"MADRE", "RADIO"}
    assert conf["prodotti"][0]["nome"] == "CentralinaProva"
    coll = conf["prodotti"][0]["collegamenti"]
    assert any("MANCA LA BOM" in r for r in rapporto)
    if coll:
        assert {coll[0]["da"], coll[0]["a"]} == {"MADRE.J4", "RADIO.J1"}
    (tmp_path / "prodotti.yaml").write_text(yaml.safe_dump(conf), encoding="utf-8")
    assert set(Catalogo.carica(tmp_path).schede) == {"MADRE", "RADIO"}
    shutil.rmtree(prodotto)
