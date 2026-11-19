"""Painel de segurança SIMULADO (SAFE-02 #115): estado, propostas de armar/desarmar e a vista da
app. Síncrono sobre SQLite (`db.run`); nunca toca em MCP, conectores nem hardware.

Invariantes (todos testados):
- só existe fonte SIMULADA do painel (D-07/P-01: leitura/armamento real = MCP-04, PLANEADO). O
  estado vem do último `safety.security_changed` da casa; sem leitura é `unknown`, nunca se assume
  armado nem desarmado; numa casa real o painel está indisponível e nada se propõe;
- armar/desarmar são duas fases: uma proposta (`safety.security_action`, `proposed`, caduca em 10
  min) e uma confirmação humana explícita de um morador (`confirmed`) que só muda o painel
  SIMULADO. `executed` é sempre falso: o resultado é sempre rotulado SIMULADO;
- uma proposta pendente de cada vez; confirmar/cancelar é compare-and-set (uma proposta decidida
  ou caducada nunca se decide outra vez); o painel nunca decide AWAY (ver `assess`);
- a vista não leva dados pessoais (nem quem propôs nem quem confirmou) e nunca vai ao senhorio.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID

from homemind.contracts.common import (
    ContractModel,
    Origin,
    Provenance,
    UtcDatetime,
    ValueKind,
    new_id,
    stable_id,
)
from homemind.contracts.domain_events import (
    DomainEvent,
    SafetySecurityAction,
    SafetySecurityChanged,
)
from homemind.contracts.safety import (
    AwayStatus,
    SecurityAction,
    SecurityActionKind,
    SecurityActionStatus,
    SecurityPanelState,
    SecurityPanelStatus,
)
from homemind.core.events import append_event, load_events
from homemind.features.safety.texts import ASSESSMENT_TEXT, PANEL_RESULT, SECURITY_NOTICE

PROPOSAL_TTL = timedelta(minutes=10)
SIM = Provenance(origin=Origin.simulated, kind=ValueKind.inferred)

NOT_FOUND = "proposal_not_found"
NOT_PENDING = "proposal_not_pending"
EXPIRED = "proposal_expired"
PENDING_EXISTS = "proposal_pending"
NOT_APPLICABLE = "action_not_applicable"
UNAVAILABLE = "panel_unavailable"


class Assessment(StrEnum):
    consistent = "consistent"  # armado e casa aparentemente vazia
    suggest_arm = "suggest_arm"  # desarmado e casa aparentemente vazia
    armed_with_people = "armed_with_people"  # armado mas há sinais de presença: pergunta
    normal = "normal"  # desarmado e há pessoas
    no_signal = "no_signal"  # painel ou presença sem leitura fiável


def assess(away: AwayStatus, panel: SecurityPanelStatus) -> Assessment:
    """O painel é só um sinal extra que corrobora ou contradiz o estado AWAY; nunca o decide
    sozinho: com o painel ou a presença sem leitura (`unknown`) não se infere nada (nunca se
    deduz casa vazia de uma falha de Wi-Fi nem de um painel armado)."""
    if away is AwayStatus.unknown or panel is SecurityPanelStatus.unknown:
        return Assessment.no_signal
    if away is AwayStatus.away:
        return (
            Assessment.consistent if panel is SecurityPanelStatus.armed else Assessment.suggest_arm
        )
    return Assessment.armed_with_people if panel is SecurityPanelStatus.armed else Assessment.normal


class SecurityActionView(ContractModel):
    """Sem pessoas: nem quem propôs nem quem confirmou."""

    id: UUID
    kind: SecurityActionKind
    status: SecurityActionStatus
    proposed_at: UtcDatetime
    expires_at: UtcDatetime
    executed: Literal[False] = False


class SecurityView(ContractModel):
    available: bool  # false numa casa real: não há painel real
    origin: Literal["simulated"] = "simulated"
    panel_status: SecurityPanelStatus
    panel_since: UtcDatetime | None
    away_status: AwayStatus
    assessment: Assessment
    assessment_text: str
    pending: SecurityActionView | None
    can_arm: bool
    can_disarm: bool
    notice: str = SECURITY_NOTICE
    last_result: str | None = None  # só na resposta a uma confirmação


@dataclass(frozen=True)
class Result:
    """`error` (código) ou a vista. `events` já estão no outbox: acordar o barramento depois do
    COMMIT."""

    view: SecurityView | None = None
    error: str | None = None
    events: tuple[DomainEvent, ...] = ()


# leitura ------------------------------------------------------------------------------------


def _available(conn: sqlite3.Connection, household_id: UUID) -> bool:
    row = conn.execute(
        "SELECT source_kind FROM household WHERE id = ?", (str(household_id),)
    ).fetchone()
    return row is not None and row["source_kind"] == "demo"


def _panel(conn: sqlite3.Connection, household_id: UUID) -> SecurityPanelState | None:
    found = [
        s.event.data
        for s in load_events(conn, types=("safety.security_changed",))
        if s.event.household_id == household_id
    ]
    return found[-1] if found else None


def _actions(conn: sqlite3.Connection, household_id: UUID) -> dict[UUID, SecurityAction]:
    """Último estado de cada proposta da casa."""
    latest: dict[UUID, SecurityAction] = {}
    for s in load_events(conn, types=("safety.security_action",)):
        if s.event.household_id == household_id:
            latest[s.event.data.id] = s.event.data
    return latest


def _pending(actions: dict[UUID, SecurityAction], now: datetime) -> SecurityAction | None:
    open_ = [
        a
        for a in actions.values()
        if a.status is SecurityActionStatus.proposed and a.expires_at > now
    ]
    return max(open_, key=lambda a: a.proposed_at, default=None)


def _view(
    conn: sqlite3.Connection,
    household_id: UUID,
    away: AwayStatus,
    now: datetime,
    last_result: str | None = None,
) -> SecurityView:
    available = _available(conn, household_id)
    panel = _panel(conn, household_id) if available else None
    status = panel.status if panel else SecurityPanelStatus.unknown
    pending = _pending(_actions(conn, household_id), now) if available else None
    a = assess(away, status)
    return SecurityView(
        available=available,
        panel_status=status,
        panel_since=panel.since if panel else None,
        away_status=away,
        assessment=a,
        assessment_text=ASSESSMENT_TEXT[a.value],
        pending=SecurityActionView(
            **pending.model_dump(include=set(SecurityActionView.model_fields))
        )
        if pending
        else None,
        can_arm=available and pending is None and status is not SecurityPanelStatus.armed,
        can_disarm=available and pending is None and status is not SecurityPanelStatus.disarmed,
        last_result=last_result,
    )


def get_view(
    conn: sqlite3.Connection, household_id: UUID, away: AwayStatus, now: datetime
) -> SecurityView:
    return _view(conn, household_id, away, now)


# escrita ------------------------------------------------------------------------------------


def _action_event(a: SecurityAction, ts: datetime, correlation: UUID) -> SafetySecurityAction:
    return SafetySecurityAction(
        id=stable_id("safety-event", "action", str(a.id), a.status.value),
        ts=ts,
        household_id=a.household_id,
        correlation_id=correlation,
        provenance=a.provenance,
        data=a,
    )


def propose(
    conn: sqlite3.Connection,
    household_id: UUID,
    kind: SecurityActionKind,
    away: AwayStatus,
    now: datetime,
) -> Result:
    view = _view(conn, household_id, away, now)
    if not view.available:
        return Result(error=UNAVAILABLE)
    if view.pending is not None:
        return Result(error=PENDING_EXISTS)
    if not (view.can_arm if kind is SecurityActionKind.arm else view.can_disarm):
        return Result(error=NOT_APPLICABLE)
    action = SecurityAction(
        id=new_id(),
        household_id=household_id,
        kind=kind,
        proposed_at=now,
        expires_at=now + PROPOSAL_TTL,
        provenance=SIM,
    )
    event = _action_event(action, now, action.id)
    append_event(conn, event)
    return Result(view=_view(conn, household_id, away, now), events=(event,))


def decide(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    action_id: UUID,
    confirm: bool,
    away: AwayStatus,
    now: datetime,
) -> Result:
    if not _available(conn, household_id):
        return Result(error=UNAVAILABLE)
    action = _actions(conn, household_id).get(action_id)
    if action is None:  # inexistente ou de outra casa: nunca se distingue
        return Result(error=NOT_FOUND)
    if action.status is not SecurityActionStatus.proposed:
        return Result(error=NOT_PENDING)
    if action.expires_at <= now:
        return Result(error=EXPIRED)
    decided = action.model_copy(
        update={
            "status": SecurityActionStatus.confirmed if confirm else SecurityActionStatus.cancelled,
            "decided_at": now,
            "decided_by": resident_id,
        }
    )
    events: list[DomainEvent] = [_action_event(decided, now, action.id)]
    result = None
    if confirm:
        # só o painel SIMULADO muda de estado; não há MCP, conector nem escrita física
        armed = action.kind is SecurityActionKind.arm
        panel = SecurityPanelState(
            id=stable_id("safety", "panel", str(household_id), str(action.id)),
            household_id=household_id,
            status=SecurityPanelStatus.armed if armed else SecurityPanelStatus.disarmed,
            since=now,
            provenance=SIM,
        )
        events.append(
            SafetySecurityChanged(
                id=stable_id("safety-event", "panel", str(panel.id)),
                ts=now,
                household_id=household_id,
                correlation_id=action.id,
                provenance=SIM,
                data=panel,
            )
        )
        result = PANEL_RESULT[action.kind.value]
    for e in events:
        append_event(conn, e)
    return Result(view=_view(conn, household_id, away, now, result), events=tuple(events))
