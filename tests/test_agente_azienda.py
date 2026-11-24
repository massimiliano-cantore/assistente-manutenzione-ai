"""Modalità 'azienda': l'agente lavora sulla documentazione elettronica (qui finta) con gli strumenti sul circuito."""
import dataclasses

from app.componenti import costruisci
from tests.dati_elettrici import cartella_azienda
from tests.llm_finto import LLMCopione, chiamata, testo


def test_diagnosi_con_strumenti_elettrici(cfg, tmp_path):
    (tmp_path / "azienda").mkdir()
    azienda = cartella_azienda(tmp_path / "azienda")
    c_cfg = dataclasses.replace(cfg, dati_azienda=azienda, cartella_immagini=tmp_path / "img")
    llm = LLMCopione(copione=[
        chiamata("panoramica_prodotti", "a1"),
        chiamata("cerca_componenti", "a2", testo="transceiver"),
        chiamata("percorso_segnale", "a3", scheda_da="MADRE", pin_da="U3-1", scheda_a="RADIO", pin_a="U1-1"),
        chiamata("evidenzia_su_disegno", "a4", scheda="MADRE", designators=["R10", "J4"]),
        testo("Controlla R10 e il connettore J4/J1. Misure da fare: ..."),
    ])
    c = costruisci(c_cfg, llm=llm)
    assert c.cfg.modalita == "azienda" and c.archivio is None and c.cmms is None
    nomi = {s.name for s in c.strumenti}
    assert {"percorso_segnale", "piedinatura_componente", "evidenzia_su_disegno"} <= nomi
    assert "interroga_archivio" not in nomi and "apri_ordine_di_lavoro" not in nomi   # niente dati KYROS
    r = c.assistente.chiedi("La centralina non comunica più via radio: cosa può essere?")
    assert [p["strumento"] for p in r.passi] == ["panoramica_prodotti", "cerca_componenti", "percorso_segnale",
                                                 "evidenzia_su_disegno"]
    assert r.passi[2]["esito"]["componenti_attraversati"] == ["R10"]
    assert (tmp_path / "img" / r.passi[3]["esito"]["immagine"]).exists()
    assert "laboratorio riparazioni" in llm.ricevuti[0][0].content and "BREVE" in llm.ricevuti[0][0].content


def test_storico_collegato_all_agente(cfg, tmp_path):
    import json
    (tmp_path / "azienda").mkdir()
    azienda = cartella_azienda(tmp_path / "azienda")
    (azienda / "storico").mkdir()
    scheda = {"formato": "docai-scheda/1", "id": "00001_reso",
              "campi": {"articolo": {"valore": "X1"}, "note": {"valore": "radio muta, sostituita R10"}}, "righe": []}
    (azienda / "storico" / "00001_reso.json").write_text(json.dumps(scheda), encoding="utf-8")
    c_cfg = dataclasses.replace(cfg, dati_azienda=azienda, cartella_immagini=tmp_path / "img")
    llm = LLMCopione(copione=[chiamata("storico_riparazioni", "s1", sintomo="radio muta"),
                              testo("Già visto: R10.")])
    c = costruisci(c_cfg, llm=llm)
    assert {"storico_riparazioni", "statistiche_guasti"} <= {s.name for s in c.strumenti}
    r = c.assistente.chiedi("La radio è muta")
    assert r.passi[0]["esito"]["casi"][0]["note"] == "radio muta, sostituita R10"


def test_limite_passi_risponde_comunque(cfg, tmp_path):
    (tmp_path / "azienda").mkdir()
    azienda = cartella_azienda(tmp_path / "azienda")
    c_cfg = dataclasses.replace(cfg, dati_azienda=azienda, cartella_immagini=tmp_path / "img", max_passi=2)
    llm = LLMCopione(copione=[chiamata("panoramica_prodotti", f"p{i}") for i in range(3)]
                     + [testo("Risposta con i dati raccolti. Misure da fare: ...")])
    c = costruisci(c_cfg, llm=llm)
    r = c.assistente.chiedi("guasto qualsiasi")
    assert r.testo.startswith("Risposta con i dati raccolti")
