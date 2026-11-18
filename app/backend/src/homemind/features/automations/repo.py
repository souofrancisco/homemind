"""SQL das regras da casa (`automation_rule`, `automation_vote`, `automation_log`).

Síncrono sobre a ligação da transação (`db.run`). Cada mudança de estado é um *compare-and-set*
(devolve `False` se perdeu); o log só acrescenta. Sem regras de negócio: ver `service.py`.
"""

import json
import sqlite3
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.agent import AutomationRule, AutomationStatus, AutomationVote


def iso(dt: datetime) -> str:
    """Datas sempre em UTC ISO: a comparação de texto é cronológica."""
    return dt.astimezone(UTC).isoformat()


def active_tenants(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> list[UUID]:
    """Inquilinos ativos da casa, ordenados. Só o papel `tenant`: o senhorio e o operador nunca
    votam. DUPLICAÇÃO CONSCIENTE de `core.access.find_membership` (que procura por `sub`)."""
    house = conn.execute(
        "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
    ).fetchone()
    if house is None:
        return []
    today = now.astimezone(ZoneInfo(house["timezone"])).date().isoformat()
    rows = conn.execute(
        "SELECT DISTINCT resident_id FROM membership WHERE household_id = ? AND role = 'tenant'"
        " AND status = 'active' AND starts_on <= ? AND (ends_on IS NULL OR ends_on >= ?)"
        " ORDER BY resident_id",
        (str(household_id), today, today),
    ).fetchall()
    return [UUID(r["resident_id"]) for r in rows]


def insert_rule(
    conn: sqlite3.Connection,
    rule: AutomationRule,
    *,
    origin: str,
    device_name: str,
    now: datetime,
    deadline: datetime,
    eligible: list[UUID],
) -> None:
    conn.execute(
        "INSERT INTO automation_rule (id, household_id, name, status, origin,"
        " created_by_resident_id, approved_by_resident_id, device_name, proposed_at, vote_round,"
        " vote_open, vote_deadline, eligible_json, rev, json, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,1,1,?,?,1,?,?)",
        (
            str(rule.id), str(rule.household_id), rule.name, rule.status.value, origin,
            str(rule.created_by_resident_id), None, device_name, iso(now), iso(deadline),
            json.dumps([str(e) for e in eligible]), rule.model_dump_json(), iso(now),
        ),
    )  # fmt: skip


def get_row(conn: sqlite3.Connection, household_id: UUID, rule_id: UUID) -> sqlite3.Row | None:
    """Só a regra desta casa: a de outra é como se não existisse."""
    return conn.execute(
        "SELECT * FROM automation_rule WHERE id = ? AND household_id = ?",
        (str(rule_id), str(household_id)),
    ).fetchone()


def list_rows(conn: sqlite3.Connection, household_id: UUID, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM automation_rule WHERE household_id = ?"
        " ORDER BY proposed_at DESC, rowid DESC LIMIT ?",
        (str(household_id), limit),
    ).fetchall()


def due_rows(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> list[sqlite3.Row]:
    """Votações abertas cujo prazo já acabou (a resolver na leitura)."""
    return conn.execute(
        "SELECT * FROM automation_rule WHERE household_id = ? AND vote_open = 1"
        " AND vote_deadline <= ? ORDER BY proposed_at, rowid",
        (str(household_id), iso(now)),
    ).fetchall()


def eligible_of(row: sqlite3.Row) -> list[UUID]:
    return [UUID(e) for e in json.loads(row["eligible_json"])]


def rule_of(row: sqlite3.Row) -> AutomationRule:
    return AutomationRule.model_validate_json(row["json"])


def votes_of(conn: sqlite3.Connection, rule_id: str) -> list[AutomationVote]:
    rows = conn.execute(
        "SELECT resident_id, approve, at FROM automation_vote WHERE rule_id = ? ORDER BY at",
        (rule_id,),
    ).fetchall()
    return [
        AutomationVote(
            resident_id=UUID(r["resident_id"]),
            approve=bool(r["approve"]),
            at=datetime.fromisoformat(r["at"]),
        )
        for r in rows
    ]


def insert_vote(conn: sqlite3.Connection, rule_id: UUID, vote: AutomationVote) -> bool:
    """`False` se este morador já votou nesta ronda (chave primária)."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO automation_vote (rule_id, resident_id, approve, at)"
        " VALUES (?,?,?,?)",
        (str(rule_id), str(vote.resident_id), int(vote.approve), iso(vote.at)),
    )
    return cur.rowcount == 1


def close_vote(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    rule: AutomationRule,
    verdict: str,
    now: datetime,
) -> bool:
    """CAS: fecha a ronda lida (`rev` e `vote_open = 1`); `rule` já leva o estado e a aprovação
    novos. `False` se outra transação decidiu primeiro."""
    cur = conn.execute(
        "UPDATE automation_rule SET status = ?, approved_by_resident_id = ?, vote_open = 0,"
        " last_verdict = ?, rev = rev + 1, json = ?, updated_at = ?"
        " WHERE id = ? AND rev = ? AND vote_open = 1",
        (
            rule.status.value,
            str(rule.approved_by_resident_id) if rule.approved_by_resident_id else None,
            verdict, rule.model_dump_json(), iso(now), row["id"], row["rev"],
        ),
    )  # fmt: skip
    return cur.rowcount == 1


def suspend(
    conn: sqlite3.Connection, row: sqlite3.Row, *, rule: AutomationRule, now: datetime
) -> bool:
    """CAS `active → disabled` sobre a versão lida."""
    cur = conn.execute(
        "UPDATE automation_rule SET status = 'disabled', rev = rev + 1, json = ?, updated_at = ?"
        " WHERE id = ? AND rev = ? AND status = 'active'",
        (rule.model_dump_json(), iso(now), row["id"], row["rev"]),
    )
    return cur.rowcount == 1


def open_round(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    now: datetime,
    deadline: datetime,
    eligible: list[UUID],
) -> bool:
    """CAS: nova ronda numa regra `disabled` sem votação aberta; apaga os votos da anterior."""
    cur = conn.execute(
        "UPDATE automation_rule SET vote_round = vote_round + 1, vote_open = 1,"
        " vote_deadline = ?, eligible_json = ?, rev = rev + 1, updated_at = ?"
        " WHERE id = ? AND rev = ? AND status = 'disabled' AND vote_open = 0",
        (
            iso(deadline), json.dumps([str(e) for e in eligible]), iso(now),
            row["id"], row["rev"],
        ),
    )  # fmt: skip
    if cur.rowcount != 1:
        return False
    conn.execute("DELETE FROM automation_vote WHERE rule_id = ?", (row["id"],))
    return True


def log(
    conn: sqlite3.Connection,
    rule_id: UUID | str,
    at: datetime,
    kind: str,
    *,
    from_status: AutomationStatus | None = None,
    to_status: AutomationStatus | None = None,
    by: UUID | None = None,
    approve: bool | None = None,
    code: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO automation_log (rule_id, at, kind, from_status, to_status, by_resident_id,"
        " approve, code) VALUES (?,?,?,?,?,?,?,?)",
        (
            str(rule_id), iso(at), kind,
            from_status.value if from_status else None,
            to_status.value if to_status else None,
            str(by) if by else None,
            None if approve is None else int(approve),
            code,
        ),
    )  # fmt: skip
