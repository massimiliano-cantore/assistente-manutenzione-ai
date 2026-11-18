"""Il grafo LangGraph con un modello a copione: ciclo strumenti, errori, conferma umana, conversazione a più turni."""
import pytest
from fastapi.testclient import TestClient

from app.api import crea_app
from app.componenti import costruisci
from tests.llm_finto import LLMCopione, chiamata, testo


@pytest.fixture
def crea(cfg, kb, archivio):
    def _crea(*copione):
        llm = LLMCopione(copione=list(copione))
        return costruisci(cfg, llm=llm, kb=kb, archivio=archivio), llm
    return _crea


def test_risposta_con_rag(crea):
    c, llm = crea(
        chiamata("cerca_manuale", domanda="il lettore non legge i badge", famiglia="lettore"),
        lambda msgs: testo("Controlla la bobina BOB5510 [lettore#il-lettore-non-legge-i-badge]"),
    )
    r = c.assistente.chiedi("Un lettore 31220 non legge più i badge, cosa controllo?")
    assert "BOB5510" in r.testo
    assert [p["strumento"] for p in r.passi] == ["cerca_manuale"]
    assert r.passi[0]["esito"][0]["sezione"] == "lettore#il-lettore-non-legge-i-badge"
    assert "Sei l'assistente tecnico" in llm.ricevuti[0][0].content          # prompt di sistema versionato


def test_errore_sql_torna_al_modello(crea):
    c, _ = crea(
        chiamata("interroga_archivio", "c1", query="SELECT conteggio FROM rientri"),
        chiamata("interroga_archivio", "c2", query="SELECT COUNT(*) n FROM rientri WHERE anno=2024"),
        lambda msgs: testo(f"Nel 2024: {msgs[-1].content}"),
    )
    r = c.assistente.chiedi("Quanti rientri nel 2024?")
    assert "errore" in r.passi[0]["esito"] and "righe" in r.passi[1]["esito"]


def test_ordine_richiede_conferma(crea, store):
    args = dict(impianto_id="IMP-00001", descrizione="Verifica impianto, 3 rientri in 6 mesi", priorita="alta",
                ricambi=["SCB1180"])
    c, _ = crea(chiamata("apri_ordine_di_lavoro", **args), lambda m: testo("Ordine aperto."))
    r = c.assistente.chiedi("Apri un ordine per IMP-00001")
    assert r.in_attesa_di_conferma["impianto_id"] == "IMP-00001"      # il grafo è fermo: nulla è stato scritto
    assert c.cmms.impianto("IMP-00001")["ordini"] == []
    r2 = c.assistente.conferma(r.thread_id, approvato=True)
    assert r2.in_attesa_di_conferma is None and r2.testo == "Ordine aperto."
    assert r2.passi[-1]["esito"]["esito"] == "creato"
    assert len(c.cmms.impianto("IMP-00001")["ordini"]) == 1


def test_ordine_rifiutato(crea):
    c, _ = crea(chiamata("apri_ordine_di_lavoro", impianto_id="IMP-00001", descrizione="Verifica impianto"),
                lambda m: testo("Va bene, non apro l'ordine."))
    r = c.assistente.chiedi("Apri un ordine per IMP-00001")
    r2 = c.assistente.conferma(r.thread_id, approvato=False)
    assert r2.passi[-1]["esito"]["esito"] == "annullato"
    assert c.cmms.impianto("IMP-00001")["ordini"] == []


def test_memoria_della_conversazione(crea):
    c, llm = crea(testo("Ciao, dimmi pure."), testo("Ricordo la domanda precedente."))
    r = c.assistente.chiedi("Ciao")
    c.assistente.chiedi("E ora?", thread_id=r.thread_id)
    assert [m.content for m in llm.ricevuti[1][1:]] == ["Ciao", "Ciao, dimmi pure.", "E ora?"]


def test_api_chat_conferma_metriche(crea):
    c, _ = crea(chiamata("apri_ordine_di_lavoro", impianto_id="IMP-00002", descrizione="Sostituzione in campo"),
                lambda m: testo("Fatto."))
    with TestClient(crea_app(c, frontend=None)) as client:
        r = client.post("/api/chat", json={"messaggio": "apri un ordine"}).json()
        assert r["in_attesa_di_conferma"]["azione"] == "apri_ordine_di_lavoro"
        r2 = client.post("/api/conferma", json={"thread_id": r["thread_id"], "approvato": True}).json()
        assert r2["testo"] == "Fatto."
        s = client.get("/api/salute").json()
        assert s["stato"] == "ok" and s["versione_prompt"] == "v1"
        m = client.get("/metrics").text
        assert "assistente_chiamate_strumenti_totali" in m and "assistente_token_totali" in m
        assert client.post("/api/chat", json={"messaggio": ""}).status_code == 422
