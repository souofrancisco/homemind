"""ALERT-06: `agent.budget_light` transforma o orçamento a 80/100 % numa proposta de cor.

Sem rede, LLM nem hardware. Como no AGENT-03b: o consumidor só PROPÕE; só `confirm` executa, e
numa casa demo com o executor SIMULADO.
"""

import time
from datetime import timedelta
from uuid import UUID

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.billing import BudgetThreshold
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.devices import DeviceKind
from homemind.features.agent.budget_light_consumer import (
    BUDGET_LIGHT_CONSUMER,
    SUPERSEDED,
    action_id_for,
    choose_bulb,
    make_handler,
)
from homemind.features.agent.devices import DIRECTORY_ATTR, ActuatorDevice
from homemind.features.agent.execution import EXECUTOR_ATTR
from homemind.features.agent.tests._action_fakes import REAL_PLUG, FakeDirectory, FakeExecutor
from homemind.features.agent.tests.conftest import GINA, HOUSE_C, NOW, as_

SIM = Provenance(origin=Origin.simulated, kind=ValueKind.estimated)
REAL = Provenance(origin=Origin.real, kind=ValueKind.estimated)
ROOM_GINA, ROOM_HANA = stable_id("room", "c1"), stable_id("room", "c2")
BULB_GINA = ActuatorDevice(
    stable_id("device", "bulb-g"), "Lâmpada da Gina", DeviceKind.bulb, False, room_id=ROOM_GINA
)  # noqa: E501
BULB_HANA = ActuatorDevice(
    stable_id("device", "bulb-h"), "Lâmpada da Hana", DeviceKind.bulb, False, room_id=ROOM_HANA
)  # noqa: E501


@pytest.fixture(autouse=True)
def clean_state(app):
    def clear():
        for attr in (DIRECTORY_ATTR, EXECUTOR_ATTR, "agent_simulated_executor"):
            if hasattr(app.state, attr):
                delattr(app.state, attr)

    clear()
    yield
    clear()


def crossed(pct, resident=fx.ANA, house=fx.HOUSEHOLD, provenance=SIM, ts=NOW, name="a"):
    return de.AlertsThresholdCrossed(
        id=stable_id("alerts.threshold_crossed", name, str(pct), str(resident)),
        ts=ts,
        household_id=house,
        provenance=provenance,
        data=BudgetThreshold(
            budget_id=stable_id("budget", str(resident)),
            resident_id=resident,
            period="2026-11",
            pct=pct,
            spent_cents=pct * 10,
            limit_cents=1000,
        ),
    )


def publish(app, event):
    app.state.bus.publish_threadsafe(event)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        done = app.state.db.run_sync(
            lambda c: c.execute(
                "SELECT 1 FROM processed_event WHERE consumer = ? AND event_id = ?",
                (BUDGET_LIGHT_CONSUMER, str(event.id)),
            ).fetchone()
        )
        if done:
            return event
        time.sleep(0.05)
    raise AssertionError("o consumidor não processou o evento")


def rows(app):
    return app.state.db.run_sync(
        lambda c: c.execute("SELECT * FROM agent_action ORDER BY proposed_at").fetchall()
    )


def mine(client, sub, house=fx.HOUSEHOLD):
    r = client.get(f"/api/households/{house}/agent/actions", headers=as_(sub))
    assert r.status_code == 200, r.text
    return r.json()


# --- escolha da lâmpada (pura) -----------------------------------------------------------------


def test_escolha_da_lampada():
    sala = ActuatorDevice(fx.LAMP, "Lâmpada da sala", DeviceKind.bulb, True, room_id=fx.ROOM_SALA)
    sem_divisao = ActuatorDevice(stable_id("device", "x"), "Sem divisão", DeviceKind.bulb, False)
    common = {fx.ROOM_SALA}
    assert choose_bulb([sala, BULB_GINA], ROOM_GINA, common) == (BULB_GINA, False)  # o meu quarto
    assert choose_bulb([sala, BULB_HANA], ROOM_GINA, common) == (sala, True)  # zona comum, avisa
    assert choose_bulb([BULB_HANA, sem_divisao], ROOM_GINA, common) is None  # nunca a de outro
    assert choose_bulb([REAL_PLUG], ROOM_GINA, common) is None  # uma tomada não é lâmpada


# --- casa demo ---------------------------------------------------------------------------------


def test_o_consumidor_esta_subscrito(app):
    assert BUDGET_LIGHT_CONSUMER in app.state.bus._subs


