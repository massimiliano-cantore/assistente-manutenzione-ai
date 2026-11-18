"""I valutatori stessi vanno testati: un controllo sbagliato darebbe numeri falsi."""
from app.componenti import costruisci
from tests.llm_finto import LLMCopione, chiamata, testo
from valutazioni.valuta_agente import contiene, valuta_caso


def test_contiene_normalizza_numeri():
    assert contiene("Nel 2024 ci sono stati **1.651** rientri", 1651)
    assert not contiene("16510 rientri", 1651)


def test_valuta_caso_sql_e_azione(cfg, kb, archivio):
    n = archivio.con.execute("SELECT COUNT(*) FROM rientri WHERE anno=2024").fetchone()[0]
    llm = LLMCopione(copione=[
        chiamata("interroga_archivio", query="SELECT COUNT(*) FROM rientri WHERE anno=2024"),
        testo(f"Nel 2024 i rientri sono stati {n}."),
        chiamata("apri_ordine_di_lavoro", impianto_id="IMP-04042", descrizione="Verifica in campo"),
        testo("Ordine non aperto."),
    ])
    c = costruisci(cfg, llm=llm, kb=kb, archivio=archivio)
    ok = valuta_caso(c, {"domanda": "Quanti rientri nel 2024?", "sql": "SELECT COUNT(*) FROM rientri WHERE anno=2024",
                         "strumenti": ["interroga_archivio"]})
    assert ok["ok"], ok
    az = valuta_caso(c, {"domanda": "Apri un ordine", "azione": "apri_ordine_di_lavoro"})
    assert az["ok"] and c.cmms.impianto("IMP-04042")["ordini"] == []      # rifiutato: nessuna scrittura


def test_contiene_trattini_tipografici():
    """Bug del valutatore trovato in CI: il modello scrive 'IMP‑04042' con il trattino U+2011."""
    assert contiene("Il primo impianto è IMP‑04042", "IMP-04042")
