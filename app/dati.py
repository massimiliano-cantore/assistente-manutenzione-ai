"""Dati dell'archivio riparazioni KYROS ACCESS (azienda fittizia, dati sintetici).

`carica` e `pulisci` riprendono la pulizia del progetto document-ai-schede-riparazione:
duplicati, date impossibili, esiti scritti male.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pandas as pd

NORMA_OP = {"speditp": "spedito", "spedita": "spedito", "rottamata": "rottamato", "rottamare": "rottamato"}
OGGI = "2026-09-30"   # data di riferimento del dataset sintetico


def carica(db: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    c = sqlite3.connect(db)
    d = pd.read_sql("""SELECT r.*, c.nome cliente, c.provincia, c.tipo tipo_cliente, a.codice articolo, a.famiglia
                       FROM rientri r JOIN clienti c ON c.id=r.cliente_id JOIN articoli a ON a.id=r.articolo_id""", c)
    p = pd.read_sql("SELECT * FROM pezzi_intervento", c)
    c.close()
    return d, p


def pulisci(d: pd.DataFrame, oggi: str = OGGI) -> pd.DataFrame:
    d = d.copy()
    for col in ["ddt_data", "ricevuto_il", "scheda_consegnata", "data_chiusura"]:
        d[col] = pd.to_datetime(d[col])
    d = d.drop_duplicates([c for c in d.columns if c != "id"])
    d = d[(d.ricevuto_il <= pd.Timestamp(oggi)) & d.ricevuto_il.notna()].copy()
    d["operazione"] = d.operazione.str.lower().str.strip().replace(NORMA_OP)
    d.loc[d.scheda_consegnata < d.ricevuto_il, "scheda_consegnata"] = pd.NaT
    d["giorni_lavorazione"] = (d.data_chiusura - d.ricevuto_il).dt.days
    neg = d.giorni_lavorazione < 0
    d.loc[neg, ["data_chiusura", "giorni_lavorazione"]] = [pd.NaT, None]
    return d


class ArchivioResi:
    """Archivio pulito in un SQLite in memoria, aperto in SOLA LETTURA per lo strumento SQL dell'agente."""

    MAX_RIGHE = 50

    def __init__(self, db: Path):
        d, p = carica(db)
        self.rientri = pulisci(d)
        self.pezzi = p[p.rientro_id.isin(self.rientri.id)].drop(columns=["id"])
        t = self.rientri.drop(columns=["cliente_id", "articolo_id"]).copy()
        for c in ["ddt_data", "ricevuto_il", "scheda_consegnata", "data_chiusura"]:
            t[c] = t[c].dt.strftime("%Y-%m-%d")
        uri = f"file:archivio_{id(self)}?mode=memory&cache=shared"
        self._scrittura = sqlite3.connect(uri, uri=True, check_same_thread=False)  # tiene viva la memoria
        t.to_sql("rientri", self._scrittura, index=False)
        self.pezzi.to_sql("pezzi", self._scrittura, index=False)
        self.con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.con.execute("PRAGMA query_only = ON")

    def sql(self, query: str) -> dict:
        q = query.strip().rstrip(";")
        if not re.match(r"(?is)^\s*(select|with)\b", q) or ";" in q:
            return {"errore": "ammessa solo una singola query SELECT/WITH"}
        try:
            r = pd.read_sql(q, self.con)
        except Exception as e:  # l'errore torna al modello, che può correggere la query
            return {"errore": str(e)[:300]}
        return {"righe_totali": len(r),
                "righe": json.loads(r.head(self.MAX_RIGHE).to_json(orient="records", force_ascii=False))}

    def profili_casi(self) -> list[dict]:
        """Un profilo per ogni coppia (famiglia, diagnosi): quanti casi, pezzi sostituiti, esiti, esempi.
        Sono i documenti su cui lavora la ricerca dei 'casi simili'."""
        d = self.rientri[self.rientri.note.fillna("").str.strip() != ""].copy()
        d["diagnosi"] = d.note.str.split("\n").str[0].str.strip()
        pz = self.pezzi.merge(d[["id", "famiglia", "diagnosi"]], left_on="rientro_id", right_on="id")
        profili = []
        for (fam, diag), g in d.groupby(["famiglia", "diagnosi"]):
            gp = pz[(pz.famiglia == fam) & (pz.diagnosi == diag)]
            top = (gp.groupby(["codice", "descrizione"]).size().sort_values(ascending=False).head(4))
            esiti = g.operazione.value_counts(normalize=True).head(3)
            profili.append({
                "id": f"{fam}|{diag}",
                "famiglia": fam,
                "diagnosi": diag,
                "casi": int(len(g)),
                "pezzi_frequenti": [{"codice": c, "descrizione": ds, "quota": round(n / len(g), 2)}
                                    for (c, ds), n in top.items()],
                "esiti": {k: round(float(v), 2) for k, v in esiti.items()},
                "giorni_mediani": None if g.giorni_lavorazione.isna().all() else float(g.giorni_lavorazione.median()),
                "esempi": g.sort_values("ricevuto_il", ascending=False).riparazione_numero.head(3).tolist(),
                "testo": f"{fam}: {diag}",
            })
        return profili


def sezioni_pdf(f: Path, caratteri: int = 1500) -> list[dict]:
    """Manuali e istruzioni in PDF: un documento per pagina (spezzato se troppo lungo), citabile come 'file#p3'."""
    import pypdfium2 as pdfium

    out = []
    doc = pdfium.PdfDocument(str(f))
    try:
        for n, pagina in enumerate(doc, 1):
            testo = re.sub(r"[ \t]+", " ", pagina.get_textpage().get_text_range()).strip()
            for k in range(0, len(testo), caratteri):
                pezzo = testo[k:k + caratteri]
                if len(pezzo) > 80:
                    out.append({"id": f"{f.stem}#p{n}" + (f"-{k // caratteri + 1}" if k else ""), "manuale": f.stem,
                                "famiglia": "generale", "titolo": f"{f.stem}, pagina {n}", "testo": pezzo})
    finally:
        doc.close()
    return out


def sezioni_manuali(cartella: Path) -> list[dict]:
    """Chunking dei manuali: i Markdown per sezione '## ', i PDF per pagina."""
    out = []
    if not cartella.exists():
        return out
    for f in sorted(cartella.glob("*.pdf")) + sorted(cartella.glob("*.PDF")):
        out += sezioni_pdf(f)
    for f in sorted(cartella.glob("*.md")):
        testo = f.read_text(encoding="utf-8")
        intestazione = re.search(r"^#\s+(.+)$", testo, re.M)
        fam = re.search(r"^famiglia:\s*(\w+)", testo, re.M)
        for blocco in re.split(r"(?m)^##\s+", testo)[1:]:
            titolo, _, corpo = blocco.partition("\n")
            slug = re.sub(r"[^a-z0-9]+", "-", titolo.lower()).strip("-")
            out.append({
                "id": f"{f.stem}#{slug}",
                "manuale": intestazione.group(1).strip() if intestazione else f.stem,
                "famiglia": fam.group(1) if fam else "generale",
                "titolo": titolo.strip(),
                "testo": f"{titolo.strip()}\n{corpo.strip()}",
            })
    return out
