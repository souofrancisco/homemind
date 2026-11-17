"""HOUSE-04 deterministic fixtures and P3/P4 contract integration."""

import asyncio
from datetime import date, timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import AttributionMethod, AttributionTarget, assert_single_active
from homemind.contracts.common import Audit, replace, stable_id
from homemind.contracts.domain_events import EnergyConsumptionClosed
from homemind.contracts.energy import LocationKind
from homemind.contracts.household import (
    CommonAreaRule,
    Membership,
    MembershipRole,
    MembershipStatus,
)
from homemind.contracts.notification import (
    AlreadyRespondedError,
    ConfirmationOutcome,
    ConfirmationVerdict,
    NotificationRef,
    NotificationResponse,
    NotificationStatus,
    RefType,
)
from homemind.contracts.policy import PolicyReason, PolicyStatus, PolicyVersion
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus
from homemind.features.billing.allocation import allocate, shares_from_attributions
from homemind.features.households.policies import (
    PolicyConflictError,
    PolicyExpiredError,
    apply_confirmation_outcome,
    as_attribution,
    confirmation_intent,
    expire_decision,
    resolve_policy,
)
from homemind.features.households.policy_store import (
    append_policy,
    expire_and_store,
    load_decision,
    policy_at,
    record_confirmation_outcome,
    resolve_and_store,
)
from homemind.features.households.repo import seed_demo
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.service import NotificationNotFoundError, NotificationService
from homemind.features.notifications.sqlite import SqliteNotificationRepository


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
            c,
            id=event_id or stable_id("episode", "room", str(when)),
            started_at=when,
            ended_at=when + timedelta(minutes=30),
            location=LocationKind.room,
            room_id=room,
        )
    return replace(c, id=event_id or c.id, started_at=when, ended_at=when + timedelta(minutes=90))


def decision(db, c=None, *, now=None, verified=True, policy=None, memberships=None):
    p, members, rooms = context(db)
    return resolve_policy(
        c or episode(),
        policy or p,
        rooms,
        memberships if memberships is not None else members,
        now=now or fx.T0 + timedelta(hours=2),
        household_timezone="Europe/Lisbon",
        location_verified=verified,
        appliance_name="Aquecedor do Bruno",
    )


def reply(choice, resident=fx.CARLA, at=None, target=None):
    return NotificationResponse(
        notification_id=fx.NOTIFICATION,
        action_id=choice,
        resident_id=resident,
        responded_at=at or fx.T0 + timedelta(hours=3),
        target_resident_id=target,
    )


REF = NotificationRef(type=RefType.consumption_event, id=fx.CONSUMPTION)


def test_confirmation_intermediate_outcome_keeps_policy_pending(db):
    pending = decision(db, policy=replace(context(db)[0], ask_threshold_cents=40))
    response = reply("other", fx.ANA, target=fx.DIOGO)
    result = apply_confirmation_outcome(
        pending,
        response,
        REF,
        ConfirmationOutcome(verdict=ConfirmationVerdict.pending, votes=1, votes_needed=2),
        now=fx.T0 + timedelta(hours=3),
    )
    assert result == pending
    assert result.confirmation_request is not None


def test_confirmation_outcome_uses_p3_majority_and_allows_decisive_voter_as_auditor(db):
    pending = decision(db, policy=replace(context(db)[0], ask_threshold_cents=40))
    response = reply("other", fx.BRUNO, target=fx.DIOGO)
    majority = ConfirmationOutcome(
        verdict=ConfirmationVerdict.accusation_accepted,
        resident_id=fx.DIOGO,
        votes=2,
        votes_needed=2,
    )
    resolved = apply_confirmation_outcome(
        pending, response, REF, majority, now=fx.T0 + timedelta(hours=3)
    )
    assert resolved.reason is PolicyReason.response_other
    assert resolved.target_resident_id == fx.DIOGO
    attribution = as_attribution(
        resolved,
        attribution_id=stable_id("attr", "majority"),
        actor=Audit(at=resolved.decided_at, by_resident_id=fx.BRUNO),
    )
    assert attribution.target_resident_id == fx.DIOGO


