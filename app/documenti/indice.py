"""Indice di tutti i documenti dei prodotti (Produzione1): ricerca per articolo, codice, particolare o parte di parola.

Per ogni file si salvano percorso, titolo, data, categoria (istruzioni / schemi / altri), prodotto (cartella di primo
livello) e il testo estratto (PDF, Word, Excel, testo). La ricerca usa SQLite FTS5 (libreria standard): parole
intere, inizio di parola e, sui nomi dei file, anche parti di parola. L'indice è incrementale: alla ricostruzione si
rileggono solo i file nuovi o modificati.

Le stesse idee di kb-parser (titolo, data normalizzata AAAA-MM-GG, estratto, decodifica dei testi), estese ai
formati dei documenti tecnici.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger("documenti")

CARTELLE_ESCLUSE = {"storico", "firmware_analisi", ".cache", "__pycache__"}
TESTO_MAX = 200_000
PAGINE_PDF_MAX = 40
ISTRUZIONI = re.compile(r"(?i)istruz|manual|installaz|montaggio|uso e manut|guida|user.?guide|\bist[_ -]|libretto")
SCHEMI = re.compile(r"(?i)(^|[ _\-/])(sch|schema|schemi|schematic|elettric|asm)[ _\-.]|wiring|cablaggio|\.schdoc")
VERSIONE = re.compile(r"(?i)[ _\-.]*(rev|ver|vers|v)\.?[ _]?\d+([._]\d+)*[a-z]?\b|[ _\-]\(\d+\)$|[ _\-]copia$")
DATA_TESTO = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")


@dataclass
class Documento:
    percorso: str          # relativo alla radice, con '/'
    nome: str
    titolo: str
    data: str              # AAAA-MM-GG
    categoria: str         # istruzioni | schemi | altri
    prodotto: str
    gruppo: str            # stesso documento in versioni diverse
    estensione: str
    estratto: str


# --- estrazione del testo ---------------------------------------------------------------------------------------

def _testo_pdf(f: Path) -> str:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(f))
    try:
        parti = []
        for i in range(min(len(pdf), PAGINE_PDF_MAX)):
            pagina = pdf[i]
            tp = pagina.get_textpage()
            parti.append(tp.get_text_range())
            tp.close()
            pagina.close()
        return "\n".join(parti)
    finally:
        pdf.close()


def _testo_docx(f: Path) -> str:
    with zipfile.ZipFile(f) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    return re.sub(r"<[^>]+>", " ", xml.replace("</w:p>", "\n"))


def _testo_excel(f: Path) -> str:
    import pandas as pd
    fogli = pd.read_excel(f, sheet_name=None, header=None, dtype=str)
    righe = []
    for df in fogli.values():
        for r in df.fillna("").values.tolist():
            riga = " ".join(c for c in r if c and c.lower() != "nan")
            if riga.strip():
                righe.append(riga)
    return "\n".join(righe)


def _testo_semplice(f: Path) -> str:
    dati = f.read_bytes()[:2_000_000]
    if dati.startswith((b"\xff\xfe", b"\xfe\xff")):
        return dati.decode("utf-16", "replace")
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return dati.decode(cod)
        except UnicodeDecodeError:
            pass
    return dati.decode("latin-1", "replace")


def _testo_odf(f: Path) -> str:
    """Documenti LibreOffice (odg, odt, ods, odp): il testo sta in content.xml dentro lo zip."""
    import zipfile
    with zipfile.ZipFile(f) as z:
        xml = z.read("content.xml").decode("utf-8", "replace")
    xml = re.sub(r"</text:(p|h)>|<text:line-break/>|<text:tab/>", "\n", xml)
    return re.sub(r"<[^>]+>", " ", xml).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def _testo_solidworks(f: Path) -> str:
    """Tavole, assiemi e particolari SolidWorks: codice, denominazione e righe della distinta."""
    from app.meccanica.solidworks import leggi
    sw = leggi(f)
    righe = [sw.codice, sw.denominazione, sw.proprieta.get("DATA", "")]
    righe += [f"{c} {d}" for c, d in zip(sw.distinta, sw.descrizioni, strict=False)] or sw.descrizioni
    return "\n".join(r for r in righe if r)


LETTORI = {".pdf": _testo_pdf, ".docx": _testo_docx, ".xlsx": _testo_excel, ".xls": _testo_excel,
           ".xlsm": _testo_excel, ".txt": _testo_semplice, ".md": _testo_semplice, ".csv": _testo_semplice,
           ".odg": _testo_odf, ".sldasm": _testo_solidworks, ".slddrw": _testo_solidworks,
           ".sldprt": _testo_solidworks, ".odt": _testo_odf, ".ods": _testo_odf, ".odp": _testo_odf}


def estrai_testo(f: Path) -> str:
    lettore = LETTORI.get(f.suffix.lower())
    if not lettore:
        return ""
    try:
        return re.sub(r"[ \t]+", " ", lettore(f))[:TESTO_MAX]
    except Exception as e:  # noqa: BLE001 - un file illeggibile si indicizza solo per nome
        log.info("testo non estratto da %s: %s", f.name, e)
        return ""


# --- metadati --------------------------------------------------------------------------------------------------

def data_documento(testo: str, f: Path) -> str:
    """Prima data valida nel testo (es. il cartiglio di uno schema), altrimenti la data di modifica del file."""
    oggi = date.today()
    for m in DATA_TESTO.finditer(testo[:5000]):
        try:
            d = date(int(m[3]), int(m[2]), int(m[1])) if m[1] else date(int(m[4]), int(m[5]), int(m[6]))
        except ValueError:
            continue
        if date(1990, 1, 1) <= d <= oggi:
            return d.isoformat()
    return datetime.fromtimestamp(f.stat().st_mtime).date().isoformat()


def titolo_documento(testo: str, f: Path) -> str:
    """Il nome del file è il titolo più affidabile per i documenti tecnici (i PDF hanno titoli interni vaghi);
    per i testi brevi senza nome parlante si usa la prima riga."""
    nome = re.sub(r"[_]+", " ", f.stem).strip()
    if f.suffix.lower() in (".txt", ".md") and testo.strip() and len(nome) < 4:
        return testo.strip().splitlines()[0][:120]
    return nome


def categoria(rel: str, testo: str, schemi_noti: set[str]) -> str:
    nome = rel.rsplit("/", 1)[-1]
    tabella = nome.lower().endswith((".xls", ".xlsx", ".xlsm", ".csv"))    # BOM e distinte: non sono schemi
    if rel in schemi_noti or (SCHEMI.search(nome) and not tabella):
        return "schemi"
    if ISTRUZIONI.search(rel):
        return "istruzioni"
    if rel.lower().endswith(".pdf") and re.search(r"(?i)ALTIUM PRJ|SchDoc|PcbDoc|SHEET:\s*\d+ of", testo[:20000]):
        return "schemi"
    return "altri"


def gruppo(nome: str) -> str:
    """Chiave che accomuna le versioni dello stesso documento: 'Istruzioni_EP_rev3.pdf' ~ 'Istruzioni EP v4.pdf'."""
    base = Path(nome).stem.lower()
    for _ in range(3):
        base = VERSIONE.sub("", base)
    base = re.sub(r"(?<![a-z0-9])(19|20)\d{2}([-_.]?\d{2}){0,2}(?![a-z0-9])", "", base)   # date nel nome
    return re.sub(r"[^a-z0-9]+", " ", base).strip()


# --- indice ----------------------------------------------------------------------------------------------------

VERSIONE_INDICE = 2


class IndiceDocumenti:
    def __init__(self, file_db: str | Path, radice: str | Path | None = None):
        """radice: cartella da indicizzare; se manca si usa quella registrata nell'indice."""
        self.db = sqlite3.connect(str(file_db), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS impostazioni(chiave TEXT PRIMARY KEY, valore TEXT);
            CREATE TABLE IF NOT EXISTS meta(percorso TEXT PRIMARY KEY, dimensione INTEGER, mtime REAL, nome TEXT,
                titolo TEXT, data TEXT, categoria TEXT, prodotto TEXT, gruppo TEXT, estensione TEXT, estratto TEXT);
            CREATE VIRTUAL TABLE IF NOT EXISTS testi USING fts5(percorso UNINDEXED, titolo, cartelle, testo,
                tokenize = "unicode61 remove_diacritics 2");
        """)
        registrata = self.db.execute("SELECT valore FROM impostazioni WHERE chiave='radice'").fetchone()
        if radice is None:
            if not registrata:
                raise ValueError("indice senza cartella registrata: ricostruiscilo con scripts.indicizza_documenti")
            radice = registrata[0]
        elif registrata and Path(registrata[0]).resolve() != Path(radice).resolve():
            self.db.executescript("DELETE FROM meta; DELETE FROM testi;")   # cambiata cartella: si riparte
        self.radice = Path(radice)
        versione = self.db.execute("SELECT valore FROM impostazioni WHERE chiave='versione'").fetchone()
        if not versione or int(versione[0]) < VERSIONE_INDICE:   # file LibreOffice prima senza testo: si rileggono
            vecchi = [r[0] for r in self.db.execute(
                "SELECT percorso FROM meta WHERE estensione IN ('odg','odt','ods','odp')")]
            for v in vecchi:
                self.db.execute("DELETE FROM meta WHERE percorso=?", (v,))
                self.db.execute("DELETE FROM testi WHERE percorso=?", (v,))
            self.db.execute("INSERT OR REPLACE INTO impostazioni VALUES ('versione', ?)", (str(VERSIONE_INDICE),))
        self.db.execute("INSERT OR REPLACE INTO impostazioni VALUES ('radice', ?)", (str(self.radice),))
        self.db.commit()

    def aggiorna(self, schemi_noti: set[str] | None = None, avanzamento=None,
                 cartelle: list[str] | None = None) -> dict:
        """Indicizza i file nuovi o modificati e toglie quelli spariti.
        cartelle: sottocartelle della radice da indicizzare (le altre si saltano); None = tutta la radice."""
        schemi_noti = schemi_noti or set()
        salta_radice = (self.radice / "prodotti.yaml").exists()
        visti, nuovi, errori = set(), 0, 0
        presenti = {p: (d, m) for p, d, m in self.db.execute("SELECT percorso, dimensione, mtime FROM meta")}
        cartelle_abs = [self.radice] if cartelle is None else [self.radice / c for c in dict.fromkeys(cartelle)]
        self.registra_cartelle(cartelle_abs)
        base = self.radice.resolve()
        for c in cartelle_abs:
            for f in sorted(c.rglob("*")):
                rel_parti = f.relative_to(c).parts
                if not f.is_file() or any(p.startswith(".") or p in CARTELLE_ESCLUSE for p in rel_parti):
                    continue
                if f.parent == self.radice and salta_radice:   # rapporti e configurazioni dell'assistente
                    continue
                try:      # dentro la cartella principale: percorso relativo; altrove: percorso completo
                    rel = f.resolve().relative_to(base).as_posix()
                except ValueError:
                    rel = f.resolve().as_posix()
                if rel in visti:
                    continue
                visti.add(rel)
                st = f.stat()
                if presenti.get(rel) == (st.st_size, st.st_mtime):
                    continue
                try:
                    self._indicizza(f, rel, st, schemi_noti)
                    nuovi += 1
                except Exception as e:  # noqa: BLE001
                    errori += 1
                    log.warning("non indicizzato %s: %s", rel, e)
                if avanzamento and nuovi % 200 == 0 and nuovi:
                    avanzamento(nuovi)
        spariti = set(presenti) - visti
        for p in spariti:
            self.db.execute("DELETE FROM meta WHERE percorso=?", (p,))
            self.db.execute("DELETE FROM testi WHERE percorso=?", (p,))
        self.db.commit()
        return {"documenti": len(visti), "indicizzati_ora": nuovi, "rimossi": len(spariti), "errori": errori}

    def registra_cartelle(self, cartelle: list[Path]) -> None:
        import json
        self.db.execute("INSERT OR REPLACE INTO impostazioni VALUES ('cartelle', ?)",
                        (json.dumps([str(Path(c).resolve()) for c in cartelle]),))

    def cartelle_consentite(self) -> list[Path]:
        """Cartelle i cui file si possono aprire dai link: la principale più quelle indicizzate."""
        import json
        r = self.db.execute("SELECT valore FROM impostazioni WHERE chiave='cartelle'").fetchone()
        return [self.radice.resolve()] + [Path(c) for c in (json.loads(r[0]) if r else [])]

    def file_di(self, percorso: str) -> Path | None:
        """File su disco per un percorso dell'indice, solo se sta in una cartella consentita."""
        p = Path(percorso)
        f = (p if p.is_absolute() else self.radice / p).resolve()
        if f.is_file() and any(c == f or c in f.parents for c in self.cartelle_consentite()):
            return f
        return None

    def _indicizza(self, f: Path, rel: str, st, schemi_noti: set[str]) -> None:
        testo = estrai_testo(f)
        prodotto = rel.split("/", 1)[0] if not Path(rel).is_absolute() else f.parent.name
        doc = Documento(rel, f.name, titolo_documento(testo, f), data_documento(testo, f),
                        categoria(rel, testo, schemi_noti), prodotto, gruppo(f.name), f.suffix.lower().lstrip("."),
                        re.sub(r"\s+", " ", testo[:400]).strip()[:200])
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (rel, st.st_size, st.st_mtime, doc.nome, doc.titolo, doc.data, doc.categoria, doc.prodotto,
                         doc.gruppo, doc.estensione, doc.estratto))
        self.db.execute("DELETE FROM testi WHERE percorso=?", (rel,))
        cartelle = " ".join(rel.split("/")[:-1])
        self.db.execute("INSERT INTO testi VALUES (?,?,?,?)", (rel, doc.titolo + " " + f.stem, cartelle, testo))

    # --- ricerca -----------------------------------------------------------------------------------------------
    @staticmethod
    def _query_fts(testo: str) -> str:
        """Ogni parola cercata deve comparire (anche come inizio di parola). '1407/1811' diventa la frase
        '1407 1811*'; i codici restano interi."""
        termini = []
        for parola in testo.split():
            pezzi = [p for p in re.split(r"[^\w]+", parola, flags=re.UNICODE) if p]
            if pezzi:
                termini.append('"' + " ".join(pezzi) + '"*')
        return " AND ".join(termini)

    def _con_termine(self, termine: str, limite: int = 2000) -> set[str]:
        """Documenti che contengono il termine (testo, titolo, cartelle) o lo hanno nel percorso."""
        out = set()
        q = self._query_fts(termine)
        if q:
            out |= {p for (p,) in self.db.execute("SELECT percorso FROM testi WHERE testi MATCH ? LIMIT ?",
                                                  (q, limite))}
        out |= {p for (p,) in self.db.execute("SELECT percorso FROM meta WHERE lower(percorso) LIKE ? LIMIT ?",
                                              (f"%{termine.lower()}%", limite))}
        return out

    def cerca_domanda(self, domanda: str, limite: int = 300) -> dict:
        """Ricerca da una frase ("trova lo schema di collegamento della 2560035 con la consolle 54612"):
        i documenti devono riguardare TUTTI i codici citati; le altre parole (collegamento, consolle...) e il tipo
        di documento chiesto ordinano i risultati. Se nessun documento ha tutti i codici, si mostrano quelli con
        il maggior numero di codici, avvisando."""
        d = interpreta_domanda(domanda)
        if not d["codici"] and not d["parole"]:
            return {**self.cerca(domanda, limite), "domanda": d}
        per_codice = {c: self._con_termine(c) for c in d["codici"]}
        per_parola = {w: self._con_termine(w) for w in d["parole"]}
        if per_codice:
            conta: dict[str, int] = {}
            for docs in per_codice.values():
                for x in docs:
                    conta[x] = conta.get(x, 0) + 1
            massimo = max(conta.values(), default=0)
            candidati = {x for x, n in conta.items() if n == massimo}
            d["tutti_i_codici"] = massimo == len(per_codice)
            d["codici_mancanti"] = [] if d["tutti_i_codici"] else \
                [c for c, docs in per_codice.items() if not docs & candidati]
        else:   # solo parole: devono esserci tutte
            candidati = set.intersection(*per_parola.values()) if per_parola else set()
            d["tutti_i_codici"] = True
        if not candidati:
            return {"istruzioni": [], "schemi": [], "altri": [], "totale": 0, "proposti": [], "domanda": d}
        segnaposti = ",".join("?" * len(candidati))
        righe = self.db.execute(f"SELECT percorso, nome, titolo, data, categoria, prodotto, gruppo, estensione, "
                                f"estratto FROM meta WHERE percorso IN ({segnaposti})", list(candidati)).fetchall()
        docs = [dict(zip(("percorso", "nome", "titolo", "data", "categoria", "prodotto", "gruppo", "estensione",
                          "estratto"), r, strict=True)) for r in righe]
        for doc in docs:
            parole_ok = sum(doc["percorso"] in v for v in per_parola.values())
            nel_titolo = sum(w in doc["titolo"].lower() for w in d["parole"])
            doc["punteggio"] = -(parole_ok * 2 + nel_titolo * 3 + (5 if doc["categoria"] == d["tipo"] else 0))
        proposti = sorted(docs, key=lambda x: (x["punteggio"], x["data"]), reverse=False)
        migliore = proposti[0]["punteggio"]
        proposti = [x for x in proposti if x["punteggio"] == migliore][:10]
        proposti.sort(key=lambda x: x["data"], reverse=True)
        return {"istruzioni": self._ultime_versioni([x for x in docs if x["categoria"] == "istruzioni"]),
                "schemi": sorted((x for x in docs if x["categoria"] == "schemi"), key=lambda x: x["data"],
                                 reverse=True),
                "altri": sorted((x for x in docs if x["categoria"] == "altri"),
                                key=lambda x: (x["punteggio"], -int(x["data"].replace("-", "")))),
                "totale": len(docs), "proposti": proposti, "domanda": d}

    def cerca(self, testo: str, limite: int = 300) -> dict:
        testo = testo.strip()
        if not testo:
            return {"istruzioni": [], "schemi": [], "altri": [], "totale": 0}
        trovati: dict[str, float] = {}
        q = self._query_fts(testo)
        if q:
            for p, punteggio in self.db.execute(
                    "SELECT percorso, bm25(testi, 0, 10.0, 3.0, 1.0) FROM testi WHERE testi MATCH ? "
                    "ORDER BY 2 LIMIT ?", (q, limite)):
                trovati[p] = punteggio
        # parti di parola nel nome del file o nelle cartelle (es. '8003' dentro '2480035')
        simile = f"%{testo.lower()}%"
        for (p,) in self.db.execute("SELECT percorso FROM meta WHERE lower(percorso) LIKE ? LIMIT ?",
                                    (simile, limite)):
            trovati.setdefault(p, -100.0)
        if not trovati:
            return {"istruzioni": [], "schemi": [], "altri": [], "totale": 0}
        segnaposti = ",".join("?" * len(trovati))
        righe = self.db.execute(f"SELECT percorso, nome, titolo, data, categoria, prodotto, gruppo, estensione, "
                                f"estratto FROM meta WHERE percorso IN ({segnaposti})", list(trovati)).fetchall()
        docs = [dict(zip(("percorso", "nome", "titolo", "data", "categoria", "prodotto", "gruppo", "estensione",
                          "estratto"), r, strict=True)) for r in righe]
        for d in docs:
            d["punteggio"] = trovati[d["percorso"]]
        return {"istruzioni": self._ultime_versioni([d for d in docs if d["categoria"] == "istruzioni"]),
                "schemi": sorted((d for d in docs if d["categoria"] == "schemi"), key=lambda d: d["data"],
                                 reverse=True),
                "altri": sorted((d for d in docs if d["categoria"] == "altri"),
                                key=lambda d: (d["punteggio"], -int(d["data"].replace("-", "")))),
                "totale": len(docs)}

    @staticmethod
    def _ultime_versioni(docs: list[dict]) -> list[dict]:
        """Per ogni documento di istruzioni la versione più recente, con le precedenti a parte."""
        gruppi: dict[tuple, list[dict]] = {}
        for d in docs:
            gruppi.setdefault((d["prodotto"], d["gruppo"]), []).append(d)
        out = []
        for versioni in gruppi.values():
            versioni.sort(key=lambda d: (d["data"], d["nome"]), reverse=True)
            out.append({**versioni[0], "versioni_precedenti": versioni[1:]})
        return sorted(out, key=lambda d: d["data"], reverse=True)

    def statistiche(self) -> dict:
        per = dict(self.db.execute("SELECT categoria, COUNT(*) FROM meta GROUP BY categoria").fetchall())
        return {"documenti": sum(per.values()), **per}


