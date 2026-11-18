"""SAFE-02: estado AWAY SIMULADO de `presence.occupancy_changed`. Relógio = ts do evento."""

import asyncio

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind
from homemind.contracts.presence import HouseOccupancy, OccupancyState
from homemind.contracts.safety import AwayStatus
from homemind.core.events import EventBus, load_events
from homemind.features.safety import engine as engine_mod
from homemind.features.safety.engine import SafetyEngine
from homemind.features.safety.service import SafetyService
from homemind.features.safety.tests.test_engine import at
from homemind.features.safety.tests.test_service import make

REAL = Provenance(origin=Origin.real, kind=ValueKind.inferred)


def occ(state: OccupancyState, m: float, prov=fx.SIM_INFERRED) -> de.PresenceOccupancyChanged:
    kw = {
        OccupancyState.likely_empty: dict(people_inside=0, visitors=0, residents_home=0),
        OccupancyState.occupied: dict(people_inside=2, visitors=0, residents_home=2),
        OccupancyState.uncertain: dict(people_inside=None, visitors=None, residents_home=0),
    }[state]
    return de.PresenceOccupancyChanged(
        ts=at(m),
        household_id=fx.HOUSEHOLD,
        provenance=prov,
        data=HouseOccupancy(ts=at(m), state=state, provenance=prov, **kw),
    )


E, OC, U = OccupancyState.likely_empty, OccupancyState.occupied, OccupancyState.uncertain


def test_likely_empty_goes_away_with_simulated_arm_proposal_only():
    e = SafetyEngine()
    assert e.away_status(fx.HOUSEHOLD) is AwayStatus.unknown  # sem eventos
    out = e.on_event(occ(E, 0))
    assert [x.type for x in out] == ["safety.away_changed"]
    a = out[0].data
    assert a.status is AwayStatus.away and a.arm_proposed and a.executed is False
    assert a.provenance.simulated and out[0].provenance == a.provenance and a.since == at(0)
    assert e.away_status(fx.HOUSEHOLD) is AwayStatus.away


def test_real_occupancy_still_yields_only_a_simulated_proposal():
    out = SafetyEngine().on_event(occ(E, 0, REAL))
    assert out[0].data.provenance.simulated


def test_occupied_leaves_away():
    e = SafetyEngine()
    e.on_event(occ(E, 0))
    out = e.on_event(occ(OC, 5))
    assert out[0].data.status is AwayStatus.home and not out[0].data.arm_proposed
    assert e.away_status(fx.HOUSEHOLD) is AwayStatus.home


@pytest.mark.parametrize("first", [None, U])
def test_uncertain_or_no_events_is_unknown_never_away(first):
    e = SafetyEngine()
    out = e.on_event(occ(U, 0)) if first else []
    assert out == [] and e.away_status(fx.HOUSEHOLD) is AwayStatus.unknown


def test_uncertain_after_away_drops_to_unknown():
    e = SafetyEngine()
    e.on_event(occ(E, 0))
    out = e.on_event(occ(U, 5))
    assert out[0].data.status is AwayStatus.unknown and not out[0].data.arm_proposed


def test_same_event_twice_and_same_state_do_not_duplicate():
    e = SafetyEngine()
    ev = occ(E, 0)
    assert len(e.on_event(ev)) == 1
    assert e.on_event(ev) == [] and e.on_event(occ(E, 9)) == []
    assert e.on_event(occ(OC, -3)) == []  # atrasado: ignorado
    assert e.away_status(fx.HOUSEHOLD) is AwayStatus.away


def test_arming_never_touches_connectors():
    imported = [getattr(m, "__name__", "") for m in vars(engine_mod).values()]
    assert not [n for n in imported if n.startswith("homemind.connectors")]
    assert (
        not hasattr(engine_mod, "McpHome")
        and "connectors" not in open(engine_mod.__file__).read().split('"""', 2)[2]
    )


def away_events(db):
    return db.run_sync(lambda c: load_events(c, types=["safety.away_changed"]))


def test_bus_replay_restore_gives_same_state_without_duplicates():
    db = make()

    async def run(events):
        bus = EventBus(db)
        svc = SafetyService()
        svc.attach(bus)
        await bus.start()
        for ev in events:
            await bus.publish(ev)
        await asyncio.sleep(0.3)
        await bus.stop()
        return svc

    svc = asyncio.run(run([occ(E, 0), occ(E, 0)]))
    assert svc.engine.away_status(fx.HOUSEHOLD) is AwayStatus.away
    assert [s.event.data.status for s in away_events(db)] == [AwayStatus.away]
    # reinício: o estado refaz-se do registo; repetir não duplica; sair regista uma vez
    svc2 = asyncio.run(run([occ(E, 10)]))
    assert svc2.engine.away_status(fx.HOUSEHOLD) is AwayStatus.away
    assert len(away_events(db)) == 1
    svc3 = asyncio.run(run([occ(OC, 20)]))
    assert svc3.engine.away_status(fx.HOUSEHOLD) is AwayStatus.home
    assert [s.event.data.status.value for s in away_events(db)] == ["away", "home"]
    assert all(s.event.data.provenance.simulated for s in away_events(db)[:1])
