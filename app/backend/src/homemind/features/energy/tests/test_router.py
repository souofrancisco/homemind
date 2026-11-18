"""Signature REST against real temporary SQLite; no external services."""

import asyncio
from datetime import timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from homemind.contracts import fixtures as fx
from homemind.core.access import get_clock
from homemind.core.errors import register_errors
from homemind.features.appliances import repo
from homemind.features.appliances.schemas import ApplianceCreate
from homemind.features.auth.service import User, current_user
from homemind.features.energy.router import router
from homemind.features.energy.tests.test_learning_consumer import (
    access,
    add_appliance,
    bus_for,
    deliver_session,
    signature,
)
from homemind.features.households.tests.conftest import HOUSE_B, NOW, as_


@pytest.fixture
def client(db):
    app = FastAPI()
    app.state.db = db
    app.include_router(router)
    register_errors(app)

    def user(request: Request):
        return User(sub=request.headers.get("x-test-sub", "unknown"))

    app.dependency_overrides[current_user] = user
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    with TestClient(app) as test_client:
        yield test_client


def url(aid=None, house=fx.HOUSEHOLD):
    base = f"/api/households/{house}/energy/signatures"
    return f"{base}/{aid}" if aid else base


def test_roles_isolation_and_operator_has_no_hours(client, db):
    aid = add_appliance(db)
    asyncio.run(deliver_session(bus_for(db)))
    own = client.get(url(), headers=as_("sub-ana"))
    assert own.status_code == 200 and own.json()[0]["typical_hours"] == [12]
    assert client.get(url(), headers=as_("sub-bruno")).json() == []
    diagnostic = client.get(url(), headers=as_("sub-operador"))
    assert diagnostic.status_code == 200
    assert "typical_hours" not in diagnostic.json()[0]
    for method, path, kwargs in [
        ("get", url(), {}),
        ("patch", url(aid), {"json": {"pattern": "short"}}),
    ]:
        result = getattr(client, method)(path, headers=as_("sub-senhorio"), **kwargs)
        assert result.status_code == 403
    assert (
        client.patch(url(aid), headers=as_("sub-bruno"), json={"pattern": "short"}).status_code
        == 404
    )
    assert (
        client.patch(url(aid), headers=as_("sub-operador"), json={"pattern": "short"}).status_code
        == 403
    )
    assert client.get(url(house=HOUSE_B), headers=as_("sub-ana")).status_code == 404
    assert client.get(url(house=HOUSE_B), headers=as_("sub-bruno")).json() == []


def test_pattern_lock_survives_learning_and_mean_keeps_updating(client, db):
    aid = add_appliance(db)
    asyncio.run(deliver_session(bus_for(db)))
    corrected = client.patch(url(aid), headers=as_("sub-ana"), json={"pattern": "decaying"})
    assert corrected.status_code == 200
    assert corrected.json()["pattern_locked"] and corrected.json()["pattern"] == "decaying"
    asyncio.run(deliver_session(bus_for(db), number=1, watts=2200, cyclic=True))
    sig = signature(db, aid)[0]
    assert sig.pattern.value == "decaying" and sig.samples == 2 and sig.watts_mean == 2100
    assert client.get(url(), headers=as_("sub-ana")).json()[0]["pattern_locked"]


def test_no_signature_and_strict_request_body(client, db):
    aid = add_appliance(db)
    assert (
        client.patch(url(aid), headers=as_("sub-ana"), json={"pattern": "continuous"}).status_code
        == 404
    )
    asyncio.run(deliver_session(bus_for(db)))
    for body in [{"pattern": "invalid"}, {"pattern": "short", "samples": 100}]:
        result = client.patch(url(aid), headers=as_("sub-ana"), json=body)
        assert result.status_code == 400
        assert result.json()["error"]["code"] == "invalid_request"
    assert client.delete(url(aid), headers=as_("sub-ana")).status_code == 405


def test_common_visible_to_tenants_only_author_can_correct(client, db):
    aid = db.run_sync(
        lambda c: repo.create_appliance(
            c,
            access(),
            ApplianceCreate(
                name="Chaleira comum", category="kitchen", scope="common", typical_watts=2000
            ),
            NOW - timedelta(days=1),
        )
    ).id
    asyncio.run(deliver_session(bus_for(db)))
    view = client.get(url(), headers=as_("sub-bruno")).json()
    assert view[0]["appliance_id"] == str(aid) and "typical_hours" in view[0]
    assert (
        client.patch(url(aid), headers=as_("sub-bruno"), json={"pattern": "short"}).status_code
        == 403
    )
    assert (
        client.patch(url(aid), headers=as_("sub-ana"), json={"pattern": "short"}).status_code == 200
    )