def test_actual_p3_votes_drive_household_policy_and_p4_attribution(db):
    db.run_sync(
        lambda c: c.execute(
            "UPDATE household SET ask_threshold_cents=40 WHERE id=?", (str(fx.HOUSEHOLD),)
        )
    )
    opened = db.run_sync(
        lambda c: resolve_and_store(
            c,
            episode(),
            now=fx.T0 + timedelta(hours=2),
            location_verified=True,
            source_event_id=stable_id("energy", "p3-integration"),
        )
    )
    request = opened.decision.confirmation_request
    assert request is not None

    def create_notification(conn):
        svc = NotificationService(
            SqliteNotificationRepository(conn),
            SqliteResidentDirectory(conn),
            lambda: fx.T0 + timedelta(hours=2),
        )
        return svc.on_confirmation_needed(
            request,
            source_event_id=stable_id("billing.confirmation_needed", "p3-integration"),
            household_id=fx.HOUSEHOLD,
            correlation_id=fx.CORRELATION,
            provenance=fx.SIM_INFERRED,
        )

    created = db.run_sync(create_notification)
    assert created.notification is not None
    assert created.notification.status is NotificationStatus.unread
    notification_id = created.notification.id

    def p3_vote(resident, target):
        def vote(conn):
            svc = NotificationService(
                SqliteNotificationRepository(conn),
                SqliteResidentDirectory(conn),
                lambda: fx.T0 + timedelta(hours=3),
            )
            return svc.respond(
                notification_id,
                household_id=fx.HOUSEHOLD,
                resident_id=resident,
                action_id="other",
                target_resident_id=target,
            )

        return db.run_sync(vote)

    first_vote = p3_vote(fx.ANA, fx.DIOGO)
    first_event = first_vote.events[0]
    first_result = db.run_sync(
        lambda c: record_confirmation_outcome(
            c,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            first_event.data.response,
            first_event.data.ref,
            first_event.data.outcome,
            now=first_event.ts,
            source_event_id=first_event.id,
        )
    )
    assert first_result.revision == 1
    assert first_result.decision.status is PolicyStatus.pending

    second_vote = p3_vote(fx.BRUNO, fx.DIOGO)
    second_event = second_vote.events[0]
    final = db.run_sync(
        lambda c: record_confirmation_outcome(
            c,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            second_event.data.response,
            second_event.data.ref,
            second_event.data.outcome,
            now=second_event.ts,
            source_event_id=second_event.id,
        )
    )
    assert final.decision.status is PolicyStatus.confirmed
    assert final.decision.reason is PolicyReason.response_other
    assert final.decision.target_resident_id == fx.DIOGO
    assert final.revision == 2
    attr = as_attribution(
        final.decision,
        attribution_id=stable_id("attr", "p3-integration"),
        actor=Audit(at=final.decision.decided_at, by_resident_id=fx.BRUNO),
    )
    assert attr.method is AttributionMethod.confirmation
    assert_single_active([attr])
    closed = episode()
    shares = shares_from_attributions([attr], {closed.id: closed})
    assert shares[0].resident_id == fx.DIOGO
    bill, _ = fx.bill_a()
    allocations = allocate(bill, {tenant: None for tenant in fx.TENANTS}, shares)
    assert sum(allocation.amount_cents for allocation in allocations) == bill.total_cents
    assert sum(allocation.attributed_total_wh for allocation in allocations) == closed.energy_wh
    with pytest.raises(AlreadyRespondedError):
        p3_vote(fx.BRUNO, fx.DIOGO)


def test_bedroom_contract_not_appliance_owner(db):
    outcome = decision(db, episode(fx.ROOM_ANA))
    assert outcome.status is PolicyStatus.automatic
    assert outcome.target_resident_id == fx.ANA
    assert outcome.method is AttributionMethod.room_rule
    assert outcome.reason is PolicyReason.room_contract
    attr = as_attribution(
        outcome,
        attribution_id=stable_id("attr", "room"),
        actor=Audit(at=outcome.decided_at, by_system="households.policies"),
    )
    assert attr.target_resident_id == fx.ANA
    assert_single_active([attr])


