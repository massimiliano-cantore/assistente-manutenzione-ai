"""Storico delle riparazioni a partire dalle esportazioni JSON di Document AI.

Flusso: Document AI legge le schede di riparazione (anche scritte a mano), l'operatore le conferma, l'export JSON
(`docai-scheda/1`, un file per scheda) va nella cartella `storico/` dei dati aziendali. Qui le schede vengono:
- normalizzate (i nomi dei campi cambiano da cliente a cliente: si usano dei sinonimi, estendibili in storico.yaml);
- collegate al prodotto della documentazione elettronica tramite il codice articolo;
- collegate ai componenti dello schema quando le note o gli interventi citano un riferimento (es. "sostituito U3");
- rese consultabili: casi simili a un sintomo e statistiche dei guasti per prodotto.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

log = logging.getLogger("storico")

SINONIMI = {
    "numero": ["riparazione_n", "numero", "n_riparazione", "numero_riparazione", "rma", "reso_n"],
    "data": ["data", "data_riparazione", "data_reso", "data_ingresso"],
    "cliente": ["ditta", "cliente", "ragione_sociale"],
    "articolo": ["articolo", "codice_articolo", "prodotto", "codice_prodotto", "modello"],
    "seriale": ["seriale", "matricola", "numero_serie", "sn", "serial"],
    "prodotto_il": ["prodotto_il", "data_produzione", "lotto"],
    "firmware": ["firmware", "fw", "versione_firmware", "versione_fw"],
    "note": ["note", "difetto", "difetto_riscontrato", "diagnosi", "guasto", "sintomo", "descrizione_guasto",
             "lavori_eseguiti", "osservazioni"],
    "tempo": ["tempo_riparazione", "tempo", "minuti", "ore"],
    "aperta": ["aperta_manomessa", "manomessa", "aperta"],
}
SINONIMI_RIGHE = {
    "codice": ["codice", "codice_ricambio", "articolo", "cod"],
    "descrizione": ["descrizione", "descr", "componente"],
    "intervento": ["intervento", "lavorazione", "azione", "operazione", "difetto"],
    "pz": ["pz", "quantita", "qta", "pezzi"],
}
# riferimenti di componenti su uno schema (R12, C3, U4, IC2, Q1, K1, RL2, F1, CONN4, LED3, ZD1, FB2, Y1...)
RIF = re.compile(r"\b(?:CONN|LED|IC|RL|ZD|FB|SW|CN|R|C|L|D|Q|U|K|F|J|Y|X|T|P)\d{1,3}[A-Z]?\b")


@dataclass
class Riparazione:
    id: str
    numero: str = ""
    data: str = ""                    # ISO yyyy-mm-dd se riconosciuta, altrimenti come scritta
    cliente: str = ""
    articolo: str = ""
    seriale: str = ""
    prodotto_il: str = ""
    firmware: str = ""
    note: str = ""
    tempo: float | None = None
    aperta: bool | None = None
    componenti: list[dict] = field(default_factory=list)   # codice, descrizione, intervento, pz
    riferimenti: list[str] = field(default_factory=list)   # designator citati (es. U3, R44)
    prodotto: str = ""                                     # prodotto della documentazione, se collegato
    corretti: list[str] = field(default_factory=list)      # campi corretti a mano dall'operatore in Document AI
    file: str = ""
    immagini: list[str] = field(default_factory=list)

    def testo(self) -> str:
        """Testo su cui cercare i casi simili: note e componenti/interventi."""
        parti = [self.note] + [" ".join(str(c.get(k) or "") for k in ("descrizione", "intervento", "codice"))
                               for c in self.componenti]
        return " ".join(p for p in parti if p)

    def breve(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if v not in ("", None, [], {})}
        d.pop("immagini", None)
        return d


def _data_iso(v: str) -> str:
    v = (v or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    return v


def _numero(v) -> float | None:
    if v is None or v == "":
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", str(v))
    return float(m.group().replace(",", ".")) if m else None


def _valore(cella):
    return cella.get("valore") if isinstance(cella, dict) else cella


def _prendi(campi: dict, nomi: list[str]):
    bassi = {k.lower(): k for k in campi}
    for n in nomi:
        if n in bassi:
            return campi[bassi[n]]
    return None


def normalizza(dati: dict, sinonimi: dict | None = None, sinonimi_righe: dict | None = None) -> Riparazione:
    """Da un JSON docai-scheda/1 (o da un dizionario di campi semplici) a una Riparazione."""
    s = {k: v + (sinonimi or {}).get(k, []) for k, v in SINONIMI.items()}
    sr = {k: v + (sinonimi_righe or {}).get(k, []) for k, v in SINONIMI_RIGHE.items()}
    campi = dati.get("campi", dati)
    val = {k: _valore(_prendi(campi, nomi)) for k, nomi in s.items()}
    corretti = [k for k, c in campi.items() if isinstance(c, dict) and c.get("origine") == "corretto"]
    righe = []
    for r in dati.get("righe", []):
        v = {k: _valore(_prendi(r, nomi)) for k, nomi in sr.items()}
        if any(v.values()):
            righe.append({k: (x.strip() if isinstance(x, str) else x) for k, x in v.items()
                          if x not in (None, "")})
    aperta = val["aperta"]
    rip = Riparazione(
        id=str(dati.get("id") or dati.get("file_origine") or ""),
        numero=str(val["numero"] or ""), data=_data_iso(str(val["data"] or "")), cliente=str(val["cliente"] or ""),
        articolo=str(val["articolo"] or "").strip(), seriale=str(val["seriale"] or "").strip(),
        prodotto_il=str(val["prodotto_il"] or ""), firmware=str(val["firmware"] or "").strip(),
        note=str(val["note"] or "").strip(), tempo=_numero(val["tempo"]),
        aperta=None if aperta in (None, "") else str(aperta).lower() in ("si", "sì", "true", "1", "x"),
        componenti=righe, corretti=corretti, file=str(dati.get("file_origine", "")),
        immagini=list(dati.get("immagini", [])))
    testo = (rip.note + " " + " ".join(str(c.get("intervento", "")) + " " + str(c.get("descrizione", ""))
                                       for c in righe)).upper()
    rip.riferimenti = sorted(set(RIF.findall(testo)))
    return rip


class Storico:
    def __init__(self, riparazioni: list[Riparazione]):
        self.riparazioni = riparazioni
        self._tfidf = None

    # --- caricamento -----------------------------------------------------------------------------------------
    @classmethod
    def carica(cls, cartella: str | Path, conf: dict | None = None) -> Storico:
        """Legge tutti i JSON della cartella (anche nelle sottocartelle). conf: contenuto di storico.yaml."""
        cartella = Path(cartella)
        if conf is None and (cartella / "storico.yaml").exists():
            conf = yaml.safe_load((cartella / "storico.yaml").read_text(encoding="utf-8")) or {}
        conf = conf or {}
        rip, saltati = [], 0
        for f in sorted(cartella.rglob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                saltati += 1
                continue
            if not isinstance(d, dict) or not str(d.get("formato", "docai-scheda")).startswith("docai-scheda"):
                saltati += 1
                continue
            r = normalizza(d, conf.get("campi"), conf.get("colonne"))
            r.id = r.id or f.stem
            rip.append(r)
        log.info("storico: %d riparazioni caricate, %d file saltati", len(rip), saltati)
        s = cls(rip)
        s.articoli_a_mano = {str(k): v for k, v in (conf.get("articoli") or {}).items()}
        return s

    # --- collegamento alla documentazione ---------------------------------------------------------------------
    def collega(self, catalogo=None, prodotti_yaml: Path | None = None) -> dict:
        """Associa ogni riparazione a un prodotto della documentazione: prima la tabella 'articoli' di
        storico.yaml, poi la voce 'articoli' dei prodotti in prodotti.yaml, poi il codice articolo trovato nel
        nome del prodotto o nei nomi dei suoi file (BOM, schemi, firmware). Tiene solo i riferimenti che esistono
        davvero sulle schede del prodotto. Restituisce un riepilogo."""
        indice: dict[str, str] = dict(getattr(self, "articoli_a_mano", {}))
        testi: dict[str, str] = {}
        schede_di: dict[str, list[str]] = {}
        if prodotti_yaml and Path(prodotti_yaml).exists():
            conf = yaml.safe_load(Path(prodotti_yaml).read_text(encoding="utf-8")) or {}
            file_scheda = {v["codice"]: " ".join(str(x) for k, x in v.items() if k in ("netlist", "bom", "disegno"))
                           + " " + " ".join(v.get("varianti_bom", [])) for v in conf.get("schede", [])}
            for p in conf.get("prodotti", []):
                for a in p.get("articoli", []) or []:
                    indice.setdefault(str(a), p["nome"])
                fw = " ".join(b.get("file", "") for b in (p.get("firmware") or {}).get("binari", []))
                testi[p["nome"]] = (p["nome"] + " " + " ".join(file_scheda.get(c, "") for c in p.get("schede", []))
                                    + " " + fw).upper()
                schede_di[p["nome"]] = list(p.get("schede", []))
        elif catalogo is not None:
            for p in catalogo.prodotti:
                testi[p.nome] = p.nome.upper()
                schede_di[p.nome] = list(p.schede)
        collegate, sconosciuti = 0, Counter()
        for r in self.riparazioni:
            r.prodotto = self._prodotto_di(r.articolo, indice, testi)
            if r.prodotto:
                collegate += 1
                if catalogo is not None and r.riferimenti:
                    presenti = set()
                    for codice in schede_di.get(r.prodotto, []):
                        if codice in catalogo.schede:
                            presenti |= set(catalogo.schede[codice].componenti)
                    if presenti:
                        r.riferimenti = [x for x in r.riferimenti if x in presenti]
            elif r.articolo:
                sconosciuti[r.articolo] += 1
        return {"riparazioni": len(self.riparazioni), "collegate_a_prodotto": collegate,
                "articoli_non_riconosciuti": dict(sconosciuti.most_common(30))}

    @staticmethod
    def _prodotto_di(articolo: str, indice: dict[str, str], testi: dict[str, str]) -> str:
        a = (articolo or "").strip().upper()
        if not a:
            return ""
        if a in {k.upper() for k in indice}:
            return next(v for k, v in indice.items() if k.upper() == a)
        cifre = re.match(r"\d{4,6}", a)
        chiavi = [a] + ([cifre.group()] if cifre else [])
        trovati = []
        for nome, t in testi.items():
            for k in chiavi:
                if re.search(rf"(?<![0-9A-Z]){re.escape(k)}", t):
                    trovati.append((len(k), nome))
                    break
            else:   # famiglie scritte come 40xxx nei nomi dei file
                for fam in re.findall(r"(\d{2,4})X{1,4}", t):
                    if a.startswith(fam):
                        trovati.append((len(fam), nome))
                        break
        if not trovati:
            return ""
        trovati.sort(reverse=True)
        return trovati[0][1] if len(trovati) == 1 or trovati[0][0] > trovati[1][0] else ""

    # --- consultazione ----------------------------------------------------------------------------------------
    def _filtra(self, prodotto: str = "", articolo: str = "", seriale: str = "") -> list[Riparazione]:
        out = self.riparazioni
        if prodotto:
            p = prodotto.lower()
            out = [r for r in out if p in r.prodotto.lower() or p == r.articolo.lower()]
        if articolo:
            out = [r for r in out if r.articolo.upper() == articolo.upper()]
        if seriale:
            sn = re.sub(r"\W", "", seriale).upper()
            out = [r for r in out if re.sub(r"\W", "", r.seriale).upper() == sn]
        return out

    def cerca(self, sintomo: str = "", prodotto: str = "", articolo: str = "", seriale: str = "",
              limite: int = 8) -> list[dict]:
        """Riparazioni più simili al sintomo descritto (TF-IDF sul testo di note e interventi)."""
        candidati = self._filtra(prodotto, articolo, seriale)
        if not candidati:
            return []
        if not sintomo.strip():
            return [r.breve() for r in sorted(candidati, key=lambda r: r.data, reverse=True)[:limite]]
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        testi = [r.testo() or " " for r in candidati]
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True, min_df=1)
        m = vec.fit_transform(testi + [sintomo])
        sim = cosine_similarity(m[-1], m[:-1]).ravel()
        ordine = sim.argsort()[::-1][:limite]
        return [{**candidati[i].breve(), "somiglianza": round(float(sim[i]), 2)} for i in ordine if sim[i] > 0.05]

    def statistiche(self, prodotto: str = "", articolo: str = "") -> dict:
        rip = self._filtra(prodotto, articolo)
        if not rip:
            return {"riparazioni": 0}
        comp = Counter()
        cause = Counter()
        for r in rip:
            for c in r.componenti:
                chiave = " ".join(x for x in (str(c.get("codice") or ""), str(c.get("descrizione") or "")) if x)
                if chiave:
                    comp[chiave] += 1
                for m in re.findall(r"\(([^)]{3,30})\)", str(c.get("intervento") or "")):
                    cause[m.strip().upper()] += 1
        rif = Counter(x for r in rip for x in r.riferimenti)
        fw = Counter(r.firmware for r in rip if r.firmware)
        seriali = Counter(re.sub(r"\W", "", r.seriale).upper() for r in rip if r.seriale)
        tempi = [r.tempo for r in rip if r.tempo]
        anni = Counter(r.data[:4] for r in rip if re.match(r"\d{4}-", r.data))
        return {
            "riparazioni": len(rip),
            "componenti_piu_sostituiti": comp.most_common(10),
            "cause_annotate": cause.most_common(8),
            "riferimenti_schema_citati": rif.most_common(10),
            "versioni_firmware": fw.most_common(8),
            "seriali_tornati_piu_volte": [(s, n) for s, n in seriali.most_common(10) if n > 1],
            "tempo_medio_minuti": round(sum(tempi) / len(tempi), 1) if tempi else None,
            "per_anno": dict(sorted(anni.items())),
            "aperte_o_manomesse": sum(1 for r in rip if r.aperta),
        }

    def riepilogo(self) -> dict:
        per_prodotto = Counter(r.prodotto or f"(articolo {r.articolo or '?'})" for r in self.riparazioni)
        date_ok = sorted(r.data for r in self.riparazioni if re.match(r"\d{4}-\d{2}-\d{2}", r.data))
        return {"riparazioni": len(self.riparazioni), "dal": date_ok[0] if date_ok else None,
                "al": date_ok[-1] if date_ok else None, "per_prodotto": per_prodotto.most_common(40)}
