import os
import time
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.documenti.indice import IndiceDocumenti, gruppo


def _archivio(tmp: Path) -> Path:
    r = tmp / "Produzione1"
    (r / "Elettropistoni Prima" / "Istruzioni").mkdir(parents=True)
    (r / "Elettropistoni Prima" / "Schemi").mkdir()
    (r / "Arca").mkdir()
    ist = r / "Elettropistoni Prima" / "Istruzioni"
    (ist / "Istruzioni_EP_2480035_rev1.txt").write_text("Istruzioni elettropistone 2480035\n12/03/2021", "utf-8")
    (ist / "Istruzioni_EP_2480035_rev2.txt").write_text("Istruzioni elettropistone 2480035\n05/06/2024", "utf-8")
    (r / "Elettropistoni Prima" / "Schemi" / "Sch_SP112A.txt").write_text("schema scheda SP112A 2480035", "utf-8")
    (r / "Arca" / "Bom_00341.csv").write_text("Designator;Codice\nU4;STM32G031G4U6\nR9;330R nottolino", "utf-8")
    (r / "Arca" / "note varie.md").write_text("# Note\nIl nottolino 1407/1811 va ingrassato", "utf-8")
    w = PdfWriter()
    w.add_blank_page(100, 100)
    with open(r / "Arca" / "Sch_OPR030.pdf", "wb") as f:
        w.write(f)
    (r / "prodotti.yaml").write_text("schede: []\n", "utf-8")       # nella radice: non indicizzato
    return r


def test_gruppo_versioni():
    assert gruppo("Istruzioni_EP_rev3.pdf") == gruppo("Istruzioni EP v4.pdf") == "istruzioni ep"
    assert gruppo("Manuale 2023-05.pdf") == gruppo("Manuale.pdf")


def test_indice_e_ricerca(tmp_path: Path):
    r = _archivio(tmp_path)
    ix = IndiceDocumenti(tmp_path / "i.db", r)
    s = ix.aggiorna()
    assert s["documenti"] == 6 and s["indicizzati_ora"] == 6
    res = ix.cerca("2480035")
    assert len(res["istruzioni"]) == 1
    ultima = res["istruzioni"][0]
    assert ultima["nome"].endswith("rev2.txt") and ultima["data"] == "2024-06-05"
    assert [v["nome"] for v in ultima["versioni_precedenti"]] == ["Istruzioni_EP_2480035_rev1.txt"]
    assert [d["nome"] for d in res["schemi"]] == ["Sch_SP112A.txt"]
    assert {d["nome"] for d in ix.cerca("nottol")["altri"]} == {"Bom_00341.csv", "note varie.md"}   # inizio parola
    assert ix.cerca("1407/1811")["altri"][0]["nome"] == "note varie.md"
    assert ix.cerca("8003")["totale"] == 2       # parte di un codice nel nome del file
    assert ix.cerca("OPR030")["schemi"][0]["nome"] == "Sch_OPR030.pdf"
    assert ix.cerca("inesistente")["totale"] == 0


def test_aggiornamento_incrementale(tmp_path: Path):
    r = _archivio(tmp_path)
    ix = IndiceDocumenti(tmp_path / "i.db", r)
    ix.aggiorna()
    assert ix.aggiorna()["indicizzati_ora"] == 0
    f = r / "Arca" / "note varie.md"
    f.write_text("# Note\nnuovo testo con encoder", "utf-8")
    os.utime(f, (time.time() + 5, time.time() + 5))
    (r / "Arca" / "Bom_00341.csv").unlink()
    s = ix.aggiorna()
    assert s["indicizzati_ora"] == 1 and s["rimossi"] == 1 and ix.cerca("encoder")["totale"] == 1


