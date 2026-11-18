"""Grafo LangGraph dell'agente: modello -> strumenti -> modello, finché non c'è una risposta finale.

    START -> agente --(chiamate a strumenti?)--> strumenti -> agente
                    \\--(risposta finale)-------> END

Lo stato (la conversazione) è salvato da un checkpointer per thread: serve per le conversazioni a più turni
e per riprendere il grafo dopo la conferma umana (interrupt).
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition


def crea_llm(cfg, strumenti: list):
    """Modello principale + modelli di riserva, tutti con gli strumenti collegati."""
    from langchain_openai import ChatOpenAI

    if not cfg.api_key:
        raise RuntimeError(f"manca la chiave API: imposta {cfg.provider.upper()}_API_KEY (o LLM_API_KEY)")

    def modello(nome: str):
        return ChatOpenAI(model=nome, base_url=cfg.base_url, api_key=cfg.api_key, temperature=cfg.temperatura,
                          max_retries=2, timeout=60).bind_tools(strumenti)

    principale = modello(cfg.modello)
    riserve = [modello(m) for m in cfg.alternative if m != cfg.modello]
    return principale.with_fallbacks(riserve) if riserve else principale


def crea_grafo(llm: BaseChatModel, strumenti: list, prompt_sistema: str, checkpointer=None):
    def agente(stato: MessagesState):
        risposta = llm.invoke([SystemMessage(prompt_sistema)] + stato["messages"])
        return {"messages": [risposta]}

    g = StateGraph(MessagesState)
    g.add_node("agente", agente)
    # handle_tool_errors: un'eccezione in uno strumento torna al modello come messaggio, non blocca la chat
    g.add_node("strumenti", ToolNode(strumenti, handle_tool_errors=True))
    g.add_edge(START, "agente")
    g.add_conditional_edges("agente", tools_condition, {"tools": "strumenti", "__end__": "__end__"})
    g.add_edge("strumenti", "agente")
    return g.compile(checkpointer=checkpointer or InMemorySaver())
