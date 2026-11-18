"""`/api/households/{id}/automations`: papel × rota (PRIV-01), outra casa, votação ponta a ponta,
suspensão e reativação. Casa A é a demo SIMULADA (executor nunca chamado: nada executa)."""

import json
from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.core.events import load_events
from homemind.features.automations.tests.conftest import (
    DEMO_PLUG,
    HOUSE_B,
    LAMP,
    as_,
)

A = fx.HOUSEHOLD
ANA, BRUNO, CARLA, DIOGO = "sub-ana", "sub-bruno", "sub-carla", "sub-diogo"
LANDLORD, OPERATOR, EVA, NOBODY = "sub-senhorio", "sub-operador", "sub-eva", "sub-ninguem"
URL = f"/api/households/{A}/automations"
RANDOM = "00000000-0000-0000-0000-0000000000aa"


def body(target=DEMO_PLUG):
    return {
        "name": "Desligar tomada em pico",
        "trigger": {"kind": "power_above", "device_id": str(target), "threshold_w": 1500,
                    "duration_s": 1800},
        "target_device_id": str(target),
    }  # fmt: skip


def err(r):
    b = r.json()
    assert set(b) == {"error"} and set(b["error"]) == {"code", "message"}
    return r.status_code, b["error"]["code"]


def create(client, sub=ANA, **kw):
    r = client.post(URL, json=body(**kw), headers=as_(sub))
    assert r.status_code == 201, r.text
    return r.json()


def vote(client, sub, aid, approve=True, house=A):
    return client.post(
        f"/api/households/{house}/automations/{aid}/vote", json={"approve": approve},
        headers=as_(sub),
    )  # fmt: skip


def active(client):
    aid = create(client)["id"]
    for sub in (BRUNO, CARLA):  # a Ana propôs: já votou a favor
        assert vote(client, sub, aid).status_code == 200
    return aid


def events(app, *types):
    return [s.event for s in app.state.db.run_sync(lambda c: load_events(c, types=types))]


# --- papel × rota --------------------------------------------------------------------------------

ROUTES = [
    ("get", URL, None),
    ("post", URL, body()),
    ("post", f"{URL}/{RANDOM}/vote", {"approve": True}),
    ("patch", f"{URL}/{RANDOM}", {"status": "disabled"}),
    ("post", f"{URL}/{RANDOM}/reactivate", None),
]


@pytest.mark.parametrize("method,url,payload", ROUTES)
@pytest.mark.parametrize("sub", [LANDLORD, OPERATOR])
def test_senhorio_e_operador_nao_tem_acesso_a_nenhuma_rota(client, app, method, url, payload, sub):
    r = getattr(client, method)(url, headers=as_(sub), **({"json": payload} if payload else {}))
    assert err(r) == (403, "forbidden_role")
    assert events(app, "automation.proposed") == []


@pytest.mark.parametrize("method,url,payload", ROUTES)
@pytest.mark.parametrize("sub", [NOBODY, EVA])  # sem membership / inquilina só de outra casa
def test_quem_nao_e_membro_da_casa_recebe_404(client, method, url, payload, sub):
    r = getattr(client, method)(url, headers=as_(sub), **({"json": payload} if payload else {}))
    assert err(r) == (404, "household_not_found")


def test_sem_token_e_401(client):
    assert client.get(URL).status_code == 401


def test_regra_de_outra_casa_e_404_mesmo_pelo_caminho_da_propria(client):
    aid = create(client)["id"]
    eva = f"/api/households/{HOUSE_B}/automations"
    assert client.get(eva, headers=as_(EVA)).json() == []  # a Eva não vê a regra da casa A
    assert err(vote(client, EVA, aid, house=HOUSE_B)) == (404, "automation_not_found")
    assert err(client.patch(f"{eva}/{aid}", json={"status": "disabled"}, headers=as_(EVA))) == (
        404, "automation_not_found",
    )  # fmt: skip
    assert err(client.post(f"{eva}/{aid}/reactivate", headers=as_(EVA))) == (
        404, "automation_not_found",
    )  # fmt: skip


# --- ponta a ponta -----------------------------------------------------------------------


def test_propor_votar_ativar_suspender_e_reativar(client, app):
    v = create(client)
    aid = v["id"]
    assert v["status"] == "proposed" and v["vote_open"] and v["proposed_by_me"] is True
    assert v["majority"] == 3 and v["eligible"] == 4 and v["origin"] == "simulated"
    assert v["device_name"] and v["message"].startswith("SIMULADO")
    assert [e.type for e in events(app, "automation.proposed")] == ["automation.proposed"]

    assert (v["votes_for"], v["my_vote"]) == (1, True)  # o proponente vota a favor ao propor
    assert err(vote(client, ANA, aid)) == (409, "already_voted")
    assert vote(client, BRUNO, aid, approve=False).json()["votes_against"] == 1
    assert vote(client, CARLA, aid).json()["status"] == "proposed"  # 2 a favor de 4: falta uma
    final = vote(client, DIOGO, aid).json()
    assert final["status"] == "active" and final["my_vote"] is True and not final["vote_open"]
    decided = events(app, "automation.vote_decided", "automation.status_changed")
    assert [e.type for e in decided] == ["automation.vote_decided", "automation.status_changed"]

    paused = client.patch(f"{URL}/{aid}", json={"status": "disabled"}, headers=as_(BRUNO))
    assert paused.status_code == 200 and paused.json()["status"] == "disabled"
    assert err(client.patch(f"{URL}/{aid}", json={"status": "disabled"}, headers=as_(ANA))) == (
        409, "automation_not_active",
    )  # fmt: skip

    reopened = client.post(f"{URL}/{aid}/reactivate", headers=as_(DIOGO)).json()
    assert reopened["status"] == "disabled" and reopened["vote_open"]
    assert reopened["votes_for"] == 0 and reopened["vote_round"] == 2
    for sub in (ANA, BRUNO):
        vote(client, sub, aid)
    last = vote(client, CARLA, aid).json()
    assert last["status"] == "active"
    assert [r["status"] for r in client.get(URL, headers=as_(ANA)).json()] == ["active"]