def test_ended_tenant_keeps_historical_room_and_tenant_change_is_respected(db):
    old = fx.memberships()[0]

    def modify(conn):
        conn.execute(
            "UPDATE membership SET status='ended', ends_on='2026-11-18' WHERE id=?", (str(old.id),)
        )
        new = Membership(
            id=stable_id("membership", "new-ana"),
            household_id=fx.HOUSEHOLD,
            resident_id=stable_id("resident", "new-ana"),
            role=MembershipRole.tenant,
            room_id=fx.ROOM_ANA,
            starts_on=date(2026, 11, 19),
            status=MembershipStatus.active,
        )
        from homemind.contracts.household import Resident
        from homemind.features.households.repo import insert_membership, insert_resident

        insert_resident(conn, Resident(id=new.resident_id, display_name="Novo inquilino"))
        insert_membership(conn, new)
        return new

    new = db.run_sync(modify)
    members = db.run_sync(
        lambda conn: [
            Membership(**dict(r))
            for r in conn.execute(
                "SELECT * FROM membership WHERE household_id = ?", (str(fx.HOUSEHOLD),)
            )
        ]
    )
    before = decision(db, episode(fx.ROOM_ANA), memberships=members)
    after_time = fx.T0 + timedelta(days=2)
    after = decision(
        db,
        episode(fx.ROOM_ANA, after_time),
        now=after_time + timedelta(hours=2),
        memberships=members,
    )
    crossing_time = fx.T0 + timedelta(days=1, hours=4)  # 18 Nov, 23:00 UTC
    crossing_episode = replace(
        episode(fx.ROOM_ANA, crossing_time),
        ended_at=crossing_time + timedelta(hours=2),
    )
    crossing = decision(
        db,
        crossing_episode,
        now=crossing_time + timedelta(hours=3),
        memberships=members,
    )
    assert before.target_resident_id == fx.ANA
    assert after.target_resident_id == new.resident_id
    assert crossing.reason is PolicyReason.room_occupancy_unknown
    assert crossing.target_resident_id is None


def test_uncertain_room_and_unverified_location_never_assign(db):
    assert (
        decision(db, episode(fx.ROOM_ANA), verified=False).reason
        is PolicyReason.location_unverified
    )
    unknown = replace(episode(), location=LocationKind.unknown, room_id=None)
    assert decision(db, unknown).status is PolicyStatus.pending
    unknown_room = episode(stable_id("room", "missing"))
    assert decision(db, unknown_room).target_resident_id is None


def test_vacant_room_and_common_appliance_never_use_owner_as_payer(db):
    vacant = decision(db, episode(fx.ROOM_ANA), memberships=[])
    assert vacant.status is PolicyStatus.pending
    assert vacant.reason is PolicyReason.room_occupancy_unknown

    p = replace(context(db)[0], common_area_rule=CommonAreaRule.equal)
    common_appliance = replace(episode(), appliance_owner_resident_id=None)
    result = decision(db, common_appliance, policy=p)
    assert result.target_type is AttributionTarget.common
    assert result.target_resident_id is None


def test_common_equal_is_automatic_even_if_heater_is_personal(db):
    p = PolicyVersion(
        household_id=fx.HOUSEHOLD,
        version=1,
        valid_from=fx.T0 - timedelta(days=30),
        common_area_rule=CommonAreaRule.equal,
    )
    result = decision(db, policy=p)
    assert result.target_type is AttributionTarget.common
    assert result.method is AttributionMethod.equal_rule
    assert result.status is PolicyStatus.automatic


def test_common_ask_threshold_missing_cost_and_open_episode(db):
    p, _, _ = context(db)
    assert decision(db, policy=p).reason is PolicyReason.below_threshold  # 48c < 50c
    use_at_threshold = replace(
        episode(),
        cost_estimate=replace(
            episode().cost_estimate,
            cents=50,
            price_millicents_per_kwh=16_667,
        ),
    )
    assert decision(db, use_at_threshold, policy=p).reason is PolicyReason.awaiting_confirmation
    requested = replace(p, ask_threshold_cents=40)
    assert decision(db, policy=requested).reason is PolicyReason.awaiting_confirmation
    without_cost = replace(episode(), cost_estimate=None)
    assert decision(db, without_cost, policy=requested).reason is PolicyReason.cost_unknown
    assert (
        decision(db, fx.consumption(), policy=requested).reason is PolicyReason.consumption_ongoing
    )
    discarded = replace(episode(), status="discarded")
    assert decision(db, discarded, policy=requested).reason is PolicyReason.consumption_discarded


