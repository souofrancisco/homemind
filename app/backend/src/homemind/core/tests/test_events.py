"""Barramento persistente: persistência antes da entrega, idempotência, falhas, recuperação."""

import asyncio
import logging
import threading
import time

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.core.db import Database, migrate
from homemind.core.events import (
    EventBus,
    EventConflictError,
    SimulatedEventInRealHouseholdError,
    UnknownHouseholdError,
    append_event,
    load_events,
    replay,
)
from homemind.features.households.repo import seed_demo

BILL = "billing.bill_created"


def ev(i: int, household=fx.HOUSEHOLD) -> de.BillingBillCreated:
    return de.BillingBillCreated(
        id=stable_id("ev", str(i)),
        correlation_id=stable_id("corr", str(i)),
        ts=fx.T0,
        household_id=household,
        provenance=fx.SIM_MEASURED,
        data=de.BillRef(bill_id=stable_id("bill", str(i))),
    )


def make_db(path=":memory:") -> Database:
    db = Database(path)
    db.open()
    migrate(db)
    db.run_sync(seed_demo)
    return db


async def until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condição não cumprida a tempo")


def count(db, sql, *args):
    return db.run_sync(lambda c: c.execute(sql, args).fetchone()[0])


class Effects:
    """Efeito de negócio de teste: uma linha por evento, na mesma transação do registo."""

    def __init__(self, db: Database, name="fx"):
        self.db, self.name = db, name
        db.run_sync(
            lambda c: c.execute(f"CREATE TABLE IF NOT EXISTS {name} (event_id TEXT, seq INT)")
        )

    def handler(self, conn, stored):
        conn.execute(f"INSERT INTO {self.name} VALUES (?,?)", (str(stored.event.id), stored.seq))

    @property
    def rows(self):
        return self.db.run_sync(
            lambda c: [tuple(r) for r in c.execute(f"SELECT * FROM {self.name} ORDER BY seq")]
        )


def test_event_is_persisted_before_delivery_and_seq_is_assigned_by_store():
    async def main():
        db = make_db()
        bus = EventBus(db)
        a = await bus.publish(ev(1))  # sem consumidores nem start(): fica gravado
        b = await bus.publish(ev(2))
        assert (a.seq, b.seq) == (1, 2)
        assert count(db, "SELECT count(*) FROM domain_event") == 2
        assert count(db, "SELECT count(*) FROM processed_event") == 0
        eff = Effects(db)
        bus.subscribe("c", eff.handler, [BILL])
        await bus.start()  # recuperação: entrega o que já estava gravado
        await until(lambda: len(eff.rows) == 2)
        await bus.stop()
        assert [r[1] for r in eff.rows] == [1, 2]
        db.close()

    asyncio.run(main())


def test_publish_is_idempotent_by_id_and_conflict_is_an_error():
    db = make_db()
    first = db.run_sync(lambda c: append_event(c, ev(1)))
    again = db.run_sync(lambda c: append_event(c, ev(1)))
    assert again == first and count(db, "SELECT count(*) FROM domain_event") == 1
    clash = ev(1).model_copy(update={"data": de.BillRef(bill_id=stable_id("outra"))})
    with pytest.raises(EventConflictError):
        db.run_sync(lambda c: append_event(c, clash))
    db.close()


def test_duplicate_delivery_does_not_repeat_the_effect():
    async def main():
        db = make_db()
        bus, eff = EventBus(db), None
        eff = Effects(db)
        bus.subscribe("c", eff.handler, [BILL])
        stored = await bus.publish(ev(1))
        assert await bus.deliver("c", stored) is True
        assert await bus.deliver("c", stored) is False  # reentrega: ignorada
        assert await bus.deliver("c", stored) is False
        assert len(eff.rows) == 1
        await bus.publish(ev(1))  # republicar o mesmo evento: sem novo `seq`, sem novo efeito
        assert count(db, "SELECT count(*) FROM domain_event") == 1 and len(eff.rows) == 1
        db.close()

    asyncio.run(main())


def test_each_consumer_processes_independently():
    async def main():
        db = make_db()
        bus = EventBus(db)
        a, b = Effects(db, "a"), Effects(db, "b")
        bus.subscribe("a", a.handler)
        bus.subscribe("b", b.handler)
        await bus.start()
        for i in range(3):
            await bus.publish(ev(i))
        await until(lambda: len(a.rows) == 3 and len(b.rows) == 3)
        await bus.stop()
        assert count(db, "SELECT count(*) FROM processed_event") == 6
        db.close()

    asyncio.run(main())


