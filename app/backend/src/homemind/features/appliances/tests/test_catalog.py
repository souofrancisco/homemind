"""HOUSE-03: real REST, SQLite temporal history and ConsumptionEvent contracts.

All devices are simulated; these tests never contact the MCP or physical hardware.
"""

from datetime import timedelta
from uuid import UUID, uuid4

from homemind.contracts import fixtures as fx
from homemind.contracts.common import inferred
from homemind.contracts.devices import Device, DeviceKind, DeviceRole, DeviceSource
from homemind.contracts.energy import (
    ApplianceCandidate,
    ApplianceMatch,
    ConsumptionEvent,
    ConsumptionStatus,
    LocationKind,
)
from homemind.features.appliances import repo
from homemind.features.households.tests.conftest import HOUSE_B, NOW, ROOM_B1, as_

pytest_plugins = ("homemind.features.households.tests.conftest",)
A = str(fx.HOUSEHOLD)
BRUNO, CARLA, ANA, OP, LL = (
    "sub-bruno", "sub-carla", "sub-ana", "sub-operador", "sub-senhorio"
)


def make_appliance(client, sub=BRUNO, **changes):
    data = {
        "name": "Aquecedor",
        "category": "heating",
        "scope": "personal",
        "home_room_id": str(fx.ROOM_BRUNO),
        "typical_watts": 2000,
    } | changes
    return client.post(f"/api/households/{A}/appliances", json=data, headers=as_(sub))


def appliance_url(id):
    return f"/api/households/{A}/appliances/{id}"


def test_personal_common_isolation_and_operator_redaction(client):
    heater = make_appliance(client)
    assert heater.status_code == 201, heater.text
    obj = heater.json()
    assert obj["ownership"]["owner_resident_id"] == str(fx.BRUNO)
    assert obj["ownership"]["home_room_id"] == str(fx.ROOM_BRUNO)
    assert obj["typical_watts"] == 2000
    assert obj["status"] == "active"
    assert client.get(appliance_url(obj["id"]), headers=as_(BRUNO)).status_code == 200
    assert client.get(appliance_url(obj["id"]), headers=as_(CARLA)).status_code == 404
    assert client.get(appliance_url(obj["id"]), headers=as_(LL)).status_code == 403

    technical = client.get(appliance_url(obj["id"]), headers=as_(OP))
    assert technical.status_code == 200
    assert "ownership" not in technical.json()
    assert "name" not in technical.json()
    assert "registered_by_resident_id" not in technical.json()

    kettle = make_appliance(
        client, CARLA, name="Chaleira", category="kitchen", scope="common",
        home_room_id=str(fx.ROOM_SALA), typical_watts=None,
    )
    assert kettle.status_code == 201
    assert kettle.json()["ownership"]["owner_resident_id"] is None
    seen = client.get(f"/api/households/{A}/appliances", headers=as_(ANA)).json()
    assert [a["name"] for a in seen] == ["Chaleira"]
    assert client.patch(
        appliance_url(kettle.json()["id"]), json={"name": "Chaleira nova"}, headers=as_(ANA)
    ).status_code == 403


def test_house_foreign_key_owner_and_duplicate_validation(client):
    assert make_appliance(client, home_room_id=str(ROOM_B1)).status_code == 422
    assert make_appliance(client, owner_resident_id=str(fx.CARLA)).status_code == 422
    first = make_appliance(client)
    assert first.status_code == 201
    duplicate = make_appliance(client)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "catalog_conflict"
    assert client.get(
        f"/api/households/{HOUSE_B}/appliances/{first.json()['id']}",
        headers=as_("sub-eva"),
    ).status_code == 404
    assert client.get(appliance_url(first.json()["id"]), headers=as_("sub-eva")).status_code == 404
    assert client.patch(
        appliance_url(first.json()["id"]), json={"owner_resident_id": str(fx.ROOM_SALA)},
        headers=as_(BRUNO),
    ).status_code == 422