def test_personal_heater_borrowed_by_carla_and_three_choices(db):
    p = replace(context(db)[0], ask_threshold_cents=40)
    pending = decision(db, policy=p)
    assert pending.confirmation_request.eligible_resident_ids == sorted(fx.TENANTS, key=str)
    mine = apply_confirmation_outcome(
        pending,
        reply("mine"),
        REF,
        ConfirmationOutcome(
            verdict=ConfirmationVerdict.self_claimed,
            resident_id=fx.CARLA,
            votes=1,
            votes_needed=2,
        ),
        now=fx.T0 + timedelta(hours=3),
    )
    assert mine.status is PolicyStatus.confirmed
    assert mine.reason is PolicyReason.response_mine
    assert mine.target_resident_id == fx.CARLA  # not its owner Bruno
    attr = as_attribution(
        mine,
        attribution_id=stable_id("attr", "carla"),
        actor=Audit(at=mine.decided_at, by_resident_id=fx.CARLA),
    )
    assert attr.method is AttributionMethod.confirmation
    with pytest.raises(PolicyConflictError):
        apply_confirmation_outcome(
            mine,
            reply("everyone"),
            REF,
            ConfirmationOutcome(verdict=ConfirmationVerdict.everyone, votes=4, votes_needed=2),
            now=fx.T0 + timedelta(hours=3),
        )
    everyone = apply_confirmation_outcome(
        pending,
        reply("unknown", fx.DIOGO),
        REF,
        ConfirmationOutcome(verdict=ConfirmationVerdict.everyone, votes=4, votes_needed=2),
        now=fx.T0 + timedelta(hours=3),
    )
    assert everyone.status is PolicyStatus.confirmed
    assert everyone.target_type is AttributionTarget.common
    pending_vote = apply_confirmation_outcome(
        pending,
        reply("unknown"),
        REF,
        ConfirmationOutcome(verdict=ConfirmationVerdict.pending, votes=1, votes_needed=2),
        now=fx.T0 + timedelta(hours=3),
    )
    assert pending_vote == pending


def test_unauthorized_wrong_ref_and_expired_reply_are_rejected(db):
    p = replace(context(db)[0], ask_threshold_cents=40)
    pending = decision(db, policy=p)
    self_claim = ConfirmationOutcome(
        verdict=ConfirmationVerdict.self_claimed,
        resident_id=fx.LANDLORD,
        votes=1,
        votes_needed=2,
    )
    with pytest.raises(PolicyConflictError):
        apply_confirmation_outcome(
            pending, reply("mine", fx.LANDLORD), REF, self_claim, now=fx.T0 + timedelta(hours=3)
        )
    wrong = NotificationRef(type=RefType.consumption_event, id=stable_id("other"))
    with pytest.raises(PolicyConflictError):
        apply_confirmation_outcome(
            pending,
            reply("mine"),
            wrong,
            ConfirmationOutcome(
                verdict=ConfirmationVerdict.self_claimed,
                resident_id=fx.CARLA,
                votes=1,
                votes_needed=2,
            ),
            now=fx.T0 + timedelta(hours=3),
        )
    with pytest.raises(PolicyExpiredError):
        apply_confirmation_outcome(
            pending,
            reply("mine", at=fx.T0 + timedelta(hours=27)),
            REF,
            ConfirmationOutcome(
                verdict=ConfirmationVerdict.self_claimed,
                resident_id=fx.CARLA,
                votes=1,
                votes_needed=2,
            ),
            now=fx.T0 + timedelta(hours=27),
        )
    expired = expire_decision(
        pending,
        ConfirmationOutcome(verdict=ConfirmationVerdict.everyone, votes=1, votes_needed=2),
        expired=True,
        now=fx.T0 + timedelta(hours=27),
    )
    assert expired.method is AttributionMethod.equal_fallback
    assert (
        expire_decision(
            expired,
            ConfirmationOutcome(verdict=ConfirmationVerdict.everyone, votes=1, votes_needed=2),
            expired=True,
            now=fx.T0 + timedelta(hours=100),
        )
        == expired
    )
    with pytest.raises(PolicyConflictError):
        as_attribution(
            pending,
            attribution_id=stable_id("attr", "pending"),
            actor=Audit(at=fx.T0, by_system="households.policies"),
        )


