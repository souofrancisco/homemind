"""O contrato OpenAPI das rotas de notificações."""

import json
import re

import pytest

from homemind.main import app

BASE = "/api/households/{household_id}"


@pytest.fixture(scope="module")
def spec():
    return app.openapi()


def test_caminhos_da_p3_existem(spec):
    paths = spec["paths"]
    assert set(paths[f"{BASE}/notifications"]) == {"get"}
    assert set(paths[f"{BASE}/notifications/{{notification_id}}/read"]) == {"post"}
    assert set(paths[f"{BASE}/notifications/{{notification_id}}/respond"]) == {"post"}
    assert set(paths[f"{BASE}/notification-preferences"]) == {"get", "put"}


def test_respostas_usam_os_modelos_publicos(spec):
    paths = spec["paths"]

    def ref(path, method):
        schema = paths[path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        return json.dumps(schema)

    assert "NotificationView" in ref(f"{BASE}/notifications", "get")
    assert "NotificationView" in ref(f"{BASE}/notifications/{{notification_id}}/read", "post")
    assert "NotificationView" in ref(f"{BASE}/notifications/{{notification_id}}/respond", "post")
    assert "NotificationPreferences" in ref(f"{BASE}/notification-preferences", "get")
    assert "NotificationPreferences" in ref(f"{BASE}/notification-preferences", "put")


def test_sem_entidade_interna_nem_ids_de_terceiros_nem_pares_ambiguos(spec):
    schemas = spec["components"]["schemas"]
    for internal in ("Notification", "ConfirmationRequest"):
        assert internal not in schemas, internal
    props = {p for s in schemas.values() for p in s.get("properties", {})}
    assert "responder_ids" not in props
    assert not [n for n in schemas if re.search(r"-(Input|Output)$", n)]


def test_modelos_de_entrada_locais_so_com_o_que_o_cliente_pode_enviar(spec):
    schemas = spec["components"]["schemas"]
    # o corpo do POST /respond é o do contrato (`NotificationRespondIn`): não há cópia local
    assert "RespondIn" not in schemas
    assert set(schemas["NotificationRespondIn"]["properties"]) == {
        "action_id",
        "target_resident_id",
    }
    assert schemas["NotificationRespondIn"]["additionalProperties"] is False
    assert set(schemas["NotificationPreferencesIn"]["properties"]) == {
        "quiet_hours",
        "disabled_kinds",
    }
    assert schemas["NotificationPreferencesIn"]["additionalProperties"] is False


def test_respond_recebe_o_corpo_do_contrato_e_a_vista_expoe_a_votacao(spec):
    op = spec["paths"][f"{BASE}/notifications/{{notification_id}}/respond"]["post"]
    body = op["requestBody"]["content"]["application/json"]["schema"]
    assert body["$ref"].endswith("/NotificationRespondIn")
    view = spec["components"]["schemas"]["NotificationView"]["properties"]
    assert "voting" in view
    # a vista da votação nunca tem ids de quem votou (só alvos e contagens)
    voting = spec["components"]["schemas"]["VotingView"]["properties"]
    assert set(voting) == {
        "verdict",
        "pays_me",
        "votes",
        "eligible",
        "votes_needed",
        "accusations",
        "my_vote",
    }


def test_lista_limita_o_tamanho_e_exige_casa(spec):
    op = spec["paths"][f"{BASE}/notifications"]["get"]
    params = {p["name"]: p for p in op["parameters"]}
    assert params["household_id"]["in"] == "path"
    assert params["limit"]["schema"]["minimum"] == 1
    assert params["limit"]["schema"]["maximum"] == 100
