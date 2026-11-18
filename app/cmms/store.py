"""Finto CMMS (sistema di gestione della manutenzione) di KYROS ACCESS.

Impianti installati presso i clienti, magazzino ricambi e ordini di lavoro. Il contenuto iniziale è
generato in modo deterministico dall'archivio resi sintetico, così clienti, articoli e codici ricambio
coincidono con quelli che l'agente trova nello storico.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import date
from pathlib import Path

import numpy as np

from app.dati import carica, pulisci

SCHEMA = """
CREATE TABLE impianti (id TEXT PRIMARY KEY, cliente TEXT, provincia TEXT, articolo TEXT, famiglia TEXT,
                       seriale TEXT UNIQUE, installato_il DATE, rientri_6_mesi INTEGER, ultimo_rientro DATE);
CREATE TABLE ricambi (codice TEXT PRIMARY KEY, descrizione TEXT, giacenza INTEGER, scorta_minima INTEGER,
                      prezzo_eur REAL);
CREATE TABLE ordini (id TEXT PRIMARY KEY, impianto_id TEXT REFERENCES impianti(id), descrizione TEXT,
                     priorita TEXT, stato TEXT, ricambi TEXT, creato_il DATE, creato_da TEXT);
"""
PRIORITA = ("bassa", "media", "alta")
FORME_SOCIETARIE = {"SRL", "SPA", "SNC", "SAS", "SRLS", "SS"}


class CMMSStore:
    def __init__(self, db_resi: Path, percorso: str = ":memory:", oggi: str = "2026-09-30"):
        self.oggi = oggi
        self._lock = threading.Lock()
        self.con = sqlite3.connect(percorso, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        if not self.con.execute("SELECT name FROM sqlite_master WHERE name='impianti'").fetchone():
            self.con.executescript(SCHEMA)
            self._popola(db_resi)

    def _popola(self, db_resi: Path) -> None:
        rng = np.random.default_rng(7)
        d, p = carica(db_resi)
        d = pulisci(d)
        recenti = d[d.ricevuto_il > np.datetime64(self.oggi) - np.timedelta64(183, "D")]
        imp = (d.groupby(["cliente", "provincia", "articolo", "famiglia"])
               .agg(ultimo=("ricevuto_il", "max")).reset_index().sort_values(["cliente", "articolo"]))
        n6 = recenti.groupby(["cliente", "articolo"]).size()
        righe = []
        for i, r in enumerate(imp.itertuples(), 1):
            anno = int(rng.integers(2016, 2025))
            righe.append((f"IMP-{i:05d}", r.cliente, r.provincia, r.articolo, r.famiglia,
                          f"KY{anno % 100:02d}{i:05d}{int(rng.integers(0, 10))}",
                          f"{anno}-{int(rng.integers(1, 13)):02d}-01",
                          int(n6.get((r.cliente, r.articolo), 0)), r.ultimo.strftime("%Y-%m-%d")))
        self.con.executemany("INSERT INTO impianti VALUES (?,?,?,?,?,?,?,?,?)", righe)
        ric = p.groupby(["codice", "descrizione"]).size().reset_index()
        self.con.executemany("INSERT INTO ricambi VALUES (?,?,?,?,?)", [
            (r.codice, r.descrizione, int(rng.integers(0, 40)), int(rng.integers(3, 10)),
             float(round(rng.uniform(2, 90), 2))) for r in ric.itertuples()])
        self.con.commit()

    # --- letture ----------------------------------------------------------------------------------------
    def cerca_impianti(self, cliente: str = "", seriale: str = "", articolo: str = "", limite: int = 20) -> list[dict]:
        q, par = "SELECT * FROM impianti WHERE 1=1", []
        # "NovaPorta s.r.l." trova "NOVAPORTA SRL": ogni parola significativa deve comparire nel nome
        parole = [p for p in re.sub(r"[^\w\s]", "", cliente.upper()).split() if p not in FORME_SOCIETARIE]
        if cliente.strip() and not parole:
            return []
        for parola in parole:
            q += " AND cliente LIKE ?"; par.append(f"%{parola}%")
        if seriale:
            q += " AND seriale = ?"; par.append(seriale.strip().upper())
        if articolo:
            q += " AND articolo = ?"; par.append(articolo.strip())
        q += " ORDER BY rientri_6_mesi DESC, id LIMIT ?"; par.append(limite)
        return [dict(r) for r in self.con.execute(q, par)]

    def impianto(self, impianto_id: str) -> dict | None:
        r = self.con.execute("SELECT * FROM impianti WHERE id=?", (impianto_id,)).fetchone()
        return dict(r) if r else None

    def ricambio(self, codice: str) -> dict | None:
        r = self.con.execute("SELECT * FROM ricambi WHERE codice=?", (codice.strip().upper(),)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["sotto_scorta"] = d["giacenza"] < d["scorta_minima"]
        return d

    def ordini(self, stato: str = "", impianto_id: str = "") -> list[dict]:
        q, par = "SELECT * FROM ordini WHERE 1=1", []
        if stato:
            q += " AND stato=?"; par.append(stato)
        if impianto_id:
            q += " AND impianto_id=?"; par.append(impianto_id)
        return [{**dict(r), "ricambi": [x for x in r["ricambi"].split(",") if x]}
                for r in self.con.execute(q + " ORDER BY id DESC", par)]

    # --- scrittura --------------------------------------------------------------------------------------
    def crea_ordine(self, impianto_id: str, descrizione: str, priorita: str, ricambi: list[str],
                    creato_da: str = "assistente-ai") -> dict:
        if not self.impianto(impianto_id):
            raise ValueError(f"impianto inesistente: {impianto_id}")
        if priorita not in PRIORITA:
            raise ValueError(f"priorità non valida: {priorita} (ammesse: {', '.join(PRIORITA)})")
        ricambi = [c.strip().upper() for c in ricambi if c.strip()]
        sconosciuti = [c for c in ricambi if not self.ricambio(c)]
        if sconosciuti:
            raise ValueError(f"codici ricambio inesistenti: {', '.join(sconosciuti)}")
        with self._lock:
            n = self.con.execute("SELECT COUNT(*) FROM ordini").fetchone()[0] + 1
            oid = f"ODL-{self.oggi[:4]}-{n:04d}"
            self.con.execute("INSERT INTO ordini VALUES (?,?,?,?,?,?,?,?)",
                             (oid, impianto_id, descrizione, priorita, "aperto", ",".join(ricambi),
                              date.fromisoformat(self.oggi).isoformat(), creato_da))
            self.con.commit()
        avvisi = [f"{c} sotto scorta (giacenza {r['giacenza']})" for c in ricambi
                  if (r := self.ricambio(c)) and r["sotto_scorta"]]
        return {**self.ordine(oid), "avvisi": avvisi}

    def ordine(self, oid: str) -> dict | None:
        r = self.con.execute("SELECT * FROM ordini WHERE id=?", (oid,)).fetchone()
        return {**dict(r), "ricambi": [x for x in r["ricambi"].split(",") if x]} if r else None
