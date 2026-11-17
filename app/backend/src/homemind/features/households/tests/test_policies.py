"""HOUSE-04 deterministic fixtures; no live hardware, network, LLM or monetary allocations."""
import asyncio
import threading
from datetime import date, timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import AttributionMethod, AttributionTarget, assert_single_active
from homemind.contracts.common import Audit, replace, stable_id
from homemind.contracts.domain_events import EnergyConsumptionClosed
from homemind.contracts.energy import LocationKind
from homemind.contracts.household import (
    CommonAreaRule, Membership, MembershipRole, MembershipStatus,
)
from homemind.contracts.notification import NotificationRef, NotificationResponse, RefType
from homemind.contracts.policy import PolicyReason, PolicyStatus, PolicyVersion
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus
from homemind.features.households.policies import (
    PolicyConflictError, PolicyExpiredError, apply_response, as_attribution,
    confirmation_intent, expire_decision, resolve_policy,
)
from homemind.features.households.policy_store import (
    append_policy, ensure_initial_policy, expire_and_store, load_decision,
    policy_at, resolve_and_store, respond_and_store,
)
from homemind.features.households.repo import seed_demo


@pytest.fixture
def db():
    database = Database(":memory:")
    database.open()
    migrate(database)
    database.run_sync(seed_demo)
    yield database
    database.close()


def context(db):
    def get(conn):
        return (
            policy_at(conn, fx.HOUSEHOLD, fx.T0),
            [m for m in fx.memberships()],
            fx.rooms(),
        )
    return db.run_sync(get)


def episode(room=None, when=fx.T0, event_id=None):
    c = fx.consumption(closed=True)
    if room is not None:
        return replace(
            c, id=event_id or stable_id("episode", "room", str(when)),
            started_at=when, ended_at=when + timedelta(minutes=30),
            location=LocationKind.room, room_id=room,
        )
    return replace(c, id=event_id or c.id, started_at=when,
                   ended_at=when + timedelta(minutes=90))


def decision(db, c=None, *, now=None, verified=True, policy=None, memberships=None):
    p, members, rooms = context(db)
    return resolve_policy(
        c or episode(), policy or p, rooms,
        memberships if memberships is not None else members,
        now=now or fx.T0 + timedelta(hours=2),
        household_timezone="Europe/Lisbon", location_verified=verified,
        appliance_name="Aquecedor do Bruno",
    )


def reply(choice, resident=fx.CARLA, at=None):
    return NotificationResponse(
        notification_id=fx.NOTIFICATION, action_id=choice, resident_id=resident,
        responded_at=at or fx.T0 + timedelta(hours=3),
    )


REF = NotificationRef(type=RefType.consumption_event, id=fx.CONSUMPTION)


def test_bedroom_contract_not_appliance_owner(db):
    outcome = decision(db, episode(fx.ROOM_ANA))
    assert outcome.status is PolicyStatus.automatic
    assert outcome.target_resident_id == fx.ANA
    assert outcome.method is AttributionMethod.room_rule
    assert outcome.reason is PolicyReason.room_contract
    attr = as_attribution(
        outcome, attribution_id=stable_id("attr", "room"),
        actor=Audit(at=outcome.decided_at, by_system="households.policies"),
    )
    assert attr.target_resident_id == fx.ANA
    assert_single_active([attr])


