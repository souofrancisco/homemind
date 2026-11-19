"""Fecho do mês (BILL-04): calcula, fixa e publica as parcelas de uma fatura; correções.

Tudo numa transação: fatura `draft → finalized`, parcelas gravadas (imutáveis) e eventos
(`billing.bill_finalized`, `billing.allocation_published`) no *outbox*. Repetir o fecho é
`409 bill_finalized` e nunca duplica nada. Uma correção é uma nova revisão (a anterior fica
`superseded`, com as suas parcelas, para auditoria).

Entram na fatura os consumos FECHADOS iniciados no período (dia no fuso da casa) com
atribuição ativa; o resto fica no resíduo, dividido por igual (nunca cria dívida). Moradores =
inquilinos com contrato no período (entradas e saídas no fim do mês, D-33).
"""

import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts import domain_events as de
from homemind.contracts.billing import (
    AllocationStatus,
    Attribution,
    BillAllocation,
    BillIn,
    BillInconsistentError,
    BillPeriod,
    BillStatus,
    ElectricityBill,
    LandlordBillView,
    RoomTotal,
)
from homemind.contracts.common import Audit, Provenance, replace, stable_id
from homemind.contracts.energy import ConsumptionEvent
from homemind.features.billing import allowance, attributor, bills
from homemind.features.billing.allocation import (
    EnergyShare,
    allocate,
    shares_from_attributions,
)


