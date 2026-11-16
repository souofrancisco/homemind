from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_ok_and_safe_defaults():
    body = client.get("/healthz").json()
    assert body == {"status": "ok", "mode": "simulation", "physical_writes": False}


def test_healthz_never_leaks_token(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "super-secret")
    assert "super-secret" not in client.get("/healthz").text