def test_failing_handler_rolls_back_effect_and_marker_then_retries(caplog):
    caplog.set_level(logging.WARNING)

    async def main():
        db = make_db()
        bus = EventBus(db, max_attempts=3, retry_delay_s=0.01)
        eff, calls = Effects(db), []

        def flaky(conn, stored):
            eff.handler(conn, stored)  # efeito feito...
            calls.append(1)
            if len(calls) < 3:
                raise ValueError("segredo@exemplo.pt")  # ...e depois falha

        bus.subscribe("c", flaky)
        await bus.start()
        await bus.publish(ev(1))
        await until(lambda: len(eff.rows) == 1)
        await bus.stop()
        assert len(calls) == 3 and len(eff.rows) == 1  # os 2 efeitos falhados foram revertidos
        assert count(db, "SELECT count(*) FROM processed_event") == 1
        row = db.run_sync(
            lambda c: tuple(
                c.execute("SELECT attempts,last_error_type,dead FROM event_failure").fetchone()
            )
        )
        assert row == (2, "ValueError", 0)
        db.close()

    asyncio.run(main())
    assert "segredo@exemplo.pt" not in caplog.text and "ValueError" in caplog.text


def test_poison_event_goes_dead_without_blocking_the_consumer_or_others():
    async def main():
        db = make_db()
        bus = EventBus(db, max_attempts=2, retry_delay_s=0.01)
        good = Effects(db, "good")

        def poison(conn, stored):
            if stored.event.data.bill_id == stable_id("bill", "1"):
                raise RuntimeError
            good.handler(conn, stored)

        bus.subscribe("fussy", poison)
        other = Effects(db, "other")
        bus.subscribe("other", other.handler)
        await bus.start()
        for i in (1, 2, 3):
            await bus.publish(ev(i))
        await until(lambda: len(good.rows) == 2 and len(other.rows) == 3)
        await until(lambda: count(db, "SELECT dead FROM event_failure") == 1)
        await bus.stop()
        assert count(db, "SELECT attempts FROM event_failure") == 2
        # `dead` não volta a ser entregue depois de reiniciar
        bus2 = EventBus(db, max_attempts=2, retry_delay_s=0.01)
        bus2.subscribe("fussy", poison)
        await bus2.start()
        await asyncio.sleep(0.1)
        await bus2.stop()
        assert count(db, "SELECT attempts FROM event_failure") == 2
        db.close()

    asyncio.run(main())


def test_failed_event_can_be_overtaken_by_later_ones():
    async def main():
        db = make_db()
        bus = EventBus(db, max_attempts=3, retry_delay_s=0.2)
        seen, failed = [], []

        def handler(conn, stored):
            if stored.seq == 1 and not failed:
                failed.append(1)
                raise RuntimeError
            seen.append(stored.seq)

        bus.subscribe("c", handler)
        for i in (1, 2, 3):
            await bus.publish(ev(i))
        await bus.start()
        await until(lambda: len(seen) == 3)
        await bus.stop()
        assert seen == [2, 3, 1]  # fora de ordem: os consumidores têm de o tolerar
        db.close()

    asyncio.run(main())


def test_handler_follow_up_events_are_atomic_with_the_effect():
    async def main():
        db = make_db()
        bus = EventBus(db)
        eff = Effects(db)

        def bad_follow_up(conn, stored):
            eff.handler(conn, stored)
            return [ev(99, household=stable_id("casa-inexistente"))]  # falha ao gravar

        bus.subscribe("c", bad_follow_up)
        stored = await bus.publish(ev(1))
        with pytest.raises(UnknownHouseholdError):
            await bus.deliver("c", stored)
        assert eff.rows == [] and count(db, "SELECT count(*) FROM processed_event") == 0
        assert count(db, "SELECT count(*) FROM domain_event") == 1
        db.close()

    asyncio.run(main())


