"""Strumenti dell'agente sulla documentazione elettronica: schede, componenti, collegamenti, datasheet, disegni.

Il modello ragiona sul guasto; i dati esatti (quale pin va dove, cosa fa ogni pin) li forniscono questi strumenti.
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from app.datasheet.servizio import ServizioDatasheet, confronta_con_netlist
from app.elettrico.catalogo import Catalogo
from app.elettrico.evidenzia import evidenzia


def _pin(rif: str) -> str:
    return rif.strip().upper().replace(" ", "").replace(".", "-")


def crea_strumenti_elettrici(catalogo: Catalogo, datasheet: ServizioDatasheet | None, cartella_immagini: Path) -> list:
    @tool
    def panoramica_prodotti() -> dict:
        """Elenca tutti i prodotti con le schede che li compongono e come sono collegate.
        Usalo all'inizio per capire su quale scheda si trova la funzione guasta; per un codice articolo usa
        prima cerca_prodotto."""
        p = catalogo.panoramica()
        nomi = {s["codice"]: s.get("nome") or "" for s in p["schede"]}
        return {"prodotti": [{"nome": x["nome"], "schede": [f"{c} {nomi.get(c, '')}".strip() for c in x["schede"]],
                              **({"collegamenti": x["collegamenti"]} if x["collegamenti"] else {})}
                             for x in p["prodotti"]]}

    @tool
    def cerca_componenti(testo: str, scheda: str = "") -> dict:
        """Cerca componenti per parole nel valore o nella descrizione (es. 'transceiver', 'regolatore', 'quarzo',
        'STM32', 'fuse'). scheda: codice della scheda ('' = tutte)."""
        risultati = catalogo.cerca_componenti(testo, scheda)
        return {"risultati": risultati, "trovati": len(risultati)} if risultati else \
            {"risultati": [], "trovati": 0, "nota": "nessun componente: prova parole più generiche o in inglese"}

    @tool
    def info_componente(scheda: str, designator: str) -> dict:
        """Dati di un componente (valore, descrizione, montato o no) e, per ogni pin, la net e cosa vi è collegato,
        compreso il pin corrispondente sull'altra scheda se è un connettore."""
        return catalogo.info_componente(scheda, designator)

    @tool
    def collegamenti_pin(scheda: str, pin: str) -> dict:
        """Tutti i pin collegati a un pin (es. 'U1-14'), anche oltre i connettori verso le altre schede."""
        return catalogo.collegati(scheda, _pin(pin))

    @tool
    def percorso_segnale(scheda_da: str, pin_da: str, scheda_a: str, pin_a: str) -> dict:
        """Strada di un segnale da un pin a un altro, anche tra schede diverse: elenca net, connettori e
        componenti attraversati (resistenze, induttanze, ferriti, fusibili): sono i punti da controllare."""
        return catalogo.percorso(scheda_da, _pin(pin_da), scheda_a, _pin(pin_a))

    @tool
    def componenti_vicini(scheda: str, designator: str) -> dict:
        """Componenti collegati direttamente a un componente (escluse masse e alimentazioni), con le net in comune:
        utile per capire il circuito attorno a un integrato (quarzo, filtri, rete d'antenna...)."""
        return catalogo.sottocircuito(scheda, designator.strip().upper())

    @tool
    def piedinatura_componente(scheda: str, designator: str, aggiorna: bool = False) -> dict:
        """Funzione di ogni pin di un integrato, presa dal datasheet trovato in internet (o da quello di un
        compatibile, che viene segnalato), unita ai collegamenti reali sulla scheda. Indica il segnale atteso su
        ogni pin: usalo per dire al tecnico cosa misurare e cosa aspettarsi."""
        if datasheet is None:
            return {"errore": "ricerca datasheet non configurata (manca MOUSER_API_KEY o TAVILY_API_KEY)"}
        info = catalogo.info_componente(scheda, designator.strip().upper())
        codice = info.get("codice_produttore") or info.get("valore")
        if not codice:
            return {"errore": f"{designator}: nella documentazione manca il codice del componente"}
        p = datasheet.piedinatura(codice, n_pin=info["numero_pin"], package=info.get("footprint", ""),
                                  aggiorna=aggiorna)
        if "errore" in p:
            return p
        reti = {x["pin"]: x for x in info["pin"]}
        pin_uniti = []
        for d in p["pin"]:
            r = reti.get(str(d["numero"]).strip(), {})
            pin_uniti.append({**d, "net": r.get("net", "(pin non presente sulla scheda)"),
                              "collegato_a": r.get("collegato_a", [])[:6], "verso_altra_scheda":
                              r.get("verso_altra_scheda")})
        avviso = ("ATTENZIONE: datasheet di un componente compatibile, non del codice esatto"
                  if p.get("compatibile") else None)
        return {"componente": designator, "codice": codice, "datasheet_di": p.get("datasheet_di"),
                "fonte": p["fonte"], "url": p["url"], "ufficiale": p.get("ufficiale"), "avviso": avviso,
                "package": p.get("package"), **confronta_con_netlist(p, set(reti)), "pin": pin_uniti}

    @tool
    def evidenzia_su_disegno(scheda: str, designators: list[str]) -> dict:
        """Evidenzia uno o più componenti sul disegno della scheda (schema o montaggio) e restituisce l'immagine
        da mostrare al tecnico. Usalo per indicare dove misurare o cosa controllare."""
        s = catalogo.scheda(scheda)
        if not s.pdf_disegno:
            return {"errore": f"nessun disegno disponibile per la scheda {s.codice}"}
        return evidenzia(s.pdf_disegno, [d.strip().upper() for d in designators][:8], cartella_immagini)

    return [panoramica_prodotti, cerca_componenti, info_componente, collegamenti_pin, percorso_segnale,
            componenti_vicini, piedinatura_componente, evidenzia_su_disegno]
