"""Envelope de erro único: {"error": {"code", "message"}}."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from homemind.core.errors import register_errors


class Corpo(BaseModel):
    brilho: int


def _app() -> FastAPI:
    app = FastAPI()
    register_errors(app)

    @app.post("/x")
    def x(corpo: Corpo) -> Corpo:
        return corpo

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("https://user:segredo@host/")

    return app


def test_validation_error_names_field_but_not_value():
    r = TestClient(_app()).post("/x", json={"brilho": "segredo"})
    assert r.status_code == 400
    erro = r.json()["error"]
    assert erro["code"] == "invalid_request" and "body.brilho" in erro["message"]
    assert "segredo" not in r.text


def test_unhandled_error_uses_envelope_without_details():
    r = TestClient(_app(), raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal_error", "message": "Erro interno"}}
