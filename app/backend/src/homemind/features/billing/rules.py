"""Regras da casa versionadas (HOUSE-04): que regra da sala vale em cada dia.

Premissas (explícitas, documentadas em `docs/modules/billing.md`):
- A regra que decide um consumo é a do DIA em que começou (fuso da casa), como o contrato de
  quarto (`attributor.active_tenants`). Antes da primeira versão vale a política inicial da casa
  (`household`, definida na criação).
- Mudar a regra só vale a partir do dia 1 do mês seguinte: o mês em curso, as faturas fechadas
  e os consumos já decididos nunca mudam. Todos os moradores veem a mudança agendada antes de
  ela começar. Quem muda: a casa (v5.1 §6.2), por MAIORIA: um morador propõe (conta como «sim»)
  e a mudança só fica agendada quando pelo menos metade dos moradores com contrato ativo a
  aprova (como a D-32). Sem maioria até o mês começar, caduca. O senhorio só lê.
- A regra C (`presence`) ainda não existe (BILL-07): não se agenda.
- Sem resposta à pergunta nunca há cobrança individual: o prazo (`ask_timeout_hours`, da
  versão do dia do consumo) termina na divisão por igual (D-32).
"""

import sqlite3
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts import domain_events as de
from homemind.contracts.billing import (
    HouseRulesView,
    PolicyVersion,
    RuleProposal,
    RuleProposalStatus,
    RuleProposalView,
)
from homemind.contracts.common import Origin, Provenance, ValueKind, new_id, stable_id
from homemind.contracts.household import CommonAreaRule, HouseholdPolicy

_COLS = "common_area_rule, ask_threshold_cents, ask_timeout_hours"


class RuleChangeError(ValueError):
    """Mudança recusada (regra inexistente, nada agendado…)."""


