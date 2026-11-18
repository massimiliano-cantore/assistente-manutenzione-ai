"""Modello linguistico 'a copione' per i test: restituisce risposte predefinite, così il grafo, gli strumenti,
l'interrupt e l'API si testano in modo deterministico, senza rete e senza chiavi."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def chiamata(nome: str, id_: str = "c1", **argomenti) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": nome, "args": argomenti, "id": id_, "type": "tool_call"}],
                     usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})


def testo(t: str) -> AIMessage:
    return AIMessage(t, usage_metadata={"input_tokens": 150, "output_tokens": 40, "total_tokens": 190})


class LLMCopione(BaseChatModel):
    """Ogni chiamata consuma il prossimo elemento del copione: un AIMessage o una funzione(messaggi) -> AIMessage."""

    copione: list[Any]
    ricevuti: list[list] = []

    @property
    def _llm_type(self) -> str:
        return "copione"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.ricevuti.append(list(messages))
        if not self.copione:
            raise RuntimeError("copione finito: il grafo ha chiamato il modello più volte del previsto")
        passo: AIMessage | Callable = self.copione.pop(0)
        msg = passo(messages) if callable(passo) else passo
        return ChatResult(generations=[ChatGeneration(message=msg)])