def test_ended_tenant_keeps_historical_room_and_tenant_change_is_respected(db):
    old = fx.memberships()[0]
    def modify(conn):
        conn.execute("UPDATE membership SET status='ended', ends_on='2026-11-18' WHERE id=?",
                     (str(old.id),))
        new = Membership(
            id=stable_id("membership", "new-ana"),
            household_id=fx.HOUSEHOLD, resident_id=fx.LANDLORD,
            role=MembershipRole.tenant, room_id=fx.ROOM_ANA,
            starts_on=date(2026, 11, 19), status=MembershipStatus.active,
        )
        # Using a new identity avoids reusing any of the existing demo tenants.
        from homemind.features.households.repo import insert_membership
        insert_membership(conn, new)
        return new
    new = db.run_sync(modify)
    members = db.run_sync(lambda conn: [
        Membership(**dict(r)) for r in conn.execute(
            "SELECT * FROM membership WHERE household_id = ?", (str(fx.HOUSEHOLD),)
        )
    ])
    before = decision(db, episode(fx.ROOM_ANA), memberships=members)
    after_time = fx.T0 + timedelta(days=2)
    after = decision(db, episode(fx.ROOM_ANA, after_time),
                     now=after_time + timedelta(hours=2), memberships=members)
    crossing_time = fx.T0 + timedelta(days=1, hours=4)
    crossing = decision(
        db, episode(fx.ROOM_ANA, crossing_time), now=crossing_time + timedelta(hours=2),
        memberships=members,
    )
    assert before.target_resident_id == fx.ANA
    assert after.target_resident_id == new.resident_id
    # Here the crossing episode does not span midnight; it still belongs to the old tenant.
    assert crossing.target_resident_id == fx.ANA


def test_uncertain_room_and_unverified_location_never_assign(db):
    assert decision(db, episode(fx.ROOM_ANA), verified=False).reason is PolicyReason.location_unverified
    unknown = replace(episode(), location=LocationKind.unknown, room_id=None)
    assert decision(db, unknown).status is PolicyStatus.pending
    unknown_room = episode(stable_id("room", "missing"))
    assert decision(db, unknown_room).target_resident_id is None


def test_common_equal_is_automatic_even_if_heater_is_personal(db):
    p = PolicyVersion(
        household_id=fx.HOUSEHOLD, version=1, valid_from=fx.T0-timedelta(days=30),
        common_area_rule=CommonAreaRule.equal,
    )
    result = decision(db, policy=p)
    assert result.target_type is AttributionTarget.common
    assert result.method is AttributionMethod.equal_rule
    assert result.status is PolicyStatus.automatic


def test_common_ask_threshold_missing_cost_and_open_episode(db):
    p, _, _ = context(db)
    assert decision(db, policy=p).reason is PolicyReason.below_threshold  # 48c < 50c
    requested = replace(p, ask_threshold_cents=40)
    assert decision(db, policy=requested).reason is PolicyReason.awaiting_confirmation
    without_cost = replace(episode(), cost_estimate=None)
    assert decision(db, without_cost, policy=requested).reason is PolicyReason.cost_unknown
    assert decision(db, fx.consumption(), policy=requested).reason is PolicyReason.consumption_ongoing
    discarded = replace(episode(), status="discarded")
    assert decision(db, discarded, policy=requested).reason is PolicyReason.consumption_discarded


def test_personal_heater_borrowed_by_carla_and_three_choices(db):
    p = replace(context(db)[0], ask_threshold_cents=40)
    pending = decision(db, policy=p)
    assert pending.confirmation_request.eligible_resident_ids == sorted(fx.TENANTS, key=str)
    mine = apply_response(pending, reply("mine"), REF, now=fx.T0 + timedelta(hours=3))
    assert mine.status is PolicyStatus.confirmed
    assert mine.target_resident_id == fx.CARLA  # not its owner Bruno
    attr = as_attribution(
        mine, attribution_id=stable_id("attr", "carla"),
        actor=Audit(at=mine.decided_at, by_resident_id=fx.CARLA),
    )
    assert attr.method is AttributionMethod.confirmation
    with pytest.raises(PolicyConflictError):
        apply_response(mine, reply("everyone"), REF, now=fx.T0 + timedelta(hours=3))
    everyone = apply_response(pending, reply("everyone"), REF, now=fx.T0 + timedelta(hours=3))
    assert everyone.status is PolicyStatus.confirmed
    assert everyone.target_type is AttributionTarget.common
    unknown = apply_response(pending, reply("unknown"), REF, now=fx.T0 + timedelta(hours=3))
    assert unknown.status is PolicyStatus.pending
    assert unknown.reason is PolicyReason.response_unknown
    assert unknown.confirmation_request is None
    with pytest.raises(PolicyConflictError):
        apply_response(unknown, reply("mine"), REF, now=fx.T0 + timedelta(hours=3))
    assert expire_decision(unknown, now=fx.T0 + timedelta(hours=27)).status is PolicyStatus.fallback