def test_api_ricerca_e_apertura(tmp_path: Path, cfg):
    import dataclasses
    from types import SimpleNamespace

    from app.api import crea_app
    r = _archivio(tmp_path)
    IndiceDocumenti(r / "indice_documenti.db", r).aggiorna()
    c = SimpleNamespace(cfg=dataclasses.replace(cfg, dati_azienda=r), extra={})
    with TestClient(crea_app(componenti=c, frontend=None)) as cl:
        assert "Cerca nei documenti" in cl.get("/documenti").text
        j = cl.get("/api/documenti/cerca", params={"q": "2480035"}).json()
        p = j["istruzioni"][0]["percorso"]
        a = cl.get("/api/documenti/apri", params={"p": p})
        assert a.status_code == 200 and "2480035" in a.text
        assert cl.get("/api/documenti/apri", params={"p": "../../etc/passwd"}).status_code == 404


def test_cartella_documenti_separata(tmp_path):
    from app.documenti.indice import IndiceDocumenti
    prod = tmp_path / "Produzione1"
    prod.mkdir()
    doc = tmp_path / "Documenti condivisi" / "Varie"
    doc.mkdir(parents=True)
    (doc / "Istruzioni montaggio 4000123.txt").write_text("articolo 4000123 montaggio", encoding="utf-8")
    IndiceDocumenti(prod / "indice_documenti.db", tmp_path / "Documenti condivisi").aggiorna()
    i = IndiceDocumenti(prod / "indice_documenti.db")        # riapertura: cartella letta dall'indice
    assert i.radice == tmp_path / "Documenti condivisi"
    assert i.cerca("4000123")["istruzioni"]


def test_solo_cartelle_elencate(tmp_path):
    from app.documenti.indice import IndiceDocumenti, leggi_elenco_cartelle
    for nome in ("Prodotti", "Amministrazione"):
        (tmp_path / nome).mkdir()
        (tmp_path / nome / f"{nome}.txt").write_text("articolo 4000999", encoding="utf-8")
    elenco = tmp_path / "elenco.txt"
    elenco.write_text("# commento\nProdotti\nNonEsiste\n", encoding="utf-8")
    cartelle = leggi_elenco_cartelle(elenco, tmp_path)
    assert cartelle == ["Prodotti"]
    i = IndiceDocumenti(tmp_path / "i.db", tmp_path)
    assert i.aggiorna(cartelle=cartelle)["documenti"] == 1


def test_testo_odg(tmp_path):
    import zipfile

    from app.documenti.indice import estrai_testo
    f = tmp_path / "disegno.odg"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("content.xml", "<office:document-content><text:p>Staffa 4000555</text:p></office:document-content>")
    assert "Staffa 4000555" in estrai_testo(f)


def test_cartelle_in_altre_posizioni(tmp_path):
    from app.documenti.indice import IndiceDocumenti, leggi_elenco_cartelle
    condivisi, altrove = tmp_path / "condivisi", tmp_path / "altro_disco" / "Manuali"
    (condivisi / "Prodotti").mkdir(parents=True)
    altrove.mkdir(parents=True)
    (condivisi / "Prodotti" / "a.txt").write_text("articolo 4000777", encoding="utf-8")
    (altrove / "Manuale 4000777.txt").write_text("articolo 4000777", encoding="utf-8")
    elenco = tmp_path / "elenco.txt"
    elenco.write_text(f"Prodotti\n{altrove}\n", encoding="utf-8")
    i = IndiceDocumenti(tmp_path / "i.db", condivisi)
    assert i.aggiorna(cartelle=leggi_elenco_cartelle(elenco, condivisi))["documenti"] == 2
    r = i.cerca("4000777")
    percorsi = [d["percorso"] for k in ("istruzioni", "schemi", "altri") for d in r[k]]
    assert len(percorsi) == 2 and all(i.file_di(p) for p in percorsi)
    assert i.file_di(str(tmp_path / "elenco.txt")) is None          # fuori dalle cartelle: non si apre


