"""Importatore di distinte base (BOM) in Excel (.xls, .xlsx) o CSV, con colonne riconosciute per nome.

Funziona con le BOM di Altium e con le intestazioni più comuni in italiano e in inglese; la riga di
intestazione viene cercata automaticamente (le BOM aziendali hanno spesso un cartiglio sopra la tabella).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from app.elettrico.modello import Componente, Scheda

COLONNE = {  # campo -> nomi possibili (minuscolo, confronto per inclusione)
    "designator": ["designator", "riferiment", "refdes", "reference", "sigla"],
    "valore": ["comment", "value", "valore"],
    "descrizione": ["description", "descrizione"],
    "footprint": ["footprint", "package", "contenitore"],
    "montato": ["fitted", "montat", "dnp", "populate"],
    "codice_produttore": ["manufacturer part", "mpn", "codice produttore", "part number"],
    "fornitore": ["supplier 1", "fornitore", "supplier"],
}


def _riga_intestazione(grezzo: pd.DataFrame) -> int:
    for i, riga in grezzo.head(40).iterrows():
        celle = [str(c).lower() for c in riga if pd.notna(c)]
        if any(any(n in c for n in COLONNE["designator"]) for c in celle):
            return int(i)
    raise ValueError("nessuna colonna dei riferimenti (Designator) trovata nella BOM")


def _mappa_colonne(colonne: list[str]) -> dict[str, str]:
    mappa = {}
    for campo, nomi in COLONNE.items():
        for c in colonne:
            cl = str(c).lower()
            if campo == "codice_produttore" and "supplier" in cl:
                continue        # il codice del fornitore non è il codice del produttore
            if any(n in cl for n in nomi) and c not in mappa.values():
                mappa[campo] = c
                break
    return mappa


def espandi_designator(testo: str) -> list[str]:
    """'R1, R2, R5-R7' -> ['R1', 'R2', 'R5', 'R6', 'R7']"""
    out = []
    for parte in re.split(r"[,;\s]+", str(testo).strip()):
        if not parte or parte.lower() == "nan":
            continue
        m = re.fullmatch(r"([A-Za-z]+)(\d+)-\1?(\d+)", parte)
        if m:
            out += [f"{m.group(1)}{k}" for k in range(int(m.group(2)), int(m.group(3)) + 1)]
        else:
            out.append(parte)
    return out


def _montato(valore) -> bool | None:
    if pd.isna(valore):
        return None
    v = str(valore).strip().lower()
    if v in ("not fitted", "no", "n", "dnp", "non montato", "n.m.", "nm", "false", "0"):
        return False
    return True


def _leggi_csv(p: Path) -> pd.DataFrame:
    """CSV con righe di lunghezza diversa (cartiglio sopra la tabella): separatore dedotto e righe completate."""
    import csv

    testo = p.read_text(encoding="utf-8-sig", errors="replace")
    sep = max([";", ",", "\t"], key=testo.count)
    righe = list(csv.reader(testo.splitlines(), delimiter=sep))
    larghezza = max((len(r) for r in righe), default=0)
    return pd.DataFrame([r + [None] * (larghezza - len(r)) for r in righe], dtype=str).replace({"": None})


def leggi(percorso: str | Path) -> list[Componente]:
    p = Path(percorso)
    if p.suffix.lower() in (".csv", ".txt"):
        grezzo = _leggi_csv(p)
    else:
        grezzo = pd.read_excel(p, header=None, dtype=str)
    h = _riga_intestazione(grezzo)
    tabella = grezzo.iloc[h + 1:].copy()
    tabella.columns = [str(c) for c in grezzo.iloc[h]]
    mappa = _mappa_colonne(list(tabella.columns))
    componenti = []
    for _, r in tabella.iterrows():
        des = r.get(mappa["designator"])
        if pd.isna(des) or not str(des).strip():
            continue
        campi = {k: ("" if pd.isna(r.get(c)) else str(r.get(c)).strip()) for k, c in mappa.items()
                 if k not in ("designator", "montato")}
        for d in espandi_designator(des):
            componenti.append(Componente(designator=d, montato=_montato(r.get(mappa.get("montato"))),
                                         **{k: v.replace("[NoValue]", "").strip(", ") for k, v in campi.items()}))
    return componenti


def unisci(scheda: Scheda, componenti: list[Componente]) -> list[str]:
    """Aggiunge i dati della BOM ai componenti della scheda; restituisce le incongruenze trovate."""
    avvisi = []
    for c in componenti:
        esistente = scheda.componenti.get(c.designator)
        if esistente is None:
            avvisi.append(f"{c.designator} è nella BOM ma non nella netlist")
            scheda.componenti[c.designator] = c
            continue
        for campo in ("valore", "descrizione", "footprint", "codice_produttore", "fornitore"):
            if getattr(c, campo):
                setattr(esistente, campo, getattr(c, campo))
        esistente.montato = c.montato
    nella_bom = {c.designator for c in componenti}
    mancanti = sorted(d for d in scheda.componenti if d not in nella_bom and not re.match(r"^(TP|FID|LOGO|MH|H)\d*", d))
    if mancanti:
        avvisi.append(f"sulla scheda ma non nella BOM: {', '.join(mancanti)}")
    return avvisi
