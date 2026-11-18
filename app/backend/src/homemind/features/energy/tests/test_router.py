"""Runtime: leituras publicadas no barramento real viram sessões; RBAC da leitura."""

import time

import pytest

from homemind.core.events import append_event
from homemind.demo.scenario import events as scenario_events

URL = "/api/households/{}/energy/overview"


def _house():
    from homemind.contracts import fixtures as fx

    return str(fx.HOUSEHOLD)


def _publish_readings(app):
    bus = app.state.bus
    readings = [e for e in scenario_events() if e.type == "energy.reading_recorded"]
    for e in readings:
        app.state.db.run_sync(lambda c, e=e: append_event(c, e))
    bus._loop.call_soon_threadsafe(bus._wake)


def _wait_sessions(client, sub, expected_min=1, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(URL.format(_house()), headers={"x-test-sub": sub})
        if r.status_code == 200 and len(r.json()["sessions"]) >= expected_min:
            return r.json()
        time.sleep(0.1)
    return client.get(URL.format(_house()), headers={"x-test-sub": sub}).json()


def test_tenant_sees_meter_and_sessions_unidentified(app, client):
    _publish_readings(app)
    body = _wait_sessions(client, "sub-ana")
    assert body["meters"], "última leitura por tomada"
    assert body["sessions"], "o consumidor corre no runtime"
    # Sem assinatura no catálogo, nada é identificado nem tem custo inventado.
    assert all(s["appliance_id"] is None and s["cost_cents"] is None for s in body["sessions"])
    assert all(s["provenance"]["origin"] == "simulated" for s in body["sessions"])


@pytest.mark.parametrize("sub", ["sub-senhorio", "sub-operador"])
def test_landlord_and_operator_never_get_readings(app, client, sub):
    _publish_readings(app)
    r = client.get(URL.format(_house()), headers={"x-test-sub": sub})
    assert r.status_code == 403
    assert "meters" not in r.text


def test_other_household_is_denied(app, client):
    from homemind.features.households.tests.conftest import HOUSE_B

    r = client.get(URL.format(HOUSE_B), headers={"x-test-sub": "sub-ana"})
    assert r.status_code in (403, 404)


def test_unauthenticated(client):
    assert client.get(URL.format(_house())).status_code == 401


def test_catalog_vem_de_app_state_sem_import_cruzado(app):
    assert app.state.appliance_catalog is not None
