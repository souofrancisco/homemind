"""Ponta a ponta com a app real: evento das fixtures no barramento -> `GET` das notificações ->
resposta -> `notification.responded` na outbox, e a subscrição dos consumidores no lifespan."""

import time

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.notification import NotificationKind, RefType
from homemind.core.events import load_events
from homemind.features.notifications.handlers import CONSUMERS
from homemind.features.notifications.tests.conftest import as_

A = str(fx.HOUSEHOLD)
CARLA, ANA, LANDLORD = "sub-carla", "sub-ana", "sub-senhorio"
URL = f"/api/households/{A}/notifications"


def _wait(predicate, what: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.05)
    raise AssertionError(f"não aconteceu a tempo: {what}")


def _publish(client, ev):
    return client.app.state.bus.publish_threadsafe(ev)


def _list(client, sub, **params):
    r = client.get(URL, headers=as_(sub), params=params)
    assert r.status_code == 200
    return r.json()


def test_o_lifespan_subscreve_os_consumidores(client):
    subs = set(client.app.state.bus._subs)
    assert {c[0] for c in CONSUMERS} <= subs
    assert {
        "notifications.confirmation_needed",
        "notifications.presence_check",
        "notifications.safety_alert",
        "notifications.attribution_changed",
        "notifications.allocation_published",
        "notifications.budget_threshold",  # ALERT-01: BudgetThreshold já traz dono e limite
        "notifications.peak_alert",  # ALERT-03: AlertRaisedData já traz potência e início
        "notifications.cold_room",  # ALERT-06: aviso privado de quarto frio
        "notifications.contestation",  # BILL-06: aberta -> senhorio; decidida -> morador
        "notifications.appliance_identification",  # ENERGY-04
        "notifications.agent_action",  # AGENT-03: «Ação por confirmar», sem botões
    } <= subs


def test_presence_check_do_evento_ate_a_resposta_na_outbox(client):
    req = fx.presence_confirmation()
    _publish(
        client,
        de.PresenceConfirmationNeeded(
            ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=fx.SIM_INFERRED, data=req
        ),
    )
    (item,) = _wait(lambda: _list(client, CARLA, status="unread"), "notificação de Carla")
    assert item["kind"] == "presence_check" and item["can_respond"] is True
    assert [a["id"] for a in item["actions"]] == ["in", "out"]
    assert _list(client, ANA) == []  # pessoal: ninguém mais a vê
    assert _list(client, LANDLORD) == []

    r = client.post(f"{URL}/{item['id']}/respond", json={"action_id": "in"}, headers=as_(CARLA))
    assert r.status_code == 200 and r.json()["status"] == "actioned"

    def responded():
        evs = client.app.state.db.run_sync(
            lambda c: load_events(c, types=["notification.responded"])
        )
        return evs or None

    (stored,) = _wait(responded, "notification.responded")
    data = stored.event.data
    assert (data.ref.type, data.ref.id) == (RefType.presence_check, req.id)
    assert data.response.action_id == "in" and data.response.resident_id == fx.CARLA
    # repetir: 409 e nenhum segundo evento
    again = client.post(
        f"{URL}/{item['id']}/respond", json={"action_id": "out"}, headers=as_(CARLA)
    )
    assert again.status_code == 409


def test_alerta_de_fumo_chega_aos_inquilinos_e_nao_ao_senhorio(client):
    alert = fx.smoke_alert()
    assert alert.notify_landlord
    _publish(
        client,
        de.SafetyAlertRaised(
            ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=alert.provenance, data=alert
        ),
    )
    (item,) = _wait(lambda: _list(client, ANA), "alerta de fumo")
    assert item["kind"] == NotificationKind.security_alert.value
    assert _list(client, LANDLORD) == []
    r = client.post(f"{URL}/{item['id']}/read", headers=as_(LANDLORD))
    assert r.status_code == 404  # escondido, como se não existisse


def test_recibo_publicado_chega_so_ao_dono(client):
    _publish(
        client,
        de.BillingAllocationPublished(
            ts=fx.T0,
            household_id=fx.HOUSEHOLD,
            provenance=fx.SIM_MEASURED,
            data=de.AllocationPublished(
                bill_id=fx.BILL_A,
                allocation_id=fx.bill_a()[1][0].id,
                resident_id=fx.ANA,
            ),
        ),
    )
    (item,) = _wait(lambda: _list(client, ANA), "recibo")
    assert item["kind"] == "info" and item["title"] == "Recibo disponível"
    assert _list(client, CARLA) == []