# --- domande in linguaggio naturale -----------------------------------------------------------------------------

PAROLE_VUOTE = set("""trova trovami cerca cercami cercare dammi dai mostra mostrami fammi vedere voglio vorrei serve
servono mi ci si il lo la i gli le un uno una di del dello della dei degli delle da dal dallo dalla dai dagli dalle
in nel nello nella nei negli nelle con col coi su sul sullo sulla sui sugli sulle per tra fra a al allo alla ai agli
alle e ed o od che chi cosa quale quali dove come c è e' ha hanno sono c'è tutti tutte tutto ogni anche
documento documenti file articolo articoli codice prodotto modello per favore grazie""".split())
TIPI_DOCUMENTO = {
    "schemi": re.compile(r"^(schem|elettric|collegament|cablagg|wiring|circuit|layout|sch$)"),
    "istruzioni": re.compile(r"^(istruz|manual|montagg|installaz|guida|uso$|procedur|libretto)"),
}
CODICE = re.compile(r"^[\w./-]*\d[\w./-]*$")


def interpreta_domanda(testo: str) -> dict:
    """Da una frase ricava codici (parole con cifre, es. 2560035, 54612, SP112A), parole utili e tipo di
    documento chiesto (schemi o istruzioni). Niente AI: veloce e gratis anche per i colleghi."""
    codici, parole, tipo = [], [], None
    for w in re.findall(r"[\w./'-]+", testo.lower()):
        w = w.strip(".'-")
        if not w or w in PAROLE_VUOTE:
            continue
        if CODICE.match(w) and len(re.sub(r"\D", "", w)) >= 3:
            codici.append(w.upper())
            continue
        for t, rx in TIPI_DOCUMENTO.items():
            if rx.match(w):
                tipo = tipo or t
        if len(w) > 2:
            parole.append(w)
    return {"codici": list(dict.fromkeys(codici)), "parole": list(dict.fromkeys(parole)), "tipo": tipo}


