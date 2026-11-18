"""AGENT-03b: `agent.safety_suggestion` transforma um alerta de janela em propostas a confirmar.

Sem rede, LLM nem hardware. Prova central: o consumidor só PROPÕE; nunca chama o executor (um
executor falso que falha, registado, fica com zero chamadas) e só `confirm` executa.
"""

import time
from datetime import timedelta
from uuid import UUID

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.agent import DeviceCapability, DeviceCommand
from homemind.contracts.common import Origin, Provenance, ValueKind, new_id
from homemind.contracts.safety import SafetyAlertStatus
from homemind.core.events import load_events
from homemind.features.agent.devices import DIRECTORY_ATTR
from homemind.features.agent.execution import EXECUTOR_ATTR
from homemind.features.agent.safety_consumer import (
    ALERT_RESOLVED,
    RATIONALE,
    SAFETY_CONSUMER,
    action_id_for,
    make_handler,
)
from homemind.features.agent.tests._action_fakes import REAL_PLUG, FakeDirectory, FakeExecutor
from homemind.features.agent.tests.conftest import HOUSE_C, as_

HOUSE_A = fx.HOUSEHOLD
ANA, BRUNO, CARLA, DIOGO = "sub-ana", "sub-bruno", "sub-carla", "sub-diogo"
GINA, HANA, IVO = "sub-gina", "sub-hana", "sub-ivo"
LANDLORD, OPERATOR = "sub-senhorio", "sub-operador"

REAL_INFERRED = Provenance(origin=Origin.real, kind=ValueKind.inferred)


def fresh(app, now, **update):
    """O alerta das fixtures, com o relógio do teste um minuto depois do início (dentro do TTL)."""
    alert = fx.window_alert().model_copy(update=update)
    now["value"] = alert.started_at + timedelta(minutes=1)
    return alert


def publish(app, alert) -> de.SafetyAlertRaised:
    event = de.SafetyAlertRaised(
        ts=alert.resolved_at or alert.started_at,
        household_id=alert.household_id,
        provenance=alert.provenance,
        data=alert,
    )
    app.state.bus.publish_threadsafe(event)
    _wait(
        lambda: app.state.db.run_sync(
            lambda c: c.execute(
                "SELECT 1 FROM processed_event WHERE consumer = ? AND event_id = ?",
                (SAFETY_CONSUMER, str(event.id)),
            ).fetchone()
        ),
        "o consumidor processar o alerta",
    )
    return event


def _wait(predicate, what: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.05)
    raise AssertionError(f"não aconteceu a tempo: {what}")


def rows(app, sql="SELECT * FROM agent_action ORDER BY proposed_for_resident_id", args=()):
    return app.state.db.run_sync(lambda c: c.execute(sql, args).fetchall())


def base(house=HOUSE_A) -> str:
    return f"/api/households/{house}/agent"


def mine(client, sub, house=HOUSE_A):
    r = client.get(f"{base(house)}/actions", headers=as_(sub))
    assert r.status_code == 200, r.text
    return r.json()


def act(client, sub, action_id, verb, house=HOUSE_A):
    return client.post(f"{base(house)}/actions/{action_id}/{verb}", headers=as_(sub))


@pytest.fixture(autouse=True)
def clean_state(app):
    """A app é partilhada entre testes: nada do que um registou (diretório, executor, executor
    simulado com o relógio dele) pode ficar para o seguinte."""

    def clear():
        for attr in (DIRECTORY_ATTR, EXECUTOR_ATTR, "agent_simulated_executor"):
            if hasattr(app.state, attr):
                delattr(app.state, attr)

    clear()
    yield
    clear()


@pytest.fixture
def failing_executor(app, now):
    ex = FakeExecutor(lambda: now["value"], "raise")
    setattr(app.state, EXECUTOR_ATTR, ex)
    return ex


# --- propor ---------------------------------------------------------------------------------


def test_o_consumidor_esta_subscrito(app):
    assert SAFETY_CONSUMER == "agent.safety_suggestion"
    assert SAFETY_CONSUMER in app.state.bus._subs


def test_zona_comum_propoe_a_cada_inquilino_ativo_simulada(app, client, now, failing_executor):
    alert = fresh(app, now)
    publish(app, alert)
    got = rows(app)
    assert len(got) == 4  # Ana, Bruno, Carla e Diogo; nunca o senhorio nem o operador
    assert {UUID(r["proposed_for_resident_id"]) for r in got} == {
        fx.ANA,
        fx.BRUNO,
        fx.CARLA,
        fx.DIOGO,
    }
    for r in got:
        assert r["status"] == "proposed" and r["source"] == "safety"
        assert r["origin"] == "simulated" and r["target_device_id"] == str(fx.METER)
        assert r["capability"] == "power"
        assert UUID(r["id"]) == action_id_for(alert.id, UUID(r["proposed_for_resident_id"]))
    events = app.state.db.run_sync(lambda c: load_events(c, types=["agent.action_proposed"]))
    assert len(events) == 4
    assert {e.event.data.rationale for e in events} == {RATIONALE} and len(RATIONALE) <= 300
    assert all(e.event.provenance.origin is Origin.simulated for e in events)
    # cada um vê só a sua, SIMULADA e por confirmar; senhorio e operador não têm acesso
    (view,) = mine(client, ANA)
    assert view["action"]["status"] == "proposed" and view["origin"] == "simulated"
    assert "SIMULADO" in view["message"] and view["execution"] is None
    cmd = view["action"]["command"]
    assert cmd["target_device_id"] == str(fx.METER) and cmd["power"] is False
    for sub in (LANDLORD, OPERATOR):
        assert client.get(f"{base()}/actions", headers=as_(sub)).status_code == 403
    assert failing_executor.calls == []  # propor nunca executa


