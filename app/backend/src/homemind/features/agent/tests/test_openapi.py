"""O endpoint do assistente está no contrato e reutiliza `AgentResponse`/`AgentMessageIn`."""

import json
import re

import pytest

from homemind.main import app

PATH = "/api/households/{household_id}/agent/messages"


@pytest.fixture(scope="module")
def spec():
    return app.openapi()


def test_caminho_do_agente_existe_e_reutiliza_os_contratos(spec):
    op = spec["paths"][PATH]["post"]
    body = op["requestBody"]["content"]["application/json"]["schema"]
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/AgentMessageIn"}
    assert ok == {"$ref": "#/components/schemas/AgentResponse"}


def test_sem_pares_input_output_e_sem_caminho_antigo(spec):
    assert not [n for n in spec["components"]["schemas"] if re.search(r"-(Input|Output)$", n)]
    assert "/api/agent/messages" not in spec["paths"]
    assert "AgentSettings" not in json.dumps(spec)


def test_historico_da_conversa_existe_e_reutiliza_agent_message(spec):
    op = spec["paths"][PATH]["get"]
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok["type"] == "array" and ok["items"] == {"$ref": "#/components/schemas/AgentMessage"}
    (limit,) = [p for p in op["parameters"] if p["name"] == "limit"]
    assert limit["schema"]["minimum"] == 1 and limit["schema"]["maximum"] == 100
    assert limit["schema"]["default"] == 50


def test_ferramentas_novas_e_transparencia_no_contrato(spec):
    schemas = spec["components"]["schemas"]
    tools = schemas["AgentTool"]["enum"]
    assert {
        "top_appliances",
        "consumption_change",
        "explain_attribution",
        "pending_confirmations",
    } <= set(tools)
    assert "interpreter" in schemas["AgentResponse"]["properties"]
    assert {"llm", "rules"} <= set(
        schemas["AgentResponse"]["properties"]["interpreter"]["anyOf"][0]["enum"]
    )
    assert "appliances" in schemas["AgentToolResult"]["properties"]
    assert {"attribution_parts", "final", "pending", "pending_count"} <= set(
        schemas["AgentToolResult"]["properties"]
    )
    assert "tool_results" in schemas["AgentResponse"]["properties"]