class BillStateError(ValueError):
    """Operação incompatível com o estado da fatura (→ 409)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def tenants_in_period(
    conn: sqlite3.Connection, household_id: UUID, period: BillPeriod
) -> dict[UUID, UUID | None]:
    rows = conn.execute(
        "SELECT resident_id, room_id FROM membership WHERE household_id = ? AND role = 'tenant'"
        " AND status IN ('active', 'ended') AND starts_on <= ?"
        " AND (ends_on IS NULL OR ends_on >= ?) ORDER BY starts_on",
        (str(household_id), period.end.isoformat(), period.start.isoformat()),
    ).fetchall()
    return {UUID(r["resident_id"]): UUID(r["room_id"]) if r["room_id"] else None for r in rows}


def period_inputs(
    conn: sqlite3.Connection, household_id: UUID, period: BillPeriod
) -> tuple[list[Attribution], dict[UUID, ConsumptionEvent]]:
    """Atribuições ativas e consumos iniciados no período (dia local da casa)."""
    tz = ZoneInfo(
        conn.execute(
            "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
        ).fetchone()["timezone"]
    )
    lo = (period.start - timedelta(days=1)).isoformat()
    hi = (period.end + timedelta(days=2)).isoformat()
    rows = conn.execute(
        "SELECT c.json AS c_json, a.json AS a_json FROM billing_consumption c"
        " JOIN billing_attribution a ON a.consumption_event_id = c.id AND a.status = 'active'"
        " WHERE c.household_id = ? AND c.started_at >= ? AND c.started_at < ?",
        (str(household_id), lo, hi),
    ).fetchall()
    attributions, consumptions = [], {}
    for r in rows:
        c = ConsumptionEvent.model_validate_json(r["c_json"])
        if period.start <= c.started_at.astimezone(tz).date() <= period.end:
            consumptions[c.id] = c
            attributions.append(Attribution.model_validate_json(r["a_json"]))
    return attributions, consumptions


def undecided_in_period(
    conn: sqlite3.Connection, household_id: UUID, period: BillPeriod
) -> list[ConsumptionEvent]:
    """Consumos fechados do período SEM atribuição ativa: ficam no resíduo (BILL-05 explica)."""
    tz = ZoneInfo(
        conn.execute(
            "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
        ).fetchone()["timezone"]
    )
    lo = (period.start - timedelta(days=1)).isoformat()
    hi = (period.end + timedelta(days=2)).isoformat()
    rows = conn.execute(
        "SELECT c.json FROM billing_consumption c WHERE c.household_id = ?"
        " AND c.status = 'closed' AND c.energy_wh > 0 AND c.started_at >= ? AND c.started_at < ?"
        " AND NOT EXISTS (SELECT 1 FROM billing_attribution a"
        "  WHERE a.consumption_event_id = c.id AND a.status = 'active') ORDER BY c.started_at",
        (str(household_id), lo, hi),
    ).fetchall()
    out = [ConsumptionEvent.model_validate_json(r["json"]) for r in rows]
    return [c for c in out if period.start <= c.started_at.astimezone(tz).date() <= period.end]


def _save_evidence(
    conn: sqlite3.Connection,
    bill: ElectricityBill,
    attributions: list[Attribution],
    consumptions: dict[UUID, ConsumptionEvent],
    shares: list[EnergyShare],
    residents: dict[UUID, UUID | None],
    heating: frozenset[UUID],
    covered: dict[UUID, int],
) -> None:
    """Fotografia do que entrou na fatura (e do que ficou no resíduo), para a explicar depois.
    `shares` são as partes ANTES do plafond (uma por consumo); `covered` diz quanto ele cobriu."""
    by_consumption = {a.consumption_event_id: a for a in attributions}
    rows = []
    for s in shares:
        a, c = by_consumption[s.consumption_id], consumptions[s.consumption_id]
        superseded = conn.execute(
            "SELECT count(*) FROM billing_attribution WHERE consumption_event_id = ?"
            " AND status = 'superseded'",
            (str(c.id),),
        ).fetchone()[0]
        proven = s.resident_id is not None and allowance.is_proven_heating(
            c, residents.get(s.resident_id), heating
        )
        rows.append(
            (c, 1, s.resident_id, superseded, a.model_dump_json(), proven, covered.get(c.id, 0))
        )
    for c in undecided_in_period(conn, bill.household_id, bill.period):
        rows.append((c, 0, None, 0, None, False, 0))
    conn.executemany(
        "INSERT INTO billing_allocation_item (bill_id, consumption_event_id, household_id,"
        " attributed, target_resident_id, energy_wh, superseded_count, consumption_json,"
        " attribution_json, heating, covered_wh) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                str(bill.id),
                str(c.id),
                str(bill.household_id),
                attributed,
                str(resident) if resident else None,
                c.energy_wh,
                superseded,
                c.model_dump_json(),
                a_json,
                int(proven),
                cov,
            )
            for c, attributed, resident, superseded, a_json, proven, cov in rows
        ],
    )


def heating_appliances(conn: sqlite3.Connection, household_id: UUID) -> frozenset[UUID]:
    """Aparelhos do catálogo da casa na categoria `heating` (inclui os já retirados: um consumo
    antigo continua a ser de um aquecedor)."""
    rows = conn.execute(
        "SELECT id FROM appliance WHERE household_id = ? AND category = 'heating'",
        (str(household_id),),
    ).fetchall()
    return frozenset(UUID(r["id"]) for r in rows)


def monthly_allowance(
    conn: sqlite3.Connection, household_id: UUID
) -> dict[UUID, Callable[[date], int]]:
    """Quarto → (dia 1 do mês → plafond mensal em Wh). A versão mais recente já começada nesse
    mês (`billing_room_allowance`) ou, antes dela, o `room.included_wh` da criação."""
    rooms = conn.execute(
        "SELECT id, included_wh FROM room WHERE household_id = ? AND kind = 'bedroom'",
        (str(household_id),),
    ).fetchall()
    changes: dict[str, list[tuple[date, int]]] = {}
    for r in conn.execute(
        "SELECT room_id, effective_from, included_wh FROM billing_room_allowance"
        " WHERE household_id = ? ORDER BY effective_from",
        (str(household_id),),
    ):
        changes.setdefault(r["room_id"], []).append(
            (date.fromisoformat(r["effective_from"]), r["included_wh"])
        )

    def per_month(initial: int, versions: list[tuple[date, int]]) -> Callable[[date], int]:
        def wh(month: date) -> int:
            value = initial
            for start, v in versions:
                if start <= month:
                    value = v
            return value

        return wh

    return {
        UUID(r["id"]): per_month(r["included_wh"] or 0, changes.get(r["id"], [])) for r in rooms
    }


def room_limits(
    conn: sqlite3.Connection, household_id: UUID, period: BillPeriod
) -> dict[UUID, int]:
    """Plafond solidário de cada quarto para o período (mensal, com as mudanças por mês)."""
    limits = {
        room: allowance.period_limit(wh, period)
        for room, wh in monthly_allowance(conn, household_id).items()
    }
    return {room: wh for room, wh in limits.items() if wh > 0}


def _bill(conn: sqlite3.Connection, household_id: UUID, bill_id: UUID) -> sqlite3.Row:
    row = bills.get_bill(conn, household_id, bill_id)
    if row is None:
        raise LookupError("fatura não encontrada")
    return row


def _model(row: sqlite3.Row) -> ElectricityBill:
    return ElectricityBill(
        id=row["id"],
        household_id=row["household_id"],
        period=BillPeriod(start=row["period_start"], end=row["period_end"]),
        total_cents=row["total_cents"],
        fixed_cents=row["fixed_cents"],
        total_wh=row["total_wh"],
        source=row["source"],
        status=row["status"],
        provenance=Provenance(origin=row["origin"], kind=row["kind"]),
        created_by=Audit(at=row["created_at"], by_resident_id=row["created_by_resident_id"]),
        revision=row["revision"],
        supersedes_id=row["supersedes_id"],
    )


def finalize(
    conn: sqlite3.Connection, household_id: UUID, bill_id: UUID, now: datetime
) -> list[de.DomainEvent]:
    """Fecha um rascunho. Devolve os eventos a publicar (já gravados nesta transação pelo
    chamador). `BillInconsistentError` se os kWh atribuídos excedem a fatura."""
    bill = _model(_bill(conn, household_id, bill_id))
    if bill.status is not BillStatus.draft:
        raise BillStateError("bill_finalized", "a fatura já foi fechada")
    events: list[de.DomainEvent] = list(attributor.expire_pending(conn, now))
    attributions, consumptions = period_inputs(conn, household_id, bill.period)
    residents = tenants_in_period(conn, household_id, bill.period)
    shares = shares_from_attributions(attributions, consumptions)
    heating = heating_appliances(conn, household_id)
    limits = room_limits(conn, household_id, bill.period)
    split, covered = allowance.apply(shares, consumptions, residents, limits, heating)
    conn.executemany(
        "INSERT INTO billing_allowance (bill_id, room_id, limit_wh) VALUES (?,?,?)",
        [(str(bill.id), str(room), wh) for room, wh in limits.items()],
    )
    allocations = [
        replace(a, status=AllocationStatus.published) for a in allocate(bill, residents, split)
    ]
    _save_evidence(conn, bill, attributions, consumptions, shares, residents, heating, covered)
    for a in allocations:
        conn.execute(
            "INSERT INTO billing_allocation (id, bill_id, household_id, resident_id, room_id,"
            " amount_cents, attributed_wh, status, json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(a.id),
                str(bill.id),
                str(household_id),
                str(a.resident_id),
                str(a.room_id) if a.room_id else None,
                a.amount_cents,
                a.attributed_total_wh,
                a.status.value,
                a.model_dump_json(),
                now.isoformat(),
            ),
        )
    bill.transition(BillStatus.finalized)
    conn.execute(
        "UPDATE billing_bill SET status = 'finalized' WHERE id = ? AND status = 'draft'",
        (str(bill.id),),
    )
    base = {"ts": now, "household_id": household_id, "provenance": bill.provenance}
    correlation = stable_id("correlation", "bill", str(bill.id))
    events.append(
        de.BillingBillFinalized(
            id=stable_id("billing.bill_finalized", str(bill.id)),
            correlation_id=correlation,
            data=de.BillRef(bill_id=bill.id, revision=bill.revision),
            **base,
        )
    )
    events += [
        de.BillingAllocationPublished(
            id=stable_id("billing.allocation_published", str(a.id)),
            correlation_id=correlation,
            data=de.AllocationPublished(
                bill_id=bill.id, allocation_id=a.id, resident_id=a.resident_id
            ),
            **base,
        )
        for a in allocations
    ]
    return events


def revise(
    conn: sqlite3.Connection,
    household_id: UUID,
    bill_id: UUID,
    body: BillIn,
    new_id: UUID,
    by_resident: UUID,
    now: datetime,
) -> list[de.DomainEvent]:
    """Correção de uma fatura fechada: nova revisão já fechada; a anterior fica `superseded`
    (com as suas parcelas). O chamador já validou `body` (`bills.check_bill`)."""
    old = _model(_bill(conn, household_id, bill_id))
    if old.status is not BillStatus.finalized:
        raise BillStateError("bill_not_finalized", "só se corrige uma fatura fechada")
    old.transition(BillStatus.superseded)
    conn.execute(
        "UPDATE billing_bill SET status = 'superseded' WHERE id = ? AND status = 'finalized'",
        (str(old.id),),
    )
    if bills.overlaps(conn, household_id, body.period):
        raise BillInconsistentError("já existe outra fatura para (parte d)este período")
    new = replace(
        bills.new_bill(new_id, household_id, body, by_resident, now),
        revision=old.revision + 1,
        supersedes_id=old.id,
    )
    bills.insert_bill(conn, new, body.price_millicents_per_kwh)
    created = de.BillingBillCreated(
        id=stable_id("billing.bill_created", str(new.id)),
        ts=now,
        household_id=household_id,
        provenance=new.provenance,
        data=de.BillRef(bill_id=new.id, revision=new.revision),
    )
    return [created, *finalize(conn, household_id, new.id, now)]


# --- leituras ----------------------------------------------------------------------------------


def allocations_of(conn: sqlite3.Connection, bill_id: UUID) -> list[BillAllocation]:
    rows = conn.execute(
        "SELECT json FROM billing_allocation WHERE bill_id = ? ORDER BY resident_id",
        (str(bill_id),),
    ).fetchall()
    return [BillAllocation.model_validate_json(r["json"]) for r in rows]


def landlord_view(conn: sqlite3.Connection, row: sqlite3.Row) -> LandlordBillView:
    """Só totais por quarto: nunca aparelhos, horários, presença nem nomes de moradores."""
    names = {
        r["id"]: r["name"]
        for r in conn.execute(
            "SELECT id, name FROM room WHERE household_id = ?", (row["household_id"],)
        )
    }
    view = bills.to_view(row)
    return LandlordBillView(
        bill_id=view.id,
        period=view.period,
        total_cents=view.total_cents,
        status=view.status,
        rooms=[
            RoomTotal(
                room_id=a.room_id,
                room_name=names.get(str(a.room_id), "Quarto"),
                amount_cents=a.amount_cents,
                energy_wh=a.attributed_total_wh,
            )
            for a in allocations_of(conn, view.id)
            if a.room_id is not None
        ],
    )