def test_quarto_so_propoe_aos_inquilinos_do_quarto(app, now):
    publish(app, fresh(app, now, room_id=fx.ROOM_BRUNO))
    (r,) = rows(app)
    assert UUID(r["proposed_for_resident_id"]) == fx.BRUNO


def test_membership_terminada_nao_recebe(app, now):
    app.state.db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET status = 'ended', ends_on = '2026-11-01'"
            " WHERE resident_id = ? AND household_id = ?",
            (str(fx.DIOGO), str(HOUSE_A)),
        )
    )
    publish(app, fresh(app, now))
    assert {UUID(r["proposed_for_resident_id"]) for r in rows(app)} == {fx.ANA, fx.BRUNO, fx.CARLA}


def test_reprocessar_nao_duplica(app, now):
    alert = fresh(app, now)
    event = publish(app, alert)
    publish(app, alert)  # outro evento, o mesmo alerta
    assert len(rows(app)) == 4
    # o mesmo evento chamado duas vezes diretamente, fora do `processed_event`
    handler = make_handler(app, lambda: now["value"])
    stored = app.state.db.run_sync(lambda c: load_events(c, types=["safety.alert_raised"]))[0]
    assert stored.event.id == event.id

    def again(conn):
        return handler(conn, stored), handler(conn, stored)

    first, second = app.state.db.run_sync(again)
    assert first == [] and second == []
    assert len(rows(app)) == 4
    assert (
        len(app.state.db.run_sync(lambda c: load_events(c, types=["agent.action_proposed"]))) == 4
    )


def test_alerta_alem_do_ttl_nao_propoe(app, now):
    alert = fresh(app, now)
    now["value"] = alert.started_at + timedelta(seconds=601)
    publish(app, alert)
    assert rows(app) == []


def test_alerta_no_limite_do_ttl_ainda_propoe(app, now):
    alert = fresh(app, now)
    now["value"] = alert.started_at + timedelta(seconds=600)
    publish(app, alert)
    assert len(rows(app)) == 4


def test_fumo_nunca_propoe(app, now):
    alert = fx.smoke_alert()
    now["value"] = alert.started_at + timedelta(seconds=30)
    publish(app, alert)
    assert rows(app) == []


def test_sem_comando_sugerido_nao_propoe(app, now):
    publish(app, fresh(app, now, suggested_command=None))
    assert rows(app) == []


def test_sem_quarto_nao_propoe(app, now):
    publish(app, fresh(app, now, room_id=None))
    assert rows(app) == []


def test_dispositivo_fora_do_diretorio_nao_propoe(app, now):
    other = DeviceCommand(target_device_id=new_id(), capability=DeviceCapability.power, power=False)
    publish(app, fresh(app, now, suggested_command=other))
    assert rows(app) == []


def test_lampada_nao_e_tomada_nao_propoe(app, now):
    lamp = DeviceCommand(target_device_id=fx.LAMP, capability=DeviceCapability.power, power=False)
    publish(app, fresh(app, now, suggested_command=lamp))
    assert rows(app) == []


def test_casa_real_sem_diretorio_nao_propoe(app, real_house, now):
    alert = real_alert(now)
    publish(app, alert)
    assert rows(app) == []


def real_alert(now, **update):
    from homemind.contracts.common import stable_id

    alert = fx.window_alert().model_copy(
        update={
            "id": stable_id("safety", "janela-c"),
            "household_id": HOUSE_C,
            "room_id": stable_id("room", "c1"),
            "sensor_device_id": None,
            "provenance": REAL_INFERRED,
            "suggested_command": DeviceCommand(
                target_device_id=REAL_PLUG.id, capability=DeviceCapability.power, power=False
            ),
            **update,
        }
    )
    now["value"] = alert.started_at + timedelta(minutes=1)
    return alert


