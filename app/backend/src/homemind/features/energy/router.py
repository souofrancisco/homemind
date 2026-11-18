"""Runtime da energia: liga o `StepTracker` ao barramento e expõe a leitura ao morador.

Não reimplementa deteção nem classificação (ENERGY-02/03): só subscreve o consumidor existente.
O senhorio e o operador nunca recebem leituras nem sessões (RBAC: só o morador, âmbito casa).
"""

import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from homemind.contracts.appliance_catalog import ApplianceCatalog
from homemind.contracts.common import ContractModel, Provenance
from homemind.contracts.domain_events import StoredEvent
from homemind.contracts.energy import ConsumptionEvent, EnergyReading, LocationKind
from homemind.core.access import (
    ClockDep,
    DbDep,
    Grant,
    HouseholdAccess,
    Resource,
    require_access,
)
from homemind.core.events import Handler
from homemind.features.energy.consumer import make_step_consumer
from homemind.features.energy.home_runtime import home_runtime
from homemind.features.energy.identification_consumer import INPUT_TYPES as IDENTIFICATION_TYPES
from homemind.features.energy.identification_consumer import make_identification_consumer
from homemind.features.energy.learning_consumer import INPUT_TYPES as LEARNING_TYPES
from homemind.features.energy.learning_consumer import make_learning_consumer
from homemind.features.energy.signatures import signatures_router
from homemind.features.energy.steps import StepTracker, reading_time

CONSUMER = "energy.steps"
LEARNING_CONSUMER = "energy.learning"
IDENTIFICATION_CONSUMER = "energy.identification"  # ENERGY-04 (nome permanente)
EVENT_TYPES = ["energy.reading_recorded"]


def make_dispatcher(app: FastAPI) -> Handler:
    """Um `StepTracker` por casa, criado à primeira leitura.

    shortcut: o estado dos trackers vive só em memória; após reinício a sessão em curso perde-se
    e recomeça na próxima leitura. Persistir o estado quando houver medição real contínua.
    """
    handlers: dict[UUID, Handler] = {}

    def handle(conn: sqlite3.Connection, stored: StoredEvent):
        house = stored.event.household_id
        if house not in handlers:
            handlers[house] = make_step_consumer(
                StepTracker(household_id=house),
                # Publicado por `appliances` em app.state (sem importar a feature); lido tarde
                # para não depender da ordem de arranque. Sem catálogo: nada é identificado.
                catalog=getattr(app.state, "appliance_catalog", None),
            )
        return handlers[house](conn, stored)

    return handle


def make_learning_dispatcher(app: FastAPI) -> Handler:
    """Aprendizagem (ENERGY-01) com o catálogo publicado por `appliances` em `app.state`.

    Lido tarde, como o dispatcher dos degraus, para não depender da ordem de arranque. Sem
    catálogo não há nada a aprender: o evento é dado como tratado sem efeitos.
    """
    handler: Handler | None = None

    def handle(conn: sqlite3.Connection, stored: StoredEvent):
        nonlocal handler
        if handler is None:
            catalog = getattr(app.state, "appliance_catalog", None)
            if catalog is None:
                return []
            handler = make_learning_consumer(catalog)
        return handler(conn, stored)

    return handle


def make_identification_dispatcher(app: FastAPI) -> Handler:
    """Aprendizagem por confirmação (ENERGY-04), com o catálogo lido tarde de `app.state`.

    Sem catálogo não se agrupa nem se responde: o evento é dado como tratado sem efeitos.
    """
    handler: Handler | None = None

    def handle(conn: sqlite3.Connection, stored: StoredEvent):
        nonlocal handler
        if handler is None:
            catalog = getattr(app.state, "appliance_catalog", None)
            if catalog is None:
                return []
            handler = make_identification_consumer(catalog)
        return handler(conn, stored)

    return handle


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.bus.subscribe(CONSUMER, make_dispatcher(app), EVENT_TYPES)
    # ENERGY-01: aprendizagem automática de assinaturas a partir das sessões fechadas.
    app.state.bus.subscribe(LEARNING_CONSUMER, make_learning_dispatcher(app), LEARNING_TYPES)
    # ENERGY-04: «O que é este aparelho?» para consumos desconhecidos repetidos, e as respostas.
    app.state.bus.subscribe(
        IDENTIFICATION_CONSUMER, make_identification_dispatcher(app), IDENTIFICATION_TYPES
    )
    # O `Home` do kit (MCP) e os seus coletores/atuador (antes no lifespan do motor ObjectOS).
    async with home_runtime(app):
        yield


router = APIRouter(
    prefix="/api/households/{household_id}/energy", tags=["energy"], lifespan=lifespan
)
Read = Annotated[HouseholdAccess, Depends(require_access(Resource.consumption))]
router.include_router(signatures_router)  # ENERGY-01/04: /signatures, /identifications

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
    declared_room_id: UUID | None = None  # Pista declarada, nunca localização medida.


class EnergyCoverage(ContractModel):
    period_start: datetime
    period_end: datetime
    total_wh: int
    measured_wh: int
    inferred_wh: int
    unattributed_wh: int
    measured_percent: int
    inferred_percent: int
    unattributed_percent: int
    status: Literal["ok", "no_data"]
    adjusted: bool
    provenance: list[Provenance]


class EnergyOverview(ContractModel):
    now: datetime
    meters: list[MeterReadingView]
    sessions: list[ConsumptionSessionView]
    coverage: EnergyCoverage


def _apportion(values: list[Decimal], total: int) -> list[int]:
    """Largest remainder; ties follow measured, inferred, unattributed order."""
    weight = sum(values)
    if not weight:
        return [0] * len(values)
    exact = [v * total / weight for v in values]
    result = [int(v) for v in exact]
    order = sorted(range(len(values)), key=lambda i: (-(exact[i] - result[i]), i))
    for i in order[: total - sum(result)]:
        result[i] += 1
    return result


