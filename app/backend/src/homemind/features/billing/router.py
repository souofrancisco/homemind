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
    BillAllocation,
    BillIn,
    BillInconsistentError,
    BillPreview,
    BillStatus,
    BillView,
    LandlordBillView,
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
from homemind.features.billing import attributor, bills, closing

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
    if access.grant is Grant.own:  # inquilino: só fechadas (e revisões antigas, para auditoria)
        return (BillStatus.finalized, BillStatus.superseded)
    return tuple(BillStatus)


def _validate(conn, access: HouseholdAccess, body: BillIn, now) -> BillPreview:
    house = conn.execute(
        "SELECT timezone, source_kind FROM household WHERE id = ?", (str(access.household_id),)
    ).fetchone()
    today = now.astimezone(ZoneInfo(house["timezone"])).date()
    return bills.check_bill(body, today, real_household=house["source_kind"] == "real")


def _check(conn, access: HouseholdAccess, body: BillIn, now):
    preview = _validate(conn, access, body, now)
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


# --- fecho do mês e correções (BILL-04) ------------------------------------------------------

ReceiptAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.receipt))]


def _state_error(e: closing.BillStateError) -> HTTPException:
    return HTTPException(409, {"code": e.code, "message": str(e)})


async def _commit(request: Request, db: Database, work):
    """Corre `work(conn) -> (eventos, resultado)` numa transação, grava os eventos no outbox e
    acorda os consumidores. Traduz os erros de domínio para HTTP."""

    def run(conn):
        events, result = work(conn)
        for e in events:
            append_event(conn, e)
        return events, result

    try:
        events, result = await db.run(run)
    except LookupError:
        raise _not_found() from None
    except closing.BillStateError as e:
        raise _state_error(e) from None
    except BillInconsistentError as e:
        raise _inconsistent(e) from None
    for e in events:
        await request.app.state.bus.publish(e)  # idempotente por id
    return result


@router.post("/households/{household_id}/bills/{bill_id}/finalize")
async def finalize_bill(
    bill_id: UUID, access: WriteAccess, db: DbDep, clock: ClockDep, request: Request
) -> BillView:
    """Calcula e fixa as parcelas (Σ = total ao cêntimo). Repetir: `409 bill_finalized`."""
    now = clock()

    def work(conn):
        events = closing.finalize(conn, access.household_id, bill_id, now)
        return events, bills.get_bill(conn, access.household_id, bill_id)

    return bills.to_view(await _commit(request, db, work))


@router.post("/households/{household_id}/bills/{bill_id}/revisions", status_code=201)
async def revise_bill(
    bill_id: UUID,
    body: BillIn,
    access: WriteAccess,
    db: DbDep,
    clock: ClockDep,
    request: Request,
) -> BillView:
    """Correção de uma fatura fechada: nova revisão já fechada; a anterior fica `superseded`
    com as suas parcelas (auditoria). Rascunho: `409 bill_not_finalized`."""
    now, new = clock(), new_id()

    def work(conn):
        _validate(conn, access, body, now)
        events = closing.revise(
            conn, access.household_id, bill_id, body, new, access.resident_id, now
        )
        return events, bills.get_bill(conn, access.household_id, new)

    return bills.to_view(await _commit(request, db, work))


def _closed_bill(conn, access: HouseholdAccess, bill_id: UUID):
    row = bills.get_bill(conn, access.household_id, bill_id)
    if row is None or row["status"] not in (BillStatus.finalized, BillStatus.superseded):
        raise LookupError
    return row


@router.get("/households/{household_id}/bills/{bill_id}/summary")
async def bill_summary(bill_id: UUID, access: ReceiptAccess, db: DbDep) -> LandlordBillView:
    """Senhorio: totais por quarto (nunca aparelhos, horários nem presença)."""
    if access.grant is not Grant.aggregate:
        raise HTTPException(403, {"code": "forbidden_role", "message": "Só para o senhorio"})
    try:
        return await db.run(lambda c: closing.landlord_view(c, _closed_bill(c, access, bill_id)))
    except LookupError:
        raise _not_found() from None


@router.get("/households/{household_id}/bills/{bill_id}/receipt")
async def my_receipt(bill_id: UUID, access: ReceiptAccess, db: DbDep) -> BillAllocation:
    """Inquilino: o seu recibo, linha a linha, com a proveniência de cada valor."""
    if access.grant is not Grant.own:
        raise HTTPException(403, {"code": "forbidden_role", "message": "Só para inquilinos"})

    def read(conn):
        _closed_bill(conn, access, bill_id)
        mine = [
            a for a in closing.allocations_of(conn, bill_id) if a.resident_id == access.resident_id
        ]
        if not mine:
            raise LookupError
        return mine[0]

    try:
        return await db.run(read)
    except LookupError:
        raise _not_found() from None
