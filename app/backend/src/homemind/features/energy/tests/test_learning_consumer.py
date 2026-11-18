"""Real SQLite and bus deliveries; fixed times and simulated data only."""

import asyncio
from datetime import timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.domain_events import (
    EnergyConsumptionClosed,
    EnergyConsumptionDetected,
    EnergyReadingRecorded,
)
from homemind.core.access import Grant, HouseholdAccess
from homemind.core.events import EventBus
from homemind.features.appliances import repo
from homemind.features.appliances.schemas import ApplianceCreate
from homemind.features.energy.learning_consumer import INPUT_TYPES, make_learning_consumer
from homemind.features.households.tests.conftest import HOUSE_B, NOW


def access(house=fx.HOUSEHOLD, actor=fx.ANA):
    return HouseholdAccess(house, actor, stable_id("test", "membership"), "tenant", None, Grant.own)


def add_appliance(db, name="Aquecedor Ana", watts=2000, house=fx.HOUSEHOLD, actor=fx.ANA):
    return db.run_sync(
        lambda c: repo.create_appliance(
            c,
            access(house, actor),
            ApplianceCreate(name=name, category="heating", scope="personal", typical_watts=watts),
            fx.T0 - timedelta(days=1),
        )
    ).id


async def deliver_session(bus, *, number=0, watts=2000, cyclic=False, house=fx.HOUSEHOLD):
    start = NOW + timedelta(days=number)
    session = replace(
        fx.consumption(),
        id=stable_id("learning-session", str(number), str(house)),
        household_id=house,
        started_at=start,
        ended_at=None,
        status="ongoing",
        peak_w=watts,
        match={"candidates": []},
        appliance_owner_resident_id=None,
        cost_estimate=None,
    )
    series = [
        (0, watts + 100),
        (3600, 100 if cyclic else watts + 100),
        (5400, watts + 100),
        (10800, 100),
    ]
    # Opening reading precedes detection, as in ENERGY-02.
    for i, (seconds, power) in enumerate(series):
        at = start + timedelta(seconds=seconds)
        r = replace(
            fx.reading(power, at),
            device_id=session.device_id,
            id=stable_id(str(session.id), str(seconds)),
        )
        event = EnergyReadingRecorded(ts=at, household_id=house, provenance=r.provenance, data=r)
        await bus.deliver("energy.learning", await bus.publish(event))
        if i == 0:
            detected = EnergyConsumptionDetected(
                ts=at, household_id=house, provenance=session.provenance, data=session
            )
            await bus.deliver("energy.learning", await bus.publish(detected))
    closed = replace(session, status="closed", ended_at=start + timedelta(hours=3), energy_wh=5000)
    event = EnergyConsumptionClosed(
        ts=closed.ended_at, household_id=house, provenance=closed.provenance, data=closed
    )
    stored = await bus.publish(event)
    await bus.deliver("energy.learning", stored)
    return stored


def bus_for(db, catalog=None):
    bus = EventBus(db)
    bus.subscribe(
        "energy.learning", make_learning_consumer(catalog or repo.appliance_catalog()), INPUT_TYPES
    )
    return bus


def signature(db, aid):
    return db.run_sync(lambda c: repo.signatures_for_household(c, fx.HOUSEHOLD)).get(aid, [])


def test_link_three_sessions_local_hours_and_duplicate_delivery(db):
    aid = add_appliance(db, watts=None)
    device = replace(fx.meter(), id=fx.consumption().device_id)

    def setup(c):
        repo.register_device(c, device)
        c.execute(
            "INSERT INTO appliance_meter_link VALUES (?,?,?,?,?,?,?)",
            (
                str(stable_id("learning-link")),
                str(aid),
                str(device.id),
                str(fx.HOUSEHOLD),
                repo.timestamp(fx.T0 - timedelta(days=1)),
                None,
                str(fx.ANA),
            ),
        )
        c.execute("UPDATE household SET timezone='Asia/Tokyo' WHERE id=?", (str(fx.HOUSEHOLD),))

    db.run_sync(setup)

    async def run():
        bus = bus_for(db)
        for n, w in enumerate([1800, 2000, 2200]):
            closed = await deliver_session(bus, number=n, watts=w, cyclic=n < 2)
            assert await bus.deliver("energy.learning", closed) is False
        learned = signature(db, aid)[0]
        assert learned.samples == 3 and learned.watts_mean == 2000
        assert learned.pattern.value == "cyclic" and learned.typical_hours == [21]
        assert learned.origin.value == "learned"

    asyncio.run(run())


def test_unique_power_then_ambiguous_and_no_evidence(db):
    aid = add_appliance(db)

    async def run():
        bus = bus_for(db)
        await deliver_session(bus)
        assert signature(db, aid)[0].samples == 1
        other = add_appliance(db, name="Chaleira Bruno", actor=fx.BRUNO)
        await deliver_session(bus, number=1)
        assert signature(db, aid)[0].samples == 1 and not signature(db, other)
        await deliver_session(bus, number=2, watts=900)
        assert signature(db, aid)[0].samples == 1

    asyncio.run(run())


def test_other_house_and_missing_registered_power_do_not_learn(db):
    aid = add_appliance(db, watts=None)
    add_appliance(db, house=HOUSE_B, actor=fx.BRUNO)
    asyncio.run(deliver_session(bus_for(db)))
    assert not signature(db, aid)


def test_recovery_after_restart_and_rollback(db):
    aid = add_appliance(db)

    class FailsOnce(repo.SqliteApplianceCatalog):
        failed = False

        def save_appliance_signature(self, conn, household_id, sig):
            super().save_appliance_signature(conn, household_id, sig)
            if not self.failed:
                self.failed = True
                raise RuntimeError("injected rollback")

    async def run():
        bus = bus_for(db, FailsOnce())
        with pytest.raises(RuntimeError):
            await deliver_session(bus)
        assert not signature(db, aid)
        from homemind.core.events import load_events

        closed = db.run_sync(lambda c: load_events(c, types=["energy.consumption_closed"]))[0]
        # A fresh handler has no in-memory readings; recovery uses the committed log.
        assert await bus_for(db).deliver("energy.learning", closed)
        assert signature(db, aid)[0].samples == 1

    asyncio.run(run())


def test_retired_appliance_is_ignored_without_stats(db):
    aid = add_appliance(db)
    db.run_sync(
        lambda c: repo.retire_appliance(
            c,
            access(),
            aid,
            NOW + timedelta(hours=1),
        )
    )
    # It was active at session start, but persistence rejects its current retirement.
    asyncio.run(deliver_session(bus_for(db)))
    for table in ("appliance_signature", "energy_signature_stats"):
        assert (
            db.run_sync(
                lambda c, table=table: c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            )
            == 0
        )


def test_late_session_counts_without_stats_divergence(db):
    aid = add_appliance(db)

    async def run():
        bus = bus_for(db)
        await deliver_session(bus, number=2, watts=2200)
        await deliver_session(bus, number=0, watts=1800, cyclic=True)
        sig = signature(db, aid)[0]
        assert sig.samples == 2 and sig.watts_mean == 2000
        assert sig.updated_at == NOW + timedelta(hours=3)
        assert (
            db.run_sync(
                lambda c: c.execute(
                    "SELECT sum(count) FROM energy_signature_stats WHERE signature_id=?",
                    (str(sig.id),),
                ).fetchone()[0]
            )
            == 2
        )

    asyncio.run(run())
