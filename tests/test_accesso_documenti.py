from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.documenti.accesso import AccessoDocumenti, imposta_utente


def _app(tmp_path):
    app = FastAPI()
    app.add_middleware(AccessoDocumenti, cartella=tmp_path)

    @app.get("/documenti")
    def pagina():
        return {"ok": True}

    @app.get("/api/documenti/cerca")
    def cerca(q: str):
        return {"q": q}

    @app.post("/api/chat")
    def chat():
        return {}
    return app


def test_colleghi_solo_documenti_con_password(tmp_path):
    imposta_utente(tmp_path / "utenti_documenti.txt", "Mario", "password123")
    c = TestClient(_app(tmp_path))                     # host "testclient": come un altro PC
    assert c.post("/api/chat").status_code == 403
    assert c.get("/api/documenti/cerca?q=x").status_code == 401
    assert "Password" in c.get("/documenti").text
    assert c.post("/accesso", data={"nome": "mario", "password": "sbagliata"}).status_code == 401
    r = c.post("/accesso", data={"nome": "mario", "password": "password123", "vai": "/documenti"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert c.get("/api/documenti/cerca?q=staffa").json() == {"q": "staffa"}
    assert c.post("/api/chat").status_code == 403
    registro = (tmp_path / "accessi_documenti.csv").read_text(encoding="utf-8-sig")
    assert "accesso fallito" in registro and "ricerca;staffa" in registro
