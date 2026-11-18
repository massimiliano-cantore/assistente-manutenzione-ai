"""Configurazione: file versionato config/agente.yaml + variabili d'ambiente (che hanno la precedenza)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RADICE = Path(__file__).resolve().parents[1]

PROVIDER = {  # nome -> base_url delle API compatibili OpenAI
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openai": "https://api.openai.com/v1",
}


@dataclass
class Config:
    versione_prompt: str
    provider: str
    modello: str
    alternative: list[str]
    temperatura: float
    max_passi: int
    embedder: str
    modello_embedding: str
    top_k: int
    soglia_rag: float
    soglia_agente: float
    db_resi: Path = RADICE / "dati" / "resi_kyros.db"
    db_cmms: str = ":memory:"
    cartella_manuali: Path = RADICE / "dati" / "manuali"
    cartella_indice: str | None = None          # indice Qdrant su disco (costruito nell'immagine Docker)
    qdrant_url: str | None = None               # se impostato usa un server Qdrant (docker compose)
    cmms_url: str | None = None                 # se impostato l'agente chiama il CMMS via HTTP
    extra: dict = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        return os.getenv("LLM_BASE_URL") or PROVIDER[self.provider]

    @property
    def api_key(self) -> str | None:
        return os.getenv("LLM_API_KEY") or os.getenv(f"{self.provider.upper()}_API_KEY")

    def prompt_sistema(self) -> str:
        return (RADICE / "prompts" / f"sistema_{self.versione_prompt}.md").read_text(encoding="utf-8")

    def firma(self) -> dict:
        """Quello che identifica una versione dell'agente nei report di valutazione."""
        return {"versione_prompt": self.versione_prompt, "provider": self.provider, "modello": self.modello,
                "embedder": self.embedder, "modello_embedding": self.modello_embedding, "top_k": self.top_k}


@lru_cache
def carica_config(percorso: str | None = None) -> Config:
    p = Path(percorso or os.getenv("CONFIG_AGENTE", RADICE / "config" / "agente.yaml"))
    y = yaml.safe_load(p.read_text(encoding="utf-8"))
    llm, rag, soglie = y["llm"], y["rag"], y["soglie"]
    return Config(
        versione_prompt=os.getenv("VERSIONE_PROMPT", y["versione_prompt"]),
        provider=os.getenv("LLM_PROVIDER", llm["provider"]),
        modello=os.getenv("LLM_MODEL", llm["modello"]),
        alternative=llm.get("alternative", []),
        temperatura=float(llm.get("temperatura", 0)),
        max_passi=int(llm.get("max_passi", 8)),
        embedder=os.getenv("EMBEDDER", rag["embedder"]),
        modello_embedding=os.getenv("MODELLO_EMBEDDING", rag["modello_embedding"]),
        top_k=int(rag.get("top_k", 4)),
        soglia_rag=float(soglie["rag_hit_at_k"]),
        soglia_agente=float(soglie["agente_corrette"]),
        db_cmms=os.getenv("DB_CMMS", ":memory:"),
        cartella_indice=os.getenv("CARTELLA_INDICE") or None,
        qdrant_url=os.getenv("QDRANT_URL") or None,
        cmms_url=os.getenv("CMMS_URL") or None,
    )
