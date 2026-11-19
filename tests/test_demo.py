"""La demo Streamlit con il modello a copione: domanda, passi, conferma, limite di domande."""
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.llm_finto import LLMCopione, chiamata, testo  # noqa: E402


def avvia(*copione, max_domande=None, monkeypatch=None):
    if max_domande is not None:
        monkeypatch.setenv("DEMO_MAX_DOMANDE", str(max_domande))
    at = AppTest.from_file("../demo/streamlit_app.py", default_timeout=120)
    at.session_state["_llm_test"] = LLMCopione(copione=list(copione))
    return at.run()


def test_domanda_e_conferma(monkeypatch):
    monkeypatch.setenv("EMBEDDER", "tfidf")
    at = avvia(chiamata("cerca_manuale", domanda="badge", famiglia="lettore"), testo("Controlla la bobina BOB5510."),
               chiamata("apri_ordine_di_lavoro", "c2", impianto_id="IMP-04042", descrizione="Verifica in campo"),
               testo("Ordine aperto."))
    assert not at.exception
    at.button(key="esempio_0").click().run()
    assert "BOB5510" in at.chat_message[-1].markdown[0].value
    at.chat_input[0].set_value("Apri un ordine per IMP-04042").run()
    assert at.session_state["in_attesa"]["impianto_id"] == "IMP-04042"
    next(b for b in at.button if b.label == "Conferma").click().run()
    assert at.session_state["in_attesa"] is None
    assert at.chat_message[-1].markdown[0].value == "Ordine aperto."


def test_limite_domande(monkeypatch):
    monkeypatch.setenv("EMBEDDER", "tfidf")
    at = avvia(testo("Uno."), testo("Due."), max_domande=1, monkeypatch=monkeypatch)
    at.chat_input[0].set_value("prima").run()
    at.chat_input[0].set_value("seconda").run()
    assert at.session_state["domande"] == 1
    assert "domande di questa demo" in at.info[0].value