def _coverage(conn: sqlite3.Connection, house: UUID, now: datetime) -> EnergyCoverage:
    """Reconcile month-to-date socket energy with the latest session snapshots.

    Gaps break sample-and-hold, just as in StepTracker. Session Wh crossing the
    month boundary can only be prorated by duration: the persisted snapshots do
    not contain an hourly energy curve. This approximation concerns coverage,
    never strengthens location evidence and never changes billing events.
    """
    row = conn.execute("SELECT timezone FROM household WHERE id=?", (str(house),)).fetchone()
    zone = ZoneInfo(row[0])
    start = now.astimezone(zone).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = start.astimezone(UTC)
    previous: dict[UUID, EnergyReading] = {}
    latest_poll: dict[UUID, datetime] = {}
    latest_observation: dict[UUID, datetime] = {}
    total = Decimal(0)
    provenance: set[Provenance] = set()
    # Full history is intentional: neither SCAN_LIMIT nor SESSIONS_LIMIT defines
    # monthly coverage. The preceding month's last reading can bracket midnight.
    rows = conn.execute(
        "SELECT payload_json FROM domain_event WHERE household_id=?"
        " AND type='energy.reading_recorded' ORDER BY seq",
        (str(house),),
    )
    for row in rows:
        r = EnergyReading.model_validate(json.loads(row["payload_json"]))
        device, at = r.device_id, reading_time(r)
        if r.ts > now or (device in latest_poll and r.ts <= latest_poll[device]):
            continue
        latest_poll[device] = r.ts
        if not r.usable:
            previous.pop(device, None)
            latest_observation[device] = max(latest_observation.get(device, at), at)
            continue
        if device in latest_observation and at <= latest_observation[device]:
            continue
        latest_observation[device] = at
        before = previous.get(device)
        if before is not None:
            left, right = max(start, reading_time(before)), min(now, at)
            if right > left:
                seconds = Decimal(str((right - left).total_seconds()))
                total += Decimal(str(before.power_w)) * seconds / 3600
                provenance.update((before.provenance, r.provenance))
        previous[device] = r

    measured = inferred = Decimal(0)
    seen: set[UUID] = set()
    rows = conn.execute(
        "SELECT payload_json,ts FROM domain_event WHERE household_id=?"
        " AND type IN ('energy.consumption_detected','energy.consumption_closed')"
        " ORDER BY seq DESC",
        (str(house),),
    )
    for row in rows:
        event_at = datetime.fromisoformat(row["ts"])
        if event_at > now:
            continue
        c = ConsumptionEvent.model_validate(json.loads(row["payload_json"]))
        if c.id in seen:
            continue
        seen.add(c.id)
        if c.status.value == "discarded" or not c.energy_wh:
            continue
        end = c.ended_at or event_at
        left, right = max(start, c.started_at), min(now, end)
        if right <= left or end <= c.started_at:
            continue
        # Only cumulative session Wh exists. Across a month boundary use an
        # explicit duration prorata; never extrapolate an ongoing snapshot to now.
        energy = (
            Decimal(c.energy_wh)
            * Decimal(str((right - left).total_seconds()))
            / Decimal(str((end - c.started_at).total_seconds()))
        )
        if c.location in (LocationKind.room, LocationKind.common):
            measured += energy
        elif c.match.appliance_id is not None:
            inferred += energy
    total_wh = int(round(total))  # One final Wh rounding, ties to even (ENERGY-02).
    adjusted = measured + inferred > total
    values = [measured, inferred, max(Decimal(0), total - measured - inferred)]
    # If session rounding/overlap exceeds measured supply, scale proportionally;
    # no negative residual and no silent preference for either location category.
    wh = _apportion(values, total_wh) if total_wh else [0, 0, 0]
    percent = _apportion([Decimal(v) for v in wh], 100) if total_wh else [0, 0, 0]
    return EnergyCoverage(
        period_start=start,
        period_end=now,
        total_wh=total_wh,
        measured_wh=wh[0],
        inferred_wh=wh[1],
        unattributed_wh=wh[2],
        measured_percent=percent[0],
        inferred_percent=percent[1],
        unattributed_percent=percent[2],
        status="ok" if total_wh else "no_data",
        adjusted=adjusted,
        provenance=sorted(provenance, key=lambda p: (p.origin.value, p.kind.value)),
    )


def _overview(
    conn: sqlite3.Connection,
    house: UUID,
    now: datetime,
    catalog: ApplianceCatalog | None = None,
) -> EnergyOverview:
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
        ownership = (
            catalog.ownership_at(conn, house, c.match.appliance_id, c.started_at)
            if catalog is not None and c.match.appliance_id is not None
            else None
        )
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
            declared_room_id=ownership.home_room_id if ownership is not None else None,
        )
    recent = sorted(sessions.values(), key=lambda s: s.started_at, reverse=True)
    return EnergyOverview(
        now=now,
        meters=list(meters.values()),
        sessions=recent[:SESSIONS_LIMIT],
        coverage=_coverage(conn, house, now),
    )


@router.get("/overview")
async def energy_overview(
    access: Read, db: DbDep, clock: ClockDep, request: Request
) -> EnergyOverview:
    """Leituras por tomada e sessões recentes. Só moradores (dados de hábitos)."""
    if access.grant is not Grant.household:
        raise HTTPException(403, {"code": "forbidden_role", "message": "Só para moradores"})
    now = clock()
    catalog = getattr(request.app.state, "appliance_catalog", None)
    return await db.run(lambda c: _overview(c, access.household_id, now, catalog))
