"""Lettura dei file SolidWorks (.SLDPRT, .SLDASM, .SLDDRW, formato 2015+) senza SolidWorks.

Il file è una sequenza di blocchi compressi (deflate). Se ne ricavano:
- le proprietà del cartiglio (DENOMINAZIONE, DISEGNO_NUM, DATA, COMPILATO_DA, STATO, MATERIALE, ...);
- nelle tavole (.SLDDRW) le righe della distinta, nell'ordine della tabella (codice di ogni riga);
- i componenti referenziati (percorsi .SLDPRT/.SLDASM nel PDM);
- le immagini di anteprima (PNG): l'esploso della tavola e la vista 3D dell'assieme.
Non si leggono la geometria né i vincoli: per quelli serve lo STEP.
"""
from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path

MARCATORE = bytes.fromhex("1400060008")
ESTENSIONI = {".sldprt", ".sldasm", ".slddrw"}

# cartelle del PDM Opera: la lettera iniziale dice la categoria
CATEGORIE_PDM = {"A": "commerciale", "E": "elettronica", "F": "particolare a disegno", "G": "grezzo/semilavorato",
                 "L": "gruppo", "V": "viteria", "X": "progettazione"}
# riferimenti da ignorare: copie temporanee, prove, studi, file personali
RIF_SCARTATI = re.compile(r"\\(temp|appdata|desktop|studi|solidworks impostazioni|solidworks data)\\|file di prova|"
                          r"^c:\\users\\|x_progettazione", re.I)
RIGA_DISTINTA = re.compile(r'"([0-9A-Z][\w/\-]{3,})"\+"[^"]*"')
DENOMINAZIONE_PRP = re.compile(r'\$PRP:"DENOMINAZIONE"=\[([^\]]+)\]')
RIFERIMENTO = re.compile(r"[A-Za-z]:\\[^<>\"|?*\x00-\x1f]+?\.sld(?:prt|asm)", re.I)


@dataclass
class FileSW:
    percorso: Path
    tipo: str                                   # parte | assieme | tavola
    proprieta: dict = field(default_factory=dict)
    distinta: list[str] = field(default_factory=list)       # codici delle righe della distinta (solo tavole)
    componenti: list[str] = field(default_factory=list)     # codici dei file referenziati
    descrizioni: list[str] = field(default_factory=list)    # denominazioni dei componenti trovate nel file
    anteprime: list[bytes] = field(default_factory=list)    # PNG

    @property
    def codice(self) -> str:
        return (self.proprieta.get("DISEGNO_NUM") or self.percorso.stem).strip()

    @property
    def denominazione(self) -> str:
        return self.proprieta.get("DENOMINAZIONE", "").strip()


def blocchi(dati: bytes):
    """Contenuti decompressi dei blocchi del file.
    Intestazione di ogni blocco: marcatore (6 byte), 4 byte, CRC (4), dimensione compressa (4),
    dimensione originale (4), lunghezza del nome (4), nome, dati compressi (deflate senza intestazione)."""
    i = 0
    while (i := dati.find(MARCATORE, i)) >= 0:
        if i + 26 <= len(dati):
            compr, orig, lnome = struct.unpack_from("<III", dati, i + 14)
            inizio = i + 26 + lnome
            if 0 < compr <= len(dati) - inizio and lnome < 1024 and orig < 200_000_000:
                try:
                    yield zlib.decompress(dati[inizio:inizio + compr], -15)
                    i = inizio + compr
                    continue
                except zlib.error:
                    pass
        i += 1


def _testi(b: bytes) -> list[str]:
    """Il blocco letto come testo a 8 bit e come UTF-16 (i caratteri nulli tolti)."""
    t = b.decode("latin-1")
    return [t, re.sub(r"([^\x00])\x00", r"\1", t)]


def ripara_testo(t: str) -> str:
    """Testo UTF-8 letto come 8 bit (es. 'â\x80\x93' per il trattino lungo): lo riporta corretto."""
    try:
        return t.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return t


def _proprieta(xml: str) -> dict:
    out = {}
    for nome, val in re.findall(r'<property name="([^"]+)"[^>]*>\s*<vt:\w+(?: [^>]*)?>([^<]*)</vt:', xml):
        val = ripara_testo(unescape(val)).strip()
        if val and not nome.startswith("_"):
            out.setdefault(nome, val)
    return out


def codice_da_percorso(p: str) -> str:
    return re.sub(r"\.sld(prt|asm)$", "", p.replace("/", "\\").rsplit("\\", 1)[-1], flags=re.I).split(" ")[0]


def categoria_da_percorso(p: str) -> str:
    m = re.search(r"\\([A-Z])_[^\\]+\\[^\\]+$", p, re.I)
    return CATEGORIE_PDM.get(m[1].upper(), "") if m else ""


def leggi(percorso: str | Path) -> FileSW:
    percorso = Path(percorso)
    tipo = {".sldprt": "parte", ".sldasm": "assieme", ".slddrw": "tavola"}[percorso.suffix.lower()]
    sw = FileSW(percorso, tipo)
    dati = percorso.read_bytes()
    distinta, rif, descr = [], [], []
    for b in blocchi(dati):
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            sw.anteprime.append(b)
            continue
        for t in _testi(b):
            if "<Properties" in t and "DENOMINAZIONE" in t and not sw.proprieta:
                sw.proprieta = _proprieta(t)
            if tipo == "tavola":
                distinta += RIGA_DISTINTA.findall(t)
            rif += RIFERIMENTO.findall(t)
            descr += DENOMINAZIONE_PRP.findall(t)
    sw.distinta = list(dict.fromkeys(distinta))
    proprio = sw.codice.lower()
    buoni = [r for r in rif if not RIF_SCARTATI.search(r)]
    sw.componenti = [c for c in dict.fromkeys(codice_da_percorso(r) for r in buoni) if c.lower() != proprio]
    sw.descrizioni = list(dict.fromkeys(ripara_testo(d).strip() for d in descr if d.strip()))
    sw._categorie = {codice_da_percorso(r).lower(): categoria_da_percorso(r) for r in buoni}  # type: ignore[attr-defined]
    return sw