def test_casa_real_com_diretorio_propoe_real_so_aos_do_quarto(app, real_house, now):
    setattr(app.state, DIRECTORY_ATTR, FakeDirectory([REAL_PLUG]))
    publish(app, real_alert(now))
    (r,) = rows(app)
    assert r["origin"] == "real" and r["source"] == "safety"
    assert UUID(r["proposed_for_resident_id"]) == UUID(
        rows(
            app,
            "SELECT resident_id FROM membership WHERE household_id = ? AND room_id IS NOT NULL"
            " AND resident_id IN (SELECT id FROM resident WHERE auth_subject = 'sub-gina')",
            (str(HOUSE_C),),
        )[0]["resident_id"]
    )


# --- resolver -------------------------------------------------------------------------------


def resolve(alert, now, at):
    resolved = alert.model_copy(update={"status": SafetyAlertStatus.resolved, "resolved_at": at})
    now["value"] = at
    return resolved


def test_alerta_resolvido_rejeita_as_abertas_e_a_confirmacao_seguinte_da_409(
    app, client, now, failing_executor
):
    alert = fresh(app, now)
    publish(app, alert)
    (view,) = mine(client, ANA)
    aid = view["action"]["id"]
    publish(app, resolve(alert, now, alert.started_at + timedelta(minutes=2)))
    assert {r["status"] for r in rows(app)} == {"rejected"}
    log = rows(
        app,
        "SELECT * FROM agent_action_log WHERE to_status = 'rejected' ORDER BY seq",
    )
    assert len(log) == 4
    assert all(r["by_resident_id"] is None and r["code"] == ALERT_RESOLVED for r in log)
    assert all(r["from_status"] == "proposed" for r in log)
    r = act(client, ANA, aid, "confirm")
    assert r.status_code == 409 and r.json()["error"]["code"] == "action_not_pending"
    assert failing_executor.calls == []
    (after,) = mine(client, ANA)
    assert after["action"]["status"] == "rejected"


def test_resolvido_nao_toca_numa_ja_confirmada(app, client, now):
    alert = fresh(app, now)
    publish(app, alert)
    (view,) = mine(client, ANA)
    assert act(client, ANA, view["action"]["id"], "confirm").status_code == 200
    publish(app, resolve(alert, now, alert.started_at + timedelta(minutes=2)))
    by = {UUID(r["proposed_for_resident_id"]): r["status"] for r in rows(app)}
    assert by[fx.ANA] == "executed" and by[fx.BRUNO] == "rejected"


def test_resolvido_sem_propostas_nao_faz_nada(app, now):
    alert = fresh(app, now)
    publish(app, resolve(alert, now, alert.started_at + timedelta(minutes=2)))
    assert rows(app) == []


def test_resolvido_nao_rejeita_uma_proposta_ja_expirada(app, client, now):
    alert = fresh(app, now)
    publish(app, alert)
    publish(app, resolve(alert, now, alert.started_at + timedelta(hours=1)))
    assert {r["status"] for r in rows(app)} == {"proposed"}  # expirou: continua `expired` derivado
    (view,) = mine(client, ANA)
    assert view["action"]["status"] == "expired"


# --- e2e e execução -------------------------------------------------------------------------


def test_confirmar_na_casa_demo_usa_o_executor_simulado(app, client, now, failing_executor):
    publish(app, fresh(app, now))
    (view,) = mine(client, ANA)
    r = act(client, ANA, view["action"]["id"], "confirm")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["origin"] == "simulated" and "SIMULADO" in body["message"]
    assert body["execution"]["status"] == "confirmed"
    assert body["execution"]["readback_confirmed"] is True
    assert failing_executor.calls == []  # o registado nunca é usado numa casa demo
    assert act(client, ANA, view["action"]["id"], "confirm").status_code == 409  # uma vez só


def test_o_handler_nunca_chama_o_executor_numa_casa_real(app, real_house, client, now):
    ex = FakeExecutor(lambda: now["value"], "raise")
    setattr(app.state, EXECUTOR_ATTR, ex)
    setattr(app.state, DIRECTORY_ATTR, FakeDirectory([REAL_PLUG]))
    publish(app, real_alert(now))
    assert ex.calls == []  # propor não executa
    (view,) = mine(client, GINA, HOUSE_C)
    assert view["action"]["status"] == "proposed" and view["origin"] == "real"
    # só a confirmação humana executa, e uma única vez (aqui o executor falha: incerto)
    r = act(client, GINA, view["action"]["id"], "confirm", HOUSE_C)
    assert r.status_code == 200 and r.json()["execution"]["status"] == "uncertain"
    assert len(ex.calls) == 1
    assert act(client, GINA, view["action"]["id"], "confirm", HOUSE_C).status_code == 409
    assert len(ex.calls) == 1


def test_hana_nao_recebe_a_proposta_do_quarto_da_gina(app, real_house, client, now):
    setattr(app.state, DIRECTORY_ATTR, FakeDirectory([REAL_PLUG]))
    publish(app, real_alert(now))
    assert len(mine(client, GINA, HOUSE_C)) == 1
    assert mine(client, HANA, HOUSE_C) == []
    assert client.get(f"{base(HOUSE_C)}/actions", headers=as_(IVO)).status_code == 403