def e_domanda(testo: str) -> bool:
    """Frase (almeno tre parole, o due con una parola vuota tipo 'della') invece di un codice o una parola."""
    parole = re.findall(r"[\w'-]+", testo.lower())
    return len(parole) >= 3 or any(w in PAROLE_VUOTE for w in parole)


def schemi_da_prodotti_yaml(radice: Path, radice_indice: Path | None = None) -> set[str]:
    """I PDF che lo scanner ha riconosciuto come schemi Altium sono schemi con certezza.
    Percorsi resi relativi a radice_indice (la cartella indicizzata), se diversa da quella di prodotti.yaml."""
    import yaml
    f = radice / "prodotti.yaml"
    if not f.exists():
        return set()
    conf = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    rel = {str(v[k]).replace("\\", "/") for v in conf.get("schede", []) for k in ("netlist", "disegno") if v.get(k)}
    if radice_indice is None or Path(radice_indice).resolve() == Path(radice).resolve():
        return rel
    out, base = set(), Path(radice_indice).resolve()
    for r in rel:
        try:
            out.add((Path(radice) / r).resolve().relative_to(base).as_posix())
        except ValueError:
            pass
    return out


def leggi_elenco_cartelle(file: Path, radice: Path) -> list[str]:
    """Una sottocartella per riga (relativa alla radice o percorso completo); # per i commenti.
    Restituisce i percorsi validi (relativi alla radice, o completi se altrove); avvisa per quelli inesistenti."""
    out = []
    for riga in file.read_text(encoding="utf-8-sig").splitlines():
        riga = riga.split("#", 1)[0].strip().strip('"').rstrip("\\/")
        if not riga:
            continue
        c = Path(riga)
        c = c if c.is_absolute() else radice / c
        if not c.is_dir():
            log.warning("cartella non trovata, saltata: %s (cercata in %s)", riga, c)
            continue
        try:
            out.append(c.resolve().relative_to(radice.resolve()).as_posix())
        except ValueError:
            out.append(str(c.resolve()))      # cartella in un'altra posizione: percorso completo
    return out
