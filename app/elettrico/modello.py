"""Modello comune dei dati elettronici, indipendente dal programma CAD."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# net di alimentazione e massa: collegano quasi tutto, quindi nei percorsi e nei sottocircuiti si saltano
_ALIMENTAZIONE = re.compile(r"^(GND|AGND|DGND|PGND|VSS|VDD|VCC|VBAT|V\d|\+?\d+V\d*|\+?\d+V|3V3|5V|12V|24V)", re.I)


def e_alimentazione(net: str) -> bool:
    n = net.lstrip("+").upper()
    return bool(_ALIMENTAZIONE.match(n)) or "GND" in n


def pin_di(rif: str) -> tuple[str, str]:
    """'U1-14' -> ('U1', '14')"""
    des, _, pin = rif.rpartition("-")
    return des, pin


@dataclass
class Componente:
    designator: str
    valore: str = ""               # commento / valore (es. '22K', 'NRF905', 'STM32F401VDT6')
    descrizione: str = ""
    footprint: str = ""
    montato: bool | None = None    # None = non indicato (nessuna BOM)
    codice_produttore: str = ""
    fornitore: str = ""
    pin: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {"designator": self.designator, "valore": self.valore, "descrizione": self.descrizione,
                "footprint": self.footprint, "montato": self.montato, "codice_produttore": self.codice_produttore,
                "fornitore": self.fornitore, "numero_pin": len(self.pin)}


@dataclass
class Scheda:
    codice: str                                       # es. 'RADIO01'
    nome: str = ""                                    # es. 'Modulo radio 433 MHz'
    componenti: dict[str, Componente] = field(default_factory=dict)
    nets: dict[str, set[str]] = field(default_factory=dict)      # nome net -> {'U1-14', 'R4-2', ...}
    pdf_disegno: str | None = None                    # PDF su cui evidenziare (schema o montaggio)
    note: list[str] = field(default_factory=list)     # note di revisione, avvisi di importazione

    def __post_init__(self):
        self._indice: dict[str, str] | None = None

    def net_del_pin(self, rif: str) -> str | None:
        if self._indice is None:
            self._indice = {p: n for n, pins in self.nets.items() for p in pins}
        return self._indice.get(rif)

    def invalida(self) -> None:
        self._indice = None


@dataclass
class Collegamento:
    """Connettore di una scheda collegato a quello di un'altra, pin per pin."""
    scheda_a: str
    connettore_a: str
    scheda_b: str
    connettore_b: str
    mappa: dict[str, str] = field(default_factory=dict)   # pin_a -> pin_b; vuota = stesso numero

    def corrispondente(self, scheda: str, connettore: str, pin: str) -> tuple[str, str, str] | None:
        if scheda == self.scheda_a and connettore == self.connettore_a:
            return self.scheda_b, self.connettore_b, self.mappa.get(pin, pin)
        if scheda == self.scheda_b and connettore == self.connettore_b:
            inversa = {v: k for k, v in self.mappa.items()}
            return self.scheda_a, self.connettore_a, inversa.get(pin, pin)
        return None


@dataclass
class Prodotto:
    nome: str
    schede: list[str]
    collegamenti: list[Collegamento] = field(default_factory=list)
    descrizione: str = ""
