"""API do motor (contrato v3) com FakeHome e auth substituída (sem Authentik/câmara/MCP/NVIDIA)."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from homemind.connectors.fake_home import FakeHome
from homemind.features.auth.service import User, current_user
from homemind.features.engine import router as engine_router
from homemind.features.engine.config import EngineSettings
from homemind.main import app

LIVRO = {"tipo": "objeto_levantado", "classe": "livro", "hora": "2026-11-17T15:20:00Z"}


def _settings(tmp_path):
    return EngineSettings(
        rules_path=tmp_path / "rules.json", events_path=tmp_path / "e.jsonl", nvidia_api_key=""
    )


def _token_valido(cred):
    if cred.credentials != "bom":
        raise HTTPException(401, "Não autenticado")
    return User(sub="t")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_router, "get_engine_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(engine_router, "current_user", _token_valido)
    app.dependency_overrides[current_user] = lambda: User(sub="t")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_sem_login_401_com_envelope_de_erro(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_router, "get_engine_settings", lambda: _settings(tmp_path))
    with TestClient(app) as c:
        r = c.get("/api/state")
        assert r.status_code == 401 and r.json()["error"]["code"] == "http_401"


def test_status_e_state(client):
    assert client.get("/api/status").json()["backend"] == "fake"
    s = client.get("/api/state").json()
    assert s["state"] == "inativo" and s["mode"] is None and s["casa"]["backend"] == "fake"
    assert s["mcp_ok"] is False and s["camera_ok"] is False


def test_simulate_off_e_historico(client):
    s = client.post("/api/simulate", json=LIVRO).json()
    assert s["state"] == "ativo" and s["mode"] == "leitura" and s["mode_name"] == "Modo leitura"
    off = client.post("/api/off").json()
    assert off == {
        "success": True,
        "state": "inativo",
        "backend": "fake",
        "devices": {"lampada": "off", "tomada": "off"},
        "code": None,
        "message": None,
    }
    eventos = client.get("/api/events?limit=50").json()["events"]
    assert any("[SIMULADO]" in e["message"] for e in eventos)
    assert set(eventos[0]) == {"id", "timestamp", "level", "message", "source"}
    assert len(client.get("/api/events?limit=2").json()["events"]) == 2


def test_off_falha_parcial(client, monkeypatch):
    class TomadaAvariada(FakeHome):
        async def definir_tomada(self, ligada):
            return False

    client.app.state.engine.home = TomadaAvariada()
    off = client.post("/api/off").json()
    assert not off["success"] and off["code"] == "partial_failure"
    assert off["devices"] == {"lampada": "off", "tomada": "unknown"}


def test_evento_invalido_400(client):
    r = client.post("/api/simulate", json=LIVRO | {"classe": "chaves"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_crud_regras(client):
    regra = {
        "id": "verde",
        "nome": "Modo verde",
        "objeto": "caneca",
        "acoes": [{"dispositivo": "lampada", "ligada": True, "cor": "rosa", "brilho": 60}],
    }
    assert client.post("/api/rules", json=regra).status_code == 201
    regras = {r["id"]: r for r in client.get("/api/rules").json()["rules"]}
    assert regras["verde"]["enabled"] and not regras["pausa"]["enabled"]
    assert client.patch("/api/rules/pausa", json={"enabled": True}).json()["enabled"]
    assert client.delete("/api/rules/verde").status_code == 204
    r = client.delete("/api/rules/verde")
    assert r.status_code == 404 and r.json()["error"]["code"] == "rule_not_found"


def test_parse_sem_chave_503_e_nada_gravado(client):
    antes = client.get("/api/rules").json()
    r = client.post("/api/rules/parse", json={"text": "luz verde com o livro"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "nvidia_unavailable"
    assert client.get("/api/rules").json() == antes


def test_parse_proposta_nao_grava(client, monkeypatch):
    async def falso(texto, completar):
        from homemind.contracts.regras import Rule

        return Rule.model_validate(
            {
                "id": "leitura",
                "nome": "Modo verde",
                "objeto": "livro",
                "acoes": [{"dispositivo": "lampada", "ligada": True, "cor": "verde"}],
            }
        )

    monkeypatch.setattr(engine_router, "cliente_nvidia", lambda s: None)
    monkeypatch.setattr(engine_router, "propor_regra", falso)
    p = client.post("/api/rules/parse", json={"text": "luz verde com o livro"}).json()
    assert p["proposal"]["id"] == "leitura-2"  # não sobrescreve a predefinida
    assert p["replaces"] == "Modo leitura" and "luz verde" in p["summary"]
    assert "leitura-2" not in {r["id"] for r in client.get("/api/rules").json()["rules"]}


def test_websocket_auth_estado_e_eventos(client):
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "auth", "token": "bom"})
        assert ws.receive_json()["type"] == "home_state"
        client.post("/api/simulate", json=LIVRO | {"classe": "comando"})
        msgs = [ws.receive_json()]
        while msgs[-1]["type"] != "home_state" and len(msgs) < 20:
            msgs.append(ws.receive_json())
        assert msgs[0]["type"] == "event" and "Comando" in msgs[0]["data"]["message"]
        assert msgs[-1]["data"]["mode"] == "cinema"


def test_websocket_sem_token_fecha(client):
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "auth", "token": "mau"})
        assert ws.receive_json() == {
            "type": "error",
            "data": {"code": "unauthorized", "message": "Não autenticado"},
        }
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
