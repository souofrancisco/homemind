"""Integração com o barramento persistente (base em memória), sem hardware nem rede."""

import asyncio

from homemind.contracts import fixtures as fx
from homemind.contracts.sensors import ContactState as C
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus, load_events
from homemind.features.households.repo import seed_demo
from homemind.features.safety import simulation as sim
from homemind.features.safety.service import SafetyService
from homemind.features.safety.tests.test_engine import at


def make():
    db = Database(":memory:")
    db.open()
    migrate(db)
    db.run_sync(seed_demo)
    return db


def alerts(db):
    return db.run_sync(lambda c: load_events(c, types=["safety.alert_raised"]))


async def settle(db, n, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        if len(alerts(db)) >= n:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("alerta não chegou")


def test_bus_flow_persists_one_alert_and_restore_after_restart_does_not_duplicate():
    db = make()

    async def run(events, expect):
        bus = EventBus(db)
        svc = SafetyService(lambda a: a == fx.HEATER)
        svc.attach(bus)
        await bus.start()
        for e in events:
            await bus.publish(e)
        await settle(db, expect)
        await asyncio.sleep(0.1)
        await bus.stop()

    asyncio.run(
        run([sim.heater_on(fx.T0), sim.contact(fx.T0, C.open), sim.contact(at(5), C.open)], 1)
    )
    assert len(alerts(db)) == 1
    # reinício: estado refeito do registo; novas leituras repetidas não duplicam; fechar resolve
    asyncio.run(run([sim.contact(at(6), C.open), sim.contact(at(7), C.closed)], 2))
    got = [s.event.data for s in alerts(db)]
    assert [a.status.value for a in got] == ["active", "resolved"] and got[0].id == got[1].id
    assert all(s.event.provenance.simulated for s in alerts(db))


def test_failed_transaction_then_retry_emits_the_alert_once():
    db = make()
    svc = SafetyService(lambda a: a == fx.HEATER)
    boom = {"left": 1}

    def flaky(conn, stored):
        out = svc.handle(conn, stored)
        if out and boom["left"]:
            boom["left"] -= 1
            raise RuntimeError("falha depois do handler")
        return out

    async def main():
        bus = EventBus(db)
        bus.subscribe(
            "safety", flaky, types=["sensor.reading_recorded", "energy.consumption_detected"]
        )
        evs = [sim.heater_on(fx.T0), sim.contact(fx.T0, C.open), sim.contact(at(5), C.open)]
        stored = [await bus.publish(e) for e in evs]
        for s in stored[:2]:
            await bus.deliver("safety", s)
        try:
            await bus.deliver("safety", stored[2])
        except RuntimeError:
            pass
        assert alerts(db) == []  # a transação fez rollback
        assert await bus.deliver("safety", stored[2])  # retry

    asyncio.run(main())
    assert [s.event.data.status.value for s in alerts(db)] == ["active"]
