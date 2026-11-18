"""Editar o plafond solidário de um quarto depois de criado (BILL-03).

Como as regras da casa (HOUSE-04): a mudança só vale a partir do dia 1 do mês seguinte (fuso da
casa), por isso nunca muda um mês já começado nem uma fatura fechada; até lá pode ser substituída.
Só o senhorio a faz (é ele quem define o plafond na criação do quarto); todos a veem.
"""

import sqlite3
from datetime import datetime
from uuid import UUID

from homemind.contracts.billing import RoomAllowanceView
from homemind.features.billing.closing import monthly_allowance
from homemind.features.billing.rules import first_of_next_month, local_day


def views(conn: sqlite3.Connection, household_id: UUID, now: datetime) -> list[RoomAllowanceView]:
    this_month = local_day(conn, household_id, now).replace(day=1)
    upcoming = {
        r["room_id"]: r
        for r in conn.execute(
            "SELECT room_id, effective_from, included_wh FROM billing_room_allowance"
            " WHERE household_id = ? AND effective_from > ?",
            (str(household_id), this_month.isoformat()),
        )
    }
    out = []
    for room, wh in sorted(
        monthly_allowance(conn, household_id).items(), key=lambda kv: str(kv[0])
    ):
        u = upcoming.get(str(room))
        out.append(
            RoomAllowanceView(
                room_id=room,
                current_wh=wh(this_month),
                upcoming_wh=u["included_wh"] if u else None,
                upcoming_from=u["effective_from"] if u else None,
            )
        )
    return out


def schedule(
    conn: sqlite3.Connection,
    household_id: UUID,
    room_id: UUID,
    included_wh: int,
    resident_id: UUID,
    now: datetime,
) -> RoomAllowanceView:
    room = conn.execute(
        "SELECT kind FROM room WHERE household_id = ? AND id = ?", (str(household_id), str(room_id))
    ).fetchone()
    if room is None:
        raise LookupError("quarto não encontrado")
    if room["kind"] != "bedroom":
        raise ValueError("o plafond solidário só existe em quartos")
    start = first_of_next_month(local_day(conn, household_id, now))
    conn.execute(
        "INSERT INTO billing_room_allowance (household_id, room_id, effective_from, included_wh,"
        " created_by_resident_id, created_at) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT (room_id, effective_from) DO UPDATE SET included_wh = excluded.included_wh,"
        " created_by_resident_id = excluded.created_by_resident_id,"
        " created_at = excluded.created_at",
        (
            str(household_id),
            str(room_id),
            start.isoformat(),
            included_wh,
            str(resident_id),
            now.isoformat(),
        ),
    )
    return next(v for v in views(conn, household_id, now) if v.room_id == room_id)
