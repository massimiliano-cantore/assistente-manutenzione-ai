"""Importatore per i PDF esportati da Altium Designer (schemi e disegni di montaggio).

Altium, esportando in PDF, scrive nei segnalibri l'elenco di componenti, pin e net con i pin collegati,
e nel disegno lascia etichette invisibili con la posizione di ogni componente ('CO' + designator).
Dai segnalibri si ricava quindi la netlist esatta, senza bisogno dei file di progetto.

Usa pypdfium2 (licenza BSD/Apache): compatibile anche con un prodotto commerciale.
"""
from __future__ import annotations

import re
from pathlib import Path

import pypdfium2 as pdfium

from app.elettrico.modello import Componente, Scheda

_RIF_PIN = re.compile(r"^[A-Za-z]+[A-Za-z0-9_]*-[A-Za-z0-9_+]+$")   # es. U1-14, C2A-1, J4-16
_SOTTOSEZIONI = {"Pins", "NetLabels", "Ports", "Power Ports", "Sheet Entries"}


def e_pdf_altium(percorso: str | Path) -> bool:
    pdf = pdfium.PdfDocument(str(percorso))
    try:
        return any(t.get_title() in ("Components", "Nets") for t in pdf.get_toc())
    finally:
        pdf.close()


def importa(percorso: str | Path, codice: str, nome: str = "") -> Scheda:
    pdf = pdfium.PdfDocument(str(percorso))
    try:
        voci = [(t.level, t.get_title()) for t in pdf.get_toc()]
    finally:
        pdf.close()
    scheda = Scheda(codice=codice, nome=nome, pdf_disegno=str(percorso))
    sezione, base, corrente, sotto = None, 0, None, None
    for livello, titolo in voci:
        if titolo in ("Components", "Nets"):
            sezione, base, corrente = titolo, livello, None
            continue
        if sezione and livello <= base:
            sezione = None
        if not sezione:
            continue
        rel = livello - base
        if sezione == "Components":
            if rel == 1:
                corrente = titolo
                scheda.componenti.setdefault(titolo, Componente(designator=titolo))
            elif rel == 2 and corrente and _RIF_PIN.match(titolo):
                scheda.componenti[corrente].pin.add(titolo.rpartition("-")[2])
        else:
            if rel == 1:
                corrente, sotto = titolo, None
                scheda.nets.setdefault(titolo, set())
            elif titolo in _SOTTOSEZIONI:
                sotto = titolo
            elif corrente and sotto in (None, "Pins") and _RIF_PIN.match(titolo):
                scheda.nets[corrente].add(titolo)
    scheda.nets = {n: p for n, p in scheda.nets.items() if p}
    if not scheda.componenti:
        scheda.note.append("nessun segnalibro di componenti: PDF non esportato da Altium o senza segnalibri")
    scheda.note += note_di_revisione(percorso)
    return scheda


def note_di_revisione(percorso: str | Path) -> list[str]:
    """Le note scritte nel cartiglio (es. 'Changing obj from Rev1.0 to Rev2.0: ...') aiutano la diagnosi."""
    pdf = pdfium.PdfDocument(str(percorso))
    try:
        testo = " ".join(pg.get_textpage().get_text_range() for pg in pdf)
    finally:
        pdf.close()
    trovate = re.findall(r"(Chang\w* obj[^\r\n]{0,200}(?:\r?\n[^\r\n]{0,200}){0,2})", testo)
    pulite = [re.sub(r"\b(?:PI|CO|NL)[A-Z]+\d+[A-Z0-9]*\b", "", t) for t in trovate]   # etichette invisibili
    return [re.sub(r"\s+", " ", t).strip() for t in pulite]


def posizioni(percorso: str | Path, designators: list[str]) -> dict[str, tuple[int, tuple[float, float, float, float]]]:
    """Posizione dei componenti sul disegno, dalle etichette invisibili 'CO<designator>'.
    Restituisce designator -> (pagina, (x0, y0, x1, y1)) in punti PDF con origine in alto a sinistra."""
    pdf = pdfium.PdfDocument(str(percorso))
    trovate = {}
    try:
        for indice, pagina in enumerate(pdf):
            altezza = pagina.get_size()[1]
            tp = pagina.get_textpage()
            for des in designators:
                if des in trovate:
                    continue
                ricerca = tp.search(f"CO{des}", match_case=True, match_whole_word=True)
                esito = ricerca.get_next()
                if esito:
                    i, n = esito
                    riquadri = [tp.get_charbox(k) for k in range(i, i + n)]
                    x0 = min(r[0] for r in riquadri); x1 = max(r[2] for r in riquadri)
                    y0 = min(r[1] for r in riquadri); y1 = max(r[3] for r in riquadri)
                    trovate[des] = (indice, (x0, altezza - y1, x1, altezza - y0))
    finally:
        pdf.close()
    return trovate