def test_a_resposta_nao_diz_quem_votou_o_que_nem_expoe_ids_de_moradores(client):
    aid = create(client)["id"]
    vote(client, ANA, aid)
    raw = json.dumps(client.get(URL, headers=as_(BRUNO)).json())
    for resident in (fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO, fx.LANDLORD):
        assert str(resident) not in raw
    assert client.get(URL, headers=as_(BRUNO)).json()[0]["my_vote"] is None  # o voto da Ana é dela


def test_erros_de_estado_tem_codigos(client):
    aid = create(client)["id"]
    assert vote(client, BRUNO, aid).status_code == 200
    assert err(vote(client, BRUNO, aid)) == (409, "already_voted")
    assert err(client.post(f"{URL}/{aid}/reactivate", headers=as_(ANA))) == (
        409, "automation_not_disabled",
    )  # fmt: skip
    assert err(client.patch(f"{URL}/{aid}", json={"status": "disabled"}, headers=as_(ANA))) == (
        409, "automation_not_active",
    )  # fmt: skip
    assert err(vote(client, ANA, RANDOM)) == (404, "automation_not_found")


def test_voto_depois_do_prazo_e_409_e_rejeita_a_regra(client, now):
    aid = create(client)["id"]
    vote(client, ANA, aid)
    now["value"] = now["value"] + timedelta(hours=24, minutes=1)
    assert err(vote(client, BRUNO, aid)) == (409, "vote_expired")
    (rule,) = client.get(URL, headers=as_(ANA)).json()
    assert rule["status"] == "draft" and rule["last_verdict"] == "rejected"
    assert rule["votes_for"] == 1


def test_leitura_resolve_a_expiracao_uma_so_vez(client, app, now):
    create(client)
    now["value"] = now["value"] + timedelta(hours=25)
    for _ in range(3):
        (rule,) = client.get(URL, headers=as_(ANA)).json()
        assert rule["status"] == "draft"
    assert len(events(app, "automation.vote_decided")) == 1


# --- alvo e corpo ------------------------------------------------------------------------


def test_regra_com_lampada_e_recusada(client, app):
    r = client.post(URL, json=body(target=LAMP), headers=as_(ANA))
    assert err(r) == (400, "invalid_target")
    assert events(app, "automation.proposed") == []


def test_regra_para_uma_tomada_desconhecida_e_recusada(client):
    r = client.post(URL, json=body(target=fx.PLUG_SALA), headers=as_(ANA))
    assert err(r) == (400, "invalid_target")


def test_gatilho_incoerente_e_recusado_pelo_contrato(client, app):
    bad = {**body(), "trigger": {"kind": "power_above"}}
    assert err(client.post(URL, json=bad, headers=as_(ANA))) == (400, "invalid_request")
    assert events(app, "automation.proposed") == []


def test_a_acao_nao_vem_do_cliente_so_se_desliga_a_tomada(client):
    r = client.post(URL, json={**body(), "actions": [{"power": True}]}, headers=as_(ANA))
    assert err(r) == (400, "invalid_request")  # campo extra recusado
    (action,) = create(client)["actions"]
    assert (action["capability"], action["power"]) == ("power", False)


def test_patch_so_aceita_suspender(client):
    aid = active(client)
    r = client.patch(f"{URL}/{aid}", json={"status": "active"}, headers=as_(ANA))
    assert err(r) == (400, "invalid_request")
    assert client.get(URL, headers=as_(ANA)).json()[0]["status"] == "active"


def test_o_residente_vem_sempre_do_token_e_nao_do_corpo(client):
    r = client.post(URL, json={**body(), "created_by_resident_id": str(fx.BRUNO)}, headers=as_(ANA))
    assert err(r)[0] == 400  # campo extra recusado; o autor é o do token
    assert create(client, ANA)["proposed_by_me"] is True
    assert client.get(URL, headers=as_(BRUNO)).json()[0]["proposed_by_me"] is False


def test_device_id_do_gatilho_de_outra_casa_e_recusado(client, app):
    bad = {**body(), "trigger": {**body()["trigger"], "device_id": str(fx.PLUG_SALA)}}
    assert err(client.post(URL, json=bad, headers=as_(ANA))) == (400, "invalid_target")
    assert events(app, "automation.proposed") == []
    # a casa B não tem dispositivos: a tomada da casa A não é dela, nem como alvo nem como gatilho
    eva = f"/api/households/{HOUSE_B}/automations"
    assert err(client.post(eva, json=body(), headers=as_(EVA))) == (400, "invalid_target")


def test_a_quarta_proposta_aberta_e_recusada(client):
    for _ in range(3):
        create(client)
    assert err(client.post(URL, json=body(), headers=as_(ANA))) == (409, "too_many_open")
    create(client, BRUNO)  # o limite é por proponente


def test_reativar_reemite_automation_proposed_com_a_regra_suspensa(client, app):
    aid = active(client)
    client.patch(f"{URL}/{aid}", json={"status": "disabled"}, headers=as_(DIOGO))
    client.post(f"{URL}/{aid}/reactivate", headers=as_(DIOGO))
    assert [e.data.status.value for e in events(app, "automation.proposed")] == [
        "proposed",
        "disabled",
    ]
