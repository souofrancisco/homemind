"""Regras da casa versionadas (HOUSE-04): que regra da sala vale em cada dia.

Premissas (explícitas, documentadas em `docs/modules/billing.md`):
- A regra que decide um consumo é a do DIA em que começou (fuso da casa), como o contrato de
  quarto (`attributor.active_tenants`). Antes da primeira versão vale a política inicial da casa
  (`household`, definida na criação).
- Mudar a regra só vale a partir do dia 1 do mês seguinte: o mês em curso, as faturas fechadas
  e os consumos já decididos nunca mudam. Todos os moradores veem a mudança agendada antes de
  ela começar; até lá pode ser substituída ou cancelada. Quem muda: um morador (a casa escolhe,
  v5.1 §6.2); o senhorio só lê.
- A regra C (`presence`) ainda não existe (BILL-07): não se agenda.
- Sem resposta à pergunta nunca há cobrança individual: o prazo (`ask_timeout_hours`, da
  versão do dia do consumo) termina na divisão por igual (D-32).
"""

import sqlite3
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.billing import HouseRulesView, PolicyVersion
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


def view(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> HouseRulesView:
    today = local_day(conn, household_id, now)
    all_versions = versions(conn, household_id)
    started = [v for v in all_versions if v.effective_from is None or v.effective_from <= today]
    upcoming = [v for v in all_versions if v not in started]
    return HouseRulesView(
        current=started[-1],
        upcoming=upcoming[0] if upcoming else None,
        history=started[::-1],
        next_change_from=first_of_next_month(today),
    )


def schedule(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    policy: HouseholdPolicy,
    now: datetime,
) -> HouseRulesView:
    """Agenda (ou substitui) a mudança para o dia 1 do mês seguinte."""
    if policy.common_area_rule is CommonAreaRule.presence:
        raise RuleChangeError("a regra «por presença» (C) ainda não existe")
    start = first_of_next_month(local_day(conn, household_id, now))
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
            str(household_id),
            start.isoformat(),
            policy.common_area_rule.value,
            policy.ask_threshold_cents,
            policy.ask_timeout_hours,
            str(resident_id),
            now.isoformat(),
        ),
    )
    return view(conn, household_id, now)


def cancel(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> HouseRulesView:
    """Cancela a mudança agendada. As versões que já começaram nunca se apagam."""
    today = local_day(conn, household_id, now)
    deleted = conn.execute(
        "DELETE FROM billing_policy_version WHERE household_id = ? AND effective_from > ?",
        (str(household_id), today.isoformat()),
    ).rowcount
    if not deleted:
        raise RuleChangeError("não há nenhuma mudança agendada")
    return view(conn, household_id, now)
