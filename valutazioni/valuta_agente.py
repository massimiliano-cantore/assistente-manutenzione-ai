"""Valutazione end-to-end dell'agente con il modello vero.

Uso: GROQ_API_KEY=... python -m valutazioni.valuta_agente
Nella CI gira a mano o una volta a settimana (workflow 'Valutazione agente'), perché consuma chiamate al modello.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import yaml

from app.componenti import costruisci
from valutazioni.comune import salva_report, verifica_soglia


def norm(x) -> str:
    s = re.sub(r"(?<=\d)[.\s](?=\d{3}\b)", "", str(x))   # 1.651 / 1 651 -> 1651
    return s.lower().replace("*", "").replace("`", "")


def contiene(risposta: str, valore) -> bool:
    return re.search(rf"(?<![\w]){re.escape(norm(valore))}(?![\w])", norm(risposta)) is not None


def valuta_caso(c, caso: dict) -> dict:
    r = c.assistente.chiedi(caso["domanda"])
    usati = [p["strumento"] for p in r.passi]
    controlli = {}
    if "sql" in caso:
        attesi = list(c.archivio.con.execute(caso["sql"]).fetchone())
        controlli["valori"] = all(contiene(r.testo, a) for a in attesi)
    if "contiene" in caso:
        controlli["testo"] = all(norm(t) in norm(r.testo) for t in caso["contiene"])
    if "ricambio" in caso:
        codice, campo = caso["ricambio"]
        controlli["cmms"] = contiene(r.testo, c.cmms.ricambio(codice)[campo])
    if "strumenti" in caso:
        controlli["strumenti"] = all(s in usati for s in caso["strumenti"])
    if "azione" in caso:
        attesa = r.in_attesa_di_conferma or {}
        controlli["conferma_richiesta"] = attesa.get("azione") == caso["azione"]
        if r.in_attesa_di_conferma:   # nella valutazione l'azione viene sempre rifiutata: nessuna scrittura
            c.assistente.conferma(r.thread_id, approvato=False)
    return {"domanda": caso["domanda"], "ok": all(controlli.values()), "controlli": controlli,
            "strumenti_usati": usati, "risposta": r.testo, "secondi": r.secondi}


def main() -> None:
    c = costruisci()
    casi = yaml.safe_load((Path(__file__).parent / "domande_agente.yaml").read_text(encoding="utf-8"))
    dettaglio = []
    for caso in casi:
        try:
            esito = valuta_caso(c, caso)
        except Exception as e:
            esito = {"domanda": caso["domanda"], "ok": False, "errore": str(e)[:300]}
        dettaglio.append(esito)
        print(("OK " if esito["ok"] else "NO ") + caso["domanda"], esito.get("controlli", esito.get("errore")))
        if not esito["ok"]:   # nel log della CI si vede subito perché ha sbagliato
            print("   strumenti:", esito.get("strumenti_usati"), "| risposta:",
                  (esito.get("risposta") or "").replace("\n", " ")[:400])
        time.sleep(2)   # quota gratuita: poche richieste al minuto
    corrette = sum(d["ok"] for d in dettaglio)
    secondi = [d["secondi"] for d in dettaglio if "secondi" in d]
    risultati = {"casi": len(casi), "corrette": corrette, "quota": round(corrette / len(casi), 3),
                 "secondi_medi": round(sum(secondi) / max(len(secondi), 1), 2)}
    p = salva_report("agente", c.cfg.firma(), risultati, dettaglio)
    print(f"\nCorrette: {corrette}/{len(casi)}   report: {p}")
    verifica_soglia("Agente: risposte corrette", corrette / len(casi), c.cfg.soglia_agente)


if __name__ == "__main__":
    main()
