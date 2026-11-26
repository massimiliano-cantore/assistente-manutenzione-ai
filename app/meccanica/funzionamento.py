"""Funzionamento meccanico degli articoli, proposto dall'AI e confermato dal tecnico.

File <Produzione1>/meccanica/funzionamento.yaml, modificabile a mano:

  01542L00:
    stato: confermato            # oppure: da_confermare
    descrizione: ...             # come funziona, in poche righe
    catena: [bobina 9709-093, nucleo 01269L10, leva catenaccio 00940F00, catenaccio, molla conica 01345F00]
    guasti_tipici:
      - sintomo: il catenaccio non rientra
        controlli: [tensione sulla bobina, ...]

Le voci confermate non vengono mai riscritte dalla generazione automatica.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

PROMPT = """Sei un tecnico meccanico ed elettrotecnico. Ti do la tavola (esploso) e la vista 3D di un assieme,
con la sua distinta su più livelli (le righe marcate [E] sono parti elettriche/elettroniche).
Spiega come funziona l'articolo meccanicamente e come la parte elettrica comanda o legge la meccanica.
Rispondi SOLO con un oggetto JSON con queste chiavi:
  "descrizione": 3-6 frasi su come funziona (cosa muove cosa, cosa riporta in posizione, cosa rileva la posizione),
  "catena": elenco ordinato degli elementi della catena di funzionamento, ognuno "nome codice" (dalla distinta),
  "guasti_tipici": elenco di 3-6 oggetti {"sintomo": ..., "controlli": [controlli in ordine, elettrici e meccanici,
                   ognuno con DOVE e COSA aspettarsi]}.
Usa solo codici presenti nella distinta. Se qualcosa non si capisce dalle immagini, dillo nella descrizione."""


def file_funzionamento(cartella_dati: Path) -> Path:
    return Path(cartella_dati) / "meccanica" / "funzionamento.yaml"


def carica(cartella_dati: Path) -> dict:
    f = file_funzionamento(cartella_dati)
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}


def salva(cartella_dati: Path, dati: dict) -> None:
    f = file_funzionamento(cartella_dati)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# Funzionamento meccanico degli articoli: controlla le voci 'da_confermare', correggile se serve e\n"
                 "# cambia lo stato in 'confermato'. Le voci confermate non vengono più riscritte.\n" +
                 yaml.safe_dump(dati, allow_unicode=True, sort_keys=True, width=110), encoding="utf-8")


def _immagine(percorso: Path) -> dict:
    return {"type": "image_url",
            "image_url": {"url": "data:image/png;base64," + base64.b64encode(percorso.read_bytes()).decode()}}


def genera(indice, codice: str, llm) -> dict:
    """Chiede all'LLM il funzionamento di un assieme (immagini + distinta)."""
    from langchain_core.messages import HumanMessage

    a = indice.articoli[codice]
    righe = [f"{'  ' * (r['livello'] - 1)}- {r['codice']} {r['descrizione']}{' [E]' if r.get('elettrico') else ''}"
             for r in indice.esplodi(codice)]
    testo = f"{PROMPT}\n\nAssieme {codice}: {a['denominazione']}\nDistinta:\n" + "\n".join(righe)
    contenuto = [{"type": "text", "text": testo}]
    for k in ("tavola", "3d"):
        if a["immagini"].get(k):
            contenuto.append(_immagine(indice.cartella / "img" / a["immagini"][k]))
    risposta = llm.invoke([HumanMessage(content=contenuto)])
    testo = risposta.content if isinstance(risposta.content, str) else \
        "".join(b.get("text", "") for b in risposta.content if isinstance(b, dict))
    m = re.search(r"\{.*\}", testo, re.S)
    if not m:
        raise ValueError("risposta senza JSON")
    dati = json.loads(m.group())
    return {"stato": "da_confermare", "descrizione": dati.get("descrizione", ""), "catena": dati.get("catena", []),
            "guasti_tipici": dati.get("guasti_tipici", [])}


def da_descrivere(indice, gia: dict) -> list[str]:
    """Assiemi da descrivere: gruppi con distinta e immagini, più in alto nella gerarchia o con parti elettriche,
    non ancora descritti. Prima quelli con parti elettriche."""
    out = []
    for c, a in indice.articoli.items():
        if c in gia or not a["distinta"] or not a["immagini"]:
            continue
        elettrico = any(r.get("elettrico") for r in indice.esplodi(c))
        if a["padri"] and not elettrico:
            continue
        out.append((not elettrico, bool(a["padri"]), c))
    return [c for *_, c in sorted(out)]