def test_presence_c_is_model_only_even_with_evidence(db):
    p = replace(context(db)[0], common_area_rule=CommonAreaRule.presence)
    result = decision(db, policy=p)
    assert result.reason is PolicyReason.presence_deferred
    assert result.target_resident_id is None


def test_repository_processes_intermediate_and_final_p3_outcomes_once(db):
    db.run_sync(
        lambda c: c.execute(
            "UPDATE household SET ask_threshold_cents=40 WHERE id=?", (str(fx.HOUSEHOLD),)
        )
    )
    source = stable_id("energy", "episode")
    initial = db.run_sync(
        lambda conn: resolve_and_store(
            conn,
            episode(),
            now=fx.T0 + timedelta(hours=2),
            location_verified=True,
            source_event_id=source,
        )
    )
    again = db.run_sync(
        lambda conn: resolve_and_store(
            conn,
            episode(),
            now=fx.T0 + timedelta(hours=9),
            location_verified=True,
            source_event_id=source,
        )
    )
    assert initial == again and initial.revision == 1
    pending_outcome = ConfirmationOutcome(
        verdict=ConfirmationVerdict.pending, votes=1, votes_needed=2
    )
    intermediate_event_id = stable_id("notification", "intermediate")
    intermediate = db.run_sync(
        lambda conn: record_confirmation_outcome(
            conn,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            reply("unknown", fx.ANA),
            REF,
            pending_outcome,
            now=fx.T0 + timedelta(hours=3),
            source_event_id=intermediate_event_id,
        )
    )
    assert intermediate.revision == 1 and intermediate.decision.status is PolicyStatus.pending
    final_outcome = ConfirmationOutcome(
        verdict=ConfirmationVerdict.self_claimed,
        resident_id=fx.CARLA,
        votes=2,
        votes_needed=2,
    )
    final_event_id = stable_id("notification", "final")
    final = db.run_sync(
        lambda conn: record_confirmation_outcome(
            conn,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            reply("mine", fx.CARLA),
            REF,
            final_outcome,
            now=fx.T0 + timedelta(hours=4),
            source_event_id=final_event_id,
        )
    )
    repeated = db.run_sync(
        lambda conn: record_confirmation_outcome(
            conn,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            reply("mine", fx.CARLA),
            REF,
            final_outcome,
            now=fx.T0 + timedelta(hours=4),
            source_event_id=final_event_id,
        )
    )
    # A delayed intermediate event after the final decision cannot roll it back.
    delayed = db.run_sync(
        lambda conn: record_confirmation_outcome(
            conn,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            reply("unknown", fx.BRUNO),
            REF,
            pending_outcome,
            now=fx.T0 + timedelta(hours=5),
            source_event_id=stable_id("notification", "delayed-intermediate"),
        )
    )
    final = db.run_sync(lambda conn: load_decision(conn, fx.HOUSEHOLD, fx.CONSUMPTION))
    assert final.decision.status is PolicyStatus.confirmed and final.revision == 2
    assert repeated == final and delayed == final
    assert (
        db.run_sync(
            lambda c: c.execute("SELECT count(*) FROM household_policy_audit").fetchone()[0]
        )
        == 2
    )


