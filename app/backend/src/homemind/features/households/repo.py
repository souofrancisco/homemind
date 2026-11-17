"""Escrita de casas, quartos, moradores e memberships (dono: households). Só SQL e invariantes.

Funções síncronas sobre uma `conn` já dentro de uma transação (`db.run`/`db.run_sync`).
A leitura para autorização está em `core/access.py`.
"""

import sqlite3
from datetime import date

from homemind.contracts import fixtures
from homemind.contracts.household import (
    Household,
    Membership,
    Resident,
    Room,
    check_membership_room,
)


def insert_household(conn: sqlite3.Connection, h: Household) -> None:
    s, p = h.settings, h.policy
    conn.execute(
        "INSERT INTO household (id, name, timezone, common_area_rule, ask_threshold_cents,"
        " ask_timeout_hours, energy_price_millicents_per_kwh, source_kind, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            str(h.id), h.name, s.timezone, p.common_area_rule.value, p.ask_threshold_cents,
            p.ask_timeout_hours, s.energy_price_millicents_per_kwh, s.source_kind.value,
            h.created_at.isoformat(),
        ),
    )  # fmt: skip


def insert_room(conn: sqlite3.Connection, r: Room) -> None:
    conn.execute(
        "INSERT INTO room (id, household_id, name, kind, included_wh) VALUES (?,?,?,?,?)",
        (str(r.id), str(r.household_id), r.name, r.kind.value, r.included_wh),
    )


def insert_resident(conn: sqlite3.Connection, r: Resident) -> None:
    conn.execute(
        "INSERT INTO resident (id, display_name, auth_subject, created_at) VALUES (?,?,?,?)",
        (str(r.id), r.display_name, r.auth_subject, fixtures.T0.isoformat()),
    )


def get_room(conn: sqlite3.Connection, room_id: object) -> Room | None:
    row = conn.execute("SELECT * FROM room WHERE id = ?", (str(room_id),)).fetchone()
    return Room(**dict(row)) if row else None


def insert_membership(conn: sqlite3.Connection, m: Membership) -> None:
    """Valida que o quarto é da mesma casa e é um quarto, antes de gravar."""
    room = get_room(conn, m.room_id) if m.room_id else None
    check_membership_room(m, room)
    conn.execute(
        "INSERT INTO membership (id, household_id, resident_id, role, room_id, starts_on,"
        " ends_on, status, presence_opt_in) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            str(m.id), str(m.household_id), str(m.resident_id), m.role.value,
            str(m.room_id) if m.room_id else None, m.starts_on.isoformat(),
            m.ends_on.isoformat() if m.ends_on else None, m.status.value, int(m.presence_opt_in),
        ),
    )  # fmt: skip


def end_membership(conn: sqlite3.Connection, membership_id: object, ends_on: date) -> None:
    """Saída a meio do mês: fecha com `ends_on` (nunca apaga)."""
    cur = conn.execute(
        "UPDATE membership SET status = 'ended', ends_on = ? WHERE id = ? AND status != 'ended'",
        (ends_on.isoformat(), str(membership_id)),
    )
    if cur.rowcount != 1:
        raise LookupError("membership inexistente ou já terminada")


def seed_demo(conn: sqlite3.Connection) -> bool:
    """Casa de demonstração determinística (Ana, Bruno, Carla, Diogo + senhorio e operador).
    Idempotente: devolve `False` se já existir."""
    h = fixtures.household()
    if conn.execute("SELECT 1 FROM household WHERE id = ?", (str(h.id),)).fetchone():
        return False
    insert_household(conn, h)
    for room in fixtures.rooms():
        insert_room(conn, room)
    for resident in fixtures.residents():
        insert_resident(conn, resident)
    for m in fixtures.memberships():
        insert_membership(conn, m)
    return True