def test_temporal_owner_and_room_snapshots_for_consumption(client, app, now):
    first = make_appliance(client)
    aid = UUID(first.json()["id"])
    before = NOW + timedelta(seconds=1)
    moved = NOW + timedelta(minutes=10)
    now["value"] = moved
    result = client.patch(
        appliance_url(aid),
        json={"owner_resident_id": str(fx.CARLA), "home_room_id": str(fx.ROOM_SALA)},
        headers=as_(BRUNO),
    )
    assert result.status_code == 200, result.text
    assert result.json()["ownership"]["owner_resident_id"] == str(fx.CARLA)

    def snap(conn):
        old = repo.ownership_at(conn, fx.HOUSEHOLD, aid, before)
        current = repo.ownership_at(conn, fx.HOUSEHOLD, aid, moved)
        return old, current
    old, current = app.state.db.run_sync(snap)
    assert old.owner_resident_id == fx.BRUNO
    assert old.home_room_id == fx.ROOM_BRUNO
    assert current.owner_resident_id == fx.CARLA
    assert current.home_room_id == fx.ROOM_SALA

    # P1's probabilistic match is NOT an attribution. P4 must use the original
    # event timestamp and independently decide who USED the heater.
    e = ConsumptionEvent(
        id=uuid4(), household_id=fx.HOUSEHOLD, device_id=uuid4(),
        match=ApplianceMatch(appliance_id=aid, confidence=0.84),
        started_at=before, ended_at=before + timedelta(seconds=30),
        status=ConsumptionStatus.closed, peak_w=2000, energy_wh=500,
        location=LocationKind.common, room_id=fx.ROOM_SALA,
        provenance=inferred(),
    )
    historical = app.state.db.run_sync(lambda c: repo.context_for_consumption(c, e))
    assert historical.owner_resident_id == fx.BRUNO
    assert e.match.confidence == 0.84
    assert e.location == LocationKind.common
    assert e.match.appliance_id == aid

    history = client.get(appliance_url(aid) + "/history", headers=as_(CARLA))
    assert history.status_code == 200
    assert len(history.json()) == 2
    assert history.json()[0]["owner_resident_id"] is None  # previous tenant redacted
    assert history.json()[1]["owner_resident_id"] == str(fx.CARLA)


def test_ambiguous_signatures_and_unidentified_appliances(client, app):
    a = make_appliance(client).json()
    b = make_appliance(client, name="Aquecedor B").json()
    aid, bid = UUID(a["id"]), UUID(b["id"])
    assert app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT count(*) FROM appliance_signature WHERE appliance_id = ?", (str(aid),)
        ).fetchone()[0]
    ) == 0

    def similar(conn):
        for id, appliance, watts in ((str(uuid4()), aid, 1990), (str(uuid4()), bid, 1992)):
            conn.execute(
                "INSERT INTO appliance_signature (id,appliance_id,watts_mean,watts_tolerance,"
                "pattern,samples,origin,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (id, str(appliance), watts, 50, "continuous", 1, "registered",
                 NOW.isoformat()),
            )
    app.state.db.run_sync(similar)
    ambiguous = ConsumptionEvent(
        id=uuid4(), household_id=fx.HOUSEHOLD, device_id=uuid4(),
        match=ApplianceMatch(candidates=[
            ApplianceCandidate(appliance_id=aid, confidence=0.61),
            ApplianceCandidate(appliance_id=bid, confidence=0.60),
        ]),
        started_at=NOW + timedelta(seconds=1), ended_at=NOW + timedelta(minutes=1),
        status=ConsumptionStatus.closed, peak_w=2000, energy_wh=200,
        location=LocationKind.unknown, provenance=inferred(),
    )
    assert app.state.db.run_sync(
        lambda c: repo.context_for_consumption(c, ambiguous)
    ) is None
    assert ambiguous.match.appliance_id is None


