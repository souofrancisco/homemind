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
    "energy.reading_recorded": "reading",
    "energy.step_detected": "detection",
    "energy.consumption_detected": "consumption",
    "energy.consumption_closed": "consumption",
    "billing.confirmation_needed": "confirmation_requested",
    "notification.created": "notification",
    "notification.responded": "confirmation_answered",
    "billing.attribution_changed": "attribution",
    "alerts.threshold_crossed": "budget_threshold",
    "billing.bill_created": "bill_created",
    "billing.bill_finalized": "bill_finalized",
    "billing.allocation_published": "allocation_published",
}

OperatorAccess = Annotated[
    HouseholdAccess, Depends(require_access(Resource.device))
]


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
    return TraceView(
        correlation_id=correlation_id,
        events=[
            TraceStep(
                seq=row["seq"],
                event_type=row["type"],
                phase=_PHASE_BY_EVENT[row["type"]],
                recorded_at=row["recorded_at"],
                origin=row["origin"],
                kind=row["kind"],
            )
            for row in rows
            if row["type"] in _PHASE_BY_EVENT
        ],
    )
