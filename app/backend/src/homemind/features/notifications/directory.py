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

from homemind.contracts.household import MembershipRole


class SqliteResidentDirectory:
    """Cumpre `ResidentDirectory` (ver `ports.py`) sobre a ligação da transação."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def role_in(self, household_id: UUID, resident_id: UUID, at: datetime) -> MembershipRole | None:
        house = self._conn.execute(
            "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
        ).fetchone()
        if house is None:
            return None
        today = at.astimezone(ZoneInfo(house["timezone"])).date().isoformat()
        row = self._conn.execute(
            "SELECT role FROM membership WHERE household_id = ? AND resident_id = ?"
            " AND status = 'active' AND starts_on <= ? AND (ends_on IS NULL OR ends_on >= ?)",
            (str(household_id), str(resident_id), today, today),
        ).fetchone()
        return MembershipRole(row["role"]) if row else None
