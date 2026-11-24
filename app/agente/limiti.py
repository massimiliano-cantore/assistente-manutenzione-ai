"""Risultati degli strumenti più corti: meno token per richiesta, quindi meno costi e meno limiti di velocità
(es. Groq gratuito). Le liste lunghe vengono accorciate e lo si dichiara nel risultato."""
from __future__ import annotations

import functools
import json

MAX_CARATTERI = 6000


def accorcia(valore, max_lista: int = 25):
    if isinstance(valore, dict):
        return {k: accorcia(v, max_lista) for k, v in valore.items()}
    if isinstance(valore, list):
        corta = [accorcia(v, max_lista) for v in valore[:max_lista]]
        if len(valore) > max_lista:
            corta.append(f"... e altri {len(valore) - max_lista} (chiedi in modo più mirato per vederli)")
        return corta
    if isinstance(valore, str) and len(valore) > 1500:
        return valore[:1500] + " ..."
    return valore


def limita(strumenti: list, max_caratteri: int = MAX_CARATTERI) -> list:
    """Avvolge la funzione di ogni strumento: se il risultato è troppo lungo lo accorcia per gradi."""
    for t in strumenti:
        originale = getattr(t, "func", None)
        if originale is None:
            continue

        @functools.wraps(originale)
        def avvolta(*a, _f=originale, **k):
            r = _f(*a, **k)
            for n in (25, 12, 6, 3):
                if len(json.dumps(r, ensure_ascii=False, default=str)) <= max_caratteri:
                    return r
                r = accorcia(r, n)
            return r

        t.func = avvolta
    return strumenti
