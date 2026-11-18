"""As rotas das automações estão no contrato com DTOs próprios, sem ids de moradores."""

import json

import pytest

from homemind.main import app

BASE = "/api/households/{household_id}/automations"


@pytest.fixture(scope="module")
def spec():
    return app.openapi()


def ref(schema):
    return schema["$ref"].rsplit("/", 1)[-1]


def test_rotas_e_corpos(spec):
    paths = spec["paths"]
    assert set(paths[BASE]) == {"get", "post"}
    assert set(paths[f"{BASE}/{{automation_id}}"]) == {"patch"}
    assert set(paths[f"{BASE}/{{automation_id}}/vote"]) == {"post"}
    assert set(paths[f"{BASE}/{{automation_id}}/reactivate"]) == {"post"}
    post = paths[BASE]["post"]
    assert (
        ref(post["requestBody"]["content"]["application/json"]["schema"]) == "AutomationProposeIn"
    )
    assert (
        ref(post["responses"]["201"]["content"]["application/json"]["schema"]) == "AutomationView"
    )
    items = paths[BASE]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["items"]
    assert ref(items) == "AutomationView"
    patch = paths[f"{BASE}/{{automation_id}}"]["patch"]
    assert (
        ref(patch["requestBody"]["content"]["application/json"]["schema"]) == "AutomationStatusIn"
    )


def test_a_vista_nao_expoe_quem_votou_nem_a_entidade_interna(spec):
    view = json.dumps(spec["components"]["schemas"]["AutomationView"])
    assert "resident" not in view and "voters" not in view
    assert "approved_by_resident_id" not in view and "created_by_resident_id" not in view


def test_sem_pares_input_output(spec):
    assert not [n for n in spec["components"]["schemas"] if n.endswith(("-Input", "-Output"))]
