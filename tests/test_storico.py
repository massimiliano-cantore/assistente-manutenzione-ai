import json
from pathlib import Path

import yaml

from app.agente.strumenti_storico import crea_strumenti_storico
from app.elettrico.catalogo import Catalogo
from app.elettrico.modello import Componente, Prodotto, Scheda
from app.storico import Storico
from app.storico.storico import normalizza


def _cella(v, origine="letto"):
    return {"valore": v, "colore_lettura": "verde", "origine": origine}


def _scheda(i, articolo, seriale, note, righe, data="06/12/2023", fw="V7"):
    return {"formato": "docai-scheda/1", "id": f"{i:05d}_scheda", "file_origine": f"scheda_{i}.pdf",
            "tipo": "scheda", "campi": {"riparazione_n": _cella(f"{i:02d}/12"), "data": _cella(data),
                                         "ditta": _cella("IMPIANTI ROSSI"), "articolo": _cella(articolo),
                                         "seriale": _cella(seriale, "corretto"), "firmware": _cella(fw),
                                         "tempo_riparazione": _cella("20"), "aperta_manomessa": _cella("no"),
                                         "note": _cella(note)},
            "righe": [{k: _cella(v) for k, v in r.items()} for r in righe]}


def _cartella(tmp: Path) -> Path:
    d = tmp / "storico"
    d.mkdir()
    schede = [
        _scheda(1, "40806", "961656", "Non apre. Relè K1 bruciato, sostituito K1 e R12",
                [{"codice": "REL12V", "descrizione": "RELE", "intervento": "SOSTITUZIONE (BRUCIATO)", "pz": 1}]),
        _scheda(2, "40806", "96-1656", "Non apre di nuovo, contatti relè K1 incollati",
                [{"codice": "REL12V", "descrizione": "RELE", "intervento": "SOSTITUZIONE (BRUCIATO)", "pz": 1}],
                data="10/03/2024", fw="V8"),
        _scheda(3, "40806", "970001", "Display spento, regolatore U2 in corto",
                [{"codice": "REG33", "descrizione": "REGOLATORE 3V3", "intervento": "SOSTITUZIONE (IN CORTO)",
                  "pz": 1}]),
        _scheda(4, "99999", "1", "Cavo tranciato", [{"codice": "CAV1", "descrizione": "CAVO",
                                                      "intervento": "SOSTITUZIONE (ROTTO)", "pz": 1}]),
    ]
    for s in schede:
        (d / f"{s['id']}.json").write_text(json.dumps(s), encoding="utf-8")
    (d / "non_valido.json").write_text("{", encoding="utf-8")
    return d


def _documentazione(tmp: Path):
    conf = {"schede": [{"codice": "OPR031", "netlist": "Elettromaniglie/Sch_00809.pdf",
                        "bom": "Elettromaniglie/Bom_00809E01_40xxx_Var_Std.xls"}],
            "prodotti": [{"nome": "Elettromaniglie", "schede": ["OPR031"]}]}
    (tmp / "prodotti.yaml").write_text(yaml.safe_dump(conf), encoding="utf-8")
    s = Scheda(codice="OPR031", componenti={d: Componente(d) for d in ("K1", "R12", "U1")})
    return Catalogo({"OPR031": s}, [Prodotto("Elettromaniglie", ["OPR031"])], tmp)


def test_normalizza_sinonimi():
    r = normalizza({"campi": {"Matricola": "SN 12", "Difetto_riscontrato": "fusibile F1 aperto",
                              "Codice_prodotto": "57512RF"}})
    assert r.seriale == "SN 12" and r.articolo == "57512RF" and r.riferimenti == ["F1"]


def test_carica_collega_cerca(tmp_path: Path):
    st = Storico.carica(_cartella(tmp_path))
    assert len(st.riparazioni) == 4 and st.riparazioni[0].data == "2023-12-06"
    assert st.riparazioni[0].corretti == ["seriale"]
    c = st.collega(_documentazione(tmp_path), tmp_path / "prodotti.yaml")
    assert c["collegate_a_prodotto"] == 3 and c["articoli_non_riconosciuti"] == {"99999": 1}
    assert st.riparazioni[0].riferimenti == ["K1", "R12"]
    assert st.riparazioni[2].riferimenti == []          # U2 non c'è sulla scheda: scartato
    casi = st.cerca("la serratura non apre, il relè scatta?", prodotto="elettromaniglie")
    assert casi[0]["numero"] in ("01/12", "02/12") and len(casi) >= 2
    storia = st.cerca(seriale="96 1656")
    assert len(storia) == 2


def test_statistiche_e_strumenti(tmp_path: Path):
    st = Storico.carica(_cartella(tmp_path))
    st.collega(_documentazione(tmp_path), tmp_path / "prodotti.yaml")
    s = st.statistiche("Elettromaniglie")
    assert s["riparazioni"] == 3
    assert s["componenti_piu_sostituiti"][0] == ("REL12V RELE", 2)
    assert ("BRUCIATO", 2) in s["cause_annotate"]
    assert s["seriali_tornati_piu_volte"] == [("961656", 2)]
    t = {x.name: x for x in crea_strumenti_storico(st)}
    assert t["storico_riparazioni"].invoke({"sintomo": "display spento"})["casi"][0]["seriale"] == "970001"
    assert t["statistiche_guasti"].invoke({"prodotto": "Elettromaniglie"})["riparazioni"] == 3


def test_articolo_a_mano(tmp_path: Path):
    d = _cartella(tmp_path)
    (d / "storico.yaml").write_text("articoli:\n  '99999': Elettromaniglie\n", encoding="utf-8")
    st = Storico.carica(d)
    assert st.collega(_documentazione(tmp_path), tmp_path / "prodotti.yaml")["collegate_a_prodotto"] == 4


def test_limiti_risultati():
    from langchain_core.tools import tool

    from app.agente.limiti import limita

    @tool
    def tanti() -> dict:
        """prova"""
        return {"pin": [{"n": i, "testo": "x" * 200} for i in range(200)]}

    r = limita([tanti], max_caratteri=3000)[0].invoke({})
    assert len(r["pin"]) <= 13 and str(r["pin"][-1]).startswith("... e altri")


def test_cerca_prodotto(tmp_path: Path):
    d = _cartella(tmp_path)
    (d / "storico.yaml").write_text("articoli:\n  '2580035': Elettromaniglie\n", encoding="utf-8")
    st = Storico.carica(d)
    st.collega(_documentazione(tmp_path), tmp_path / "prodotti.yaml")
    assert st.prodotto_per("2580035")["prodotti"][0]["nome"] == "Elettromaniglie"
    assert st.prodotto_per("40810N")["prodotti"][0]["schede"] == ["OPR031"]
    assert st.prodotto_per("elettromaniglie")["prodotti"]
    assert st.prodotto_per("9999999")["nota"]


def test_testo_di_blocchi_claude():
    from app.agente.servizio import testo_di
    blocchi = [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "Risposta"}]
    assert testo_di(blocchi) == "Risposta" and testo_di("ciao") == "ciao"