def test_timeout_once_no_late_or_repeated_response(db):
    db.run_sync(
        lambda c: c.execute(
            "UPDATE household SET ask_threshold_cents=40 WHERE id=?", (str(fx.HOUSEHOLD),)
        )
    )
    db.run_sync(
        lambda conn: resolve_and_store(
            conn,
            episode(),
            now=fx.T0 + timedelta(hours=2),
            location_verified=True,
            source_event_id=stable_id("energy", "timeout"),
        )
    )
    before_deadline = db.run_sync(
        lambda conn: expire_and_store(
            conn,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            ConfirmationOutcome(verdict=ConfirmationVerdict.pending, votes=1, votes_needed=2),
            expired=False,
            now=fx.T0 + timedelta(hours=25),
        )
    )
    assert before_deadline.decision.status is PolicyStatus.pending
    expired = db.run_sync(
        lambda conn: expire_and_store(
            conn,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            ConfirmationOutcome(verdict=ConfirmationVerdict.everyone, votes=1, votes_needed=2),
            expired=True,
            now=fx.T0 + timedelta(hours=27),
        )
    )
    assert expired.decision.status is PolicyStatus.fallback
    assert (
        db.run_sync(
            lambda conn: expire_and_store(
                conn,
                fx.HOUSEHOLD,
                fx.CONSUMPTION,
                ConfirmationOutcome(verdict=ConfirmationVerdict.everyone, votes=1, votes_needed=2),
                expired=True,
                now=fx.T0 + timedelta(hours=50),
            )
        )
        == expired
    )
    late = db.run_sync(
        lambda conn: record_confirmation_outcome(
            conn,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            reply("mine"),
            REF,
            ConfirmationOutcome(
                verdict=ConfirmationVerdict.self_claimed,
                resident_id=fx.CARLA,
                votes=1,
                votes_needed=2,
            ),
            now=fx.T0 + timedelta(hours=28),
            source_event_id=stable_id("late"),
        )
    )
    assert late == expired  # P3 already resolved the request; delayed events cannot replace it.


def test_real_p3_expiration_outcome_controls_household_fallback(db):
    db.run_sync(
        lambda c: c.execute(
            "UPDATE household SET ask_threshold_cents=40 WHERE id=?", (str(fx.HOUSEHOLD),)
        )
    )
    opened = db.run_sync(
        lambda conn: resolve_and_store(
            conn,
            episode(),
            now=fx.T0 + timedelta(hours=2),
            location_verified=True,
            source_event_id=stable_id("energy", "p3-timeout"),
        )
    )
    request = opened.decision.confirmation_request
    assert request is not None
    now = {"value": fx.T0 + timedelta(hours=2)}

    def notification_service(conn):
        return NotificationService(
            SqliteNotificationRepository(conn),
            SqliteResidentDirectory(conn),
            lambda: now["value"],
        )

    created = db.run_sync(
        lambda conn: notification_service(conn).on_confirmation_needed(
            request,
            source_event_id=stable_id("billing.confirmation_needed", "p3-timeout"),
            household_id=fx.HOUSEHOLD,
            correlation_id=fx.CORRELATION,
            provenance=fx.SIM_INFERRED,
        )
    )
    assert created.notification is not None
    notification_id = created.notification.id
    original_eligible = created.notification.responder_ids

    db.run_sync(
        lambda conn: conn.execute(
            "UPDATE membership SET status='ended', ends_on='2026-11-17'"
            " WHERE household_id=? AND resident_id=?",
            (str(fx.HOUSEHOLD), str(fx.ANA)),
        )
    )
    with pytest.raises(NotificationNotFoundError):
        db.run_sync(
            lambda conn: notification_service(conn).respond(
                notification_id,
                household_id=fx.HOUSEHOLD,
                resident_id=fx.ANA,
                action_id="mine",
            )
        )
    # P3 freezes the eligible list at notification creation; current membership gates new votes.
    stored_before_expiry = db.run_sync(
        lambda conn: SqliteNotificationRepository(conn).get(notification_id)
    )
    assert stored_before_expiry.responder_ids == original_eligible

    now["value"] = fx.T0 + timedelta(hours=25)
    early_outcome = created.notification.outcome(now["value"])
    assert early_outcome.verdict is ConfirmationVerdict.pending
    early = db.run_sync(
        lambda conn: expire_and_store(
            conn,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            early_outcome,
            expired=created.notification.is_expired(now["value"]),
            now=now["value"],
        )
    )
    assert early.decision.status is PolicyStatus.pending

    now["value"] = fx.T0 + timedelta(hours=26)
    expired = db.run_sync(lambda conn: notification_service(conn).expire_due())
    (p3_notification,) = [n for n in expired if n.id == notification_id]
    p3_outcome = p3_notification.outcome(now["value"])
    assert p3_outcome.verdict is ConfirmationVerdict.everyone
    fallback = db.run_sync(
        lambda conn: expire_and_store(
            conn,
            fx.HOUSEHOLD,
            fx.CONSUMPTION,
            p3_outcome,
            expired=p3_notification.is_expired(now["value"]),
            now=now["value"],
        )
    )
    assert fallback.decision.status is PolicyStatus.fallback
    assert fallback.decision.method is AttributionMethod.equal_fallback


