"""Demo pubblica dell'assistente tecnico su Streamlit Community Cloud.

Stesso agente dell'API (LangGraph, RAG, CMMS, conferma umana), con due accorgimenti per l'uso pubblico:
- ogni visitatore ha il SUO CMMS in memoria: gli ordini aperti da uno non li vede nessun altro;
- un limite di domande per visitatore e uno giornaliero totale, per proteggere la quota del modello.

Avvio in locale: streamlit run demo/streamlit_app.py   (con GROQ_API_KEY nel file .env)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # il pacchetto app/ sta nella radice del repository

MAX_DOMANDE = int(os.getenv("DEMO_MAX_DOMANDE", "10"))           # per visitatore
MAX_GIORNO = int(os.getenv("DEMO_MAX_GIORNO", "300"))            # per tutti i visitatori insieme
REPO = "https://github.com/massimiliano-cantore/assistente-manutenzione-ai"
ESEMPI = [
    "Un lettore di badge non riconosce più i tesserini: cosa controllo?",
    "Centralina con acqua dentro e circuito sporco: cosa si sostituisce di solito?",
    "Quanti rientri ci sono stati nel 2024?",
    "Apri un ordine di lavoro con priorità alta per l'impianto IMP-04042: verifica in campo dopo 3 rientri",
]
NOMI = {"cerca_manuale": "Manuali tecnici", "casi_simili": "Casi simili nello storico",
        "interroga_archivio": "Query sull'archivio", "cerca_impianto": "CMMS · impianti",
        "verifica_ricambio": "CMMS · magazzino", "apri_ordine_di_lavoro": "CMMS · ordine di lavoro"}

st.set_page_config(page_title="Assistente tecnico · demo", page_icon="🔧", layout="centered")

# la chiave del modello arriva dai secret di Streamlit Cloud (in locale dal file .env)
try:
    for k in ("GROQ_API_KEY", "LLM_MODEL", "EMBEDDER"):
        if k in st.secrets and not os.getenv(k):
            os.environ[k] = str(st.secrets[k])
except Exception:   # nessun file di secret: in locale va bene
    pass

from app.agente.grafo import crea_grafo, crea_llm  # noqa: E402
from app.agente.servizio import Assistente  # noqa: E402
from app.agente.strumenti import crea_strumenti  # noqa: E402
from app.cmms.api import crea_app as crea_app_cmms  # noqa: E402
from app.cmms.client import ClienteCMMS  # noqa: E402
from app.cmms.store import CMMSStore  # noqa: E402
from app.config import carica_config  # noqa: E402
from app.dati import ArchivioResi  # noqa: E402
from app.rag.indice import KnowledgeBase  # noqa: E402


@st.cache_resource(show_spinner="Preparo la knowledge base (solo al primo avvio, circa un minuto)…")
def risorse_condivise():
    """Parti in sola lettura, uguali per tutti: configurazione, archivio, indice dei manuali e dei casi."""
    cfg = carica_config()
    archivio = ArchivioResi(cfg.db_resi)
    return cfg, archivio, KnowledgeBase(cfg, archivio)


@st.cache_resource
def contatore_giornaliero() -> dict:
    return {"giorno": date.today().isoformat(), "domande": 0}


def assistente_del_visitatore() -> Assistente:
    """Ogni sessione ha il suo CMMS e il suo grafo: le scritture di un visitatore restano sue."""
    if "assistente" not in st.session_state:
        cfg, archivio, kb = risorse_condivise()
        cmms = ClienteCMMS(app=crea_app_cmms(CMMSStore(cfg.db_resi)))
        strumenti = crea_strumenti(archivio, kb, cmms)
        llm = st.session_state.get("_llm_test") or crea_llm(cfg, strumenti)
        grafo = crea_grafo(llm, strumenti, cfg.prompt_sistema())
        st.session_state.assistente = Assistente(grafo, cfg.max_passi, {**cfg.firma(), "canale": "demo"})
    return st.session_state.assistente


def riassunto(p: dict) -> str:
    a, e = p["argomenti"], p["esito"]
    dettaglio = next((str(a[k]) for k in ("query", "domanda", "sintomo", "codice", "impianto_id", "cliente")
                      if a.get(k)), "")
    if isinstance(e, dict) and "trovati" in e:
        esito = f"{e['trovati']} risultati"
    elif isinstance(e, dict) and "righe_totali" in e:
        esito = f"{e['righe_totali']} righe"
    elif isinstance(e, dict) and "errore" in e:
        esito = "errore, il modello riprova"
    elif isinstance(e, dict) and "esito" in e:
        esito = str(e["esito"])
    else:
        esito = ""
    return " → ".join(x for x in (dettaglio, esito) if x)


def mostra_passi(passi: list[dict]) -> None:
    if not passi:
        return
    with st.expander(f"{len(passi)} {'passo' if len(passi) == 1 else 'passi'} dell'agente"):
        for i, p in enumerate(passi, 1):
            st.markdown(f"**{i}. {NOMI.get(p['strumento'], p['strumento'])}** — {riassunto(p)}")
            st.code(json.dumps(p["esito"], ensure_ascii=False, indent=1)[:1500], language="json")


def ricevi(r) -> None:
    st.session_state.thread_id = r.thread_id
    st.session_state.in_attesa = r.in_attesa_di_conferma
    if r.testo or r.passi:
        st.session_state.messaggi.append({"ruolo": "assistant", "testo": r.testo, "passi": r.passi,
                                          "secondi": r.secondi})


def puo_chiedere() -> tuple[bool, str]:
    g = contatore_giornaliero()
    if g["giorno"] != date.today().isoformat():
        g.update(giorno=date.today().isoformat(), domande=0)
    if st.session_state.domande >= MAX_DOMANDE:
        return False, (f"Hai usato le {MAX_DOMANDE} domande di questa demo. Il codice completo è su GitHub: "
                       f"lo puoi far girare con la tua chiave, senza limiti.")
    if g["domande"] >= MAX_GIORNO:
        return False, "La demo ha raggiunto il limite di domande di oggi. Riprova domani!"
    return True, ""


def chiedi(testo: str) -> None:
    ok, motivo = puo_chiedere()
    if not ok:
        st.session_state.avviso = motivo
        return
    st.session_state.domande += 1
    contatore_giornaliero()["domande"] += 1
    st.session_state.messaggi.append({"ruolo": "user", "testo": testo})
    with st.spinner("L'agente sta lavorando…"):
        ricevi(assistente_del_visitatore().chiedi(testo, st.session_state.thread_id))


def decidi(approvato: bool) -> None:
    st.session_state.messaggi.append(
        {"ruolo": "user", "testo": "✔ Confermo l'ordine di lavoro" if approvato else "✖ Annulla"})
    with st.spinner("L'agente sta lavorando…"):
        ricevi(assistente_del_visitatore().conferma(st.session_state.thread_id, approvato))


# --- stato della sessione ---------------------------------------------------------------------------------
for chiave, iniziale in (("messaggi", []), ("thread_id", None), ("in_attesa", None), ("domande", 0),
                         ("avviso", "")):
    st.session_state.setdefault(chiave, iniziale)

# --- barra laterale -----------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Assistente tecnico")
    st.markdown("Agente **LangGraph** per un laboratorio riparazioni: cerca nei manuali e nei casi simili (RAG), "
                "interroga l'archivio in SQL e lavora su un **CMMS**. Prima di scrivere nel CMMS chiede conferma.")
    st.markdown(f"[Codice su GitHub]({REPO})")
    st.caption("Dati sintetici: KYROS ACCESS è un'azienda fittizia.")
    st.divider()
    st.metric("Domande rimaste", max(0, MAX_DOMANDE - st.session_state.domande))
    if st.button("Nuova conversazione", use_container_width=True):
        st.session_state.update(messaggi=[], thread_id=None, in_attesa=None, avviso="")
        st.rerun()

# --- conversazione ------------------------------------------------------------------------------------------
st.title("Assistente tecnico")
st.caption("KYROS ACCESS · laboratorio riparazioni · demo con dati sintetici")

if not os.getenv("GROQ_API_KEY") and "_llm_test" not in st.session_state:
    st.error("Manca la chiave del modello: aggiungi GROQ_API_KEY nei secret dell'app.")
    st.stop()

if not st.session_state.messaggi:
    st.markdown("Chiedi una diagnosi, un dato dallo storico o un'azione sul CMMS. Puoi partire da un esempio:")
    for i, esempio in enumerate(ESEMPI):
        if st.button(esempio, key=f"esempio_{i}", use_container_width=True):
            chiedi(esempio)
            st.rerun()

for m in st.session_state.messaggi:
    with st.chat_message(m["ruolo"]):
        if m["testo"]:
            st.markdown(m["testo"])
        if m["ruolo"] == "assistant":
            mostra_passi(m.get("passi", []))
            st.caption(f"{m.get('secondi', 0):.1f} s")

azione = st.session_state.in_attesa
if azione:
    with st.container(border=True):
        st.markdown("**L'agente vuole aprire un ordine di lavoro nel CMMS**")
        st.markdown(f"- Impianto: `{azione['impianto_id']}`\n- Descrizione: {azione['descrizione']}\n"
                    f"- Priorità: **{azione['priorita']}**\n"
                    f"- Ricambi: {', '.join(azione['ricambi']) or 'nessuno'}")
        c1, c2 = st.columns(2)
        if c1.button("Conferma", type="primary", use_container_width=True):
            decidi(True)
            st.rerun()
        if c2.button("Annulla", use_container_width=True):
            decidi(False)
            st.rerun()

if st.session_state.avviso:
    st.info(st.session_state.avviso)

domanda = st.chat_input("Conferma o annulla l'azione proposta" if azione else "Scrivi una domanda…",
                        disabled=bool(azione))
if domanda:
    chiedi(domanda)
    st.rerun()
