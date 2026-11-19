"""Emissão de leituras e sessões SIMULADAS, restrita ao perfil demo + fake."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel

from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.domain_events import EnergyReadingRecorded
from homemind.contracts.energy import EnergyReading, ReadingStatus
from homemind.core.access import DbDep, require_operator
from homemind.core.config import Settings, get_settings
from homemind.features.auth.service import CurrentUser

PLUG = stable_id("demo-web-device", "extensao-sala")
Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]


class DemoLive:
    """Relógio de parede injetável e tick sem esperas para condução determinística."""

    def __init__(self, bus, *, clock: Clock, started_at: datetime) -> None:
        self.bus = bus
        self.clock = clock
        self.started_at = started_at
        self.last_reading: datetime | None = None
        self.active_until: datetime | None = None
        self.active_kind: str | None = None
        self.started_session = False
        self.gap_pending = False
        self.sequence = 0

    async def start(self, kind: Literal["heater", "kettle"], at: datetime | None = None) -> None:
        now = at or self.clock()
        if self.active_until is not None and now < self.active_until:
            raise HTTPException(
                409,
                {
                    "code": "demo_session_active",
                    "message": "Já decorre uma sessão simulada",
                },
            )
        if self.active_until is not None:
            # Deixa o tracker ver o fim da carga antes de iniciar a seguinte.
            self.active_kind = None
            self.active_until = None
            self.gap_pending = True
            self.last_reading = now - timedelta(seconds=5)
            await self.tick(now)
        self.active_kind = kind
        duration = 180 if kind == "heater" else 155
        self.active_until = now + timedelta(seconds=duration)
        self.started_session = True

    async def tick(self, now: datetime | None = None) -> int:
        at = now or self.clock()
        if self.last_reading is not None and at - self.last_reading < timedelta(seconds=5):
            return 0
        if not self.started_session and at >= self.started_at + timedelta(seconds=60):
            await self.start("heater", self.started_at + timedelta(seconds=60))
        if self.active_until is not None and at >= self.active_until:
            self.active_kind = None
            self.active_until = None
            self.gap_pending = True
        watts = 40.0 + ({"heater": 2040.0, "kettle": 1820.0}.get(self.active_kind, 0.0))
        self.sequence += 1
        provenance = Provenance(origin=Origin.simulated, kind=ValueKind.measured)
        if self.gap_pending:
            # Fim da sessão: a tomada falha uma leitura e volta à base. O motor fecha o consumo
            # logo (recuperação definitiva) em vez de esperar os 10 min da pausa de termóstato,
            # senão o apresentador esperaria ~13 min pelo pedido «De quem é esta conta?».
            self.gap_pending = False
            reading = EnergyReading(
                id=stable_id("demo-live-reading", str(PLUG), at.isoformat()),
                device_id=PLUG,
                ts=at,
                status=ReadingStatus.missing,
                power_w=None,
                provenance=Provenance(origin=Origin.simulated, kind=ValueKind.estimated),
            )
        else:
            reading = EnergyReading(
                id=stable_id("demo-live-reading", str(PLUG), at.isoformat()),
                device_id=PLUG,
                ts=at,
                observed_at=at,
                status=ReadingStatus.ok,
                power_w=watts,
                raw_unit="W",
                provenance=provenance,
            )
        event = EnergyReadingRecorded(
            id=reading.id,
            household_id=fx.HOUSEHOLD,
            correlation_id=stable_id("demo-live-correlation", at.isoformat()),
            ts=at,
            provenance=reading.provenance,
            data=reading,
        )
        await self.bus.publish(event)
        self.last_reading = at
        return 1


def enabled(settings: Settings, source_kind: str) -> bool:
    return (
        settings.profile == "demo"
        and settings.home_backend == "fake"
        and settings.demo_live
        and source_kind == "demo"
    )


async def _is_demo(db) -> bool:
    row = await db.run(
        lambda c: c.execute(
            "SELECT source_kind FROM household WHERE id=?",
            (str(fx.HOUSEHOLD),),
        ).fetchone()
    )
    return row is not None and row[0] == "demo"


async def _runner(controller: DemoLive, sleep: Sleep) -> None:
    while True:
        await sleep(5)
        await controller.tick()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    source_demo = await _is_demo(app.state.db)
    app.state.demo_live = None
    task = None
    if enabled(settings, "demo" if source_demo else "real"):
        now = datetime.now(UTC)
        controller = DemoLive(app.state.bus, clock=lambda: datetime.now(UTC), started_at=now)
        app.state.demo_live = controller
        await controller.tick(now)
        task = asyncio.create_task(_runner(controller, asyncio.sleep), name="demo-live")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


router = APIRouter(prefix="/api/demo/live", tags=["demo-live"], lifespan=lifespan)


class SessionStarted(BaseModel):
    status: Literal["started"] = "started"
    provenance: Literal["simulated"] = "simulated"


async def _start(
    kind: Literal["heater", "kettle"], request: Request, user: CurrentUser, db: DbDep
) -> SessionStarted:
    controller = getattr(request.app.state, "demo_live", None)
    settings = get_settings()
    if controller is None or not enabled(settings, "demo" if await _is_demo(db) else "real"):
        raise HTTPException(
            404,
            {"code": "demo_live_unavailable", "message": "Simulador indisponível"},
        )
    await require_operator(user, db, lambda: datetime.now(UTC))
    await controller.start(kind)
    return SessionStarted()


@router.post("/heater", response_model=SessionStarted)
async def heater(request: Request, user: CurrentUser, db: DbDep):
    return await _start("heater", request, user, db)


@router.post("/kettle", response_model=SessionStarted)
async def kettle(request: Request, user: CurrentUser, db: DbDep):
    return await _start("kettle", request, user, db)
