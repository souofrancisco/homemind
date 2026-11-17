"""Cenário de integração dos contratos e da infraestrutura (F0).

NÃO é o motor de nenhum módulo: os «consumidores» abaixo são stand-ins mínimos e explícitos de
billing (P4) e notifications (P3) para provar que os contratos, o barramento, a idempotência e
a persistência se encaixam. Sem hardware, rede, IA nem frontend.
"""

import asyncio
import threading
import time
from datetime import timedelta

import pytest

from homemind.contracts import billing, notification
from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Audit, replace, stable_id
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus, load_events
from homemind.features.households.repo import seed_demo

RESPONDED_AT = fx.T0 + timedelta(minutes=2)


def setup_test_tables(conn):
    conn.execute("CREATE TABLE t_notification (id TEXT PRIMARY KEY, status TEXT, json TEXT)")
    conn.execute(
        "CREATE TABLE t_attribution (id TEXT PRIMARY KEY, event_id TEXT, status TEXT, json TEXT)"
    )
    conn.execute("CREATE UNIQUE INDEX one_active ON t_attribution(event_id) WHERE status='active'")


def stand_in_billing_request(conn, stored):
    """P4 (stand-in): consumo identificado na sala + regra «perguntar» => pede confirmação."""
    c = stored.event.data
    assert c.location.value == "common" and c.cost_estimate is not None
    return [
        de.BillingConfirmationNeeded(
            id=stable_id("needed", str(stored.event.id)),
            ts=fx.T0 + timedelta(seconds=3),
            household_id=c.household_id,
            correlation_id=stored.event.correlation_id,
            provenance=stored.event.provenance,
            data=fx.confirmation_request(),
        )
    ]


def stand_in_notifications(conn, stored):
    """P3 (stand-in): transforma o pedido numa notificação para a casa e persiste-a."""
    n = fx.confirmation_notification()
    conn.execute(
        "INSERT INTO t_notification VALUES (?,?,?)",
        (str(n.id), n.status.value, n.model_dump_json()),
    )
    return [
        de.NotificationCreated(
            id=stable_id("created", str(n.id)),
            ts=n.created_at,
            household_id=n.household_id,
            correlation_id=stored.event.correlation_id,
            provenance=stored.event.provenance,
            data=de.NotificationCreatedData(notification_id=n.id, scope=n.scope, kind=n.kind),
        )
    ]


def respond(conn, notification_id, resident_id, action_id, now):
    """P3 (stand-in da rota `respond`): regra pura + compare-and-set na base de dados."""
    row = conn.execute(
        "SELECT json FROM t_notification WHERE id=?", (str(notification_id),)
    ).fetchone()
    n = notification.Notification.model_validate_json(row["json"])
    done = n.respond(resident_id, action_id, now)  # levanta 403/409 conforme o caso
    cur = conn.execute(
        "UPDATE t_notification SET status='actioned', json=?"
        " WHERE id=? AND status IN ('unread','read')",
        (done.model_dump_json(), str(notification_id)),
    )
    if cur.rowcount != 1:  # perdeu a corrida contra uma resposta simultânea
        raise notification.AlreadyRespondedError("já respondida")
    return done


def stand_in_attribution(conn, stored):
    """P4 (stand-in): «É minha» => Attribution da Carla; nunca duas ativas para o consumo."""
    resp = stored.event.data.response
    assert resp.action_id == "mine"
    a = billing.Attribution(
        id=stable_id("attr", str(resp.notification_id)),
        household_id=stored.event.household_id,
        consumption_event_id=stored.event.data.ref.id,
        target_type=billing.AttributionTarget.resident,
        target_resident_id=resp.resident_id,
        method=billing.AttributionMethod.confirmation,
        provenance=fx.SIM_MEASURED,
        decided_by=Audit(at=resp.responded_at, by_resident_id=resp.resident_id),
    )
    conn.execute(
        "INSERT INTO t_attribution VALUES (?,?,?,?)",
        (str(a.id), str(a.consumption_event_id), a.status.value, a.model_dump_json()),
    )
    return [
        de.BillingAttributionChanged(
            id=stable_id("changed", str(a.id)),
            ts=resp.responded_at,
            household_id=a.household_id,
            correlation_id=stored.event.correlation_id,
            provenance=a.provenance,
            data=a,
        )
    ]