@pytest.mark.parametrize(
    ("pct", "rgb", "cor"), [(80, (255, 200, 0), "âmbar"), (100, (255, 0, 0), "vermelho")]
)  # noqa: E501
def test_limiar_propoe_a_cor_ao_proprio(app, client, now, pct, rgb, cor):
    ex = FakeExecutor(lambda: now["value"], "raise")
    setattr(app.state, EXECUTOR_ATTR, ex)
    publish(app, crossed(pct))
    (r,) = rows(app)
    assert UUID(r["proposed_for_resident_id"]) == fx.ANA and r["source"] == "budget"
    assert r["capability"] == "color_rgb" and r["origin"] == "simulated"
    assert r["target_device_id"] == str(fx.LAMP)
    (view,) = mine(client, "sub-ana")
    cmd = view["action"]["command"]["color_rgb"]
    assert (cmd["r"], cmd["g"], cmd["b"]) == rgb
    rationale = view["action"]["rationale"]
    assert f"{pct} %" in rationale and cor in rationale and "à vista" in rationale  # a da sala
    assert len(rationale) <= 300
    for sub in ("sub-bruno", "sub-carla", "sub-diogo"):
        assert mine(client, sub) == []  # o orçamento é pessoal
    assert ex.calls == []  # propor nunca executa


def test_verde_nao_propoe(app):
    publish(app, crossed(50))
    assert rows(app) == []


def test_confirmar_usa_o_executor_simulado_uma_vez(app, client):
    publish(app, crossed(80))
    (view,) = mine(client, "sub-ana")
    url = f"/api/households/{fx.HOUSEHOLD}/agent/actions/{view['action']['id']}"
    r = client.post(f"{url}/confirm", headers=as_("sub-ana"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["execution"]["status"] == "confirmed" and body["execution"]["readback_confirmed"]
    assert "SIMULADO" in body["message"]
    assert client.post(f"{url}/confirm", headers=as_("sub-ana")).status_code == 409
    assert client.post(f"{url}/confirm", headers=as_("sub-bruno")).status_code == 404


def test_vermelho_retira_o_ambar_por_confirmar_e_reprocessar_nao_duplica(app, now):
    ambar = publish(app, crossed(80))
    vermelho = publish(app, crossed(100))
    got = {r["id"]: r for r in rows(app)}
    assert got[str(action_id_for(ambar.id, fx.ANA))]["status"] == "rejected"
    assert got[str(action_id_for(vermelho.id, fx.ANA))]["status"] == "proposed"
    log = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT code FROM agent_action_log WHERE to_status = 'rejected'"
        ).fetchall()
    )
    assert [r["code"] for r in log] == [SUPERSEDED]
    handler = make_handler(app, lambda: now["value"])
    again = de.StoredEvent(seq=9, event=vermelho)
    assert app.state.db.run_sync(lambda c: handler(c, again)) == []
    assert len(rows(app)) == 2


def test_evento_alem_do_ttl_nao_propoe(app, now):
    publish(app, crossed(80, ts=NOW - timedelta(days=1)))
    assert rows(app) == []


def test_senhorio_nunca_recebe(app):
    publish(app, crossed(80, resident=fx.LANDLORD))
    assert rows(app) == []


# --- casa real ---------------------------------------------------------------------------------


def test_casa_real_sem_diretorio_nao_propoe(app, real_house):
    publish(app, crossed(80, resident=GINA, house=HOUSE_C, provenance=REAL))
    assert rows(app) == []


def test_casa_real_so_a_lampada_do_proprio_quarto(app, real_house, client):
    setattr(app.state, DIRECTORY_ATTR, FakeDirectory([BULB_HANA, BULB_GINA]))
    publish(app, crossed(80, resident=GINA, house=HOUSE_C, provenance=REAL))
    (r,) = rows(app)
    assert r["target_device_id"] == str(BULB_GINA.id) and r["origin"] == "real"
    (view,) = mine(client, "sub-gina", HOUSE_C)
    assert "à vista" not in view["action"]["rationale"]  # no quarto dela, só ela a vê
    assert mine(client, "sub-hana", HOUSE_C) == []


def test_casa_real_nunca_a_lampada_de_outro_quarto(app, real_house):
    setattr(app.state, DIRECTORY_ATTR, FakeDirectory([BULB_HANA]))
    publish(app, crossed(80, resident=GINA, house=HOUSE_C, provenance=REAL))
    assert rows(app) == []


def test_casa_real_ignora_eventos_simulados(app, real_house, now):
    """O barramento já os recusa; o handler defende-se na mesma (defesa em profundidade)."""
    setattr(app.state, DIRECTORY_ATTR, FakeDirectory([BULB_GINA]))
    ev = crossed(80, resident=GINA, house=HOUSE_C, provenance=SIM)
    handler = make_handler(app, lambda: now["value"])
    assert app.state.db.run_sync(lambda c: handler(c, de.StoredEvent(seq=1, event=ev))) == []
    assert rows(app) == []


def test_casa_real_sem_executor_fica_bloqueada(app, real_house, client):
    setattr(app.state, DIRECTORY_ATTR, FakeDirectory([BULB_GINA]))
    publish(app, crossed(100, resident=GINA, house=HOUSE_C, provenance=REAL))
    (view,) = mine(client, "sub-gina", HOUSE_C)
    url = f"/api/households/{HOUSE_C}/agent/actions/{view['action']['id']}/confirm"
    body = client.post(url, headers=as_("sub-gina")).json()
    assert body["execution"]["status"] == "blocked"  # sem executor da P1 nada é tentado
    assert body["execution"]["code"] == "executor_unavailable"
