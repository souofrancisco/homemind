"""Registo textual PT-PT: `events.jsonl` + últimas linhas em memória. Sem imagens."""

import logging
import uuid
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from homemind.contracts.home import Backend

log = logging.getLogger(__name__)

Nivel = Literal["info", "warning", "error"]


class EventLogItem(BaseModel):
    id: str
    timestamp: datetime
    level: Nivel
    message: str
    source: Backend  # backend da casa no momento (fake = SIMULADO)


class EventLog:
    def __init__(self, path: Path | None, source: Backend = "fake", maximo: int = 50) -> None:
        self.path = path
        self.source: Backend = source
        self.ao_registar: Callable[[EventLogItem], None] | None = None
        self._recentes: deque[EventLogItem] = deque(maxlen=maximo)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def registar(self, mensagem: str, level: Nivel = "info") -> EventLogItem:
        item = EventLogItem(
            id=f"evt-{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(UTC),
            level=level,
            message=mensagem,
            source=self.source,
        )
        self._recentes.append(item)
        if self.path:
            try:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(item.model_dump_json() + "\n")
            except OSError:
                log.exception("não foi possível escrever no registo")
        if self.ao_registar:
            self.ao_registar(item)
        return item

    def recentes(self, limite: int = 50) -> list[EventLogItem]:
        return list(self._recentes)[-limite:] if limite > 0 else []
