"""File SolidWorks sintetici (stessa struttura a blocchi dei file veri) per provare lettura e indice."""
import struct
import zlib

from app.meccanica.indice import IndiceMeccanico
from app.meccanica.solidworks import leggi


def _blocco(nome: bytes, dati: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    comp = c.compress(dati) + c.flush()
    testa = bytes.fromhex("140006000800") + b"\0" * 8 + struct.pack("<III", len(comp), len(dati), len(nome))
    return testa + nome + comp


def _proprieta(codice, denominazione):
    return (f'<Properties xmlns="x"><propertySection name="UserDefinedProperties">'
            f'<property name="DENOMINAZIONE" pid="2" TypeID="0"><vt:lpstr>{denominazione}</vt:lpstr></property>'
            f'<property name="DISEGNO_NUM" pid="3" TypeID="0"><vt:lpstr>{codice}</vt:lpstr></property>'
            f'<property name="DATA" pid="4" TypeID="0"><vt:lpstr>07/07/2023</vt:lpstr></property>'
            f'<property name="STATO" pid="5" TypeID="0"><vt:lpstr>ATTIVO</vt:lpstr></property>'
            '</propertySection></Properties>').encode()


def _file(percorso, codice, denominazione, righe=()):
    corpo = b"testa" + _blocco(b"p", _proprieta(codice, denominazione))
    if righe:
        testo = "".join(f'"{c}"+"x" ($PRP:"DENOMINAZIONE"=[{d}]=) ' for c, d in righe)
        corpo += _blocco(b"d", testo.encode("utf-16le"))
    corpo += _blocco(b"i", b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_bytes(corpo)


def test_lettura_e_indice(tmp_path):
    pdm = tmp_path / "OPERA_PDM"
    _file(pdm / "L_Gruppi logici" / "01542L00.SLDDRW", "01542L00", "Gruppo elettropistone Prima 2460030 - 2560030",
          [("01269L10", "Gruppo nucleo"), ("9709-093", "Bobina Prima"), ("01345F00", "Molla conica")])
    _file(pdm / "L_Gruppi logici" / "01269L10.SLDDRW", "01269L10", "Gruppo nucleo",
          [("00072F00", "Nucleo L49,2 bobina 9709/093"), ("0105-503", "Molla scrocco")])
    _file(pdm / "F_Particolari a disegno" / "9709-093.SLDPRT", "9709-093", "Bobina Prima")
    _file(pdm / "X_Progettazione meccanica" / "00054X00.SLDPRT", "00054X00", "studio")   # saltato

    sw = leggi(pdm / "L_Gruppi logici" / "01542L00.SLDDRW")
    assert sw.codice == "01542L00" and sw.distinta == ["01269L10", "9709-093", "01345F00"]
    assert sw.proprieta["STATO"] == "ATTIVO" and len(sw.anteprime) == 1

    dati = tmp_path / "Produzione1"
    dati.mkdir()
    r = IndiceMeccanico(dati).aggiorna(pdm)
    assert r["file"] == 3
    i = IndiceMeccanico(dati)
    assert i.trova("2560030") == ["01542L00"]
    assert i.radici("00072F00") == ["01542L00"]
    righe = {x["codice"]: x for x in i.esplodi("01542L00")}
    assert righe["9709-093"]["elettrico"] and not righe["00072F00"]["elettrico"]   # "Nucleo ... bobina" no
    assert righe["9709-093"]["categoria"] == "particolare a disegno"


def test_strumento_meccanica(tmp_path):
    from app.agente.strumenti_meccanica import crea_strumenti_meccanica
    from app.meccanica import funzionamento as fz
    pdm = tmp_path / "OPERA_PDM"
    _file(pdm / "L_Gruppi logici" / "01542L00.SLDDRW", "01542L00", "Gruppo elettropistone Prima 2560030",
          [("SP112A", "Circuito elettropistone"), ("9709-093", "Bobina Prima")])
    dati = tmp_path / "Produzione1"
    dati.mkdir()
    IndiceMeccanico(dati).aggiorna(pdm)
    fz.salva(dati, {"01542L00": {"stato": "confermato", "descrizione": "la bobina attira il nucleo"}})

    class Cat:
        schede = {"SP112A_rev3": object()}
    (s,) = crea_strumenti_meccanica(IndiceMeccanico(dati), dati, Cat())
    out = s.invoke({"articolo": "2560030"})
    assert out["codice"] == "01542L00" and out["funzionamento"]["stato"] == "confermato"
    assert out["parti_elettriche"][0]["schede_schema"] == ["SP112A_rev3"]
