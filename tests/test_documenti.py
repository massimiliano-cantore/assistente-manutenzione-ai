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
