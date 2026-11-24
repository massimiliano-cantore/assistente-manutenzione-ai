import os

from app.config import carica_env


def test_carica_env(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# commento\nCHIAVE_PROVA="abc"\nVUOTA=\nGIA_IMPOSTATA=nuovo\n', encoding="utf-8")
    monkeypatch.setenv("GIA_IMPOSTATA", "vecchio")
    monkeypatch.delenv("CHIAVE_PROVA", raising=False)
    carica_env(f)
    assert os.environ["CHIAVE_PROVA"] == "abc"
    assert os.environ["GIA_IMPOSTATA"] == "vecchio"     # le variabili già impostate vincono
    assert "VUOTA" not in os.environ
    monkeypatch.delenv("CHIAVE_PROVA")


def test_provider_anthropic(monkeypatch):
    from app.agente.grafo import crea_llm
    from app.config import carica_config
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-prova")
    carica_config.cache_clear()
    cfg = carica_config()
    assert cfg.modello == "claude-sonnet-5-5" and cfg.alternative == ["claude-haiku-5-5"]
    llm = crea_llm(cfg, [])
    assert type(llm.runnable.bound).__name__ == "ChatAnthropic"
    carica_config.cache_clear()
