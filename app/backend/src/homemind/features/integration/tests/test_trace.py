"""Testes de segurança do diagnóstico DEMO-02; NÃO são E2E do produto."""

from datetime import date

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts import household as hh
from homemind.contracts.common import stable_id
from homemind.contracts.domain_events import (
    NotificationResponded,
    NotificationRespondedData,
)
from homemind.contracts.notification import (
    ConfirmationOutcome,
    ConfirmationVerdict,
    NotificationRef,
    NotificationResponse,
    RefType,
)
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
        "missing_event_types": sorted(
            (
                "energy.reading_recorded",
                "energy.step_detected",
                "energy.consumption_detected",
                "energy.consumption_closed",
                "billing.confirmation_needed",
                "notification.created",
                "notification.responded",
                "billing.attribution_changed",
                "alerts.threshold_crossed",
                "billing.bill_created",
                "billing.bill_finalized",
                "billing.allocation_published",
            )
        ),
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
    before = app.state.db.run_sync(lambda c: c.total_changes)
    response = client.get(BASE, headers=OPERATOR)
    after = app.state.db.run_sync(lambda c: c.total_changes)
    assert response.status_code == 200
    assert before == after
    assert response.json()["events"][0]["phase"] == "reading_persisted"
    assert "energy.reading_recorded" not in response.json()["missing_event_types"]
    assert "billing.bill_finalized" in response.json()["missing_event_types"]
    assert response.json()["events"][0]["origin"] == "simulated"
    assert response.json()["events"][0]["kind"] == "measured"
    assert len(response.json()["events"]) == 1
    # Nunca devolver o payload, o identificador externo do MCP ou campos pessoais.
    assert "payload_json" not in response.text
    assert "device_id" not in response.text
    assert "resident_id" not in response.text


def test_trace_shows_real_bill_draft_event_without_claiming_finalization(client):
    bill = {
        "period": {"start": "2026-10-01", "end": "2026-10-31"},
        "total_cents": 12_000,
        "fixed_cents": 2_400,
        "total_wh": 600_000,
        "price_millicents_per_kwh": 16_000,
        "origin": "simulated",
    }
    created = client.post(
        f"/api/households/{fx.HOUSEHOLD}/bills",
        json=bill,
        headers={"x-test-sub": "sub-senhorio"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"

    correlation_id = app.state.db.run_sync(
        lambda conn: conn.execute(
            "SELECT correlation_id FROM domain_event WHERE type = 'billing.bill_created'"
        ).fetchone()[0]
    )
    trace = client.get(
        f"/api/households/{fx.HOUSEHOLD}/integration/traces/{correlation_id}",
        headers=OPERATOR,
    )
    assert trace.status_code == 200
    body = trace.json()
    assert [event["event_type"] for event in body["events"]] == ["billing.bill_created"]
    assert body["events"][0]["phase"] == "bill_recorded"
    assert "billing.bill_created" not in body["missing_event_types"]
    assert "billing.bill_finalized" in body["missing_event_types"]


def test_trace_does_not_mix_correlation_ids(client):
    other_correlation = stable_id("demo-02", "other-correlation")
    event = de.EnergyReadingRecorded(
        id=stable_id("demo-02", "other-reading"),
        household_id=fx.HOUSEHOLD,
        correlation_id=other_correlation,
        ts=fx.T0,
        provenance=fx.SIM_MEASURED,
        data=fx.reading(),
    )
    other_household = stable_id("household", "other-demo")

    def seed_other_house(conn):
        insert_household(
            conn,
            hh.Household(
                id=other_household,
                name="Outra casa demo",
                settings=hh.HouseholdSettings(source_kind=hh.SourceKind.demo),
                created_at=fx.T0,
            ),
        )
        insert_membership(
            conn,
            hh.Membership(
                id=stable_id("membership", "other-demo-operator"),
                household_id=other_household,
                resident_id=fx.OPERATOR,
                role=hh.MembershipRole.operator,
                starts_on=date(2026, 9, 1),
                status=hh.MembershipStatus.active,
            ),
        )
        append_event(conn, event)
        append_event(
            conn,
            de.EnergyReadingRecorded(
                id=stable_id("demo-02", "other-house-reading"),
                household_id=other_household,
                correlation_id=fx.CORRELATION,
                ts=fx.T0,
                provenance=fx.SIM_MEASURED,
                data=fx.reading(),
            ),
        )

    app.state.db.run_sync(seed_other_house)

    response = client.get(BASE, headers=OPERATOR)

    assert response.status_code == 200
    assert response.json()["events"] == []
    assert "energy.reading_recorded" in response.json()["missing_event_types"]


def test_trace_does_not_expose_confirmation_vote_payload(client):
    event = NotificationResponded(
        id=stable_id("demo-02", "private-vote"),
        ts=fx.T0,
        household_id=fx.HOUSEHOLD,
        correlation_id=fx.CORRELATION,
        provenance=fx.SIM_MEASURED,
        data=NotificationRespondedData(
            response=NotificationResponse(
                notification_id=fx.NOTIFICATION,
                action_id="mine",
                resident_id=fx.CARLA,
                responded_at=fx.T0,
            ),
            ref=NotificationRef(type=RefType.consumption_event, id=fx.CONSUMPTION),
            outcome=ConfirmationOutcome(
                verdict=ConfirmationVerdict.self_claimed,
                resident_id=fx.CARLA,
                votes=1,
                votes_needed=2,
            ),
        ),
    )
    app.state.db.run_sync(lambda conn: append_event(conn, event))

    response = client.get(BASE, headers=OPERATOR)

    assert response.status_code == 200
    body = response.json()
    assert body["events"][0]["phase"] == "response_persisted"
    assert "self_claimed" not in response.text
    assert str(fx.CARLA) not in response.text
    assert str(fx.CONSUMPTION) not in response.text


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
