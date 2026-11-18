"""Funzioni comuni alle valutazioni: report versionato (configurazione + commit git) e controllo della soglia."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

CARTELLA_REPORT = Path(__file__).parent / "report"


def commit_git() -> str:
    if os.getenv("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"][:12]
    try:
        return subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "sconosciuto"


def salva_report(nome: str, firma: dict, risultati: dict, dettaglio: list) -> Path:
    CARTELLA_REPORT.mkdir(exist_ok=True)
    rep = {"data": datetime.now(UTC).isoformat(timespec="seconds"), "commit": commit_git(),
           "configurazione": firma, "risultati": risultati, "dettaglio": dettaglio}
    p = CARTELLA_REPORT / f"{nome}.json"
    p.write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return p


def verifica_soglia(nome: str, valore: float, soglia: float) -> None:
    esito = "OK" if valore >= soglia else "SOTTO SOGLIA"
    print(f"{nome}: {valore:.3f} (soglia {soglia:.2f}) -> {esito}")
    riepilogo = os.getenv("GITHUB_STEP_SUMMARY")
    if riepilogo:
        with open(riepilogo, "a", encoding="utf-8") as f:
            f.write(f"| {nome} | {valore:.3f} | {soglia:.2f} | {esito} |\n")
    if valore < soglia:
        sys.exit(1)