def test_multi_appliance_one_meter_and_history(client, app, now):
    one = make_appliance(client).json()
    two = make_appliance(client, name="Computador", category="electronics").json()
    dev = client.post(
        f"/api/households/{A}/devices/demo",
        json={"name": "Tomada agregada", "kind": "plug", "role": "main_meter", "source": "fake",
              "room_id": str(fx.ROOM_SALA)},
        headers=as_(OP),
    )
    assert dev.status_code == 201, dev.text
    did = dev.json()["id"]
    assert "external_ref" not in dev.json()
    assert client.get(f"/api/households/{A}/devices", headers=as_(BRUNO)).status_code == 403
    assert client.put(
        appliance_url(one["id"]) + "/meter", json={"device_id": did},
        headers=as_(BRUNO),
    ).status_code == 403
    now["value"] = NOW + timedelta(minutes=1)
    for item in (one, two):
        result = client.put(
            appliance_url(item["id"]) + "/meter", json={"device_id": did},
            headers=as_(OP),
        )
        assert result.status_code == 200, result.text
    linked = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT count(*) FROM appliance_meter_link WHERE device_id = ? AND valid_to IS NULL",
            (did,),
        ).fetchone()[0]
    )
    assert linked == 2
    now["value"] = NOW + timedelta(minutes=2)
    assert client.put(
        appliance_url(one["id"]) + "/meter", json={"device_id": None},
        headers=as_(OP),
    ).status_code == 200
    old_meter = app.state.db.run_sync(
        lambda c: repo.meter_at(c, UUID(one["id"]), NOW + timedelta(minutes=1, seconds=1))
    )
    new_meter = app.state.db.run_sync(
        lambda c: repo.meter_at(c, UUID(one["id"]), NOW + timedelta(minutes=3))
    )
    assert str(old_meter) == did
    assert new_meter is None


def test_retirement_and_ex_member_preserve_history(client, app, now):
    heater = make_appliance(client).json()
    aid = UUID(heater["id"])
    earlier = NOW + timedelta(seconds=1)
    now["value"] = NOW + timedelta(minutes=5)
    retired = client.delete(appliance_url(aid), headers=as_(BRUNO))
    assert retired.status_code == 200
    assert retired.json()["status"] == "retired"
    assert client.patch(
        appliance_url(aid), json={"name": "Outro"}, headers=as_(BRUNO)
    ).status_code == 409
    assert app.state.db.run_sync(
        lambda c: repo.ownership_at(c, fx.HOUSEHOLD, aid, earlier)
    ).owner_resident_id == fx.BRUNO
    assert app.state.db.run_sync(
        lambda c: repo.ownership_at(c, fx.HOUSEHOLD, aid, now["value"])
    ) is None

    # End the tenant membership (without deleting any historical catalogue row).
    app.state.db.run_sync(lambda c: c.execute(
        "UPDATE membership SET status = 'ended', ends_on = '2026-11-17'"
        " WHERE household_id = ? AND resident_id = ?",
        (A, str(fx.BRUNO)),
    ))
    now["value"] = NOW + timedelta(days=1)
    assert client.get(appliance_url(aid), headers=as_(BRUNO)).status_code == 404
    assert app.state.db.run_sync(
        lambda c: repo.ownership_at(c, fx.HOUSEHOLD, aid, earlier)
    ).owner_resident_id == fx.BRUNO


def test_device_external_ref_never_leaves_internal_model(client, app):
    mcp = Device(
        id=uuid4(), household_id=fx.HOUSEHOLD, name="Medidor MCP",
        kind=DeviceKind.plug, role=DeviceRole.main_meter,
        source=DeviceSource.mcp, external_ref="private-mcp-id-do-not-expose",
    )
    app.state.db.run_sync(lambda c: repo.register_device(c, mcp))
    devices = client.get(f"/api/households/{A}/devices", headers=as_(OP))
    assert devices.status_code == 200
    assert "private-mcp-id-do-not-expose" not in devices.text
    assert "external_ref" not in devices.text
    assert client.post(
        f"/api/households/{A}/devices/demo",
        json={"name": "X", "kind": "plug", "role": "main_meter", "source": "mcp"},
        headers=as_(OP),
    ).status_code == 403
    assert client.post(
        f"/api/households/{A}/devices/demo",
        json={"name": "X", "kind": "plug", "role": "main_meter", "source": "fake"},
        headers=as_(CARLA),
    ).status_code == 403


def test_operator_cannot_reassign_owner_or_register_personal_appliance(client):
    assert make_appliance(client, OP).status_code == 403
    heater = make_appliance(client).json()
    assert client.patch(
        appliance_url(heater["id"]), json={"owner_resident_id": str(fx.CARLA)},
        headers=as_(OP),
    ).status_code == 403
