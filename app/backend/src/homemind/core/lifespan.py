"""Recursos partilhados da app: arranque e encerramento explícitos (decisão D-06).

Passado a `FastAPI(lifespan=...)`: o FastAPI aninha os lifespans dos routers dentro deste, por
isso a base de dados está pronta quando qualquer feature arranca, qualquer que seja a ordem
das pastas, e só fecha depois de todas terminarem. Se isto falhar, a app não arranca.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from homemind.core.config import get_settings
from homemind.core.db import Database, migrate


@asynccontextmanager
async def core_lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    db = Database(s.db_path, s.db_busy_timeout_ms)
    db.open()
    try:
        migrate(db)
        app.state.db = db
        yield
    finally:
        db.close()
