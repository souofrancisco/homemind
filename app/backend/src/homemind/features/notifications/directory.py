"""Diretório de moradores sobre SQLite: o papel de um residente numa casa num dado instante.

DUPLICAÇÃO CONSCIENTE: o SQL e a lógica de datas (membership `active`, dentro de `starts_on`/
`ends_on`, com «hoje» no fuso da casa) copiam `core.access.find_membership`, que procura por
`sub` do Authentik; aqui procura-se por `resident_id` (o handler do barramento não tem `sub`).
Pedir à P5 um helper `find_membership_by_resident` em `core/access.py` e passar a usá-lo.
"""

import sqlite3
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.household import MembershipRole, RoomKind


class SqliteResidentDirectory:
    """Cumpre `ResidentDirectory` (ver `ports.py`) sobre a ligação da transação."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _today(self, household_id: UUID, at: datetime) -> str | None:
        """«Hoje» no fuso da casa (ISO); `None` se a casa não existe."""
        house = self._conn.execute(
            "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
        ).fetchone()
        if house is None:
            return None
        return at.astimezone(ZoneInfo(house["timezone"])).date().isoformat()

    def role_in(self, household_id: UUID, resident_id: UUID, at: datetime) -> MembershipRole | None:
        today = self._today(household_id, at)
        if today is None:
            return None
        row = self._conn.execute(
            "SELECT role FROM membership WHERE household_id = ? AND resident_id = ?"
            " AND status = 'active' AND starts_on <= ? AND (ends_on IS NULL OR ends_on >= ?)",
            (str(household_id), str(resident_id), today, today),
        ).fetchone()
        return MembershipRole(row["role"]) if row else None

    def room(self, household_id: UUID, room_id: UUID) -> tuple[str, RoomKind] | None:
        row = self._conn.execute(
            "SELECT name, kind FROM room WHERE household_id = ? AND id = ?",
            (str(household_id), str(room_id)),
        ).fetchone()
        return (row["name"], RoomKind(row["kind"])) if row else None

    def room_tenants(self, household_id: UUID, room_id: UUID, at: datetime) -> list[UUID]:
        today = self._today(household_id, at)
        if today is None:
            return []
        rows = self._conn.execute(
            "SELECT resident_id FROM membership WHERE household_id = ? AND room_id = ?"
            " AND role = 'tenant' AND status = 'active' AND starts_on <= ?"
            " AND (ends_on IS NULL OR ends_on >= ?) ORDER BY resident_id",
            (str(household_id), str(room_id), today, today),
        ).fetchall()
        return [UUID(r["resident_id"]) for r in rows]

    def appliance_name(self, household_id: UUID, appliance_id: UUID) -> str | None:
        row = self._conn.execute(
            "SELECT name FROM appliance WHERE household_id = ? AND id = ?",
            (str(household_id), str(appliance_id)),
        ).fetchone()
        return row["name"] if row else None
