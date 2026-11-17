"""Testes de segurança do diagnóstico DEMO-02; NÃO são E2E do produto."""

from datetime import date

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts import household as hh
from homemind.contracts.common import stable_id
from homemind.core.access import get_clock
from homemind.core.events import append_event
from homemind.features.auth.service import User, current_user
from homemind.features.households.repo import (
    insert_household,
    insert_membership,
    seed_demo,
)
from homemind.main import app

BASE = f"/api/households/{fx.HOUSEHOLD}/integration/traces/{fx.CORRELATION}"
OPERATOR = {"x-test-sub": "sub-operador"}


@pytest.fixture
def client():
    def user(request: Request) -> User:
        sub = request.headers.get("x-test-sub")
        if not sub:
            raise HTTPException(401, "Não autenticado")
        return User(sub=sub)

    app.dependency_overrides[current_user] = user
    app.dependency_overrides[get_clock] = lambda: lambda: fx.T0
    try:
        with TestClient(app) as c:
            app.state.db.run_sync(seed_demo)
            yield c
    finally:
        app.dependency_overrides.clear()


def test_empty_trace_is_truthfully_empty(client):
    response = client.get(BASE, headers=OPERATOR)
    assert response.status_code == 200
    assert response.json() == {
        "correlation_id": str(fx.CORRELATION),
        "source_kind": "demo",
        "evidence_level": "persisted_events_only",
        "events": [],
    }


def test_trace_reads_persisted_events_without_payload_or_writes(client):
    event = de.EnergyReadingRecorded(
        id=stable_id("demo-02", "reading"),
        household_id=fx.HOUSEHOLD,
        correlation_id=fx.CORRELATION,
        ts=fx.T0,
        provenance=fx.SIM_MEASURED,
        data=fx.reading(),
    )

    def store_twice(conn):
        first = append_event(conn, event)
        second = append_event(conn, event)
        assert first.seq == second.seq

    app.state.db.run_sync(store_twice)
    before = app.state.db.run_sync(
        lambda c: c.execute("SELECT COUNT(*) FROM domain_event").fetchone()[0]
    )
    response = client.get(BASE, headers=OPERATOR)
    after = app.state.db.run_sync(
        lambda c: c.execute("SELECT COUNT(*) FROM domain_event").fetchone()[0]
    )
    assert response.status_code == 200
    assert before == after == 1
    assert response.json()["events"][0]["phase"] == "reading"
    assert response.json()["events"][0]["origin"] == "simulated"
    assert response.json()["events"][0]["kind"] == "measured"
    assert len(response.json()["events"]) == 1
    # Nunca devolver o payload, o identificador externo do MCP ou campos pessoais.
    assert "payload_json" not in response.text
    assert "device_id" not in response.text
    assert "resident_id" not in response.text


def test_role_and_household_isolation(client):
    assert client.get(BASE).status_code == 401
    for sub in ("sub-ana", "sub-carla", "sub-senhorio"):
        assert client.get(BASE, headers={"x-test-sub": sub}).status_code == 403
    # A Eva não é membro desta casa, nem interessa revelar se ela existe.
    assert client.get(BASE, headers={"x-test-sub": "sub-eva"}).status_code == 404


def test_real_house_is_never_traceable(client):
    real_id = stable_id("household", "real-demo02")

    def seed(conn):
        insert_household(
            conn,
            hh.Household(
                id=real_id,
                name="Casa real",
                settings=hh.HouseholdSettings(source_kind=hh.SourceKind.real),
                created_at=fx.T0,
            ),
        )
        insert_membership(
            conn,
            hh.Membership(
                id=stable_id("membership", "real-demo02-operator"),
                household_id=real_id,
                resident_id=fx.OPERATOR,
                role=hh.MembershipRole.operator,
                starts_on=date(2026, 9, 1),
                status=hh.MembershipStatus.active,
            ),
        )

    app.state.db.run_sync(seed)
    response = client.get(
        f"/api/households/{real_id}/integration/traces/{fx.CORRELATION}",
        headers=OPERATOR,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "demo_only"
