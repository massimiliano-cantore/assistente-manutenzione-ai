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


def _chat(cfg, nome: str, temperatura: float, tentativi: int, timeout: int):
    """Modello di chat del provider scelto: Claude con la libreria Anthropic, gli altri con l'API compatibile OpenAI."""
    if cfg.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        # i modelli Claude recenti accettano solo la temperatura predefinita: non si passa
        return ChatAnthropic(model=nome, api_key=cfg.api_key, max_retries=tentativi, timeout=timeout,
                             max_tokens=4096)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=nome, base_url=cfg.base_url, api_key=cfg.api_key, temperature=temperatura,
                      max_retries=tentativi, timeout=timeout)


def crea_llm(cfg, strumenti: list):
    """Modello principale + modelli di riserva, tutti con gli strumenti collegati."""

    if not cfg.api_key:
        raise RuntimeError(f"manca la chiave API: imposta {cfg.provider.upper()}_API_KEY (o LLM_API_KEY)")

    riserve_presenti = any(m != cfg.modello for m in cfg.alternative)

    def modello(nome: str):
        # con modelli di riserva non si aspetta: al limite di richieste (429) si passa subito al modello successivo,
        # che su Groq ha un limite suo
        tentativi = 0 if riserve_presenti else 2
        return _chat(cfg, nome, cfg.temperatura, tentativi, 900 if cfg.provider == "ollama" else 90
                     ).bind_tools(strumenti)

    principale = modello(cfg.modello)
    riserve = [modello(m) for m in cfg.alternative if m != cfg.modello]
    return principale.with_fallbacks(riserve) if riserve else principale


def crea_llm_semplice(cfg):
    """Modello senza strumenti, per compiti di estrazione (es. la piedinatura da un datasheet)."""

    if not cfg.api_key:
        raise RuntimeError("manca la chiave API")
    return _chat(cfg, cfg.modello, 0, 2, 900 if cfg.provider == "ollama" else 120)


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