def test_chain_producer_consumer_producer():
    async def main():
        db = make_db()
        bus = EventBus(db)
        eff = Effects(db)

        def a(conn, stored):  # consome `bill_created`, emite `bill_finalized` na mesma transação
            return [
                de.BillingBillFinalized(
                    id=stable_id("fin", str(stored.seq)),
                    ts=fx.T0,
                    household_id=fx.HOUSEHOLD,
                    correlation_id=stored.event.correlation_id,
                    provenance=fx.SIM_MEASURED,
                    data=stored.event.data,
                )
            ]

        bus.subscribe("a", a, [BILL])
        bus.subscribe("b", eff.handler, ["billing.bill_finalized"])
        await bus.start()
        await bus.publish(ev(1))
        await until(lambda: len(eff.rows) == 1)
        await bus.stop()
        events = db.run_sync(lambda c: load_events(c))
        assert [e.event.type for e in events] == [BILL, "billing.bill_finalized"]
        assert events[0].event.correlation_id == events[1].event.correlation_id
        db.close()

    asyncio.run(main())


def test_restart_resumes_pending_without_repeating_effects(tmp_path):
    path = tmp_path / "r.sqlite3"

    async def first():
        db = make_db(path)
        bus = EventBus(db)
        eff = Effects(db)
        bus.subscribe("c", eff.handler)
        await bus.start()
        await bus.publish(ev(1))
        await until(lambda: len(eff.rows) == 1)
        await bus.stop()
        await bus.publish(ev(2))  # gravado depois de o consumidor parar (processo «caiu»)
        db.close()

    async def second():
        db = make_db(path)  # reabre: a base e as migrações persistem, o seed é idempotente
        eff = Effects(db)
        assert len(eff.rows) == 1
        bus = EventBus(db)
        bus.subscribe("c", eff.handler)
        await bus.start()
        await until(lambda: len(eff.rows) == 2)
        await asyncio.sleep(0.05)
        await bus.stop()
        assert [r[1] for r in eff.rows] == [1, 2]  # o evento 1 não foi repetido
        assert count(db, "SELECT count(*) FROM processed_event") == 2
        db.close()

    asyncio.run(first())
    asyncio.run(second())


def test_shutdown_mid_work_keeps_effects_and_markers_consistent(tmp_path):
    path = tmp_path / "s.sqlite3"

    async def main():
        db = make_db(path)
        bus = EventBus(db, batch_size=5)
        eff = Effects(db)

        def slow(conn, stored):
            time.sleep(0.02)
            eff.handler(conn, stored)

        bus.subscribe("c", slow)
        for i in range(30):
            await bus.publish(ev(i))
        await bus.start()
        await until(lambda: len(eff.rows) >= 3)
        await bus.stop()  # cancela com trabalho pendente
        db.close()
        db2 = make_db(path)
        eff2 = Effects(db2)
        # invariante: efeitos == registos de processamento, nunca um sem o outro
        assert len(eff2.rows) == count(db2, "SELECT count(*) FROM processed_event")
        assert len(eff2.rows) < 30
        bus2 = EventBus(db2)
        bus2.subscribe("c", eff2.handler)
        await bus2.start()
        await until(lambda: len(eff2.rows) == 30)
        await bus2.stop()
        assert len({r[0] for r in eff2.rows}) == 30  # nenhum duplicado
        db2.close()

    asyncio.run(main())


def test_concurrent_producers_get_unique_ordered_seq_and_exactly_one_effect_each():
    async def main():
        db = make_db()
        bus = EventBus(db)
        eff = Effects(db)
        bus.subscribe("c", eff.handler)
        await bus.start()
        stored, lock = [], threading.Lock()

        def produce(worker):
            for j in range(25):
                s = bus.publish_threadsafe(ev(worker * 100 + j))
                with lock:
                    stored.append(s.seq)

        threads = [threading.Thread(target=produce, args=(w,)) for w in range(4)]
        [t.start() for t in threads]
        await asyncio.to_thread(lambda: [t.join() for t in threads])
        await until(lambda: len(eff.rows) == 100)
        await bus.stop()
        assert sorted(stored) == list(range(1, 101))
        assert len({r[0] for r in eff.rows}) == 100
        db.close()

    asyncio.run(main())


def test_async_publish_from_another_loop_wakes_consumer_thread_safely():
    async def main():
        db = make_db()
        bus = EventBus(db)
        eff = Effects(db)
        bus.subscribe("c", eff.handler)
        await bus.start()

        def publish_from_other_loop():
            asyncio.run(bus.publish(ev(1)))

        await asyncio.to_thread(publish_from_other_loop)
        await until(lambda: len(eff.rows) == 1)
        await bus.stop()
        assert len(eff.rows) == 1
        db.close()

    asyncio.run(main())


