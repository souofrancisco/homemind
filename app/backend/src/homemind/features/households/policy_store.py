"""Transactional HOUSE-04 repository. Importable by P4; no feature-to-feature imports.

All operations accept the *same* sqlite connection passed to an EventBus handler,
so policy state, processed_event and follow-up events commit atomically.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from homemind.contracts.common import stable_id
from homemind.contracts.energy import ConsumptionEvent, ConsumptionStatus
from homemind.contracts.household import Membership, Room
from homemind.contracts.notification import NotificationRef, NotificationResponse
from homemind.contracts.policy import PolicyDecision, PolicyReason, PolicyStatus, PolicyVersion
from homemind.features.households.policies import (
    PolicyConflictError,
    apply_response,
    expire_decision,
    resolve_policy,
)


@dataclass(frozen=True)
class StoredPolicy:
    decision: PolicyDecision
    revision: int


def _policy(row: sqlite3.Row) -> PolicyVersion:
    return PolicyVersion(
        household_id=row["household_id"],
        version=row["version"],
        valid_from=row["valid_from"],
        common_area_rule=row["common_area_rule"],
        ask_threshold_cents=row["ask_threshold_cents"],
        ask_timeout_hours=row["ask_timeout_hours"],
        fallback_rule=row["fallback_rule"],
    )


def ensure_initial_policy(conn: sqlite3.Connection, household_id: UUID) -> PolicyVersion:
    """Snapshot F0 household settings on first use, never overwrites an existing policy."""
    row = conn.execute(
        "SELECT * FROM household_policy_version WHERE household_id = ? ORDER BY version LIMIT 1",
        (str(household_id),),
    ).fetchone()
    if row is not None:
        return _policy(row)
    house = conn.execute("SELECT * FROM household WHERE id = ?", (str(household_id),)).fetchone()
    if house is None:
        raise LookupError("casa desconhecida")
    conn.execute(
        "INSERT INTO household_policy_version"
        " (household_id, version, valid_from, common_area_rule,"
        " ask_threshold_cents, ask_timeout_hours, fallback_rule)"
        " VALUES (?,1,?,?,?,?,'equal')",
        (
            str(household_id),
            house["created_at"],
            house["common_area_rule"],
            house["ask_threshold_cents"],
            house["ask_timeout_hours"],
        ),
    )
    return _policy(
        conn.execute(
            "SELECT * FROM household_policy_version WHERE household_id = ? AND version = 1",
            (str(household_id),),
        ).fetchone()
    )


def policy_at(conn: sqlite3.Connection, household_id: UUID, at: datetime) -> PolicyVersion:
    ensure_initial_policy(conn, household_id)
    row = conn.execute(
        "SELECT * FROM household_policy_version WHERE household_id = ? AND valid_from <= ?"
        " AND (valid_until IS NULL OR valid_until > ?) ORDER BY version DESC LIMIT 1",
        (str(household_id), at.isoformat(), at.isoformat()),
    ).fetchone()
    if row is None:
        raise PolicyConflictError("nenhuma política válida para o período")
    return _policy(row)


def append_policy(
    conn: sqlite3.Connection,
    version: PolicyVersion,
    *,
    now: datetime,
) -> None:
    """Future-only amendment. Caller authenticates landlord in P5 before invoking."""
    ensure_initial_policy(conn, version.household_id)
    last = conn.execute(
        "SELECT * FROM household_policy_version WHERE household_id = ?"
        " ORDER BY version DESC LIMIT 1",
        (str(version.household_id),),
    ).fetchone()
    if (
        version.version != last["version"] + 1
        or version.valid_from <= datetime.fromisoformat(last["valid_from"])
        or version.valid_from < now
        or last["valid_until"] is not None
    ):
        raise PolicyConflictError("versão/validade inválida ou alteração retroativa")
    conn.execute(
        "UPDATE household_policy_version SET valid_until = ?"
        " WHERE household_id = ? AND version = ? AND valid_until IS NULL",
        (version.valid_from.isoformat(), str(version.household_id), last["version"]),
    )
    conn.execute(
        "INSERT INTO household_policy_version"
        " (household_id, version, valid_from, common_area_rule,"
        " ask_threshold_cents, ask_timeout_hours, fallback_rule) VALUES (?,?,?,?,?,?,?)",
        (
            str(version.household_id),
            version.version,
            version.valid_from.isoformat(),
            version.common_area_rule.value,
            version.ask_threshold_cents,
            version.ask_timeout_hours,
            version.fallback_rule,
        ),
    )


def load_decision(
    conn: sqlite3.Connection,
    household_id: UUID,
    consumption_id: UUID,
) -> StoredPolicy | None:
    row = conn.execute(
        "SELECT revision, decision_json FROM household_policy_decision"
        " WHERE household_id = ? AND consumption_event_id = ?",
        (str(household_id), str(consumption_id)),
    ).fetchone()
    if row is None:
        return None
    return StoredPolicy(PolicyDecision.model_validate_json(row["decision_json"]), row["revision"])


def _history(
    conn: sqlite3.Connection, decision: PolicyDecision, revision: int, cause: UUID
) -> None:
    conn.execute(
        "INSERT INTO household_policy_audit (household_id, consumption_event_id, revision,"
        " source_event_id, decided_at, status, reason, decision_json)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            str(decision.household_id),
            str(decision.consumption_event_id),
            revision,
            str(cause),
            decision.decided_at.isoformat(),
            decision.status.value,
            decision.reason.value,
            decision.model_dump_json(),
        ),
    )


def create_decision(
    conn: sqlite3.Connection,
    decision: PolicyDecision,
    *,
    source_event_id: UUID,
) -> StoredPolicy:
    existing = load_decision(conn, decision.household_id, decision.consumption_event_id)
    if existing is not None:
        return existing  # repeated/late detection must never replace a validated decision
    conn.execute(
        "INSERT INTO household_policy_decision"
        " (household_id, consumption_event_id, revision, status, policy_version, decision_json)"
        " VALUES (?,?,1,?,?,?)",
        (
            str(decision.household_id),
            str(decision.consumption_event_id),
            decision.status.value,
            decision.policy_version,
            decision.model_dump_json(),
        ),
    )
    _history(conn, decision, 1, source_event_id)
    return StoredPolicy(decision, 1)


def transition_decision(
    conn: sqlite3.Connection,
    decision: PolicyDecision,
    *,
    expected_revision: int,
    source_event_id: UUID,
) -> StoredPolicy:
    current = load_decision(conn, decision.household_id, decision.consumption_event_id)
    if current is None or current.revision != expected_revision:
        raise PolicyConflictError("decisão alterada entretanto")
    old = current.decision
    if (
        old.status is not PolicyStatus.pending
        or old.policy_version != decision.policy_version
        or decision.household_id != old.household_id
        or decision.consumption_event_id != old.consumption_event_id
    ):
        raise PolicyConflictError("a decisão validada é imutável")
    if old.reason is PolicyReason.consumption_ongoing:
        # Consumo finalizado: aceita outra resolução (inclusive pending sem evidência).
        pass
    elif old.reason is PolicyReason.awaiting_confirmation:
        if decision.reason not in (
            PolicyReason.response_mine,
            PolicyReason.response_everyone,
            PolicyReason.response_unknown,
            PolicyReason.confirmation_timeout,
        ):
            raise PolicyConflictError("transição inválida de confirmação")
    elif old.reason is PolicyReason.response_unknown:
        if decision.reason is not PolicyReason.confirmation_timeout:
            raise PolicyConflictError("só o timeout termina uma resposta desconhecida")
    else:
        raise PolicyConflictError("decisão pendente requer revisão explícita")
    if conn.execute(
        "SELECT 1 FROM household_policy_audit WHERE source_event_id = ?",
        (str(source_event_id),),
    ).fetchone():
        return current
    cur = conn.execute(
        "UPDATE household_policy_decision SET revision = revision + 1, status = ?,"
        " decision_json = ? WHERE household_id = ? AND consumption_event_id = ?"
        " AND revision = ? AND status = 'pending'",
        (
            decision.status.value,
            decision.model_dump_json(),
            str(decision.household_id),
            str(decision.consumption_event_id),
            expected_revision,
        ),
    )
    if cur.rowcount != 1:
        raise PolicyConflictError("perdeu a corrida de atribuição")
    _history(conn, decision, expected_revision + 1, source_event_id)
    return StoredPolicy(decision, expected_revision + 1)


def _context(
    conn: sqlite3.Connection, household_id: UUID
) -> tuple[str, list[Room], list[Membership]]:
    house = conn.execute(
        "SELECT timezone FROM household WHERE id=?", (str(household_id),)
    ).fetchone()
    if house is None:
        raise LookupError("casa desconhecida")
    rooms = [
        Room(**dict(row))
        for row in conn.execute("SELECT * FROM room WHERE household_id=?", (str(household_id),))
    ]
    memberships = [
        Membership(**dict(row))
        for row in conn.execute(
            "SELECT * FROM membership WHERE household_id=?", (str(household_id),)
        )
    ]
    return house["timezone"], rooms, memberships


def resolve_and_store(
    conn: sqlite3.Connection,
    consumption: ConsumptionEvent,
    *,
    now: datetime,
    location_verified: bool,
    source_event_id: UUID,
    appliance_name: str | None = None,
) -> StoredPolicy:
    """P4 energy handler integration: only a validated final episode can change ongoing."""
    current = load_decision(conn, consumption.household_id, consumption.id)
    if current and not (
        current.decision.reason is PolicyReason.consumption_ongoing
        and consumption.status is not ConsumptionStatus.ongoing
    ):
        return current
    tz, rooms, memberships = _context(conn, consumption.household_id)
    snapshot = policy_at(conn, consumption.household_id, consumption.started_at)
    result = resolve_policy(
        consumption,
        snapshot,
        rooms,
        memberships,
        now=now,
        household_timezone=tz,
        location_verified=location_verified,
        appliance_name=appliance_name,
    )
    if current is not None:
        return transition_decision(
            conn,
            result,
            expected_revision=current.revision,
            source_event_id=source_event_id,
        )
    return create_decision(conn, result, source_event_id=source_event_id)


def respond_and_store(
    conn: sqlite3.Connection,
    household_id: UUID,
    consumption_id: UUID,
    response: NotificationResponse,
    ref: NotificationRef | None,
    *,
    now: datetime,
    source_event_id: UUID,
) -> StoredPolicy:
    """P4 notification.responded handler; caller must verify event.household_id."""
    current = load_decision(conn, household_id, consumption_id)
    if current is None:
        raise PolicyConflictError("decisão não existe")
    decision = apply_response(current.decision, response, ref, now=now)
    return transition_decision(
        conn,
        decision,
        expected_revision=current.revision,
        source_event_id=source_event_id,
    )


def expire_and_store(
    conn: sqlite3.Connection,
    household_id: UUID,
    consumption_id: UUID,
    *,
    now: datetime,
) -> StoredPolicy | None:
    """P4 calls this from a periodic sweep or before bill finalization (no P4 money here)."""
    current = load_decision(conn, household_id, consumption_id)
    if current is None:
        return None
    expired = expire_decision(current.decision, now=now)
    if expired is current.decision:
        return current
    return transition_decision(
        conn,
        expired,
        expected_revision=current.revision,
        source_event_id=stable_id("house-04.timeout", str(household_id), str(consumption_id)),
    )