def one(db, sql, *a):
    return db.run_sync(lambda c: c.execute(sql, a).fetchone()[0])


async def until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condição não cumprida a tempo")


def build_bus(db):
    bus = EventBus(db)
    bus.subscribe("billing.requester", stand_in_billing_request, ["energy.consumption_detected"])
    bus.subscribe("notifications.creator", stand_in_notifications, ["billing.confirmation_needed"])
    bus.subscribe("billing.attributor", stand_in_attribution, ["notification.responded"])
    return bus


def test_energy_to_notification_to_attribution_to_bill(tmp_path):
    path = tmp_path / "scenario.sqlite3"

    async def run():
        # 1-2. casa simulada, quatro moradores e memberships (seed determinístico)
        db = Database(path)
        db.open()
        migrate(db)
        db.run_sync(seed_demo)
        db.run_sync(setup_test_tables)
        assert one(db, "SELECT count(*) FROM membership WHERE role='tenant'") == 4
        bus = build_bus(db)
        await bus.start()

        # 3. aparelho pessoal (modelo validado; a persistência é de P1)
        heater = fx.heater()
        assert heater.ownership.owner_resident_id == fx.BRUNO

        # 4-6. leitura e consumo com identificação provável, em eventos tipados e persistidos
        corr = fx.CORRELATION
        base = dict(household_id=fx.HOUSEHOLD, correlation_id=corr, ts=fx.T0)
        reading = await bus.publish(
            de.EnergyReadingRecorded(**base, provenance=fx.SIM_MEASURED, data=fx.reading())
        )
        detected = await bus.publish(
            de.EnergyConsumptionDetected(**base, provenance=fx.SIM_INFERRED, data=fx.consumption())
        )
        assert (reading.seq, detected.seq) == (1, 2)
        assert detected.event.data.match.confidence == 0.9
        assert detected.event.provenance.simulated  # origem simulada preservada

        # 7-8. billing pede confirmação; notifications cria a notificação para a casa
        await until(lambda: one(db, "SELECT count(*) FROM t_notification") == 1)
        n = notification.Notification.model_validate_json(
            one(db, "SELECT json FROM t_notification")
        )
        assert n.can_respond(fx.CARLA, RESPONDED_AT) and not n.can_respond(
            fx.LANDLORD, RESPONDED_AT
        )
        assert n.origin.value == "simulated"

        # 9-10. a Carla responde «É minha»: um só vencedor mesmo com respostas simultâneas
        outcomes = []

        def attempt(who, action):
            try:
                db.run_sync(lambda c: respond(c, n.id, who, action, RESPONDED_AT))
                outcomes.append((who, "ok"))
            except notification.AlreadyRespondedError:
                outcomes.append((who, "409"))

        threads = [
            threading.Thread(target=attempt, args=(fx.CARLA, "mine")),
            threading.Thread(target=attempt, args=(fx.ANA, "everyone")),
        ]
        [t.start() for t in threads]
        await asyncio.to_thread(lambda: [t.join() for t in threads])
        assert sorted(o for _, o in outcomes) == ["409", "ok"]
        winner = next(w for w, o in outcomes if o == "ok")
        stored_n = notification.Notification.model_validate_json(
            one(db, "SELECT json FROM t_notification")
        )
        assert stored_n.response.resident_id == winner  # autor e hora gravados
        assert stored_n.response.responded_at == RESPONDED_AT
        # o evento reflete a resposta que realmente venceu
        resp_event = de.NotificationResponded(
            **{**base, "ts": RESPONDED_AT},
            id=stable_id("responded", str(n.id)),
            provenance=fx.SIM_MEASURED,
            data=de.NotificationRespondedData(
                response=stored_n.response,
                ref=notification.NotificationRef(
                    type=notification.RefType.consumption_event, id=fx.CONSUMPTION
                ),
            ),
        )
        await bus.publish(resp_event)

        # 11. Attribution tipada (única ativa), 12-13. fatura e alocações de referência
        await until(lambda: one(db, "SELECT count(*) FROM t_attribution") == 1)
        attr = billing.Attribution.model_validate_json(one(db, "SELECT json FROM t_attribution"))
        assert attr.target_resident_id == winner and attr.status is billing.AttributionStatus.active
        bill, allocations = fx.bill_a()
        billing.validate_allocations(bill, allocations)  # Σ = 120,00 € exatos
        assert sum(a.amount_cents for a in allocations) == 12_000
        for ev in (
            de.BillingBillCreated(
                **base, provenance=fx.SIM_MEASURED, data=de.BillRef(bill_id=bill.id)
            ),
            de.BillingBillFinalized(
                **base, provenance=fx.SIM_MEASURED, data=de.BillRef(bill_id=bill.id)
            ),
        ):
            await bus.publish(ev)
        await until(lambda: one(db, "SELECT count(*) FROM domain_event") == 8)

        # 14. a mesma entrega repetida não repete nenhum efeito
        before = (
            one(db, "SELECT count(*) FROM t_notification"),
            one(db, "SELECT count(*) FROM t_attribution"),
            one(db, "SELECT count(*) FROM domain_event"),
        )
        for stored in db.run_sync(load_events):
            for consumer, types in (
                ("billing.requester", {"energy.consumption_detected"}),
                ("notifications.creator", {"billing.confirmation_needed"}),
                ("billing.attributor", {"notification.responded"}),
            ):
                if stored.event.type in types:
                    assert await bus.deliver(consumer, stored) is False
        await bus.publish(detected.event)  # republicar o mesmo evento: sem novo seq
        assert before == (
            one(db, "SELECT count(*) FROM t_notification"),
            one(db, "SELECT count(*) FROM t_attribution"),
            one(db, "SELECT count(*) FROM domain_event"),
        )
        await bus.stop()
        db.close()

        # 15. reabrir a base: tudo persistiu, nada pendente, nada duplicado
        db = Database(path)
        db.open()
        assert migrate(db) == []
        events = db.run_sync(load_events)
        types = [e.event.type for e in events]
        assert sorted(types) == sorted(
            [
                "energy.reading_recorded",
                "energy.consumption_detected",
                "billing.confirmation_needed",
                "notification.created",
                "notification.responded",
                "billing.attribution_changed",
                "billing.bill_created",
                "billing.bill_finalized",
            ]
        )
        assert [e.seq for e in events] == list(range(1, 9))
        assert all(e.event.provenance.simulated for e in events)
        # a cadeia manteve o correlation_id do consumo até à atribuição
        chain = {e.event.type for e in events if e.event.correlation_id == corr}
        assert {
            "billing.confirmation_needed",
            "notification.created",
            "billing.attribution_changed",
        } <= chain
        bus2 = build_bus(db)
        await bus2.start()
        await asyncio.sleep(0.1)
        await bus2.stop()
        assert one(db, "SELECT count(*) FROM domain_event") == 8  # nada de novo
        assert one(db, "SELECT count(*) FROM processed_event") == 3  # uma entrega por consumidor
        assert one(db, "SELECT count(*) FROM event_failure") == 0
        db.close()

    asyncio.run(run())


def test_confirmation_rules_for_the_scenario_notification():
    n = fx.confirmation_notification()
    with pytest.raises(notification.NotAllowedToRespondError):
        n.respond(fx.LANDLORD, "mine", RESPONDED_AT)  # o senhorio nunca responde
    done = n.respond(fx.CARLA, "mine", RESPONDED_AT)
    assert replace(done, status="actioned").response.resident_id == fx.CARLA
