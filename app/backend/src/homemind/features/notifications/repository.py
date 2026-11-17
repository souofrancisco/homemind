"""Persistência das notificações: protocolo + implementação em memória.

A implementação SQLite (`sqlite.py`) cumpre o mesmo protocolo: `compare_and_set` é
`UPDATE ... WHERE id = ? AND status = ? AND <n.º de votos> = ?` com 1 linha afetada. O par
(estado, n.º de votos) é a «versão» da notificação: só avança (os votos só se acrescentam e o
estado nunca volta atrás), por isso qualquer escrita concorrente muda-o e quem leu antes perde
(nunca se perde um voto nem se aceita um duplicado). A em memória serve de referência e de
dublê nos testes.
"""

import threading
from datetime import datetime
from typing import Protocol
from uuid import UUID

from homemind.contracts.notification import (
    Notification,
    NotificationKind,
    NotificationRef,
    NotificationStatus,
)

_OPEN = frozenset({NotificationStatus.unread, NotificationStatus.read})


class NotificationRepository(Protocol):
    def get(self, notification_id: UUID) -> Notification | None: ...

    def insert(self, n: Notification) -> bool:
        """Insere; `False` (sem alterar nada) se o id já existe."""
        ...

    def find_open(
        self,
        *,
        household_id: UUID,
        kind: NotificationKind,
        ref: NotificationRef | None,
        recipient_resident_id: UUID | None,
    ) -> Notification | None:
        """Notificação aberta (unread/read) com a mesma chave de deduplicação, a mais recente."""
        ...

    def compare_and_set(self, new: Notification, *, expected: Notification) -> bool:
        """Grava `new` só se o estado atual for o que se leu (`expected`: o mesmo estado e o
        mesmo n.º de votos); `False` se perdeu (reler e reaplicar a regra)."""
        ...

    def list_household(self, household_id: UUID) -> list[Notification]: ...

    def open_due(self, now: datetime) -> list[Notification]:
        """Abertas cujo `expires_at` já passou."""
        ...

    def mark_read(self, notification_id: UUID, resident_id: UUID, at: datetime) -> bool:
        """Recibo de leitura por residente; `True` se foi criado agora."""
        ...

    def read_at(self, notification_id: UUID, resident_id: UUID) -> datetime | None: ...


class InMemoryNotificationRepository:
    """Implementação em memória, segura entre threads (um `Lock` por repositório)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[UUID, Notification] = {}
        self._receipts: dict[tuple[UUID, UUID], datetime] = {}

    def get(self, notification_id: UUID) -> Notification | None:
        with self._lock:
            return self._items.get(notification_id)

    def insert(self, n: Notification) -> bool:
        with self._lock:
            if n.id in self._items:
                return False
            self._items[n.id] = n
            return True

    def find_open(
        self,
        *,
        household_id: UUID,
        kind: NotificationKind,
        ref: NotificationRef | None,
        recipient_resident_id: UUID | None,
    ) -> Notification | None:
        with self._lock:
            matches = [
                n
                for n in self._items.values()
                if n.household_id == household_id
                and n.kind == kind
                and n.ref == ref
                and n.recipient_resident_id == recipient_resident_id
                and n.status in _OPEN
            ]
        return max(matches, key=lambda n: (n.created_at, str(n.id)), default=None)

    def compare_and_set(self, new: Notification, *, expected: Notification) -> bool:
        with self._lock:
            current = self._items.get(new.id)
            if (
                current is None
                or current.status is not expected.status
                or len(current.responses) != len(expected.responses)
            ):
                return False
            self._items[new.id] = new
            return True

    def list_household(self, household_id: UUID) -> list[Notification]:
        with self._lock:
            return [n for n in self._items.values() if n.household_id == household_id]

    def open_due(self, now: datetime) -> list[Notification]:
        with self._lock:
            return [
                n
                for n in self._items.values()
                if n.status in _OPEN and n.expires_at is not None and now >= n.expires_at
            ]

    def mark_read(self, notification_id: UUID, resident_id: UUID, at: datetime) -> bool:
        with self._lock:
            key = (notification_id, resident_id)
            if notification_id not in self._items or key in self._receipts:
                return False
            self._receipts[key] = at
            return True

    def read_at(self, notification_id: UUID, resident_id: UUID) -> datetime | None:
        with self._lock:
            return self._receipts.get((notification_id, resident_id))
