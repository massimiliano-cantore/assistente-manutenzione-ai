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
