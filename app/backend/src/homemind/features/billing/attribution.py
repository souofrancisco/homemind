"""Primeira decisão sobre um consumo (BILL-02): quarto → morador; zona comum → perguntar ou dividir.

Regras (CLAUDE.md, «Regras de domínio»):
- «O teu quarto é teu»: consumo num quarto com morador é desse morador (vem do contrato).
- Zonas comuns e localização desconhecida: conta o sítio do aparelho, não o dono. Com a regra
  `ask` e custo estimado ≥ `ask_threshold_cents`, pergunta-se na app; abaixo do limiar, sem
  custo estimável ou com a regra `equal`, vai para a conta comum (dividida por igual).
- A regra C (`presence`) ainda não existe (BILL-07): comporta-se como `equal`.

Funções puras: sem base de dados nem barramento. Quem consome os eventos garante que cada
consumo é decidido uma só vez (idempotência do barramento, D-19).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from homemind.contracts.billing import Attribution, AttributionMethod, AttributionTarget
from homemind.contracts.common import Audit, Provenance, ValueKind, stable_id
from homemind.contracts.energy import ConsumptionEvent, ConsumptionStatus, LocationKind
from homemind.contracts.household import CommonAreaRule, HouseholdPolicy
from homemind.contracts.notification import ConfirmationRequest

SYSTEM = "billing"


@dataclass(frozen=True)
class Decision:
    """No máximo um dos dois; nenhum = ainda não há nada a decidir (esperar pelo fecho)."""

    attribution: Attribution | None = None
    confirmation: ConfirmationRequest | None = None


def worth_asking(event: ConsumptionEvent, policy: HouseholdPolicy) -> bool:
    """Perguntar só quando vale a pena: custo estimado conhecido e ≥ limiar da casa."""
    cost = event.cost_estimate
    return (
        policy.common_area_rule is CommonAreaRule.ask
        and cost is not None
        and cost.cents >= policy.ask_threshold_cents
    )


def decide(
    event: ConsumptionEvent,
    policy: HouseholdPolicy,
    room_resident: Mapping[UUID, UUID],
    tenants: Sequence[UUID],
    now: datetime,
) -> Decision:
    """`room_resident`: quarto → morador ativo; `tenants`: inquilinos ativos (quem responde)."""
    if event.status is ConsumptionStatus.discarded:
        return Decision()
    resident = room_resident.get(event.room_id) if event.location is LocationKind.room else None
    if resident is not None:
        return Decision(_attribution(event, now, AttributionMethod.room_rule, resident))
    if worth_asking(event, policy) and tenants:
        return Decision(
            confirmation=ConfirmationRequest(
                consumption_event_id=event.id,
                estimated_cost_cents=event.cost_estimate.cents,
                eligible_resident_ids=list(tenants),
                expires_at=now + timedelta(hours=policy.ask_timeout_hours),
            )
        )
    if event.status is ConsumptionStatus.ongoing:
        return Decision()  # ainda pode passar o limiar; decide-se no fecho
    return Decision(_attribution(event, now, AttributionMethod.equal_fallback, None))


def _attribution(
    event: ConsumptionEvent, now: datetime, method: AttributionMethod, resident: UUID | None
) -> Attribution:
    # Regra determinística (contrato ou divisão por igual): não é uma inferência.
    provenance = Provenance(origin=event.provenance.origin, kind=ValueKind.measured)
    return Attribution(
        id=stable_id("attribution", str(event.id), "initial"),
        household_id=event.household_id,
        consumption_event_id=event.id,
        target_type=AttributionTarget.common if resident is None else AttributionTarget.resident,
        target_resident_id=resident,
        method=method,
        provenance=provenance,
        decided_by=Audit(at=now, by_system=SYSTEM),
    )