def first_of_next_month(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


def local_day(conn: sqlite3.Connection, household_id: UUID, at: datetime) -> date:
    tz = conn.execute(
        "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
    ).fetchone()["timezone"]
    return at.astimezone(ZoneInfo(tz)).date()


def _policy(row: sqlite3.Row) -> HouseholdPolicy:
    return HouseholdPolicy(
        common_area_rule=row["common_area_rule"],
        ask_threshold_cents=row["ask_threshold_cents"],
        ask_timeout_hours=row["ask_timeout_hours"],
    )


def _initial(conn: sqlite3.Connection, household_id: UUID) -> PolicyVersion:
    row = conn.execute(f"SELECT {_COLS} FROM household WHERE id = ?", (str(household_id),))
    return PolicyVersion(effective_from=None, policy=_policy(row.fetchone()))


def _version(row: sqlite3.Row) -> PolicyVersion:
    return PolicyVersion(
        effective_from=date.fromisoformat(row["effective_from"]),
        policy=_policy(row),
        created_by_resident_id=UUID(row["created_by_resident_id"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def versions(conn: sqlite3.Connection, household_id: UUID) -> list[PolicyVersion]:
    """Todas, por ordem: a inicial e depois as datadas."""
    rows = conn.execute(
        f"SELECT effective_from, {_COLS}, created_by_resident_id, created_at"
        " FROM billing_policy_version WHERE household_id = ? ORDER BY effective_from",
        (str(household_id),),
    ).fetchall()
    return [_initial(conn, household_id), *map(_version, rows)]


def version_on(all_versions: list[PolicyVersion], day: date) -> PolicyVersion:
    """Pura: a última versão que já começou em `day` (a inicial se nenhuma)."""
    current = all_versions[0]
    for v in all_versions[1:]:
        if v.effective_from <= day:
            current = v
    return current


def policy_on(conn: sqlite3.Connection, household_id: UUID, day: date) -> HouseholdPolicy:
    return version_on(versions(conn, household_id), day).policy


class RuleVoteForbidden(PermissionError):
    """Só moradores com contrato ativo propõem e votam."""


def _eligible(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> list[UUID]:
    """Moradores com contrato ativo hoje (o mesmo critério de `attributor.active_tenants`)."""
    day = local_day(conn, household_id, now).isoformat()
    rows = conn.execute(
        "SELECT resident_id FROM membership WHERE household_id = ? AND role = 'tenant'"
        " AND status IN ('active', 'ended') AND starts_on <= ?"
        " AND (ends_on IS NULL OR ends_on >= ?) ORDER BY resident_id",
        (str(household_id), day, day),
    )
    return [UUID(r["resident_id"]) for r in rows]


def _needed(eligible: int) -> int:
    """Pelo menos metade (D-32): 4 moradores -> 2, 3 -> 2, 1 -> 1."""
    return max(1, -(-eligible // 2))


def _proposal(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> RuleProposal:
    eligible = _eligible(conn, UUID(row["household_id"]), now)
    votes = {
        UUID(v["resident_id"]): bool(v["approve"])
        for v in conn.execute(
            "SELECT resident_id, approve FROM billing_rule_vote WHERE proposal_id = ?",
            (row["id"],),
        )
    }
    counted = [votes[r] for r in eligible if r in votes]  # só quem ainda é morador conta
    return RuleProposal(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        effective_from=date.fromisoformat(row["effective_from"]),
        policy=_policy(row),
        proposed_by_resident_id=UUID(row["proposed_by_resident_id"]),
        proposed_at=datetime.fromisoformat(row["proposed_at"]),
        status=RuleProposalStatus(row["status"]),
        approvals=sum(counted),
        rejections=len(counted) - sum(counted),
        eligible=len(eligible),
        needed=_needed(len(eligible)),
        decided_at=datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None,
    )


def _event(p: RuleProposal, now: datetime) -> de.BillingRulesProposalChanged:
    return de.BillingRulesProposalChanged(
        id=stable_id("rules_proposal", str(p.id), p.status.value),
        ts=now,
        household_id=p.household_id,
        correlation_id=stable_id("correlation", "rules_proposal", str(p.id)),
        # Uma decisão humana declarada, não uma medição de sensor (como os votos D-32).
        provenance=Provenance(origin=Origin.real, kind=ValueKind.measured),
        data=p,
    )


def _open_row(conn: sqlite3.Connection, household_id: UUID) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM billing_rule_proposal WHERE household_id = ? AND status = 'open'",
        (str(household_id),),
    ).fetchone()


def _close(conn: sqlite3.Connection, row: sqlite3.Row, status: RuleProposalStatus, now):
    conn.execute(
        "UPDATE billing_rule_proposal SET status = ?, decided_at = ? WHERE id = ?",
        (status.value, now.isoformat(), row["id"]),
    )
    return _proposal(conn, conn.execute(
        "SELECT * FROM billing_rule_proposal WHERE id = ?", (row["id"],)
    ).fetchone(), now)  # fmt: skip


def expire(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> list[de.DomainEvent]:
    """A proposta aberta cujo mês já começou caduca: nunca muda um mês em curso."""
    row = _open_row(conn, household_id)
    if row is None or date.fromisoformat(row["effective_from"]) > local_day(
        conn, household_id, now
    ):
        return []
    return [_event(_close(conn, row, RuleProposalStatus.expired, now), now)]


def expire_all(conn: sqlite3.Connection, now: datetime) -> list[de.DomainEvent]:
    """Tarefa periódica: `expire` em todas as casas com uma proposta aberta."""
    houses = conn.execute(
        "SELECT household_id FROM billing_rule_proposal WHERE status = 'open'"
    ).fetchall()
    return [e for h in houses for e in expire(conn, UUID(h["household_id"]), now)]


def _tally(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> list[de.DomainEvent]:
    """Decide se já há maioria (agenda a versão) ou se a maioria já é impossível."""
    p = _proposal(conn, row, now)
    if p.approvals >= p.needed:
        _upsert_version(conn, p, now)
        return [_event(_close(conn, row, RuleProposalStatus.approved, now), now)]
    if p.rejections > p.eligible - p.needed:
        return [_event(_close(conn, row, RuleProposalStatus.rejected, now), now)]
    return []


def _upsert_version(conn: sqlite3.Connection, p: RuleProposal, now: datetime) -> None:
    conn.execute(
        f"INSERT INTO billing_policy_version (household_id, effective_from, {_COLS},"
        " created_by_resident_id, created_at) VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT (household_id, effective_from) DO UPDATE SET"
        " common_area_rule = excluded.common_area_rule,"
        " ask_threshold_cents = excluded.ask_threshold_cents,"
        " ask_timeout_hours = excluded.ask_timeout_hours,"
        " created_by_resident_id = excluded.created_by_resident_id,"
        " created_at = excluded.created_at",
        (
            str(p.household_id),
            p.effective_from.isoformat(),
            p.policy.common_area_rule.value,
            p.policy.ask_threshold_cents,
            p.policy.ask_timeout_hours,
            str(p.proposed_by_resident_id),
            now.isoformat(),
        ),
    )


def _vote(conn: sqlite3.Connection, proposal_id: str, resident_id: UUID, approve: bool, now):
    conn.execute(
        "INSERT INTO billing_rule_vote (proposal_id, resident_id, approve, voted_at)"
        " VALUES (?,?,?,?) ON CONFLICT (proposal_id, resident_id) DO UPDATE SET"
        " approve = excluded.approve, voted_at = excluded.voted_at",
        (proposal_id, str(resident_id), int(approve), now.isoformat()),
    )


def _require_tenant(conn: sqlite3.Connection, household_id: UUID, resident_id, now) -> None:
    if resident_id not in _eligible(conn, household_id, now):
        raise RuleVoteForbidden("só moradores com contrato ativo propõem e votam")


def view(
    conn: sqlite3.Connection, household_id: UUID, now: datetime, resident_id: UUID | None = None
) -> HouseRulesView:
    today = local_day(conn, household_id, now)
    all_versions = versions(conn, household_id)
    started = [v for v in all_versions if v.effective_from is None or v.effective_from <= today]
    upcoming = [v for v in all_versions if v not in started]
    row = _open_row(conn, household_id)
    proposal = None
    if row is not None and date.fromisoformat(row["effective_from"]) > today:
        mine = (
            conn.execute(
                "SELECT approve FROM billing_rule_vote WHERE proposal_id = ? AND resident_id = ?",
                (row["id"], str(resident_id)),
            ).fetchone()
            if resident_id
            else None
        )
        proposal = RuleProposalView(
            **_proposal(conn, row, now).model_dump(),
            my_vote=bool(mine["approve"]) if mine else None,
            proposed_by_me=row["proposed_by_resident_id"] == str(resident_id),
        )
    return HouseRulesView(
        current=started[-1],
        upcoming=upcoming[0] if upcoming else None,
        history=started[::-1],
        next_change_from=first_of_next_month(today),
        proposal=proposal,
    )


def propose(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    policy: HouseholdPolicy,
    now: datetime,
) -> tuple[list[de.DomainEvent], HouseRulesView]:
    """Propõe a regra para o dia 1 do mês seguinte; quem propõe vota «sim». Substitui a proposta
    aberta (os votos dela não passam para a nova). Só fica agendada com a maioria."""
    if policy.common_area_rule is CommonAreaRule.presence:
        raise RuleChangeError("a regra «por presença» (C) ainda não existe")
    _require_tenant(conn, household_id, resident_id, now)
    events = expire(conn, household_id, now)
    start = first_of_next_month(local_day(conn, household_id, now))
    if version_on(versions(conn, household_id), start).policy == policy:
        raise RuleChangeError("é a regra que já vai valer nesse mês: não há nada a mudar")
    if (old := _open_row(conn, household_id)) is not None:
        events.append(_event(_close(conn, old, RuleProposalStatus.superseded, now), now))
    pid = new_id()
    conn.execute(
        f"INSERT INTO billing_rule_proposal (id, household_id, effective_from, {_COLS},"
        " proposed_by_resident_id, proposed_at, status) VALUES (?,?,?,?,?,?,?,?,'open')",
        (
            str(pid),
            str(household_id),
            start.isoformat(),
            policy.common_area_rule.value,
            policy.ask_threshold_cents,
            policy.ask_timeout_hours,
            str(resident_id),
            now.isoformat(),
        ),
    )
    _vote(conn, str(pid), resident_id, True, now)
    row = _open_row(conn, household_id)
    decided = _tally(conn, row, now)
    events += decided or [_event(_proposal(conn, row, now), now)]
    return events, view(conn, household_id, now, resident_id)


def vote(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, approve: bool, now: datetime
) -> tuple[list[de.DomainEvent], HouseRulesView]:
    _require_tenant(conn, household_id, resident_id, now)
    events = expire(conn, household_id, now)
    row = _open_row(conn, household_id)
    if row is None:
        raise RuleChangeError("não há nenhuma proposta aberta")
    _vote(conn, row["id"], resident_id, approve, now)
    events += _tally(conn, row, now)
    return events, view(conn, household_id, now, resident_id)


def withdraw(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, now: datetime
) -> tuple[list[de.DomainEvent], HouseRulesView]:
    """Quem propôs retira a proposta aberta. Uma mudança já aprovada só se desfaz com outra
    proposta aprovada pela maioria (por exemplo, a regra atual)."""
    events = expire(conn, household_id, now)
    row = _open_row(conn, household_id)
    if row is None:
        raise RuleChangeError("não há nenhuma proposta aberta")
    if row["proposed_by_resident_id"] != str(resident_id):
        raise RuleVoteForbidden("só quem propôs a pode retirar; os outros votam contra")
    events.append(_event(_close(conn, row, RuleProposalStatus.withdrawn, now), now))
    return events, view(conn, household_id, now, resident_id)
