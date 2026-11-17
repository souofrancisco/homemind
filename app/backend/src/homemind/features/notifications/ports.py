"""Portas da feature `notifications`: dependências injetadas (relógio e diretório de moradores).

O papel é o `MembershipRole` do contrato de casas; o adaptador SQLite está em `directory.py`.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from homemind.contracts.household import MembershipRole

# Relógio injetado: devolve sempre um `datetime` com fuso (UTC).
Clock = Callable[[], datetime]


class ResidentDirectory(Protocol):
    """Papel de um residente numa casa num dado instante; `None` se não é membro ativo."""

    def role_in(
        self, household_id: UUID, resident_id: UUID, at: datetime
    ) -> MembershipRole | None: ...
