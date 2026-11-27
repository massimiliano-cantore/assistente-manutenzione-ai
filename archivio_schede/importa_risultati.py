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

DATE = ("data", "ricevuto_il", "ddt_del")
COSTO_SCHEDA_LOTTI = {"Sonnet": 0.04, "Haiku": 0.013}   # $ indicativi a scheda con la Batch API


def pulisci(v):
    """'null', 'None', '' -> None."""
    return None if isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/a", "/", "-") else v


def pulisci_codice(c: str | None) -> str | None:
    """'00244 FOO' -> '00244F00', 'SCA 4660' -> 'SCA4660'."""
    import re
    if not c:
        return c
    c = re.sub(r"\s+", "", str(c).upper())
    c = re.sub(r"(?<=\d[A-Z])OO$", "00", c)
    return re.sub(r"(?<=\d)O(?=\d)", "0", c)


def intervento_saro(v: str | None) -> str | None:
    """Il modello a volte copia le lettere prestampate 'S A R O' invece della lettera segnata."""
    import re
    if not v:
        return v
    m = re.fullmatch(r"\s*S\s*A\s*R\s*O\s*(\(.*\))?\s*", str(v).upper())
    return ("? " + (m[1] or "")).strip() if m else v


def completa_idem(righe: list[dict]) -> list[dict]:
    """Virgolette o 'n' in una cella = valore della riga sopra; '" (ROTTO)' = azione sopra + nuova causa."""
    import re
    sopra: dict = {}
    for r in righe:
        for k in list(r):
            r[k] = pulisci(r[k])
        r["codice"] = pulisci_codice(r.get("codice"))
        r["intervento"] = intervento_saro(r.get("intervento"))
        for k in ("codice", "descrizione", "intervento"):
            v = str(r.get(k) or "").strip()
            m = re.fullmatch(r"(?:\"|''|“|”|n|N)\s*(\(.*\))?", v)
            if m and sopra.get(k):
                base = re.sub(r"\s*\(.*\)$", "", sopra[k]) if m[1] else sopra[k]
                r[k] = f"{base} {m[1]}" if m[1] else base
        sopra = {k: str(r.get(k) or "") for k in ("codice", "descrizione", "intervento")}
    return righe


def anno_coerente(data: str | None, anno: str, mese: str = "") -> str | None:
    """Data successiva al mese della cartella (es. 20/12/2025 in '2025/01 - Gennaio'): è dell'anno prima,
    il tecnico o il modello hanno sbagliato l'anno."""
    import re
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", str(data or "").strip())
    mm = re.match(r"\d{1,2}", mese or "")
    if not m or not anno.isdigit():
        return data
    a = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
    limite = (int(anno), int(mm.group()) + 1 if mm else 12)       # un mese di tolleranza
    if (a, int(m[2])) > limite and a - 1 >= int(anno) - 1:
        return f"{int(m[1]):02d}/{int(m[2]):02d}/{a - 1}"
    return data


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    righe = [json.loads(r) for r in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if r.strip()]
    dest = Path(sys.argv[2]) / "storico" / "qwen"
    dest.mkdir(parents=True, exist_ok=True)
    da_controllare = []
    scartate = sum(1 for r in righe if r.get("scartata"))
    righe = [r for r in righe if not r.get("scartata")]
    for r in righe:
        pred = r.get("pred") or {}
        righe_p = pred.get("righe") or []
        if any(str(x.get("intervento") or "").replace(" ", "").upper().startswith("SARO") for x in righe_p):
            r["da_controllare"] = True
            r["motivi"] = r["motivi"] + ["intervento S/A/R/O non letto"]
        if r["da_controllare"]:
            da_controllare.append(r)
        if not pred:          # lettura fallita: resta solo nell'elenco da controllare
            continue
        scheda = {"formato": "docai-scheda/1", "id": r["id"], "file_origine": r["file"], "lettore": "qwen2.5-vl-7b",
                  "da_controllare": r["da_controllare"], "motivi": r["motivi"], "pagine": r["pagine"],
                  "campi": {k: (anno_coerente(pulisci(v), r["anno"], r.get("mese", "")) if k in DATE else pulisci(v))
                            for k, v in pred.items() if k != "righe"},
                  "righe": completa_idem(pred.get("righe") or [])}
        (dest / r["anno"]).mkdir(exist_ok=True)
        (dest / r["anno"] / f"{r['id']}.json").write_text(json.dumps(scheda, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    with open(dest / "da_controllare.csv", "w", newline="", encoding="utf-8-sig") as fo:
        w = csv.writer(fo, delimiter=";")
        w.writerow(["scheda", "anno", "mese", "file PDF", "pagina", "motivi"])
        for r in da_controllare:
            w.writerow([r["id"], r["anno"], r["mese"], r["file"], r["pagine"][0], " | ".join(r["motivi"])])
    n, c = len(righe), len(da_controllare)
    print(f"Schede lette: {n}; ok: {n - c}; da controllare: {c} ({c / max(n, 1):.0%}); "
          f"pagine scartate perché non schede: {scartate}")
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
