"""Configurazione: file versionato config/agente.yaml + variabili d'ambiente (che hanno la precedenza)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RADICE = Path(__file__).resolve().parents[1]


def carica_env(percorso: Path = RADICE / ".env") -> None:
    """Legge il file .env (CHIAVE=valore) e lo mette nelle variabili d'ambiente, senza sovrascrivere quelle
    già impostate. Così in locale basta copiare .env.example in .env e inserire la chiave."""
    if not percorso.exists():
        return
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        chiave, _, valore = riga.partition("=")
        valore = valore.strip().strip('"').strip("'")
        if valore:
            os.environ.setdefault(chiave.strip(), valore)


carica_env()

PROVIDER = {  # nome -> base_url delle API compatibili OpenAI
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",      # modelli in locale: i documenti non escono dall'azienda
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
    dati_azienda: Path | None = None            # cartella della documentazione aziendale (MAI nel repository)
    cartella_immagini: Path = RADICE / "output" / "immagini"
    extra: dict = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        return os.getenv("LLM_BASE_URL") or PROVIDER[self.provider]

    @property
    def api_key(self) -> str | None:
        chiave = os.getenv("LLM_API_KEY") or os.getenv(f"{self.provider.upper()}_API_KEY")
        return chiave or ("ollama" if self.provider == "ollama" else None)   # Ollama non chiede chiavi

    @property
    def modalita(self) -> str:
        """'demo' = azienda fittizia KYROS; 'azienda' = documentazione reale nella cartella DATI_AZIENDA."""
        return "azienda" if self.dati_azienda else "demo"

    def prompt_sistema(self) -> str:
        nome = f"azienda_{self.versione_prompt_azienda}" if self.modalita == "azienda" else \
            f"sistema_{self.versione_prompt}"
        return (RADICE / "prompts" / f"{nome}.md").read_text(encoding="utf-8")

    @property
    def versione_prompt_azienda(self) -> str:
        return os.getenv("VERSIONE_PROMPT_AZIENDA", "v1")

    def firma(self) -> dict:
        """Quello che identifica una versione dell'agente nei report di valutazione."""
        return {"modalita": self.modalita,
                "versione_prompt": self.versione_prompt_azienda if self.modalita == "azienda" else self.versione_prompt,
                "provider": self.provider, "modello": self.modello,
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
        # i modelli di riserva sono del provider di config/agente.yaml: con un altro provider non valgono
        alternative=llm.get("alternative", []) if os.getenv("LLM_PROVIDER", llm["provider"]) == llm["provider"]
        else [],
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
        dati_azienda=Path(os.environ["DATI_AZIENDA"]) if os.getenv("DATI_AZIENDA") else None,
        cartella_immagini=Path(os.getenv("CARTELLA_IMMAGINI", str(RADICE / "output" / "immagini"))),
    )
