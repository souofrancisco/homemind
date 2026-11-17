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
