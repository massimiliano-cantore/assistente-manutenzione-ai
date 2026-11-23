"""Catalogo dei prodotti e delle loro schede, con le operazioni sul circuito usate dagli strumenti dell'agente.

La documentazione di un'azienda sta in una cartella SEPARATA dal codice (mai nel repository), descritta da
un file prodotti.yaml: quali schede compongono ogni prodotto, quali file le descrivono e come sono collegate.
"""
from __future__ import annotations

import logging
import re
from collections import deque
from pathlib import Path

import yaml

from app.elettrico import altium_pdf, bom
from app.elettrico.modello import Collegamento, Componente, Prodotto, Scheda, e_alimentazione, pin_di

log = logging.getLogger(__name__)
_SERIE = re.compile(r"^(R|RN|L|FB|F|JP|D|SW|K)\d", re.I)   # componenti a 2 pin che un segnale attraversa


def importa_scheda(cartella: Path, voce: dict) -> Scheda:
    netlist = cartella / voce["netlist"]
    if netlist.suffix.lower() == ".pdf" and altium_pdf.e_pdf_altium(netlist):
        scheda = altium_pdf.importa(netlist, voce["codice"], voce.get("nome", ""))
    else:
        raise ValueError(f"formato della netlist non supportato: {netlist.name}")
    if voce.get("disegno"):
        scheda.pdf_disegno = str(cartella / voce["disegno"])
    if voce.get("bom"):
        scheda.note += bom.unisci(scheda, bom.leggi(cartella / voce["bom"]))
    for des, valore in (voce.get("componenti") or {}).items():     # integrazioni a mano (es. scheda senza BOM)
        c = scheda.componenti.setdefault(des, Componente(designator=des))
        if isinstance(valore, dict):
            for k, v in valore.items():
                setattr(c, k, v)
        else:
            c.valore = str(valore)
    return scheda


