"""Documentazione elettronica FINTA per i test: due schede collegate da un connettore, PDF 'stile Altium'
(segnalibri con componenti, pin e net, etichette invisibili CO<designator>) e una BOM in CSV.
Nessun documento reale: i test del repository pubblico non usano mai dati aziendali."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import ContentStream, DecodedStreamObject, DictionaryObject, NameObject

MADRE = {
    "componenti": {"U3": ["1", "2", "3", "4"], "R10": ["1", "2"], "J4": ["1", "2", "3", "4"], "C1": ["1", "2"]},
    "nets": {"SPI_MISO": ["U3-1", "R10-1"], "NetJ4_1": ["R10-2", "J4-1"], "SPI_CS": ["U3-2", "J4-2"],
             "+3V3": ["U3-3", "J4-3", "C1-1"], "GND": ["U3-4", "J4-4", "C1-2"]},
}
RADIO = {
    "componenti": {"U1": ["1", "2", "3", "4", "5", "6"], "J1": ["1", "2", "3", "4"], "Y1": ["1", "2"],
                   "R4": ["1", "2"]},
    "nets": {"MISO": ["J1-1", "U1-1"], "CS_TRX": ["J1-2", "U1-2"], "+3V3": ["J1-3", "U1-3"], "GND": ["J1-4", "U1-4"],
             "NetY1_1": ["U1-5", "Y1-1", "R4-1"], "NetY1_2": ["U1-6", "Y1-2", "R4-2"]},
}


def pdf_altium(percorso: Path, scheda: dict, nota: str = "") -> Path:
    w = PdfWriter()
    pagina = w.add_blank_page(842, 595)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    pagina[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject(
        {NameObject("/F1"): w._add_object(font)})})
    righe = []
    for i, des in enumerate(scheda["componenti"]):
        righe.append(f"BT /F1 8 Tf {100 + 120 * i} 400 Td (CO{des}) Tj ET")
        righe.append(f"BT /F1 10 Tf {100 + 120 * i} 420 Td ({des}) Tj ET")
    if nota:
        righe.append(f"BT /F1 9 Tf 100 100 Td ({nota}) Tj ET")
    flusso = DecodedStreamObject()
    flusso.set_data("\n".join(righe).encode("latin-1"))
    pagina[NameObject("/Contents")] = w._add_object(ContentStream(flusso, w))
    radice = w.add_outline_item("SCH", 0)
    comp = w.add_outline_item("Components", 0, parent=radice)
    for des, pins in scheda["componenti"].items():
        nodo = w.add_outline_item(des, 0, parent=comp)
        for p in pins:
            w.add_outline_item(f"{des}-{p}", 0, parent=nodo)
    nets = w.add_outline_item("Nets", 0, parent=radice)
    for net, pins in scheda["nets"].items():
        nodo = w.add_outline_item(net, 0, parent=nets)
        gruppo = w.add_outline_item("Pins", 0, parent=nodo)
        for p in pins:
            w.add_outline_item(p, 0, parent=gruppo)
    with open(percorso, "wb") as f:
        w.write(f)
    return percorso


def cartella_azienda(base: Path) -> Path:
    pdf_altium(base / "MADRE.pdf", MADRE)
    pdf_altium(base / "RADIO.pdf", RADIO, nota="Changing obj from Rev1.0 to Rev2.0: changed strip from THD to SMD")
    (base / "bom_madre.csv").write_text(
        "Progetto;MADRE\n\nFitted;Comment;Designator;Description;Footprint;Quantity\n"
        "Fitted;STM32F401VDT6;U3;ARM Cortex-M4 microcontroller;LQFP-100;1\n"
        "Fitted;22R;R10;Chip resistor 0603 22 ohm;0603R;1\n"
        "Fitted;HEADER 4 PIN;J4;Pin header;HDR4;1\n"
        "Not Fitted;100n;C1;Capacitor;0603C;0\n", encoding="utf-8")
    (base / "prodotti.yaml").write_text("""
schede:
  - {codice: MADRE, nome: Scheda madre, netlist: MADRE.pdf, bom: bom_madre.csv}
  - codice: RADIO
    nome: Modulo radio
    netlist: RADIO.pdf
    componenti: {U1: {valore: NRF905, descrizione: Transceiver 433 MHz}}
prodotti:
  - nome: Centralina di prova
    schede: [MADRE, RADIO]
    collegamenti: [{da: MADRE.J4, a: RADIO.J1}]
""", encoding="utf-8")
    return base