def test_domanda_in_linguaggio_naturale(tmp_path):
    from app.documenti.indice import IndiceDocumenti, e_domanda, interpreta_domanda
    d = interpreta_domanda("trova lo schema di collegamento della 2560035 con la consolle 54612")
    assert d["codici"] == ["2560035", "54612"] and d["tipo"] == "schemi" and "consolle" in d["parole"]
    assert e_domanda("schema della 2560035") and not e_domanda("2560035")

    cart = tmp_path / "Doc" / "Collegamenti"
    cart.mkdir(parents=True)
    (cart / "Schema collegamento 2560035 consolle 54612.txt").write_text("cablaggio", encoding="utf-8")
    (cart / "Schema collegamento 2560035 alimentatore.txt").write_text("cablaggio", encoding="utf-8")
    (cart / "Istruzioni 2560035.txt").write_text("montaggio consolle 54612", encoding="utf-8")
    i = IndiceDocumenti(tmp_path / "i.db", tmp_path / "Doc")
    i.aggiorna()
    r = i.cerca_domanda("trova lo schema di collegamento della 2560035 con la consolle 54612")
    assert r["domanda"]["tutti_i_codici"] and r["totale"] == 2          # solo i documenti con entrambi i codici
    assert [x["nome"] for x in r["proposti"]] == ["Schema collegamento 2560035 consolle 54612.txt"]
    r = i.cerca_domanda("schema della 2560035 con la consolle 99999")
    assert not r["domanda"]["tutti_i_codici"] and r["domanda"]["codici_mancanti"] == ["99999"]


def test_domanda_esclude_elenchi(tmp_path):
    from app.documenti.indice import IndiceDocumenti
    cart = tmp_path / "Doc" / "Varie"
    cart.mkdir(parents=True)
    codici = " ".join(str(2500000 + k) for k in range(80))
    (cart / "Codici a barre.txt").write_text(f"2560035 54612 {codici}", encoding="utf-8")
    (cart / "Listino consolle.txt").write_text("consolle 54612 per 2560035 prezzo", encoding="utf-8")
    (cart / "Collegamento 2560035 - 54612.txt").write_text("morsetti bobina", encoding="utf-8")
    i = IndiceDocumenti(tmp_path / "i.db", tmp_path / "Doc")
    i.aggiorna()
    r = i.cerca_domanda("trova lo schema di collegamento della 2560035 con la consolle 54612")
    assert [x["nome"] for x in r["proposti"]] == ["Collegamento 2560035 - 54612.txt"]
    assert r["domanda"]["elenchi_esclusi"] == 1


def test_foglio_codici_a_barre_non_e_uno_schema(tmp_path):
    import zipfile

    from app.documenti.indice import IndiceDocumenti
    cart = tmp_path / "Doc" / "Prod"
    cart.mkdir(parents=True)
    with zipfile.ZipFile(cart / "Codici barre OPERA.ods", "w") as z:
        z.writestr("content.xml", "<x><text:p>Elettropistone 2560030 8012345678901 54610A</text:p></x>")
    i = IndiceDocumenti(tmp_path / "i.db", tmp_path / "Doc")
    i.aggiorna()
    r = i.cerca_domanda("schema di collegamento elettrico tra 54610A e 2560030")
    assert r["proposti"] == [] and r["totale"] == 0


def test_domanda_codice_con_lettera_e_codici_parziali(tmp_path):
    from app.documenti.indice import IndiceDocumenti
    cart = tmp_path / "Doc" / "Michele_schemi" / "54610"
    cart.mkdir(parents=True)
    (cart / "54610 + 54611 + IE.txt").write_text("consolle", encoding="utf-8")
    i = IndiceDocumenti(tmp_path / "i.db", tmp_path / "Doc")
    i.aggiorna()
    r = i.cerca_domanda("schema di collegamento elettrico tra 54610A e 2560030")
    assert [x["nome"] for x in r["proposti"]] == ["54610 + 54611 + IE.txt"]
    assert r["domanda"]["codici_mancanti"] == ["2560030"]