class Catalogo:
    def __init__(self, schede: dict[str, Scheda], prodotti: list[Prodotto], cartella: Path | None = None,
                 firmware: dict[str, list[dict]] | None = None, extra: dict[str, dict] | None = None):
        self.schede, self.prodotti, self.cartella = schede, prodotti, cartella
        self.firmware = firmware or {}        # scheda -> file firmware trovati dallo scanner
        self.extra = extra or {}              # scheda -> voci a mano di prodotti.yaml (mcu, piedinatura_mcu)

    @classmethod
    def carica(cls, cartella: str | Path) -> Catalogo:
        cartella = Path(cartella)
        conf = yaml.safe_load((cartella / "prodotti.yaml").read_text(encoding="utf-8"))
        schede = {}
        for voce in conf.get("schede", []):
            schede[voce["codice"]] = importa_scheda(cartella, voce)
            log.info("scheda %s: %d componenti, %d net", voce["codice"], len(schede[voce["codice"]].componenti),
                     len(schede[voce["codice"]].nets))
        prodotti, firmware = [], {}
        for p in conf.get("prodotti", []):
            coll = []
            for c in p.get("collegamenti", []):
                if "?" in c["da"] + c["a"]:      # bozza non completata
                    continue
                sa, ca = c["da"].split(".", 1)
                sb, cb = c["a"].split(".", 1)
                coll.append(Collegamento(sa, ca, sb, cb, {str(k): str(v) for k, v in (c.get("mappa") or {}).items()}))
            prodotti.append(Prodotto(p["nome"], p["schede"], coll, p.get("descrizione", "")))
            for b in (p.get("firmware") or {}).get("binari", []):
                if b.get("scheda"):
                    firmware.setdefault(b["scheda"], []).append(b)
        extra = {v["codice"]: {k: v[k] for k in ("mcu", "piedinatura_mcu") if k in v} for v in conf.get("schede", [])}
        return cls(schede, prodotti, cartella, firmware, extra)

    # --- ricerca -------------------------------------------------------------------------------------------
    def scheda(self, codice: str) -> Scheda:
        for k, s in self.schede.items():
            if k.lower() == codice.strip().lower():
                return s
        raise KeyError(f"scheda {codice} non trovata (disponibili: {', '.join(self.schede)})")

    def panoramica(self) -> dict:
        return {"prodotti": [{"nome": p.nome, "descrizione": p.descrizione, "schede": p.schede,
                              "collegamenti": [f"{c.scheda_a}.{c.connettore_a} <-> {c.scheda_b}.{c.connettore_b}"
                                               for c in p.collegamenti]} for p in self.prodotti],
                "schede": [{"codice": s.codice, "nome": s.nome, "componenti": len(s.componenti), "net": len(s.nets),
                            "note": s.note} for s in self.schede.values()]}

    def cerca_componenti(self, testo: str, scheda: str = "", limite: int = 15) -> list[dict]:
        parole = [p for p in re.split(r"\s+", testo.lower()) if p]
        out = []
        for s in ([self.scheda(scheda)] if scheda else self.schede.values()):
            for c in s.componenti.values():
                campo = f"{c.designator} {c.valore} {c.descrizione} {c.footprint}".lower()
                if parole and all(p in campo for p in parole):
                    out.append({"scheda": s.codice, **c.to_dict()})
        return out[:limite]

    def info_componente(self, scheda: str, designator: str) -> dict:
        s = self.scheda(scheda)
        c = s.componenti.get(designator.strip().upper()) or s.componenti.get(designator.strip())
        if not c:
            raise KeyError(f"{designator} non c'è sulla scheda {s.codice}")
        pin = []
        for p in sorted(c.pin, key=lambda x: (len(x), x)):
            rif = f"{c.designator}-{p}"
            net = s.net_del_pin(rif)
            altri = sorted(x for x in s.nets.get(net, ()) if x != rif) if net else []
            pin.append({"pin": p, "net": net or "(non collegato)",
                        "collegato_a": altri[:8] + ([f"... e altri {len(altri) - 8}"] if len(altri) > 8 else []),
                        "verso_altra_scheda": self._attraverso_connettore(s.codice, rif)})
        return {"scheda": s.codice, **c.to_dict(), "pin": pin}

    # --- collegamenti ----------------------------------------------------------------------------------------
    def _attraverso_connettore(self, scheda: str, rif: str) -> str | None:
        des, pin = pin_di(rif)
        for p in self.prodotti:
            for col in p.collegamenti:
                altro = col.corrispondente(scheda, des, pin)
                if altro:
                    return f"{altro[0]}:{altro[1]}-{altro[2]}"
        return None

    def collegati(self, scheda: str, rif: str) -> dict:
        """Tutti i pin sulla stessa net, anche oltre i connettori verso le altre schede."""
        s = self.scheda(scheda)
        net = s.net_del_pin(rif)
        if not net:
            return {"pin": f"{s.codice}:{rif}", "net": None, "nota": "pin non collegato o inesistente"}
        risultato = {"pin": f"{s.codice}:{rif}", "net": net, "alimentazione": e_alimentazione(net),
                     "pin_sulla_net": sorted(s.nets[net]), "su_altre_schede": []}
        for p in s.nets[net]:
            oltre = self._attraverso_connettore(s.codice, p)
            if oltre:
                sb, rb = oltre.split(":")
                nb = self.scheda(sb).net_del_pin(rb)
                risultato["su_altre_schede"].append({"tramite": f"{s.codice}:{p} -> {oltre}", "net": nb,
                                                     "pin_sulla_net": sorted(self.scheda(sb).nets.get(nb, []))})
        return risultato

    def _vicini(self, nodo: tuple[str, str], arrivo: tuple[str, str]):
        sc, rif = nodo
        s = self.scheda(sc)
        net = s.net_del_pin(rif)
        if net and (not e_alimentazione(net) or arrivo[1] in s.nets[net] and arrivo[0] == sc):
            for p in s.nets[net]:
                if p != rif:
                    yield (sc, p), f"net {net}"
        des, pin = pin_di(rif)
        c = s.componenti.get(des)
        if c and len(c.pin) == 2 and _SERIE.match(des):
            altro = next(iter(c.pin - {pin}), None)
            if altro:
                yield (sc, f"{des}-{altro}"), f"attraverso {des} ({c.valore or c.descrizione or 'componente'})"
        oltre = self._attraverso_connettore(sc, rif)
        if oltre:
            sb, rb = oltre.split(":")
            yield (sb, rb), f"connettore verso la scheda {sb}"

    def percorso(self, scheda_da: str, pin_da: str, scheda_a: str, pin_a: str, max_passi: int = 40) -> dict:
        """Strada più breve da un pin a un altro: net, componenti in serie (R, L, ferriti...) e connettori."""
        inizio, fine = (self.scheda(scheda_da).codice, pin_da), (self.scheda(scheda_a).codice, pin_a)
        coda, provenienza = deque([inizio]), {inizio: None}
        while coda:
            nodo = coda.popleft()
            if nodo == fine:
                break
            for vicino, come in self._vicini(nodo, fine):
                if vicino not in provenienza:
                    provenienza[vicino] = (nodo, come)
                    if len(provenienza) > 20000:
                        break
                    coda.append(vicino)
        if fine not in provenienza:
            return {"trovato": False, "nota": "nessun percorso di segnale (escluse alimentazioni e masse)"}
        passi, nodo = [], fine
        while provenienza[nodo]:
            prec, come = provenienza[nodo]
            passi.append({"da": f"{prec[0]}:{prec[1]}", "a": f"{nodo[0]}:{nodo[1]}", "come": come})
            nodo = prec
        passi.reverse()
        attraversati = [p["come"].split(" ")[1] for p in passi if p["come"].startswith("attraverso")]
        return {"trovato": True, "passi": passi[:max_passi], "componenti_attraversati": attraversati}

    def sottocircuito(self, scheda: str, designator: str) -> dict:
        """Componenti collegati direttamente a un componente, esclusi alimentazioni e masse."""
        s = self.scheda(scheda)
        c = s.componenti[designator]
        vicini: dict[str, set[str]] = {}
        alimentazioni = set()
        for p in c.pin:
            net = s.net_del_pin(f"{designator}-{p}")
            if not net:
                continue
            if e_alimentazione(net):
                alimentazioni.add(net)
                continue
            for altro in s.nets[net]:
                d, _ = pin_di(altro)
                if d != designator:
                    vicini.setdefault(d, set()).add(net)
        return {"scheda": s.codice, "componente": designator, "alimentazioni": sorted(alimentazioni),
                "vicini": [{"designator": d, "valore": s.componenti[d].valore if d in s.componenti else "",
                            "descrizione": (s.componenti[d].descrizione if d in s.componenti else "")[:80],
                            "net": sorted(n)} for d, n in sorted(vicini.items())]}