def test_unauthorized_wrong_ref_and_expired_reply_are_rejected(db):
    p = replace(context(db)[0], ask_threshold_cents=40)
    pending = decision(db, policy=p)
    with pytest.raises(PolicyConflictError):
        apply_response(pending, reply("mine", fx.LANDLORD), REF,
                       now=fx.T0+timedelta(hours=3))
    wrong = NotificationRef(type=RefType.consumption_event, id=stable_id("other"))
    with pytest.raises(PolicyConflictError):
        apply_response(pending, reply("mine"), wrong, now=fx.T0+timedelta(hours=3))
    with pytest.raises(PolicyExpiredError):
        apply_response(pending, reply("mine", at=fx.T0+timedelta(hours=27)), REF,
                       now=fx.T0+timedelta(hours=27))
    expired = expire_decision(pending, now=fx.T0+timedelta(hours=27))
    assert expired.method is AttributionMethod.equal_fallback
    assert expire_decision(expired, now=fx.T0+timedelta(hours=100)) == expired
    with pytest.raises(PolicyConflictError):
        as_attribution(pending, attribution_id=stable_id("attr", "pending"),
                       actor=Audit(at=fx.T0, by_system="households.policies"))


def test_presence_c_is_model_only_even_with_evidence(db):
    p = replace(context(db)[0], common_area_rule=CommonAreaRule.presence)
    result = decision(db, policy=p)
    assert result.reason is PolicyReason.presence_deferred
    assert result.target_resident_id is None


def test_repository_duplicate_and_first_reply_wins(db):
    db.run_sync(lambda c: c.execute(
        "UPDATE household SET ask_threshold_cents=40 WHERE id=?", (str(fx.HOUSEHOLD),)
    ))
    source = stable_id("energy", "episode")
    initial = db.run_sync(lambda conn: resolve_and_store(
        conn, episode(), now=fx.T0+timedelta(hours=2), location_verified=True,
        source_event_id=source,
    ))
    again = db.run_sync(lambda conn: resolve_and_store(
        conn, episode(), now=fx.T0+timedelta(hours=9), location_verified=True,
        source_event_id=source,
    ))
    assert initial == again and initial.revision == 1
    results = []

    def attempt(which, who):
        try:
            r = db.run_sync(lambda conn: respond_and_store(
                conn, fx.HOUSEHOLD, fx.CONSUMPTION, reply(which, who), REF,
                now=fx.T0+timedelta(hours=3),
                source_event_id=stable_id("notification", which),
            ))
            results.append(("ok", r))
        except PolicyConflictError:
            results.append(("409", None))

    a = threading.Thread(target=attempt, args=("mine", fx.CARLA))
    b = threading.Thread(target=attempt, args=("everyone", fx.BRUNO))
    a.start(); b.start(); a.join(); b.join()
    assert sorted(x[0] for x in results) == ["409", "ok"]
    final = db.run_sync(lambda conn: load_decision(conn, fx.HOUSEHOLD, fx.CONSUMPTION))
    assert final.revision == 2 and final.decision.status is PolicyStatus.confirmed
    assert db.run_sync(lambda c: c.execute(
        "SELECT count(*) FROM household_policy_audit").fetchone()[0]) == 2


