from app.dati import sezioni_manuali


def test_pulizia_archivio(archivio):
    r = archivio.rientri
    assert len(r) > 7000
    assert not r.operazione.isin(["speditp", "spedita", "rottamata"]).any()   # esiti normalizzati
    assert (r.giorni_lavorazione.dropna() >= 0).all()                          # niente chiusure prima dell'arrivo


def test_sql_solo_lettura(archivio):
    assert archivio.sql("SELECT COUNT(*) n FROM rientri")["righe"][0]["n"] == len(archivio.rientri)
    for vietata in ["DELETE FROM rientri", "SELECT 1; DROP TABLE rientri", "UPDATE rientri SET anno=1"]:
        assert "errore" in archivio.sql(vietata)
    assert "errore" in archivio.sql("SELECT colonna_inesistente FROM rientri")   # l'errore torna al modello


def test_chunking_manuali(cfg):
    sezioni = sezioni_manuali(cfg.cartella_manuali)
    assert len(sezioni) >= 25
    assert len({s["id"] for s in sezioni}) == len(sezioni)          # id unici, citabili nelle risposte
    assert {s["famiglia"] for s in sezioni} >= {"serratura", "cilindro", "centralina", "lettore", "tastiera"}


def test_ricerca_manuali_con_filtro(kb):
    r = kb.cerca_manuali("il lettore non legge i badge", famiglia="lettore")
    assert r[0]["id"] == "lettore#il-lettore-non-legge-i-badge"
    assert all(x["famiglia"] in ("lettore", "generale") for x in r)


def test_casi_simili(kb):
    r = kb.cerca_casi("infiltrazione d'acqua, circuito sporco", famiglia="centralina")
    assert r and all(x["famiglia"] == "centralina" for x in r)
    assert any("INFILTRAZIONE" in x["diagnosi"] for x in r)
    assert r[0]["casi"] > 0 and r[0]["pezzi_frequenti"]
