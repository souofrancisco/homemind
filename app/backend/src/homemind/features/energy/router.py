"""Runtime da energia: liga o `StepTracker` ao barramento e expõe a leitura ao morador.

Não reimplementa deteção nem classificação (ENERGY-02/03): só subscreve o consumidor existente.
O senhorio e o operador nunca recebem leituras nem sessões (RBAC: só o morador, âmbito casa).
"""

import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException

from homemind.contracts.common import ContractModel, Provenance
from homemind.contracts.domain_events import StoredEvent
from homemind.contracts.energy import ConsumptionEvent, EnergyReading
from homemind.core.access import (
    ClockDep,
    DbDep,
    Grant,
    HouseholdAccess,
    Resource,
    require_access,
)
from homemind.core.events import Handler
from homemind.features.appliances.repo import SqliteApplianceCatalog
from homemind.features.energy.consumer import make_step_consumer
from homemind.features.energy.steps import StepTracker

CONSUMER = "energy.steps"
EVENT_TYPES = ["energy.reading_recorded"]


def make_dispatcher() -> Handler:
    """Um `StepTracker` por casa, criado à primeira leitura.

    shortcut: o estado dos trackers vive só em memória; após reinício a sessão em curso perde-se
    e recomeça na próxima leitura. Persistir o estado quando houver medição real contínua.
    """
    catalog = SqliteApplianceCatalog()
    handlers: dict[UUID, Handler] = {}

    def handle(conn: sqlite3.Connection, stored: StoredEvent):
        house = stored.event.household_id
        if house not in handlers:
            handlers[house] = make_step_consumer(StepTracker(household_id=house), catalog=catalog)
        return handlers[house](conn, stored)

    return handle


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.bus.subscribe(CONSUMER, make_dispatcher(), EVENT_TYPES)
    yield


router = APIRouter(
    prefix="/api/households/{household_id}/energy", tags=["energy"], lifespan=lifespan
)
Read = Annotated[HouseholdAccess, Depends(require_access(Resource.consumption))]

SESSIONS_LIMIT = 20
SCAN_LIMIT = 500


class MeterReadingView(ContractModel):
    """Última leitura de UMA tomada. Não é o total da casa."""

    device_id: UUID
    read_at: datetime
    status: Literal["ok", "missing", "unit_unknown", "stale"]
    power_w: float | None  # None = sem valor (nunca 0 W por omissão)
    provenance: Provenance


class ConsumptionSessionView(ContractModel):
    id: UUID
    device_id: UUID
    started_at: datetime
    ended_at: datetime | None
    status: Literal["ongoing", "closed"]
    peak_w: float
    energy_wh: float | None
    location: Literal["room", "common", "unknown"]
    appliance_id: UUID | None  # None = aparelho não identificado
    confidence: float | None
    cost_cents: int | None
    provenance: Provenance


class EnergyOverview(ContractModel):
    now: datetime
    meters: list[MeterReadingView]
    sessions: list[ConsumptionSessionView]


def _overview(conn: sqlite3.Connection, house: UUID, now: datetime) -> EnergyOverview:
    meters: dict[UUID, MeterReadingView] = {}
    rows = conn.execute(
        "SELECT payload_json FROM domain_event WHERE household_id = ?"
        " AND type = 'energy.reading_recorded' ORDER BY seq DESC LIMIT ?",
        (str(house), SCAN_LIMIT),
    )
    for row in rows:
        r = EnergyReading.model_validate(json.loads(row["payload_json"]))
        if r.device_id not in meters:
            meters[r.device_id] = MeterReadingView(
                device_id=r.device_id,
                read_at=r.ts,
                status=r.status.value,
                power_w=r.power_w,
                provenance=r.provenance,
            )
    sessions: dict[UUID, ConsumptionSessionView] = {}
    rows = conn.execute(
        "SELECT payload_json FROM domain_event WHERE household_id = ?"
        " AND type IN ('energy.consumption_detected','energy.consumption_closed')"
        " ORDER BY seq DESC LIMIT ?",
        (str(house), SCAN_LIMIT),
    )
    for row in rows:
        c = ConsumptionEvent.model_validate(json.loads(row["payload_json"]))
        if c.id in sessions or c.status.value == "discarded":
            continue
        sessions[c.id] = ConsumptionSessionView(
            id=c.id,
            device_id=c.device_id,
            started_at=c.started_at,
            ended_at=c.ended_at,
            status=c.status.value,
            peak_w=c.peak_w,
            energy_wh=c.energy_wh,
            location=c.location.value,
            appliance_id=c.match.appliance_id,
            confidence=c.match.confidence,
            cost_cents=c.cost_estimate.cents if c.cost_estimate else None,
            provenance=c.provenance,
        )
    recent = sorted(sessions.values(), key=lambda s: s.started_at, reverse=True)
    return EnergyOverview(now=now, meters=list(meters.values()), sessions=recent[:SESSIONS_LIMIT])


@router.get("/overview")
async def energy_overview(access: Read, db: DbDep, clock: ClockDep) -> EnergyOverview:
    """Leituras por tomada e sessões recentes. Só moradores (dados de hábitos)."""
    if access.grant is not Grant.household:
        raise HTTPException(403, {"code": "forbidden_role", "message": "Só para moradores"})
    now = clock()
    return await db.run(lambda c: _overview(c, access.household_id, now))
