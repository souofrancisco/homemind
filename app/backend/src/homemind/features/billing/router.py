"""Faturas (BILL-01): pré-visualizar, gravar (rascunho) e ler. Arranca o atribuidor (BILL-02).

O senhorio copia a fatura real, vê a pré-visualização (preço médio derivado, dias) e só depois
grava; gravar emite `billing.bill_created`. Inquilinos só veem faturas finalizadas; o
operador não vê faturas. Repartição e fecho: BILL-02/04.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from homemind.contracts.billing import (
    BillIn,
    BillInconsistentError,
    BillPreview,
    BillStatus,
    BillView,
)
from homemind.contracts.common import new_id, stable_id
from homemind.contracts.domain_events import BillingBillCreated, BillRef
from homemind.core.access import (
    ClockDep,
    DbDep,
    Grant,
    HouseholdAccess,
    Operation,
    Resource,
    get_clock,
    require_access,
)
from homemind.core.db import Database
from homemind.core.events import EventBus, append_event
from homemind.features.billing import attributor, bills

log = logging.getLogger(__name__)
EXPIRY_INTERVAL_S = 60.0


async def run_expiry(db: Database, bus: EventBus, now: datetime) -> int:
    """Fecha os pedidos «De quem é esta conta?» sem decisão no prazo (→ por todos)."""

    def work(conn):
        events = attributor.expire_pending(conn, now)
        for e in events:
            append_event(conn, e)  # mesma transação do efeito
        return events

    events = await db.run(work)
    for e in events:
        await bus.publish(e)  # idempotente por id: só acorda os consumidores
    return len(events)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    clock = app.dependency_overrides.get(get_clock, get_clock)()
    app.state.bus.subscribe(attributor.CONSUMER, attributor.handle, attributor.EVENT_TYPES)

    async def expiry_loop() -> None:
        while True:
            try:
                await run_expiry(app.state.db, app.state.bus, clock())
            except Exception:  # nunca derruba o servidor; tenta no próximo ciclo
                log.exception("falha ao expirar pedidos de confirmação")
            await asyncio.sleep(EXPIRY_INTERVAL_S)

    task = asyncio.create_task(expiry_loop(), name="billing:expiry")
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


router = APIRouter(prefix="/api", tags=["billing"], lifespan=lifespan)

ReadAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.bill))]
WriteAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.bill, Operation.write))]


def _inconsistent(e: BillInconsistentError) -> HTTPException:
    return HTTPException(422, {"code": "bill_inconsistent", "message": str(e)})


def _not_found() -> HTTPException:
    return HTTPException(404, {"code": "bill_not_found", "message": "Fatura não encontrada"})


def _visible(access: HouseholdAccess) -> tuple[BillStatus, ...]:
    if access.grant is Grant.own:  # inquilino: só o que já é definitivo
        return (BillStatus.finalized,)
    return tuple(BillStatus)


def _check(conn, access: HouseholdAccess, body: BillIn, now):
    house = conn.execute(
        "SELECT timezone, source_kind FROM household WHERE id = ?", (str(access.household_id),)
    ).fetchone()
    today = now.astimezone(ZoneInfo(house["timezone"])).date()
    preview = bills.check_bill(body, today, real_household=house["source_kind"] == "real")
    if bills.overlaps(conn, access.household_id, body.period):
        raise BillInconsistentError("já existe uma fatura para (parte d)este período")
    return preview


@router.post("/households/{household_id}/bills/preview")
async def preview_bill(
    body: BillIn, access: WriteAccess, db: DbDep, clock: ClockDep
) -> BillPreview:
    """Valida sem gravar: o senhorio confere os números antes de confirmar."""
    now = clock()
    try:
        return await db.run(lambda c: _check(c, access, body, now))
    except BillInconsistentError as e:
        raise _inconsistent(e) from None


@router.post("/households/{household_id}/bills", status_code=201)
async def create_bill(
    body: BillIn, access: WriteAccess, db: DbDep, clock: ClockDep, request: Request
) -> BillView:
    now = clock()
    bill = bills.new_bill(new_id(), access.household_id, body, access.resident_id, now)
    event = BillingBillCreated(
        id=stable_id("billing.bill_created", str(bill.id)),
        ts=now,
        household_id=bill.household_id,
        provenance=bill.provenance,
        data=BillRef(bill_id=bill.id, revision=bill.revision),
    )

    def save(conn):
        _check(conn, access, body, now)
        bills.insert_bill(conn, bill, body.price_millicents_per_kwh)
        append_event(conn, event)  # mesma transação (outbox)
        return bills.get_bill(conn, access.household_id, bill.id)

    try:
        row = await db.run(save)
    except BillInconsistentError as e:
        raise _inconsistent(e) from None
    await request.app.state.bus.publish(event)  # idempotente por id: só acorda os consumidores
    return bills.to_view(row)


@router.get("/households/{household_id}/bills")
async def list_bills(access: ReadAccess, db: DbDep) -> list[BillView]:
    rows = await db.run(lambda c: bills.list_bills(c, access.household_id, _visible(access)))
    return [bills.to_view(r) for r in rows]


@router.get("/households/{household_id}/bills/{bill_id}")
async def get_bill(bill_id: UUID, access: ReadAccess, db: DbDep) -> BillView:
    row = await db.run(lambda c: bills.get_bill(c, access.household_id, bill_id))
    if row is None or BillStatus(row["status"]) not in _visible(access):
        raise _not_found()  # rascunhos não existem para inquilinos
    return bills.to_view(row)
