"""Retenção (PRIV-04): expurgo periódico da telemetria expirada. Sem rotas HTTP.

A política (categorias e prazos) está em `policy.py`; o expurgo em `purge.py`. Corre um minuto
depois do arranque e depois de 6 em 6 horas; uma falha só fica no log (sem dados) e tenta-se no
ciclo seguinte. `RETENTION_TELEMETRY_DAYS=0` desliga o expurgo. A anonimização de ex-moradores
(`anonymize.py`) corre no mesmo ciclo e está DESLIGADA por omissão
(`RETENTION_ANONYMIZE_AFTER_DAYS=0`).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from homemind.core.access import get_clock
from homemind.core.config import get_settings
from homemind.features.retention.anonymize import anonymize
from homemind.features.retention.purge import purge

log = logging.getLogger(__name__)
FIRST_RUN_S = 60.0
INTERVAL_S = 6 * 3600.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    clock = app.dependency_overrides.get(get_clock, get_clock)()
    settings = get_settings()
    days = settings.retention_telemetry_days
    anonymize_days = settings.retention_anonymize_after_days

    async def loop() -> None:
        await asyncio.sleep(FIRST_RUN_S)
        while True:
            try:
                done = await asyncio.to_thread(purge, app.state.db.run_sync, clock(), days)
                if done.events or done.aggregates:
                    log.info(
                        "retenção: %d eventos de telemetria e %d agregados diários apagados",
                        done.events,
                        done.aggregates,
                    )
            except Exception as e:  # nunca derruba o servidor; tenta no próximo ciclo
                log.warning("retenção: expurgo falhou (%s)", type(e).__name__)
            try:
                n = await asyncio.to_thread(
                    anonymize, app.state.db.run_sync, clock(), anonymize_days
                )
                if n:
                    log.info("retenção: %d ex-moradores anonimizados", n)
            except Exception as e:
                log.warning("retenção: anonimização falhou (%s)", type(e).__name__)
            await asyncio.sleep(INTERVAL_S)

    enabled = days or anonymize_days
    task = asyncio.create_task(loop(), name="retention:purge") if enabled else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


router = APIRouter(prefix="/api", tags=["retention"], lifespan=lifespan)