def test_timeout_once_no_late_or_repeated_response(db):
    db.run_sync(lambda c: c.execute(
        "UPDATE household SET ask_threshold_cents=40 WHERE id=?", (str(fx.HOUSEHOLD),)
    ))
    db.run_sync(lambda conn: resolve_and_store(
        conn, episode(), now=fx.T0+timedelta(hours=2), location_verified=True,
        source_event_id=stable_id("energy", "timeout"),
    ))
    expired = db.run_sync(lambda conn: expire_and_store(
        conn, fx.HOUSEHOLD, fx.CONSUMPTION, now=fx.T0+timedelta(hours=27),
    ))
    assert expired.decision.status is PolicyStatus.fallback
    assert db.run_sync(lambda conn: expire_and_store(
        conn, fx.HOUSEHOLD, fx.CONSUMPTION, now=fx.T0+timedelta(hours=50),
    )) == expired
    with pytest.raises(PolicyConflictError):
        db.run_sync(lambda conn: respond_and_store(
            conn, fx.HOUSEHOLD, fx.CONSUMPTION, reply("mine"), REF,
            now=fx.T0+timedelta(hours=28), source_event_id=stable_id("late"),
        ))


def test_new_policy_affects_future_only_and_old_decision_is_untouched(db):
    before = db.run_sync(lambda conn: resolve_and_store(
        conn, episode(), now=fx.T0+timedelta(hours=2), location_verified=True,
        source_event_id=stable_id("event", "old"),
    ))
    v2 = PolicyVersion(
        household_id=fx.HOUSEHOLD, version=2, valid_from=fx.T0+timedelta(days=1),
        common_area_rule=CommonAreaRule.equal,
    )
    db.run_sync(lambda conn: append_policy(conn, v2, now=fx.T0))
    new = db.run_sync(lambda conn: resolve_and_store(
        conn, episode(when=fx.T0+timedelta(days=2),
                      event_id=stable_id("episode", "new")),
        now=fx.T0+timedelta(days=2, hours=2), location_verified=True,
        source_event_id=stable_id("event", "new"),
    ))
    assert before.decision.policy_version == 1
    assert new.decision.policy_version == 2
    assert new.decision.method is AttributionMethod.equal_rule
    assert db.run_sync(lambda conn: load_decision(
        conn, fx.HOUSEHOLD, fx.CONSUMPTION,
    )) == before
    with pytest.raises(PolicyConflictError):
        db.run_sync(lambda conn: append_policy(
            conn, replace(v2, version=3, valid_from=fx.T0-timedelta(days=1)), now=fx.T0,
        ))


def test_event_bus_transactional_confirmation_intent_and_idempotency(db):
    db.run_sync(lambda c: c.execute(
        "UPDATE household SET ask_threshold_cents=40 WHERE id=?", (str(fx.HOUSEHOLD),)
    ))

    def handler(conn, stored):
        result = resolve_and_store(
            conn, stored.event.data, now=fx.T0+timedelta(hours=2),
            location_verified=True, source_event_id=stored.event.id,
        )
        intent = confirmation_intent(result.decision, correlation_id=stored.event.correlation_id)
        return [intent] if intent else []

    async def run():
        bus = EventBus(db)
        bus.subscribe("test.house04", handler, ["energy.consumption_closed"])
        event = EnergyConsumptionClosed(
            id=stable_id("event", "closed"), ts=fx.T0+timedelta(hours=2),
            household_id=fx.HOUSEHOLD, correlation_id=fx.CORRELATION,
            provenance=fx.SIM_INFERRED, data=episode(),
        )
        stored = await bus.publish(event)
        assert await bus.deliver("test.house04", stored)
        assert not await bus.deliver("test.house04", stored)
        rows = db.run_sync(lambda conn: conn.execute(
            "SELECT type FROM domain_event ORDER BY seq").fetchall())
        assert [r["type"] for r in rows] == [
            "energy.consumption_closed", "billing.confirmation_needed",
        ]
        assert db.run_sync(lambda conn: conn.execute(
            "SELECT count(*) FROM household_policy_audit").fetchone()[0]) == 1

    asyncio.run(run())
