"""HOUSE-03: real REST, SQLite temporal history and ConsumptionEvent contracts.

All devices are simulated; these tests never contact the MCP or physical hardware.
"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.appliance_catalog import ApplianceCatalog
from homemind.contracts.common import inferred
from homemind.contracts.devices import (
    ApplianceCategory,
    ApplianceScope,
    ApplianceSignature,
    Device,
    DeviceKind,
    DeviceRole,
    DeviceSource,
    SignatureOrigin,
    SignaturePattern,
)
from homemind.contracts.energy import (
    ApplianceCandidate,
    ApplianceMatch,
    ConsumptionEvent,
    ConsumptionStatus,
    LocationKind,
)
from homemind.core.access import Grant, HouseholdAccess
from homemind.core.db import Database, migrate
from homemind.features.appliances import repo
from homemind.features.appliances.schemas import ApplianceCreate, AppliancePatch
from homemind.features.households.tests.conftest import (
    EVA,
    HOUSE_B,
    NOW,
    ROOM_B1,
    as_,
    seed_two_houses,
)

pytest_plugins = ("homemind.features.households.tests.conftest",)
A = str(fx.HOUSEHOLD)
BRUNO, CARLA, ANA, OP, LL = ("sub-bruno", "sub-carla", "sub-ana", "sub-operador", "sub-senhorio")


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
        client,
        CARLA,
        name="Chaleira",
        category="kitchen",
        scope="common",
        home_room_id=str(fx.ROOM_SALA),
        typical_watts=None,
    )
    assert kettle.status_code == 201
    assert kettle.json()["ownership"]["owner_resident_id"] is None
    seen = client.get(f"/api/households/{A}/appliances", headers=as_(ANA)).json()
    assert [a["name"] for a in seen] == ["Chaleira"]
    assert (
        client.patch(
            appliance_url(kettle.json()["id"]), json={"name": "Chaleira nova"}, headers=as_(ANA)
        ).status_code
        == 403
    )


def test_house_foreign_key_owner_and_duplicate_validation(client):
    assert make_appliance(client, home_room_id=str(ROOM_B1)).status_code == 422
    assert make_appliance(client, owner_resident_id=str(fx.CARLA)).status_code == 400
    first = make_appliance(client)
    assert first.status_code == 201
    duplicate = make_appliance(client)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "catalog_conflict"
    assert (
        client.get(
            f"/api/households/{HOUSE_B}/appliances/{first.json()['id']}",
            headers=as_("sub-eva"),
        ).status_code
        == 404
    )
    assert client.get(appliance_url(first.json()["id"]), headers=as_("sub-eva")).status_code == 404
    house_b_appliance = client.post(
        f"/api/households/{HOUSE_B}/appliances",
        json={
            "name": "Aquecedor B",
            "category": "heating",
            "scope": "personal",
            "home_room_id": str(ROOM_B1),
            "typical_watts": 1500,
        },
        headers=as_("sub-eva"),
    )
    assert house_b_appliance.status_code == 201, house_b_appliance.text
    assert (
        client.get(
            f"/api/households/{HOUSE_B}/appliances/{house_b_appliance.json()['id']}",
            headers=as_(BRUNO),
        ).status_code
        == 404
    )
    assert (
        client.patch(
            appliance_url(first.json()["id"]),
            json={"owner_resident_id": str(fx.ROOM_SALA)},
            headers=as_(BRUNO),
        ).status_code
        == 422
    )


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
    assert (
        app.state.db.run_sync(lambda c: repo.ownership_at(c, fx.HOUSEHOLD, aid, moved)) == current
    )

    # P1's probabilistic match is NOT an attribution. P4 must use the original
    # event timestamp and independently decide who USED the heater.
    e = ConsumptionEvent(
        id=uuid4(),
        household_id=fx.HOUSEHOLD,
        device_id=uuid4(),
        match=ApplianceMatch(appliance_id=aid, confidence=0.84),
        started_at=before,
        ended_at=before + timedelta(seconds=30),
        status=ConsumptionStatus.closed,
        peak_w=2000,
        energy_wh=500,
        location=LocationKind.common,
        room_id=fx.ROOM_SALA,
        provenance=inferred(),
    )
    catalog = repo.appliance_catalog()
    historical = app.state.db.run_sync(lambda c: catalog.context_for_consumption(c, e))
    assert historical.owner_resident_id == fx.BRUNO
    assert e.match.confidence == 0.84
    assert e.location == LocationKind.common
    assert e.match.appliance_id == aid
    ending_at_boundary = e.model_copy(update={"ended_at": moved})
    starting_at_boundary = e.model_copy(
        update={"started_at": moved, "ended_at": moved + timedelta(seconds=1)}
    )
    assert (
        app.state.db.run_sync(
            lambda c: repo.context_for_consumption(c, ending_at_boundary)
        ).owner_resident_id
        == fx.BRUNO
    )
    assert (
        app.state.db.run_sync(
            lambda c: repo.context_for_consumption(c, starting_at_boundary)
        ).owner_resident_id
        == fx.CARLA
    )

    crossing = e.model_copy(update={"ended_at": moved + timedelta(seconds=1)})
    assert app.state.db.run_sync(lambda c: catalog.context_for_consumption(c, crossing)) is None
    segments = app.state.db.run_sync(
        lambda c: catalog.context_segments_for_consumption(c, crossing)
    )
    assert [(s.started_at, s.ended_at) for s in segments] == [
        (before, moved),
        (moved, moved + timedelta(seconds=1)),
    ]
    assert [s.ownership.owner_resident_id for s in segments] == [fx.BRUNO, fx.CARLA]
    scope_changed_at = moved + timedelta(minutes=10)
    now["value"] = scope_changed_at
    scope_change = client.patch(appliance_url(aid), json={"scope": "common"}, headers=as_(CARLA))
    assert scope_change.status_code == 200, scope_change.text
    scope_crossing = e.model_copy(
        update={
            "started_at": moved + timedelta(seconds=1),
            "ended_at": scope_changed_at + timedelta(seconds=1),
        }
    )
    scope_segments = app.state.db.run_sync(
        lambda c: repo.context_segments_for_consumption(c, scope_crossing)
    )
    assert [segment.ownership.scope.value for segment in scope_segments] == ["personal", "common"]
    assert scope_segments[1].ownership.owner_resident_id is None
    assert app.state.db.run_sync(lambda c: repo.context_for_consumption(c, scope_crossing)) is None

    history = client.get(appliance_url(aid) + "/history", headers=as_(CARLA))
    assert history.status_code == 200
    assert len(history.json()) == 3
    assert history.json()[0]["owner_resident_id"] is None  # previous tenant redacted
    assert history.json()[1]["owner_resident_id"] == str(fx.CARLA)
    assert history.json()[2]["scope"] == "common"
    assert history.json()[2]["owner_resident_id"] is None


def test_sqlite_rejects_overlapping_history_and_allows_adjacent_boundaries(client, app, now):
    heater = make_appliance(client).json()
    aid = heater["id"]
    old = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT * FROM appliance_state WHERE appliance_id = ?", (aid,)
        ).fetchone()
    )
    boundary = NOW + timedelta(minutes=1)

    def close_and_insert(conn):
        conn.execute(
            "UPDATE appliance_state SET valid_to = ? WHERE appliance_id = ? AND valid_to IS NULL",
            (repo.timestamp(boundary), aid),
        )
        conn.execute(
            "INSERT INTO appliance_state (id,appliance_id,household_id,scope,owner_resident_id,"
            "home_room_id,valid_from,valid_to,changed_by_resident_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                aid,
                A,
                old["scope"],
                old["owner_resident_id"],
                old["home_room_id"],
                repo.timestamp(boundary),
                None,
                str(fx.BRUNO),
            ),
        )

    app.state.db.run_sync(close_and_insert)

    with pytest.raises(sqlite3.IntegrityError, match="overlap"):
        app.state.db.run_sync(
            lambda c: c.execute(
                "INSERT INTO appliance_state (id,appliance_id,household_id,scope,owner_resident_id,"
                "home_room_id,valid_from,valid_to,changed_by_resident_id)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    aid,
                    A,
                    old["scope"],
                    old["owner_resident_id"],
                    old["home_room_id"],
                    repo.timestamp(boundary - timedelta(microseconds=1)),
                    repo.timestamp(boundary + timedelta(minutes=1)),
                    str(fx.BRUNO),
                ),
            )
        )


def test_sqlite_rejects_noncanonical_temporal_timestamps(client, app):
    heater = make_appliance(client).json()
    boundary = NOW + timedelta(minutes=1)

    def insert_noncanonical(conn):
        conn.execute(
            "UPDATE appliance_state SET valid_to = ? WHERE appliance_id = ? AND valid_to IS NULL",
            (repo.timestamp(boundary), heater["id"]),
        )
        conn.execute(
            "INSERT INTO appliance_state (id,appliance_id,household_id,scope,owner_resident_id,"
            "home_room_id,valid_from,changed_by_resident_id) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                heater["id"],
                A,
                "personal",
                str(fx.BRUNO),
                str(fx.ROOM_BRUNO),
                (NOW + timedelta(minutes=2)).isoformat(timespec="seconds"),
                str(fx.BRUNO),
            ),
        )

    with pytest.raises(sqlite3.IntegrityError, match="UTC timestamp"):
        app.state.db.run_sync(insert_noncanonical)
    current = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT valid_to FROM appliance_state WHERE appliance_id = ? AND valid_to IS NULL",
            (heater["id"],),
        ).fetchone()
    )
    assert current is not None


def test_failed_context_change_rolls_back_closed_interval(client, app, monkeypatch):
    heater = make_appliance(client).json()
    aid = UUID(heater["id"])
    prior = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT id,valid_to FROM appliance_state WHERE appliance_id = ?", (str(aid),)
        ).fetchone()
    )
    monkeypatch.setattr(repo, "new_id", lambda: UUID(prior["id"]))
    result = client.patch(
        appliance_url(aid),
        json={"owner_resident_id": str(fx.CARLA)},
        headers=as_(BRUNO),
    )
    assert result.status_code == 409
    state = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT id,valid_to FROM appliance_state WHERE appliance_id = ?", (str(aid),)
        ).fetchall()
    )
    assert len(state) == 1
    assert state[0]["id"] == prior["id"]
    assert state[0]["valid_to"] is None


def test_ambiguous_signatures_and_unidentified_appliances(client, app):
    a = make_appliance(client).json()
    b = make_appliance(client, name="Aquecedor B").json()
    aid, bid = UUID(a["id"]), UUID(b["id"])
    assert (
        app.state.db.run_sync(
            lambda c: c.execute(
                "SELECT count(*) FROM appliance_signature WHERE appliance_id = ?", (str(aid),)
            ).fetchone()[0]
        )
        == 0
    )

    def similar(conn):
        for id, appliance, watts in ((str(uuid4()), aid, 1990), (str(uuid4()), bid, 1992)):
            conn.execute(
                "INSERT INTO appliance_signature (id,appliance_id,watts_mean,watts_tolerance,"
                "pattern,samples,origin,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    id,
                    str(appliance),
                    watts,
                    50,
                    "continuous",
                    1,
                    "registered",
                    repo.timestamp(NOW),
                ),
            )

    app.state.db.run_sync(similar)
    ambiguous = ConsumptionEvent(
        id=uuid4(),
        household_id=fx.HOUSEHOLD,
        device_id=uuid4(),
        match=ApplianceMatch(
            candidates=[
                ApplianceCandidate(appliance_id=aid, confidence=0.61),
                ApplianceCandidate(appliance_id=bid, confidence=0.60),
            ]
        ),
        started_at=NOW + timedelta(seconds=1),
        ended_at=NOW + timedelta(minutes=1),
        status=ConsumptionStatus.closed,
        peak_w=2000,
        energy_wh=200,
        location=LocationKind.unknown,
        provenance=inferred(),
    )
    assert app.state.db.run_sync(lambda c: repo.context_for_consumption(c, ambiguous)) is None
    assert (
        app.state.db.run_sync(lambda c: repo.context_segments_for_consumption(c, ambiguous)) == []
    )
    assert ambiguous.match.appliance_id is None


def test_sqlite_adapter_implements_shared_p1_p4_contract():
    assert isinstance(repo.appliance_catalog(), ApplianceCatalog)


def test_p1_signature_catalog_is_house_scoped_and_replay_safe(client, app):
    heater = make_appliance(client).json()
    signature = ApplianceSignature(
        id=uuid4(),
        appliance_id=UUID(heater["id"]),
        watts_mean=2000,
        watts_tolerance=100,
        duration_typical_s=120,
        pattern=SignaturePattern.cyclic,
        typical_hours=[7, 8, 19],
        samples=2,
        origin=SignatureOrigin.learned,
        updated_at=NOW,
    )
    catalog = repo.appliance_catalog()

    def write_and_read(conn):
        catalog.save_appliance_signature(conn, fx.HOUSEHOLD, signature)
        catalog.save_appliance_signature(conn, fx.HOUSEHOLD, signature)
        return catalog.signatures_for_household(conn, fx.HOUSEHOLD)

    signatures = app.state.db.run_sync(write_and_read)
    assert signatures == {signature.appliance_id: [signature]}
    newer = signature.model_copy(update={"samples": 3, "updated_at": NOW + timedelta(minutes=1)})
    app.state.db.run_sync(lambda c: repo.save_appliance_signature(c, fx.HOUSEHOLD, newer))
    app.state.db.run_sync(lambda c: repo.save_appliance_signature(c, fx.HOUSEHOLD, signature))
    assert (
        app.state.db.run_sync(lambda c: repo.signatures_for_household(c, fx.HOUSEHOLD))[
            signature.appliance_id
        ][0].samples
        == 3
    )
    assert app.state.db.run_sync(lambda c: repo.signatures_for_household(c, HOUSE_B)) == {}


def test_multi_appliance_one_meter_and_history(client, app, now):
    one = make_appliance(client).json()
    two = make_appliance(client, name="Computador", category="electronics").json()
    dev = client.post(
        f"/api/households/{A}/devices/demo",
        json={
            "name": "Tomada agregada",
            "kind": "plug",
            "role": "main_meter",
            "source": "fake",
            "room_id": str(fx.ROOM_SALA),
        },
        headers=as_(OP),
    )
    assert dev.status_code == 201, dev.text
    did = dev.json()["id"]
    assert "external_ref" not in dev.json()
    assert client.get(f"/api/households/{A}/devices", headers=as_(BRUNO)).status_code == 403
    assert (
        client.put(
            appliance_url(one["id"]) + "/meter",
            json={"device_id": did},
            headers=as_(BRUNO),
        ).status_code
        == 403
    )
    now["value"] = NOW + timedelta(minutes=1)
    for item in (one, two):
        result = client.put(
            appliance_url(item["id"]) + "/meter",
            json={"device_id": did},
            headers=as_(OP),
        )
        assert result.status_code == 200, result.text
    with pytest.raises(sqlite3.IntegrityError, match="interval overlap"):
        app.state.db.run_sync(
            lambda c: c.execute(
                "INSERT INTO appliance_meter_link (id,appliance_id,device_id,household_id,"
                "valid_from,valid_to,assigned_by_resident_id) VALUES (?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    one["id"],
                    did,
                    A,
                    repo.timestamp(NOW + timedelta(minutes=1, seconds=-1)),
                    repo.timestamp(NOW + timedelta(minutes=1, seconds=1)),
                    str(fx.OPERATOR),
                ),
            )
        )
    device_in_other_house = Device(
        id=uuid4(),
        household_id=HOUSE_B,
        room_id=ROOM_B1,
        name="Medidor B",
        kind=DeviceKind.plug,
        role=DeviceRole.room_meter,
        source=DeviceSource.fake,
    )
    other_device_id = app.state.db.run_sync(
        lambda c: repo.register_device(c, device_in_other_house).id
    )
    rejected_cross_house_meter = client.put(
        appliance_url(one["id"]) + "/meter",
        json={"device_id": str(other_device_id)},
        headers=as_(OP),
    )
    assert rejected_cross_house_meter.status_code == 422
    linked = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT count(*) FROM appliance_meter_link WHERE device_id = ? AND valid_to IS NULL",
            (did,),
        ).fetchone()[0]
    )
    assert linked == 2
    now["value"] = NOW + timedelta(minutes=2)
    assert (
        client.put(
            appliance_url(one["id"]) + "/meter",
            json={"device_id": None},
            headers=as_(OP),
        ).status_code
        == 200
    )
    old_meter = app.state.db.run_sync(
        lambda c: repo.meter_at(
            c, fx.HOUSEHOLD, UUID(one["id"]), NOW + timedelta(minutes=1, seconds=1)
        )
    )
    meter_at_boundary = app.state.db.run_sync(
        lambda c: repo.meter_at(c, fx.HOUSEHOLD, UUID(one["id"]), NOW + timedelta(minutes=2))
    )
    new_meter = app.state.db.run_sync(
        lambda c: repo.meter_at(c, fx.HOUSEHOLD, UUID(one["id"]), NOW + timedelta(minutes=3))
    )
    assert str(old_meter) == did
    assert meter_at_boundary is None
    assert new_meter is None

    now["value"] = NOW + timedelta(minutes=3)
    next_device = client.post(
        f"/api/households/{A}/devices/demo",
        json={
            "name": "Tomada seguinte",
            "kind": "plug",
            "role": "room_meter",
            "source": "fake",
            "room_id": str(fx.ROOM_SALA),
        },
        headers=as_(OP),
    )
    assert next_device.status_code == 201, next_device.text
    assert (
        client.put(
            appliance_url(one["id"]) + "/meter",
            json={"device_id": next_device.json()["id"]},
            headers=as_(OP),
        ).status_code
        == 200
    )
    meter_at_next = app.state.db.run_sync(
        lambda c: repo.meter_at(c, fx.HOUSEHOLD, UUID(one["id"]), NOW + timedelta(minutes=3))
    )
    assert str(meter_at_next) == next_device.json()["id"]
    period = app.state.db.run_sync(
        lambda c: repo.meters_for_period(
            c,
            fx.HOUSEHOLD,
            UUID(one["id"]),
            NOW,
            NOW + timedelta(minutes=4),
        )
    )
    actual_period = [
        (s.started_at, s.ended_at, str(s.device_id) if s.device_id else None) for s in period
    ]
    assert actual_period == [
        (NOW, NOW + timedelta(minutes=1), None),
        (NOW + timedelta(minutes=1), NOW + timedelta(minutes=2), did),
        (NOW + timedelta(minutes=2), NOW + timedelta(minutes=3), None),
        (NOW + timedelta(minutes=3), NOW + timedelta(minutes=4), next_device.json()["id"]),
    ]


def test_same_timestamp_changes_conflict_without_changing_current_state(client, app, now):
    heater = make_appliance(client).json()
    aid = UUID(heater["id"])
    changed_at = NOW + timedelta(minutes=2)
    now["value"] = changed_at
    first = client.patch(
        appliance_url(aid),
        json={"home_room_id": str(fx.ROOM_SALA)},
        headers=as_(BRUNO),
    )
    assert first.status_code == 200
    second = client.patch(
        appliance_url(aid),
        json={"owner_resident_id": str(fx.CARLA)},
        headers=as_(BRUNO),
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "catalog_time_conflict"
    history = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT owner_resident_id,home_room_id,valid_from,valid_to FROM appliance_state"
            " WHERE appliance_id = ? ORDER BY valid_from",
            (str(aid),),
        ).fetchall()
    )
    assert len(history) == 2
    assert history[1]["owner_resident_id"] == str(fx.BRUNO)
    assert history[1]["home_room_id"] == str(fx.ROOM_SALA)
    assert history[1]["valid_from"] == repo.timestamp(changed_at)
    assert history[1]["valid_to"] is None


def test_concurrent_same_timestamp_changes_commit_only_one(client, app):
    heater = make_appliance(client).json()
    access = HouseholdAccess(
        household_id=fx.HOUSEHOLD,
        resident_id=fx.BRUNO,
        membership_id=uuid4(),
        role="tenant",
        room_id=fx.ROOM_BRUNO,
        grant=Grant.own,
    )
    timestamp = NOW + timedelta(minutes=3)

    def change(room):
        try:
            return app.state.db.run_sync(
                lambda c: repo.patch_appliance(
                    c,
                    access,
                    UUID(heater["id"]),
                    AppliancePatch(home_room_id=room),
                    timestamp,
                )
            )
        except repo.CatalogError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, (fx.ROOM_SALA, fx.ROOM_BRUNO)))
    assert sum(isinstance(result, repo.CatalogError) for result in results) == 1
    state = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT count(*) FROM appliance_state WHERE appliance_id = ?", (heater["id"],)
        ).fetchone()[0]
    )
    assert state == 2


def test_foreign_house_resident_cannot_be_written_into_history(client, app):
    heater = make_appliance(client).json()

    def insert_foreign(conn):
        boundary = NOW + timedelta(minutes=1)
        conn.execute(
            "UPDATE appliance_state SET valid_to = ? WHERE appliance_id = ? AND valid_to IS NULL",
            (repo.timestamp(boundary), heater["id"]),
        )
        conn.execute(
            "INSERT INTO appliance_state (id,appliance_id,household_id,scope,owner_resident_id,"
            "home_room_id,valid_from,valid_to,changed_by_resident_id)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                heater["id"],
                A,
                "personal",
                str(EVA),
                str(fx.ROOM_BRUNO),
                repo.timestamp(boundary),
                repo.timestamp(boundary + timedelta(minutes=1)),
                str(fx.BRUNO),
            ),
        )

    with pytest.raises(sqlite3.IntegrityError, match="outside household"):
        app.state.db.run_sync(insert_foreign)


def test_file_database_reopen_preserves_temporal_owner_and_boundaries(tmp_path):
    db = Database(tmp_path / "catalog.sqlite")
    db.open()
    migrate(db)
    db.run_sync(seed_two_houses)
    access = HouseholdAccess(
        household_id=fx.HOUSEHOLD,
        resident_id=fx.BRUNO,
        membership_id=uuid4(),
        role="tenant",
        room_id=fx.ROOM_BRUNO,
        grant=Grant.own,
    )
    appliance = db.run_sync(
        lambda c: repo.create_appliance(
            c,
            access,
            ApplianceCreate(
                name="Persistent heater",
                category=ApplianceCategory.heating,
                scope=ApplianceScope.personal,
                home_room_id=fx.ROOM_BRUNO,
                typical_watts=1000,
            ),
            NOW,
        )
    )
    changed_at = NOW + timedelta(hours=1)
    db.run_sync(
        lambda c: repo.patch_appliance(
            c,
            access,
            appliance.id,
            AppliancePatch(owner_resident_id=fx.CARLA),
            changed_at,
        )
    )
    db.close()

    db.open()
    migrate(db)
    before, at = db.run_sync(
        lambda c: (
            repo.ownership_at(
                c,
                fx.HOUSEHOLD,
                appliance.id,
                changed_at - timedelta(microseconds=1),
            ),
            repo.ownership_at(c, fx.HOUSEHOLD, appliance.id, changed_at),
        )
    )
    assert before.owner_resident_id == fx.BRUNO
    assert at.owner_resident_id == fx.CARLA
    db.close()


def test_retirement_and_ex_member_preserve_history(client, app, now):
    heater = make_appliance(client).json()
    aid = UUID(heater["id"])
    earlier = NOW + timedelta(seconds=1)
    now["value"] = NOW + timedelta(minutes=5)
    retired = client.delete(appliance_url(aid), headers=as_(BRUNO))
    assert retired.status_code == 200
    assert retired.json()["status"] == "retired"
    retired_signature = ApplianceSignature(
        id=uuid4(),
        appliance_id=aid,
        watts_mean=1000,
        watts_tolerance=100,
        pattern=SignaturePattern.continuous,
        origin=SignatureOrigin.learned,
        updated_at=NOW + timedelta(minutes=5),
    )
    with pytest.raises(repo.CatalogError) as error:
        app.state.db.run_sync(
            lambda c: repo.save_appliance_signature(c, fx.HOUSEHOLD, retired_signature)
        )
    assert error.value.code == "appliance_retired"
    history = client.get(appliance_url(aid) + "/history", headers=as_(BRUNO))
    assert history.status_code == 200
    assert history.json()[0]["valid_to"] == "2026-11-17T12:05:00Z"
    crossing_retirement = ConsumptionEvent(
        id=uuid4(),
        household_id=fx.HOUSEHOLD,
        device_id=uuid4(),
        match=ApplianceMatch(appliance_id=aid, confidence=0.95),
        started_at=earlier,
        ended_at=NOW + timedelta(minutes=6),
        status=ConsumptionStatus.closed,
        peak_w=1000,
        energy_wh=100,
        location=LocationKind.unknown,
        provenance=inferred(),
    )
    segments = app.state.db.run_sync(
        lambda c: repo.context_segments_for_consumption(c, crossing_retirement)
    )
    assert segments[0].ownership.owner_resident_id == fx.BRUNO
    assert segments[1].ownership is None
    assert (
        app.state.db.run_sync(lambda c: repo.context_for_consumption(c, crossing_retirement))
        is None
    )
    assert (
        client.patch(appliance_url(aid), json={"name": "Outro"}, headers=as_(BRUNO)).status_code
        == 409
    )
    assert (
        app.state.db.run_sync(
            lambda c: repo.ownership_at(c, fx.HOUSEHOLD, aid, earlier)
        ).owner_resident_id
        == fx.BRUNO
    )
    historical_event = crossing_retirement.model_copy(
        update={"ended_at": earlier + timedelta(seconds=1)}
    )
    assert (
        app.state.db.run_sync(
            lambda c: repo.context_for_consumption(c, historical_event)
        ).owner_resident_id
        == fx.BRUNO
    )
    assert (
        app.state.db.run_sync(lambda c: repo.ownership_at(c, fx.HOUSEHOLD, aid, now["value"]))
        is None
    )

    # End the tenant membership (without deleting any historical catalogue row).
    app.state.db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET status = 'ended', ends_on = '2026-11-17'"
            " WHERE household_id = ? AND resident_id = ?",
            (A, str(fx.BRUNO)),
        )
    )
    now["value"] = NOW + timedelta(days=1)
    assert client.get(appliance_url(aid), headers=as_(BRUNO)).status_code == 404
    assert (
        app.state.db.run_sync(
            lambda c: repo.ownership_at(c, fx.HOUSEHOLD, aid, earlier)
        ).owner_resident_id
        == fx.BRUNO
    )
    assert (
        app.state.db.run_sync(
            lambda c: repo.context_for_consumption(c, historical_event)
        ).owner_resident_id
        == fx.BRUNO
    )


def test_device_external_ref_never_leaves_internal_model(client, app):
    mcp = Device(
        id=uuid4(),
        household_id=fx.HOUSEHOLD,
        name="Medidor MCP",
        kind=DeviceKind.plug,
        role=DeviceRole.main_meter,
        source=DeviceSource.mcp,
        external_ref="private-mcp-id-do-not-expose",
    )
    first = app.state.db.run_sync(lambda c: repo.register_device(c, mcp))
    replay = mcp.model_copy(update={"id": uuid4(), "online": True})
    second = app.state.db.run_sync(lambda c: repo.register_device(c, replay))
    assert second.id == first.id  # MCP identity replay retains the linked internal UUID.
    assert (
        app.state.db.run_sync(
            lambda c: c.execute(
                "SELECT count(*) FROM device WHERE household_id = ? AND source = 'mcp'",
                (A,),
            ).fetchone()[0]
        )
        == 1
    )
    devices = client.get(f"/api/households/{A}/devices", headers=as_(OP))
    assert devices.status_code == 200
    assert "private-mcp-id-do-not-expose" not in devices.text
    assert "external_ref" not in devices.text
    assert (
        client.post(
            f"/api/households/{A}/devices/demo",
            json={"name": "X", "kind": "plug", "role": "main_meter", "source": "mcp"},
            headers=as_(OP),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/households/{A}/devices/demo",
            json={"name": "X", "kind": "plug", "role": "main_meter", "source": "fake"},
            headers=as_(CARLA),
        ).status_code
        == 403
    )


def test_operator_cannot_reassign_owner_or_register_personal_appliance(client):
    assert make_appliance(client, OP).status_code == 403
    heater = make_appliance(client).json()
    assert (
        client.patch(
            appliance_url(heater["id"]),
            json={"owner_resident_id": str(fx.CARLA)},
            headers=as_(OP),
        ).status_code
        == 403
    )


def test_replayed_old_device_discovery_does_not_revert_current_metadata(client, app):
    current = Device(
        id=uuid4(),
        household_id=fx.HOUSEHOLD,
        name="Medidor atual",
        kind=DeviceKind.plug,
        role=DeviceRole.main_meter,
        source=DeviceSource.mcp,
        external_ref="mcp-stable-identity",
        last_seen_at=NOW + timedelta(minutes=2, seconds=1),
        online=True,
    )
    first = app.state.db.run_sync(lambda c: repo.register_device(c, current))
    stale = current.model_copy(
        update={
            "id": uuid4(),
            "name": "Medidor antigo",
            "last_seen_at": NOW + timedelta(minutes=2, seconds=1, microseconds=-1),
            "online": False,
        }
    )
    replayed = app.state.db.run_sync(lambda c: repo.register_device(c, stale))
    assert replayed.id == first.id
    assert replayed.name == "Medidor atual"
    assert replayed.last_seen_at == current.last_seen_at
    assert replayed.online is True
