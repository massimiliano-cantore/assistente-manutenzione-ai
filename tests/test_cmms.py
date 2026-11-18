import pytest

from app.cmms.client import ErroreCMMS


def test_cerca_impianti(cmms):
    imp = cmms.cerca_impianti(cliente="nova")
    assert imp and all("NOVA" in i["cliente"] for i in imp)
    assert cmms.cerca_impianti(seriale=imp[0]["seriale"])[0]["id"] == imp[0]["id"]


def test_ricambio(cmms):
    r = cmms.ricambio("scb1180")
    assert r["codice"] == "SCB1180" and "sotto_scorta" in r
    assert cmms.ricambio("NONESISTE") is None


def test_crea_ordine_e_validazione(cmms):
    imp = cmms.cerca_impianti(cliente="nova")[0]
    o = cmms.crea_ordine(imp["id"], "Verifica impianto con rientri ripetuti", "alta", ["SCB1180"])
    assert o["id"].startswith("ODL-") and o["stato"] == "aperto" and o["ricambi"] == ["SCB1180"]
    assert cmms.impianto(imp["id"])["ordini"][0]["id"] == o["id"]
    with pytest.raises(ErroreCMMS, match="impianto inesistente"):
        cmms.crea_ordine("IMP-99999", "intervento di prova", "media", [])
    with pytest.raises(ErroreCMMS, match="ricambio inesistenti"):
        cmms.crea_ordine(imp["id"], "intervento di prova", "media", ["XYZ000"])
    with pytest.raises(ErroreCMMS):
        cmms.crea_ordine(imp["id"], "intervento di prova", "urgentissima", [])   # priorità non ammessa