def test_type_filter_since_seq_and_subscription_validation():
    async def main():
        db = make_db()
        bus = EventBus(db)
        eff = Effects(db)
        bus.subscribe("only-finalized", eff.handler, ["billing.bill_finalized"])
        late = Effects(db, "late")
        bus.subscribe("late", late.handler, since_seq=2)
        with pytest.raises(ValueError, match="repetido"):
            bus.subscribe("late", late.handler)
        with pytest.raises(ValueError, match="desconhecidos"):
            bus.subscribe("x", late.handler, ["nope.nope"])
        for i in (1, 2, 3):
            await bus.publish(ev(i))
        await bus.start()
        await until(lambda: len(late.rows) == 1)
        late_two = Effects(db, "late2")
        bus.subscribe("added-while-running", late_two.handler)  # um módulo arranca depois do core
        await until(lambda: len(late_two.rows) == 3)
        await bus.stop()
        assert eff.rows == [] and [r[1] for r in late.rows] == [3]
        db.close()

    asyncio.run(main())


def test_simulated_events_never_enter_a_real_household():
    db = make_db()
    from homemind.contracts import household as hh
    from homemind.features.households.repo import insert_household

    real = hh.Household(
        id=stable_id("casa-real"),
        name="Casa real",
        settings=hh.HouseholdSettings(source_kind=hh.SourceKind.real),
        created_at=fx.T0,
    )
    db.run_sync(lambda c: insert_household(c, real))
    with pytest.raises(SimulatedEventInRealHouseholdError):
        db.run_sync(lambda c: append_event(c, ev(1, household=real.id)))
    real_event = de.BillingBillCreated(
        ts=fx.T0,
        household_id=real.id,
        provenance=Provenance(origin=Origin.real, kind=ValueKind.measured),
        data=de.BillRef(bill_id=stable_id("b")),
    )
    db.run_sync(lambda c: append_event(c, real_event))  # real em casa real: ok
    db.close()


def test_stored_events_are_immutable_in_the_database():
    db = make_db()
    db.run_sync(lambda c: append_event(c, ev(1)))
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        db.run_sync(lambda c: c.execute("UPDATE domain_event SET payload_json = '{}'"))
    db.close()


def test_replay_into_isolated_database_is_idempotent():
    async def main():
        src = make_db()
        sbus = EventBus(src)
        for e in fx.event_samples():
            await sbus.publish(e)
        events = src.run_sync(lambda c: load_events(c))
        n = len(fx.event_samples())
        assert len(events) == n

        dst = make_db()  # base isolada
        dbus = EventBus(dst)
        eff = Effects(dst)
        dbus.subscribe("c", eff.handler)
        await dbus.start()
        await replay(events, dbus)
        await until(lambda: len(eff.rows) == n)
        await replay(events, dbus)  # repetir o replay não duplica nada
        await asyncio.sleep(0.05)
        await dbus.stop()
        assert len(eff.rows) == n and count(dst, "SELECT count(*) FROM domain_event") == n
        # tipos e conteúdo reconstruídos fielmente a partir da base
        assert [s.event for s in dst.run_sync(lambda c: load_events(c))] == [
            e.event for e in events
        ]
        src.close()
        dst.close()

    asyncio.run(main())


def test_unreadable_stored_event_fails_per_event_and_never_kills_the_consumer():
    async def main():
        db = make_db()
        bus = EventBus(db, max_attempts=2, retry_delay_s=0.01)
        eff = Effects(db)
        bus.subscribe("c", eff.handler)
        # linha antiga que já não valida (as triggers só impedem UPDATE/DELETE)
        db.run_sync(
            lambda c: c.execute(
                "INSERT INTO domain_event (id,type,schema_version,ts,household_id,correlation_id,"
                "origin,kind,payload_json,recorded_at) VALUES ('bad','billing.bill_created',1,"
                f"'2026-11-17T19:00:00+00:00','{fx.HOUSEHOLD}','c','real','measured','{{\"x\":1}}','x')"
            )
        )
        await bus.start()
        await bus.publish(ev(1))  # um evento válido depois do inválido
        await until(lambda: len(eff.rows) == 1)
        await until(lambda: count(db, "SELECT dead FROM event_failure WHERE event_id='bad'") == 1)
        assert not any(t.done() for t in bus._tasks)  # o consumidor continua vivo
        assert count(db, "SELECT last_error_type FROM event_failure") == "ValidationError"
        await bus.publish(ev(2))
        await until(lambda: len(eff.rows) == 2)
        await bus.stop()
        db.close()

    asyncio.run(main())
