"""Deterministic HOUSE-04 policies: no I/O, side effects, money or presence guesses.

The caller (P4) supplies verified location from HOUSE-03, a policy snapshot
effective at consumption START, room/contract snapshots and an injected clock.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.billing import (
    Attribution,
    AttributionMethod,
    AttributionTarget,
)
from homemind.contracts.common import Audit, Provenance, ValueKind, replace, stable_id
from homemind.contracts.domain_events import BillingConfirmationNeeded
from homemind.contracts.energy import ConsumptionEvent, ConsumptionStatus, LocationKind
from homemind.contracts.household import (
    CommonAreaRule,
    Membership,
    MembershipRole,
    MembershipStatus,
    Room,
    RoomKind,
)
from homemind.contracts.notification import (
    ConfirmationChoice,
    ConfirmationRequest,
    NotificationRef,
    NotificationResponse,
    RefType,
)
from homemind.contracts.policy import (
    PolicyDecision,
    PolicyReason,
    PolicyStatus,
    PolicyVersion,
)


class PolicyConflictError(ValueError):
    """Resposta, transição ou contexto incompatível (não altera o estado)."""


class PolicyExpiredError(PolicyConflictError):
    """Resposta recebida depois do prazo (409 em P3/P4)."""


def _covers(m: Membership, start, end) -> bool:
    """A contract can have ended NOW while still covering a PAST consumption."""
    return (
        m.role is MembershipRole.tenant
        and m.status is not MembershipStatus.invited
        and m.starts_on <= start
        and (m.ends_on is None or m.ends_on >= end)
    )


def _overlaps(m: Membership, start, end) -> bool:
    return (
        m.role is MembershipRole.tenant
        and m.status is not MembershipStatus.invited
        and m.starts_on <= end
        and (m.ends_on is None or m.ends_on >= start)
    )


def _decision(
    c: ConsumptionEvent,
    p: PolicyVersion,
    now,
    status: PolicyStatus,
    reason: PolicyReason,
    *,
    target: AttributionTarget | None = None,
    resident: UUID | None = None,
    method: AttributionMethod | None = None,
    request: ConfirmationRequest | None = None,
    expires_at=None,
) -> PolicyDecision:
    # A policy uses contractual or human-declared facts. This provenance describes
    # the DECISION, not the accuracy of the underlying meter/signature.
    provenance = Provenance(origin=c.provenance.origin, kind=ValueKind.measured)
    return PolicyDecision(
        household_id=c.household_id,
        consumption_event_id=c.id,
        policy_version=p.version,
        status=status,
        reason=reason,
        decided_at=now,
        provenance=provenance,
        target_type=target,
        target_resident_id=resident,
        method=method,
        confirmation_request=request,
        expires_at=expires_at,
    )


def resolve_policy(
    consumption: ConsumptionEvent,
    policy: PolicyVersion,
    rooms: list[Room],
    memberships: list[Membership],
    *,
    now,
    household_timezone: str,
    location_verified: bool = False,
    appliance_name: str | None = None,
) -> PolicyDecision:
    """Resolve one episode without assuming device, appliance owner or presence is the payer.

    `location_verified` MUST come from independently verified HOUSE-03 evidence;
    the main-meter demo plug, device.room_id and a probabilistic signature alone do not suffice.
    """
    c, p = consumption, policy
    if c.household_id != p.household_id:
        raise ValueError("política de outra casa")
    if c.started_at < p.valid_from:
        raise ValueError("snapshot posterior ao início do consumo")
    if now < c.started_at:
        raise ValueError("relógio anterior ao consumo")
    if c.status is ConsumptionStatus.discarded:
        return _decision(c, p, now, PolicyStatus.pending, PolicyReason.consumption_discarded)
    if c.status is ConsumptionStatus.ongoing:
        return _decision(c, p, now, PolicyStatus.pending, PolicyReason.consumption_ongoing)
    if not location_verified or c.location is LocationKind.unknown:
        return _decision(c, p, now, PolicyStatus.pending, PolicyReason.location_unverified)

    zone = ZoneInfo(household_timezone)
    start = c.started_at.astimezone(zone).date()
    end = c.ended_at.astimezone(zone).date()
    room = next((r for r in rooms if r.id == c.room_id and r.household_id == c.household_id), None)
    if c.location is LocationKind.room:
        if room is None or room.kind is not RoomKind.bedroom:
            return _decision(c, p, now, PolicyStatus.pending, PolicyReason.room_occupancy_unknown)
        relevant = [
            m
            for m in memberships
            if m.household_id == c.household_id
            and m.room_id == room.id
            and _overlaps(m, start, end)
        ]
        whole = [m for m in relevant if _covers(m, start, end)]
        if len(relevant) != 1 or len(whole) != 1:
            return _decision(c, p, now, PolicyStatus.pending, PolicyReason.room_occupancy_unknown)
        return _decision(
            c,
            p,
            now,
            PolicyStatus.automatic,
            PolicyReason.room_contract,
            target=AttributionTarget.resident,
            resident=whole[0].resident_id,
            method=AttributionMethod.room_rule,
        )

    if c.room_id is not None and (room is None or room.kind is not RoomKind.common):
        return _decision(c, p, now, PolicyStatus.pending, PolicyReason.location_unverified)
    if p.common_area_rule is CommonAreaRule.presence:
        # C is intentionally not implemented for F1, even when presence data is supplied.
        return _decision(c, p, now, PolicyStatus.pending, PolicyReason.presence_deferred)
    if p.common_area_rule is CommonAreaRule.equal:
        return _decision(
            c,
            p,
            now,
            PolicyStatus.automatic,
            PolicyReason.equal_rule,
            target=AttributionTarget.common,
            method=AttributionMethod.equal_rule,
        )
    if c.cost_estimate is None:
        return _decision(c, p, now, PolicyStatus.pending, PolicyReason.cost_unknown)
    if c.cost_estimate.cents < p.ask_threshold_cents:
        return _decision(
            c,
            p,
            now,
            PolicyStatus.automatic,
            PolicyReason.below_threshold,
            target=AttributionTarget.common,
            method=AttributionMethod.equal_rule,
        )
    today = now.astimezone(zone).date()
    eligible = sorted(
        {
            m.resident_id
            for m in memberships
            if m.household_id == c.household_id
            and _covers(m, start, start)
            and _covers(m, today, today)
        },
        key=str,
    )
    if not eligible:
        return _decision(c, p, now, PolicyStatus.pending, PolicyReason.no_eligible_residents)
    expires = now + timedelta(hours=p.ask_timeout_hours)
    request = ConfirmationRequest(
        consumption_event_id=c.id,
        appliance_name=appliance_name,
        estimated_cost_cents=c.cost_estimate.cents,
        eligible_resident_ids=eligible,
        expires_at=expires,
    )
    return _decision(
        c,
        p,
        now,
        PolicyStatus.pending,
        PolicyReason.awaiting_confirmation,
        request=request,
        expires_at=expires,
    )


def apply_response(
    decision: PolicyDecision,
    response: NotificationResponse,
    ref: NotificationRef | None,
    *,
    now,
) -> PolicyDecision:
    """First valid reply wins. Unknown consumes the vote but leaves a timeout fallback."""
    if decision.status is not PolicyStatus.pending or decision.confirmation_request is None:
        raise PolicyConflictError("não há confirmação aberta")
    if (
        ref is None
        or ref.type is not RefType.consumption_event
        or ref.id != decision.consumption_event_id
    ):
        raise PolicyConflictError("resposta não corresponde ao consumo")
    if now >= decision.expires_at or response.responded_at >= decision.expires_at:
        raise PolicyExpiredError("pedido expirado")
    if response.responded_at < decision.decided_at or response.responded_at > now:
        raise PolicyConflictError("instante da resposta inválido")
    if response.resident_id not in decision.confirmation_request.eligible_resident_ids:
        raise PolicyConflictError("morador não elegível")
    try:
        choice = ConfirmationChoice(response.action_id)
    except ValueError as exc:
        raise PolicyConflictError("resposta desconhecida") from exc
    if choice is ConfirmationChoice.unknown:
        return replace(
            decision,
            reason=PolicyReason.response_unknown,
            decided_at=now,
            confirmation_request=None,
        )
    if choice is ConfirmationChoice.everyone:
        return replace(
            decision,
            status=PolicyStatus.confirmed,
            reason=PolicyReason.response_everyone,
            target_type=AttributionTarget.common,
            method=AttributionMethod.confirmation,
            confirmation_request=None,
            expires_at=None,
            decided_at=now,
        )
    return replace(
        decision,
        status=PolicyStatus.confirmed,
        reason=PolicyReason.response_mine,
        target_type=AttributionTarget.resident,
        target_resident_id=response.resident_id,
        method=AttributionMethod.confirmation,
        confirmation_request=None,
        expires_at=None,
        decided_at=now,
    )


def expire_decision(decision: PolicyDecision, *, now) -> PolicyDecision:
    """Only confirmation-pending decisions can fallback, never unknown location or room."""
    if (
        decision.status is not PolicyStatus.pending
        or decision.expires_at is None
        or now < decision.expires_at
    ):
        return decision
    if decision.reason not in (PolicyReason.awaiting_confirmation, PolicyReason.response_unknown):
        return decision
    return replace(
        decision,
        status=PolicyStatus.fallback,
        reason=PolicyReason.confirmation_timeout,
        target_type=AttributionTarget.common,
        method=AttributionMethod.equal_fallback,
        confirmation_request=None,
        expires_at=None,
        decided_at=now,
    )


def confirmation_intent(
    decision: PolicyDecision,
    *,
    correlation_id: UUID,
) -> BillingConfirmationNeeded | None:
    """Typed event for P4 to append through its event-bus transaction (never send P3 directly).

    The ID is stable across retries. P3 is the only module creating notifications.
    """
    if decision.confirmation_request is None:
        return None
    return BillingConfirmationNeeded(
        id=stable_id(
            "house-04.confirmation", str(decision.household_id), str(decision.consumption_event_id)
        ),
        ts=decision.decided_at,
        household_id=decision.household_id,
        correlation_id=correlation_id,
        provenance=decision.provenance,
        data=decision.confirmation_request,
    )


def as_attribution(
    decision: PolicyDecision,
    *,
    attribution_id: UUID,
    actor: Audit,
    supersedes_id: UUID | None = None,
) -> Attribution:
    """P4 adapter, NEVER persists; P4 owns the unique active attribution constraint."""
    if decision.status is PolicyStatus.pending:
        raise PolicyConflictError("consumo ainda não atribuído")
    if decision.method is AttributionMethod.confirmation:
        if actor.by_resident_id != decision.target_resident_id and (
            decision.target_type is AttributionTarget.resident
        ):
            raise PolicyConflictError("ator diferente do responsável que confirmou")
        if actor.by_resident_id is None:
            raise PolicyConflictError("a confirmação exige ator humano")
    return Attribution(
        id=attribution_id,
        household_id=decision.household_id,
        consumption_event_id=decision.consumption_event_id,
        target_type=decision.target_type,
        target_resident_id=decision.target_resident_id,
        method=decision.method,
        provenance=decision.provenance,
        decided_by=actor,
        supersedes_id=supersedes_id,
    )
