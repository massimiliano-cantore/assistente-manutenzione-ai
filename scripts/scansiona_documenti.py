"""Scansiona una cartella di documentazione (una sottocartella per prodotto) e prepara prodotti.yaml.

Uso:  python -m scripts.scansiona_documenti C:\\percorso\\produzione1
Crea nella cartella:  prodotti.yaml (bozza da completare con i collegamenti) e scansione.txt (rapporto).
Gira tutto in locale: nessun documento viene inviato da nessuna parte.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from app.elettrico import altium_pdf, bom

ESTENSIONI_BOM = {".xls", ".xlsx", ".csv"}


def _codice(nome: str) -> str:
    """'ASSEMBLY_Brd004E.PDF' -> 'Brd004E'; 'SCH_RF_MODULE_v2.0.PDF' -> 'RF_MODULE'"""
    s = re.sub(r"(?i)\.(pdf|xlsx?|csv)$", "", nome)
    s = re.sub(r"(?i)^(assembly|asm|sch|schema|schematic|bom|montaggio)[_\-\s]+", "", s)
    s = re.sub(r"(?i)[_\-\s]*v?\d+(\.\d+)*$", "", s)
    return re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_") or "SCHEDA"


def _progetto_pdf(pdf: Path) -> str | None:
    """Nome del documento Altium nei segnalibri (es. 'SP111.PcbDoc' -> 'SP111')."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        for t in list(doc.get_toc())[:4]:
            m = re.match(r"(.+?)\.(PcbDoc|SchDoc)", t.get_title())
            if m:
                return m.group(1)
    finally:
        doc.close()
    return None


def _progetto_bom(f: Path) -> tuple[str | None, str | None]:
    """Dal cartiglio di una BOM Altium: (PCB, progetto)."""
    try:
        import pandas as pd
        grezzo = pd.read_excel(f, header=None, dtype=str, nrows=12) if f.suffix.lower() != ".csv" else \
            pd.read_csv(f, header=None, dtype=str, nrows=12, sep=None, engine="python", on_bad_lines="skip")
    except Exception:
        return None, None
    testo = {str(a).strip(" :").lower(): str(b).strip() for riga in grezzo.values.tolist()
             for a, b in zip(riga, riga[1:], strict=False) if isinstance(a, str)}
    pulisci = lambda v: None if not v or v.startswith("<") or v.lower() == "nan" else v   # noqa: E731
    return pulisci(testo.get("pcb")), pulisci(testo.get("project"))


def _nets_connettori(scheda) -> dict[str, dict[str, str]]:
    """connettore -> {pin: nome net normalizzato}, solo net con un nome 'vero' (non Net..., non masse)."""
    from app.elettrico.modello import e_alimentazione
    out = {}
    for d, c in scheda.componenti.items():
        if not re.match(r"^(CONN|CN|J|P|X)\d", d):
            continue
        pins = {}
        for p in c.pin:
            n = scheda.net_del_pin(f"{d}-{p}")
            if n and not n.startswith("Net") and not e_alimentazione(n):
                pins[p] = re.sub(r"\d", "", n.upper()).replace("_", "")
        if pins:
            out[d] = pins
    return out


def suggerisci_collegamenti(schede: dict) -> list[dict]:
    """Coppie di connettori su schede diverse che portano segnali con lo stesso nome sugli stessi pin."""
    con = {c: _nets_connettori(s) for c, s in schede.items()}
    out = []
    codici = list(schede)
    for i, a in enumerate(codici):
        for b in codici[i + 1:]:
            migliore = None
            for ca, pa in con[a].items():
                for cb, pb in con[b].items():
                    uguali = sum(1 for p in pa if p in pb and (pa[p] == pb[p] or pa[p] in pb[p] or pb[p] in pa[p]))
                    quota = uguali / max(min(len(pa), len(pb)), 1)
                    if uguali >= 4 or (uguali >= 3 and quota >= 0.6):
                        if not migliore or (uguali, quota) > (migliore[0], migliore[3]):
                            migliore = (uguali, ca, cb, quota)
            if migliore:
                out.append({"da": f"{a}.{migliore[1]}", "a": f"{b}.{migliore[2]}",
                            "nota": f"suggerito ({'forte' if migliore[0] >= 6 else 'da verificare'}): "
                                    f"{migliore[0]} segnali uguali sugli stessi pin"})
    return out


def _associa_bom(bom_file: list[Path], insiemi: dict[str, set[str]]) -> tuple[dict[str, list[Path]], list[Path]]:
    """Ogni BOM va alla scheda con cui condivide più riferimenti (il nome del file spesso è una variante o una
    commessa). Restituisce scheda -> BOM (la prima è la principale, le altre varianti) e le BOM non associate."""
    per_scheda, orfane = defaultdict(list), []
    for f in bom_file:
        try:
            des = {c.designator for c in bom.leggi(f)}
        except Exception:
            orfane.append(f)
            continue
        migliore = max(((len(des & ins) / max(len(des), 1), c) for c, ins in insiemi.items()), default=(0, None))
        if migliore[1] and migliore[0] >= 0.6:
            per_scheda[migliore[1]].append(f)
        else:
            orfane.append(f)
    for c in per_scheda:   # la principale: la più completa rispetto alla netlist
        per_scheda[c].sort(key=lambda f: -len({x.designator for x in bom.leggi(f)} & insiemi[c]))
    return per_scheda, orfane


