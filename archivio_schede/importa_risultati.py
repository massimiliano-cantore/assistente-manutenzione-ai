"""PASSO 3 (sul PC): dai risultati di Kaggle allo storico dell'assistente, con il conto di cosa resta da controllare.

    python archivio_schede\\importa_risultati.py schede.jsonl C:\\percorso\\Produzione1

Scrive un JSON docai-scheda/1 per scheda in Produzione1\\storico\\qwen\\<anno>\\ (le schede da controllare
restano dentro, marcate) e un riepilogo in Produzione1\\storico\\qwen\\da_controllare.csv, da aprire con Excel.
Stima anche il costo per far rileggere a Claude (a lotti) solo le schede da controllare.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

COSTO_SCHEDA_LOTTI = {"Sonnet": 0.04, "Haiku": 0.013}   # $ indicativi a scheda con la Batch API


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    righe = [json.loads(r) for r in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if r.strip()]
    dest = Path(sys.argv[2]) / "storico" / "qwen"
    dest.mkdir(parents=True, exist_ok=True)
    da_controllare = []
    for r in righe:
        pred = r.get("pred") or {}
        if r["da_controllare"]:
            da_controllare.append(r)
        if not pred:          # lettura fallita: resta solo nell'elenco da controllare
            continue
        scheda = {"formato": "docai-scheda/1", "id": r["id"], "file_origine": r["file"], "lettore": "qwen2.5-vl-7b",
                  "da_controllare": r["da_controllare"], "motivi": r["motivi"], "pagine": r["pagine"],
                  "campi": {k: v for k, v in pred.items() if k != "righe"}, "righe": pred.get("righe") or []}
        (dest / r["anno"]).mkdir(exist_ok=True)
        (dest / r["anno"] / f"{r['id']}.json").write_text(json.dumps(scheda, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    with open(dest / "da_controllare.csv", "w", newline="", encoding="utf-8-sig") as fo:
        w = csv.writer(fo, delimiter=";")
        w.writerow(["scheda", "anno", "mese", "file PDF", "pagina", "motivi"])
        for r in da_controllare:
            w.writerow([r["id"], r["anno"], r["mese"], r["file"], r["pagine"][0], " | ".join(r["motivi"])])
    n, c = len(righe), len(da_controllare)
    print(f"Schede lette: {n}; ok: {n - c}; da controllare: {c} ({c / max(n, 1):.0%})")
    motivi = {}
    for r in da_controllare:
        for m in r["motivi"]:
            k = m.split(":")[0]
            motivi[k] = motivi.get(k, 0) + 1
    for k, v in sorted(motivi.items(), key=lambda x: -x[1]):
        print(f"  {v:5d}  {k}")
    for nome, costo in COSTO_SCHEDA_LOTTI.items():
        print(f"Rilettura delle sole schede da controllare con Claude {nome} a lotti: circa {c * costo:.0f} $")
    print(f"Salvate in {dest}; elenco in {dest / 'da_controllare.csv'}")


if __name__ == "__main__":
    main()