def test_new_policy_affects_future_only_and_old_decision_is_untouched(db):
    before = db.run_sync(
        lambda conn: resolve_and_store(
            conn,
            episode(),
            now=fx.T0 + timedelta(hours=2),
            location_verified=True,
            source_event_id=stable_id("event", "old"),
        )
    )
    v2 = PolicyVersion(
        household_id=fx.HOUSEHOLD,
        version=2,
        valid_from=fx.T0 + timedelta(days=1),
        common_area_rule=CommonAreaRule.equal,
    )
    db.run_sync(lambda conn: append_policy(conn, v2, now=fx.T0))
    new = db.run_sync(
        lambda conn: resolve_and_store(
            conn,
            episode(when=fx.T0 + timedelta(days=2), event_id=stable_id("episode", "new")),
            now=fx.T0 + timedelta(days=2, hours=2),
            location_verified=True,
            source_event_id=stable_id("event", "new"),
        )
    )
    assert before.decision.policy_version == 1
    assert new.decision.policy_version == 2
    assert new.decision.method is AttributionMethod.equal_rule
    assert (
        db.run_sync(
            lambda conn: load_decision(
                conn,
                fx.HOUSEHOLD,
                fx.CONSUMPTION,
            )
        )
        == before
    )
    with pytest.raises(PolicyConflictError):
        db.run_sync(
            lambda conn: append_policy(
                conn,
                replace(v2, version=3, valid_from=fx.T0 - timedelta(days=1)),
                now=fx.T0,
            )
        )


def test_event_bus_transactional_confirmation_intent_and_idempotency(db):
    db.run_sync(
        lambda c: c.execute(
            "UPDATE household SET ask_threshold_cents=40 WHERE id=?", (str(fx.HOUSEHOLD),)
        )
    )

    def handler(conn, stored):
        result = resolve_and_store(
            conn,
            stored.event.data,
            now=fx.T0 + timedelta(hours=2),
            location_verified=True,
            source_event_id=stored.event.id,
        )
        intent = confirmation_intent(result.decision, correlation_id=stored.event.correlation_id)
        return [intent] if intent else []

    async def run():
        bus = EventBus(db)
        bus.subscribe("test.house04", handler, ["energy.consumption_closed"])
        event = EnergyConsumptionClosed(
            id=stable_id("event", "closed"),
            ts=fx.T0 + timedelta(hours=2),
            household_id=fx.HOUSEHOLD,
            correlation_id=fx.CORRELATION,
            provenance=fx.SIM_INFERRED,
            data=episode(),
        )
        stored = await bus.publish(event)
        assert await bus.deliver("test.house04", stored)
        assert not await bus.deliver("test.house04", stored)
        rows = db.run_sync(
            lambda conn: conn.execute("SELECT type FROM domain_event ORDER BY seq").fetchall()
        )
        assert [r["type"] for r in rows] == [
            "energy.consumption_closed",
            "billing.confirmation_needed",
        ]
        assert (
            db.run_sync(
                lambda conn: conn.execute("SELECT count(*) FROM household_policy_audit").fetchone()[
                    0
                ]
            )
            == 1
        )

    asyncio.run(run())
