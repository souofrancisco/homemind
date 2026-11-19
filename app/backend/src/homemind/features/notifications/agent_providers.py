"""Provider de leitura das confirmações ainda pendentes para o próprio morador."""

import re
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from homemind.contracts.agent_providers import ConfirmationsValue, ConfirmationValue
from homemind.contracts.common import Provenance, ValueKind
from homemind.contracts.household import MembershipRole
from homemind.contracts.notification import Notification, NotificationKind
from homemind.core.db import Database
from homemind.features.notifications.directory import SqliteResidentDirectory

_COST = re.compile(r"cerca de ([\d ]+),(\d{2}) € estimados")


class NotificationAgentProviders:
    """Leitura curta da tabela de notificações, serializada no lock comum da base."""

    def __init__(self, db: Database, clock: Callable[[], datetime]):
        self._db = db
        self._clock = clock

    def pending_confirmations(self, household_id: UUID, resident_id: UUID) -> ConfirmationsValue:
        with self._db._lock:
            conn = self._db._conn
            if conn is None:
                return ConfirmationsValue(0, ())
            conn.execute("PRAGMA query_only=ON")
            try:
                rows = conn.execute(
                    "SELECT json FROM notification WHERE household_id = ? AND kind = ?"
                    " AND status IN ('unread', 'read') ORDER BY expires_at, created_at, id",
                    (str(household_id), NotificationKind.confirmation_request.value),
                ).fetchall()
                now = self._clock()
                if (
                    SqliteResidentDirectory(conn).role_in(household_id, resident_id, now)
                    is not MembershipRole.tenant
                ):
                    return ConfirmationsValue(0, ())
                pending: list[ConfirmationValue] = []
                for row in rows:
                    item = Notification.model_validate_json(row["json"])
                    if not item.can_respond(resident_id, now):
                        continue
                    appliance = item.body.split(" está ligado", 1)[0]
                    appliance = appliance.removeprefix("O ")
                    match = _COST.search(item.body)
                    cents = (
                        int(match.group(1).replace(" ", "")) * 100 + int(match.group(2))
                        if match
                        else None
                    )
                    pending.append(
                        ConfirmationValue(
                            appliance_name=appliance if appliance != "Um aparelho" else None,
                            estimated_cost_cents=cents,
                            expires_at=item.expires_at,
                            provenance=Provenance(origin=item.origin, kind=ValueKind.estimated),
                        )
                    )
                return ConfirmationsValue(len(pending), tuple(pending[:3]))
            finally:
                conn.execute("PRAGMA query_only=OFF")
