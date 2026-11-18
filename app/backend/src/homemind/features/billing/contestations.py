"""Contestar, corrigir e reemitir parcelas (BILL-06).

O inquilino contesta o PRÓPRIO recibo (opcionalmente um consumo que lhe foi atribuído); o
senhorio decide, sempre com justificação. Rejeitar não mexe em nada. Aceitar:
- com consumo: esse consumo passa para a conta comum (por igual, método `manual`, auditado com
  o senhorio como autor) — o pior caso nunca é pior do que a divisão igual;
- com `bill`: os dados da fatura são corrigidos;
- e a fatura é SEMPRE reemitida como nova revisão (BILL-04): a anterior fica `superseded`, com
  as suas parcelas, e a contestação guarda o antes/depois da parcela de quem contestou.
Nada altera uma fatura fechada em silêncio: respostas tardias a «de quem é esta conta?» já
não mudam atribuições depois do prazo (atribuidor) e só uma revisão muda parcelas.
"""

import sqlite3
from datetime import datetime
from uuid import UUID

from homemind.contracts import domain_events as de
from homemind.contracts.billing import (
    Attribution,
    AttributionMethod,
    AttributionTarget,
    BillIn,
    BillPeriod,
    BillStatus,
    Contestation,
    ContestationDecisionIn,
    ContestationIn,
    ContestationStatus,
    LandlordContestationView,
)
from homemind.contracts.common import Audit, Provenance, ValueKind, replace, stable_id
from homemind.features.billing import attributor, bills, closing
from homemind.features.billing.closing import BillStateError


class ContestationNotFound(LookupError):
    pass


class InvalidContestation(ValueError):
    """Pedido incoerente (→ 400 `invalid_request`)."""


def _event(c: Contestation, household_id: UUID, bill: sqlite3.Row, now: datetime):
    return de.BillingContestationChanged(
        id=stable_id("billing.contestation_changed", str(c.id), c.status.value),
        ts=now,
        household_id=household_id,
        correlation_id=stable_id("correlation", "contestation", str(c.id)),
        provenance=Provenance(origin=bill["origin"], kind=bill["kind"]),
        data=c,
    )


def _allocation_of(conn: sqlite3.Connection, bill_id: UUID, resident_id: UUID):
    found = [a for a in closing.allocations_of(conn, bill_id) if a.resident_id == resident_id]
    return found[0] if found else None


def _save(conn: sqlite3.Connection, household_id: UUID, c: Contestation, by: UUID | None = None):
    conn.execute(
        "INSERT INTO billing_contestation (id, household_id, bill_id, resident_id, status, json,"
        " created_at, decided_by_resident_id) VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET bill_id = excluded.bill_id, status = excluded.status,"
        " json = excluded.json, decided_by_resident_id = excluded.decided_by_resident_id",
        (
            str(c.id),
            str(household_id),
            str(c.bill_id),
            str(c.resident_id),
            c.status.value,
            c.model_dump_json(),
            c.created_at.isoformat(),
            str(by) if by else None,
        ),
    )


def open_contestation(
    conn: sqlite3.Connection,
    household_id: UUID,
    bill_id: UUID,
    resident_id: UUID,
    body: ContestationIn,
    new_id: UUID,
    now: datetime,
) -> tuple[list[de.DomainEvent], Contestation]:
    bill = bills.get_bill(conn, household_id, bill_id)
    if bill is None or bill["status"] == BillStatus.draft:
        raise LookupError("fatura não encontrada")
    if bill["status"] != BillStatus.finalized:
        raise BillStateError(
            "bill_not_finalized", "esta fatura foi substituída: contesta a revisão em vigor"
        )
    allocation = _allocation_of(conn, bill_id, resident_id)
    if allocation is None:
        raise LookupError("sem parcela nesta fatura")
    if body.consumption_event_id is not None:
        mine = conn.execute(
            "SELECT 1 FROM billing_allocation_item WHERE bill_id = ? AND consumption_event_id = ?"
            " AND attributed = 1 AND target_resident_id = ?",
            (str(bill_id), str(body.consumption_event_id), str(resident_id)),
        ).fetchone()
        if mine is None:
            raise InvalidContestation("só podes contestar consumos atribuídos a ti nesta fatura")
    if conn.execute(
        "SELECT 1 FROM billing_contestation WHERE bill_id = ? AND resident_id = ?"
        " AND status = 'open'",
        (str(bill_id), str(resident_id)),
    ).fetchone():
        raise BillStateError("contestation_open", "já tens uma contestação aberta a esta fatura")
    c = Contestation(
        id=new_id,
        bill_id=bill_id,
        allocation_id=allocation.id,
        resident_id=resident_id,
        consumption_event_id=body.consumption_event_id,
        reason=body.reason,
        created_at=now,
    )
    _save(conn, household_id, c)
    return [_event(c, household_id, bill, now)], c


def get(conn: sqlite3.Connection, household_id: UUID, contestation_id: UUID) -> Contestation:
    row = conn.execute(
        "SELECT json FROM billing_contestation WHERE id = ? AND household_id = ?",
        (str(contestation_id), str(household_id)),
    ).fetchone()
    if row is None:
        raise ContestationNotFound("contestação não encontrada")
    return Contestation.model_validate_json(row["json"])