def scansiona(radice: Path) -> tuple[dict, list[str]]:
    rapporto, schede, prodotti, usati = [], [], [], {}
    tot = defaultdict(int)
    for cartella in sorted(p for p in radice.iterdir() if p.is_dir()):
        pdf_altium, pdf_altri, bom_file = [], [], []
        for f in sorted(cartella.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix.lower() == ".pdf":
                try:
                    (pdf_altium if altium_pdf.e_pdf_altium(f) else pdf_altri).append(f)
                except Exception:
                    pdf_altri.append(f)
            elif f.suffix.lower() in ESTENSIONI_BOM and "bom" in f.name.lower():
                bom_file.append(f)
        if not pdf_altium and not bom_file:
            continue
        tot["prodotti"] += 1
        rapporto.append(f"\n== {cartella.name}: {len(pdf_altium)} PDF Altium, {len(bom_file)} BOM, "
                        f"{len(pdf_altri)} altri PDF")
        if not pdf_altium:
            tot["senza_netlist"] += 1
            rapporto.append("  nessun PDF con netlist (PDF non esportati da Altium o senza segnalibri): "
                            "per ora solo ricerca nei documenti")
            continue
        per_scheda = defaultdict(dict)
        for f in pdf_altium:
            codice = _progetto_pdf(f) or _codice(f.name)
            tipo = "schema" if re.search(r"(?i)sch", f.name) else "montaggio"
            per_scheda[codice].setdefault("pdf", []).append((tipo, f))
        insiemi = {c: set(altium_pdf.importa(i["pdf"][0][1], c).componenti) for c, i in per_scheda.items()}
        # schema e montaggio della stessa scheda hanno nomi diversi ma gli stessi componenti: si uniscono
        for a in list(per_scheda):
            for b in list(per_scheda):
                if a != b and a in per_scheda and b in per_scheda:
                    ia, ib = insiemi[a], insiemi[b]
                    if ia and ib and len(ia & ib) / len(ia | ib) >= 0.8:
                        tieni, togli = sorted([a, b], key=lambda c: (c.lower() in ("main", "mcu"), len(c)))
                        per_scheda[tieni]["pdf"] += per_scheda.pop(togli)["pdf"]
                        insiemi.pop(togli)
        bom_di, orfane = _associa_bom(bom_file, insiemi)
        codici, caricate = [], {}
        for codice, info in per_scheda.items():
            unico = codice
            if unico in usati and usati[unico] != insiemi[codice]:      # 'Main' in prodotti diversi
                unico = f"{cartella.name.split()[0].split('_')[0]}_{codice}"
            usati[unico] = insiemi[codice]
            pdf = sorted(info["pdf"], key=lambda t: t[0] != "schema")    # lo schema ha la netlist logica
            voce = {"codice": unico, "nome": codice,
                    "netlist": str(pdf[0][1].relative_to(radice)).replace("\\", "/")}
            disegni = [p for t, p in pdf if t == "montaggio" and p != pdf[0][1]]
            if disegni:
                voce["disegno"] = str(disegni[0].relative_to(radice)).replace("\\", "/")
            boms = bom_di.get(codice, [])
            if boms:
                voce["bom"] = str(boms[0].relative_to(radice)).replace("\\", "/")
                if len(boms) > 1:
                    voce["varianti_bom"] = [str(f.relative_to(radice)).replace("\\", "/") for f in boms[1:]]
            try:
                s = altium_pdf.importa(radice / voce["netlist"], unico)
                avvisi = bom.unisci(s, bom.leggi(radice / voce["bom"])) if "bom" in voce else []
            except Exception as e:
                rapporto.append(f"  {unico}: errore di lettura ({e})")
                continue
            if any(a.startswith("sulla scheda") or a.endswith("non nella netlist") for a in avvisi):
                avvisi = [f"{sum(1 for a in avvisi if 'non nella netlist' in a)} componenti della BOM non nella "
                          "netlist" if any("non nella netlist" in a for a in avvisi) else ""] + \
                         [a for a in avvisi if a.startswith("sulla scheda")]
            tot["schede"] += 1
            tot["con_bom"] += "bom" in voce
            rapporto.append(f"  {unico}: {len(s.componenti)} componenti, {len(s.nets)} net"
                            + (f", BOM {Path(voce['bom']).name}" if "bom" in voce else " | MANCA LA BOM")
                            + (f" (+{len(voce['varianti_bom'])} varianti)" if voce.get("varianti_bom") else "")
                            + "".join(f" | {a}" for a in avvisi if a))
            schede.append(voce)
            codici.append(unico)
            caricate[unico] = s
        for f in orfane:
            rapporto.append(f"  BOM senza scheda corrispondente: {f.name}")
        coll = suggerisci_collegamenti(caricate)
        for c in coll:
            rapporto.append(f"  collegamento {c['da']} <-> {c['a']} ({c['nota']})")
        if len(codici) > 1 and not coll:
            rapporto.append("  nessun collegamento riconosciuto tra le schede: aggiungilo a mano")
        prodotti.append({"nome": cartella.name, "schede": codici, "collegamenti": coll})
    rapporto.insert(0, f"RIEPILOGO: {tot['prodotti']} prodotti, {tot['schede']} schede con netlist "
                       f"({tot['con_bom']} con BOM), {tot['senza_netlist']} prodotti senza PDF con netlist")
    return {"schede": schede, "prodotti": prodotti}, rapporto


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("uso: python -m scripts.scansiona_documenti <cartella>")
    radice = Path(sys.argv[1])
    conf, rapporto = scansiona(radice)
    destinazione = radice / "prodotti.yaml"
    if destinazione.exists():
        destinazione = radice / "prodotti.bozza.yaml"
    destinazione.write_text("# Generato da scansiona_documenti: completa i collegamenti tra le schede\n"
                            + yaml.safe_dump(conf, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (radice / "scansione.txt").write_text("\n".join(rapporto), encoding="utf-8")
    print("\n".join(rapporto))
    print(f"\n{len(conf['schede'])} schede in {len(conf['prodotti'])} prodotti -> {destinazione.name}")


if __name__ == "__main__":
    main()
