"""Atribuição, fatura, alocações, orçamentos e contestações. Dono: billing (P4).

Só modelos e invariantes estruturais; o motor de cálculo é de P4. Dinheiro em cêntimos
inteiros. Nada se apaga nem se edita em silêncio: correções criam uma nova versão e marcam
a anterior `superseded`.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from homemind.contracts.common import (
    Audit,
    Cents,
    Confidence,
    ContractModel,
    EnergyWh,
    Origin,
    Pct,
    Period,
    Provenance,
    ShortText,
    SignedCents,
    UtcDatetime,
    ValueKind,
    check_transition,
    replace,
)
from homemind.contracts.energy import EnergyTotal

# --- atribuição -------------------------------------------------------------------------------


class AttributionTarget(StrEnum):
    resident = "resident"
    common = "common"


class AttributionMethod(StrEnum):
    room_rule = "room_rule"
    confirmation = "confirmation"
    presence_rule = "presence_rule"
    equal_fallback = "equal_fallback"
    manual = "manual"


class AttributionStatus(StrEnum):
    active = "active"
    superseded = "superseded"


class Attribution(ContractModel):
    id: UUID
    household_id: UUID
    consumption_event_id: UUID
    target_type: AttributionTarget
    target_resident_id: UUID | None = None
    method: AttributionMethod
    provenance: Provenance
    confidence: Confidence | None = None  # só em `inferred`
    decided_by: Audit
    status: AttributionStatus = AttributionStatus.active
    supersedes_id: UUID | None = None

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if (self.target_type is AttributionTarget.resident) != (
            self.target_resident_id is not None
        ):
            raise ValueError("target_resident_id exatamente quando o alvo é um morador")
        if (self.provenance.kind is ValueKind.inferred) != (self.confidence is not None):
            raise ValueError("confidence exatamente quando a natureza é inferred")
        if self.method is AttributionMethod.confirmation and self.decided_by.by_resident_id is None:
            raise ValueError("uma confirmação é decidida por um morador")
        return self


class AttributionConflictError(ValueError):
    """Um consumo com duas atribuições ativas, ou substituição inválida."""


def assert_single_active(attributions: list[Attribution]) -> None:
    seen: set[UUID] = set()
    for a in attributions:
        if a.status is AttributionStatus.active:
            if a.consumption_event_id in seen:
                raise AttributionConflictError("consumo com mais de uma atribuição ativa")
            seen.add(a.consumption_event_id)


def supersede(old: Attribution, new: Attribution) -> tuple[Attribution, Attribution]:
    """Troca a atribuição ativa: devolve (`old` como superseded, `new`). Nada é apagado."""
    if old.status is not AttributionStatus.active:
        raise AttributionConflictError("só se substitui uma atribuição ativa")
    if new.consumption_event_id != old.consumption_event_id or new.household_id != old.household_id:
        raise AttributionConflictError("a substituta é de outro consumo")
    if new.supersedes_id != old.id or new.status is not AttributionStatus.active:
        raise AttributionConflictError("a substituta tem de apontar para a anterior e estar ativa")
    return replace(old, status=AttributionStatus.superseded), new


# --- fatura ----------------------------------------------------------------------------------


class BillStatus(StrEnum):
    draft = "draft"
    finalized = "finalized"
    superseded = "superseded"  # substituída por uma revisão (correção)


BILL_TRANSITIONS = {
    BillStatus.draft: frozenset({BillStatus.finalized}),
    BillStatus.finalized: frozenset({BillStatus.superseded}),
    BillStatus.superseded: frozenset(),
}


class BillSource(StrEnum):
    manual = "manual"
    llm_extracted = "llm_extracted"


class BillPeriod(ContractModel):
    start: date
    end: date  # inclusivo

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("período invertido")
        return self

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


class ElectricityBill(ContractModel):
    """Totais da fatura real. `total_wh` NÃO é a soma do que a tomada mediu."""

    id: UUID
    household_id: UUID
    period: BillPeriod
    total_cents: Cents
    fixed_cents: Cents
    total_wh: Annotated[EnergyWh, Field(gt=0)]
    source: BillSource
    status: BillStatus = BillStatus.draft
    provenance: Provenance
    created_by: Audit
    revision: Annotated[int, Field(strict=True, ge=1)] = 1
    supersedes_id: UUID | None = None

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.fixed_cents > self.total_cents:
            raise ValueError("termo fixo superior ao total")
        if (self.revision > 1) != (self.supersedes_id is not None):
            raise ValueError("revisões >1 apontam para a anterior (e só elas)")
        return self

    @property
    def energy_cents(self) -> int:
        return self.total_cents - self.fixed_cents

    def transition(self, new: BillStatus) -> None:
        check_transition(BILL_TRANSITIONS, self.status, new)


class BillIn(ContractModel):
    """Entrada manual da fatura (BILL-01), copiada da fatura real pelo senhorio.

    `price_millicents_per_kwh` é opcional: a tarifa da fatura (com impostos), só para conferir
    que os valores fecham. `origin=simulated` só em casas de demonstração."""

    period: BillPeriod
    total_cents: Annotated[Cents, Field(gt=0)]
    fixed_cents: Cents
    total_wh: Annotated[EnergyWh, Field(gt=0)]
    price_millicents_per_kwh: Annotated[int, Field(strict=True, gt=0)] | None = None
    origin: Origin = Origin.real


class BillPreview(ContractModel):
    """Pré-visualização para validação humana antes de gravar (nada é gravado)."""

    period: BillPeriod
    days: int
    total_cents: Cents
    fixed_cents: Cents
    energy_cents: Cents
    total_wh: EnergyWh
    # Preço médio da energia derivado da fatura: (total − fixa) ÷ kWh.
    price_millicents_per_kwh: int
    origin: Origin


class BillView(ContractModel):
    """Cabeçalho da fatura (sem autor nem ids de terceiros)."""

    id: UUID
    period: BillPeriod
    total_cents: Cents
    fixed_cents: Cents
    total_wh: EnergyWh
    price_millicents_per_kwh: int
    status: BillStatus
    source: BillSource
    provenance: Provenance
    revision: int
    created_at: UtcDatetime


class BreakdownKind(StrEnum):
    fixed_share = "fixed_share"
    residual_share = "residual_share"
    room = "room"
    common = "common"
    appliance = "appliance"
    adjustment = "adjustment"  # único que pode ser negativo (ex.: plafond solidário)


class BillBreakdownLine(ContractModel):
    kind: BreakdownKind
    label: ShortText
    energy_wh: EnergyWh | None = None
    amount_cents: SignedCents
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def _non_negative(self) -> Self:
        if self.amount_cents < 0 and self.kind is not BreakdownKind.adjustment:
            raise ValueError("só `adjustment` pode ser negativo")
        return self


class AllocationStatus(StrEnum):
    draft = "draft"
    published = "published"
    contested = "contested"
    resolved = "resolved"


class BillAllocation(ContractModel):
    id: UUID
    bill_id: UUID
    resident_id: UUID
    room_id: UUID | None = None
    fixed_share_cents: Cents
    residual_share_cents: Cents  # parte do consumo comum não atribuído, explícita
    individual_cents: Cents
    amount_cents: Cents
    attributed_wh: list[EnergyTotal]
    breakdown: list[BillBreakdownLine]
    status: AllocationStatus = AllocationStatus.draft

    @model_validator(mode="after")
    def _adds_up(self) -> Self:
        parts = self.fixed_share_cents + self.residual_share_cents + self.individual_cents
        if parts != self.amount_cents:
            raise ValueError("amount_cents != fixa + resíduo + individual")
        if sum(line.amount_cents for line in self.breakdown) != self.amount_cents:
            raise ValueError("as linhas do recibo não somam amount_cents")
        keys = [t.provenance for t in self.attributed_wh]
        if len(set(keys)) != len(keys):
            raise ValueError("proveniência repetida nos kWh atribuídos")
        return self

    @property
    def attributed_total_wh(self) -> int:
        return sum(t.energy_wh for t in self.attributed_wh)


class BillInconsistentError(ValueError):
    """→ 422 `bill_inconsistent`."""


def validate_allocations(bill: ElectricityBill, allocations: list[BillAllocation]) -> None:
    """Soma exata, uma alocação por morador, e kWh atribuídos não excedem a fatura."""
    if any(a.bill_id != bill.id for a in allocations):
        raise BillInconsistentError("alocação de outra fatura")
    residents = [a.resident_id for a in allocations]
    if len(set(residents)) != len(residents):
        raise BillInconsistentError("morador repetido")
    if sum(a.amount_cents for a in allocations) != bill.total_cents:
        raise BillInconsistentError("a soma das alocações não é o total da fatura")
    if sum(a.attributed_total_wh for a in allocations) > bill.total_wh:
        raise BillInconsistentError("kWh atribuídos acima do total da fatura")


# --- DTO do senhorio: só totais por quarto ---------------------------------------------------


class RoomTotal(ContractModel):
    room_id: UUID
    room_name: str
    amount_cents: Cents
    energy_wh: EnergyWh


class LandlordBillView(ContractModel):
    """O senhorio vê totais por quarto, nunca aparelhos, horários nem presença."""

    bill_id: UUID
    period: BillPeriod
    total_cents: Cents
    status: BillStatus
    rooms: list[RoomTotal]


# --- orçamentos e contestações ----------------------------------------------------------------


class BudgetKind(StrEnum):
    personal = "personal"
    room_allowance = "room_allowance"


class Budget(ContractModel):
    id: UUID
    household_id: UUID
    kind: BudgetKind
    resident_id: UUID | None = None
    room_id: UUID | None = None
    period: Period
    limit_cents: Cents | None = None  # personal
    limit_wh: EnergyWh | None = None  # room_allowance
    thresholds: Annotated[list[Pct], Field(min_length=1)] = [50, 80, 100]
    last_threshold_notified: Pct | None = None

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.thresholds != sorted(set(self.thresholds)):
            raise ValueError("limiares crescentes e sem repetição")
        if self.last_threshold_notified not in (None, *self.thresholds):
            raise ValueError("último limiar notificado fora dos limiares")
        if self.kind is BudgetKind.personal:
            ok = self.resident_id is not None and self.room_id is None
            ok = ok and self.limit_cents is not None and self.limit_wh is None
        else:
            ok = self.room_id is not None and self.resident_id is None
            ok = ok and self.limit_wh is not None and self.limit_cents is None
        if not ok:
            raise ValueError("campos incoerentes com o tipo de orçamento")
        return self


class BudgetThreshold(ContractModel):
    """Uma passagem de limiar (carga do evento `alerts.threshold_crossed`). Leva o dono, o
    período e o limite para notifications escrever o aviso pessoal sem ler tabelas de billing.
    `spent_cents` inclui TODOS os custos (D-31): consumo próprio, parte da conta comum e parte
    do termo fixo e do resíduo (estimada até haver fatura)."""

    budget_id: UUID
    resident_id: UUID
    period: Period
    pct: Pct
    spent_cents: Cents
    limit_cents: Cents
    forecast_cents: Cents | None = None  # None: sem dados para prever (ALERT-02)


class BudgetIn(ContractModel):
    """`PUT …/budgets/me`: o próprio inquilino define o seu objetivo mensal. Redefinir é um
    reset explícito: os limiares voltam a poder ser avisados."""

    period: Period | None = None  # omissão: o mês corrente (fuso da casa)
    limit_cents: Annotated[Cents, Field(gt=0)]
    thresholds: Annotated[list[Pct], Field(min_length=1)] = [50, 80, 100]

    @model_validator(mode="after")
    def _sorted(self) -> Self:
        if self.thresholds != sorted(set(self.thresholds)):
            raise ValueError("limiares crescentes e sem repetição")
        return self


class BudgetStatus(ContractModel):
    """Quanto já gastei este mês face ao meu objetivo (D-31: todos os custos).

    Sem preço de referência nem fatura não há custo: `spent_cents=None` (desconhecido), nunca
    0 €. `base_cents=None`: ainda não há fatura anterior para estimar o termo fixo e o resíduo,
    por isso o gasto mostrado não os inclui. `final=True`: valores da fatura fechada do mês."""

    period: Period
    budget: Budget | None
    spent_cents: Cents | None
    confirmed_cents: Cents | None  # consumo atribuído a mim (quarto ou confirmado)
    shared_cents: Cents | None  # a minha parte igual da conta comum (estimada)
    base_cents: Cents | None  # parte do termo fixo + resíduo (estimada do último recibo)
    pct: Annotated[int, Field(strict=True, ge=0)] | None
    final: bool
    provenance: Provenance | None
    as_of: UtcDatetime


class ContestationStatus(StrEnum):
    open = "open"
    accepted = "accepted"
    rejected = "rejected"


class Contestation(ContractModel):
    id: UUID
    allocation_id: UUID
    resident_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    status: ContestationStatus = ContestationStatus.open
    created_at: UtcDatetime
    resolved_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _resolved(self) -> Self:
        if (self.status is ContestationStatus.open) != (self.resolved_at is None):
            raise ValueError("resolved_at exatamente quando já não está aberta")
        return self