def _same_bill(bill: sqlite3.Row) -> BillIn:
    return BillIn(
        period=BillPeriod(start=bill["period_start"], end=bill["period_end"]),
        total_cents=bill["total_cents"],
        fixed_cents=bill["fixed_cents"],
        total_wh=bill["total_wh"],
        price_millicents_per_kwh=bill["declared_price_millicents_per_kwh"],
        origin=bill["origin"],
    )


def decide(
    conn: sqlite3.Connection,
    household_id: UUID,
    contestation_id: UUID,
    landlord_id: UUID,
    body: ContestationDecisionIn,
    new_bill_id: UUID,
    now: datetime,
) -> tuple[list[de.DomainEvent], Contestation]:
    """O chamador já validou `body.bill` (`bills.check_bill`) quando vem preenchido."""
    c = get(conn, household_id, contestation_id)
    if c.status is not ContestationStatus.open:
        raise BillStateError("contestation_resolved", "esta contestação já foi decidida")
    bill = bills.get_bill(conn, household_id, c.bill_id)
    before = _allocation_of(conn, c.bill_id, c.resident_id)
    assert bill is not None and before is not None
    events: list[de.DomainEvent] = []
    if body.status is ContestationStatus.rejected:
        decided = replace(
            c,
            status=ContestationStatus.rejected,
            resolved_at=now,
            resolution=body.resolution,
            before_cents=before.amount_cents,
            after_cents=before.amount_cents,
        )
    else:
        if c.consumption_event_id is not None:
            consumption = attributor.load_consumption(conn, c.consumption_event_id)
            common = Attribution(
                id=stable_id("attribution", str(consumption.id), "contestation", str(c.id)),
                household_id=household_id,
                consumption_event_id=consumption.id,
                target_type=AttributionTarget.common,
                method=AttributionMethod.manual,
                provenance=Provenance(
                    origin=consumption.provenance.origin, kind=ValueKind.measured
                ),
                decided_by=Audit(at=now, by_resident_id=landlord_id),
            )
            events.append(attributor.record(conn, common, stable_id("correlation", str(c.id))))
        events += closing.revise(
            conn, household_id, c.bill_id, body.bill or _same_bill(bill), new_bill_id,
            landlord_id, now,
        )  # fmt: skip
        after = _allocation_of(conn, new_bill_id, c.resident_id)
        decided = replace(
            c,
            status=ContestationStatus.accepted,
            resolved_at=now,
            resolution=body.resolution,
            revision_bill_id=new_bill_id,
            before_cents=before.amount_cents,
            after_cents=after.amount_cents if after else 0,
        )
        carry_over(conn, household_id, c.bill_id, new_bill_id, skip=c.id)
    _save(conn, household_id, decided, by=landlord_id)
    events.append(_event(decided, household_id, bill, now))
    return events, decided


def carry_over(
    conn: sqlite3.Connection,
    household_id: UUID,
    old_bill_id: UUID,
    new_bill_id: UUID,
    skip: UUID | None = None,
) -> None:
    """Uma correção da fatura leva as contestações ainda abertas para a nova revisão (a decisão
    passa a ser sobre os valores em vigor). Continuam abertas."""
    rows = conn.execute(
        "SELECT json FROM billing_contestation WHERE bill_id = ? AND status = 'open'",
        (str(old_bill_id),),
    ).fetchall()
    for r in rows:
        c = Contestation.model_validate_json(r["json"])
        if c.id == skip:
            continue
        allocation = _allocation_of(conn, new_bill_id, c.resident_id)
        if allocation is None:
            continue
        _save(conn, household_id, replace(c, bill_id=new_bill_id, allocation_id=allocation.id))


# --- leituras ----------------------------------------------------------------------------------


def mine(conn: sqlite3.Connection, household_id: UUID, resident_id: UUID) -> list[Contestation]:
    rows = conn.execute(
        "SELECT json FROM billing_contestation WHERE household_id = ? AND resident_id = ?"
        " ORDER BY created_at DESC, id",
        (str(household_id), str(resident_id)),
    ).fetchall()
    return [Contestation.model_validate_json(r["json"]) for r in rows]


def for_landlord(conn: sqlite3.Connection, household_id: UUID) -> list[LandlordContestationView]:
    """Quarto em vez de pessoa; nunca o consumo contestado (aparelho, horas) nem presença."""
    names = {
        r["id"]: r["name"]
        for r in conn.execute(
            "SELECT id, name FROM room WHERE household_id = ?", (str(household_id),)
        )
    }
    out = []
    for r in conn.execute(
        "SELECT json FROM billing_contestation WHERE household_id = ? ORDER BY created_at DESC, id",
        (str(household_id),),
    ).fetchall():
        c = Contestation.model_validate_json(r["json"])
        allocation = _allocation_of(conn, c.bill_id, c.resident_id)
        room = allocation.room_id if allocation else None
        out.append(
            LandlordContestationView(
                id=c.id,
                bill_id=c.bill_id,
                room_id=room,
                room_name=names.get(str(room)) if room else None,
                reason=c.reason,
                contests_consumption=c.consumption_event_id is not None,
                status=c.status,
                created_at=c.created_at,
                resolved_at=c.resolved_at,
                resolution=c.resolution,
                revision_bill_id=c.revision_bill_id,
                before_cents=c.before_cents,
                after_cents=c.after_cents,
            )
        )
    return out
