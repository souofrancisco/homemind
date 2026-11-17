"""Traço técnico read-only de eventos da demo Conta Certa (DEMO-02).

Uma observação no barramento não prova que o motor de origem esteja implementado: os
eventos também podem ser publicados por um teste de contratos. Não inferimos faturas,
orçamentos, pessoas nem recibos a partir de um evento isolado.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from homemind.contracts.common import ContractModel
from homemind.core.access import DbDep, HouseholdAccess, Resource, require_access

router = APIRouter(
    prefix="/api/households/{household_id}/integration",
    tags=["integration"],
)

# Só nomes e metadados técnicos: payload_json (incluindo dados pessoais) nunca sai.
_PHASE_BY_EVENT = {
    "energy.reading_recorded": "reading_persisted",
    "energy.step_detected": "step_event_persisted",
    "energy.consumption_detected": "consumption_event_persisted",
    "energy.consumption_closed": "consumption_event_persisted",
    "billing.confirmation_needed": "confirmation_request_persisted",
    "notification.created": "notification_persisted",
    # D-32 emits one event per vote. The private outcome is deliberately not returned here.
    "notification.responded": "response_persisted",
    "billing.attribution_changed": "attribution_event_persisted",
    "alerts.threshold_crossed": "threshold_event_persisted",
    # BILL-01 currently creates drafts; only bill_finalized could prove finalization.
    "billing.bill_created": "bill_recorded",
    "billing.bill_finalized": "bill_finalized_event_persisted",
    "billing.allocation_published": "allocation_event_persisted",
}

OperatorAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.device))]


class TraceStep(ContractModel):
    seq: int = Field(strict=True, ge=1)
    event_type: str
    phase: str
    recorded_at: str
    origin: Literal["real", "simulated"]
    kind: Literal["measured", "estimated", "inferred"]


class TraceView(ContractModel):
    correlation_id: UUID
    source_kind: Literal["demo"] = "demo"
    # Nem um percurso com todos os eventos demonstra que as contas estão corretas.
    evidence_level: Literal["persisted_events_only"] = "persisted_events_only"
    # Missing event types mean only that no matching row was persisted for this correlation.
    # They do not establish why it is missing or whether a business operation succeeded.
    missing_event_types: list[str]
    events: list[TraceStep]


@router.get("/traces/{correlation_id}")
async def read_trace(
    correlation_id: UUID,
    access: OperatorAccess,
    db: DbDep,
) -> TraceView:
    """Somente operador da casa de DEMO; nunca expor consumos privados ao senhorio.

    O endpoint não consulta hardware, não publica eventos e não escreve na BD.
    Autorização por membership ativa é aplicada antes de consultar o histórico.
    """

    def query(conn):
        house = conn.execute(
            "SELECT source_kind FROM household WHERE id = ?",
            (str(access.household_id),),
        ).fetchone()
        rows = conn.execute(
            "SELECT seq, type, recorded_at, origin, kind FROM domain_event "
            "WHERE household_id = ? AND correlation_id = ? ORDER BY seq",
            (str(access.household_id), str(correlation_id)),
        ).fetchall()
        return house["source_kind"], rows

    source_kind, rows = await db.run(query)
    if source_kind != "demo":
        raise HTTPException(
            status_code=403,
            detail={"code": "demo_only", "message": "Diagnóstico reservado à demo"},
        )
    visible_rows = [row for row in rows if row["type"] in _PHASE_BY_EVENT]
    present_types = {row["type"] for row in visible_rows}
    return TraceView(
        correlation_id=correlation_id,
        missing_event_types=sorted(set(_PHASE_BY_EVENT) - present_types),
        events=[
            TraceStep(
                seq=row["seq"],
                event_type=row["type"],
                phase=_PHASE_BY_EVENT[row["type"]],
                recorded_at=row["recorded_at"],
                origin=row["origin"],
                kind=row["kind"],
            )
            for row in visible_rows
        ],
    )
