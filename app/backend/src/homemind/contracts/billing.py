"""Atribuição, fatura, alocações, orçamentos e contestações. Dono: billing (P4).

Só modelos e invariantes estruturais; o motor de cálculo é de P4. Dinheiro em cêntimos
inteiros. Nada se apaga nem se edita em silêncio: correções criam uma nova versão e marcam
a anterior `superseded`.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self
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
from homemind.contracts.energy import EnergyTotal, LocationKind, MatchOutcome
from homemind.contracts.household import CommonAreaRule, HouseholdPolicy

# --- atribuição -------------------------------------------------------------------------------


class AttributionTarget(StrEnum):
    resident = "resident"
    group = "group"  # vários moradores escolhidos por votação (D-32): por igual entre eles
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
    target_resident_ids: list[UUID] = []  # só em `group`: ≥ 2, ordenados, sem repetições
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
        if (self.target_type is AttributionTarget.group) != bool(self.target_resident_ids):
            raise ValueError("target_resident_ids exatamente quando o alvo é um grupo")
        ids = self.target_resident_ids
        if ids and (len(ids) < 2 or ids != sorted(set(ids))):
            raise ValueError("um grupo tem ≥ 2 moradores, ordenados e sem repetições")
        if (self.provenance.kind is ValueKind.inferred) != (self.confidence is not None):
            raise ValueError("confidence exatamente quando a natureza é inferred")
        if self.method is AttributionMethod.confirmation and self.decided_by.by_resident_id is None:
            raise ValueError("uma confirmação é decidida por um morador")
        return self


def payers(a: Attribution) -> list[UUID]:
    """Quem paga o consumo: o morador, os do grupo, ou ninguém (conta comum)."""
    if a.target_type is AttributionTarget.resident:
        return [a.target_resident_id]
    return list(a.target_resident_ids)


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
    heating_allowance = "heating_allowance"  # parte igual do plafond solidário (BILL-03)
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


# --- tarifário (ALERT-02) ----------------------------------------------------------------------

# Por kWh com impostos, em milicêntimos (1 € = 100 000); no máximo 1,00 €/kWh, como a fatura.
PriceMillicents = Annotated[int, Field(strict=True, gt=0, le=100_000)]


class TariffKind(StrEnum):
    simple = "simple"
    bi_hourly = "bi_hourly"


class Tariff(ContractModel):
    """Tarifa de referência da casa, para ESTIMAR custos antes da fatura (orçamento, previsão).
    O fecho reparte sempre o total real da fatura.

    Bi-horário (simplificado, v5.1 §6.6): vazio das 22h às 08h (hora local da casa) e todo o
    sábado e domingo; fora do vazio vale `price_millicents_per_kwh`."""

    kind: TariffKind
    price_millicents_per_kwh: PriceMillicents  # simples: o preço; bi-horário: fora do vazio
    offpeak_price_millicents_per_kwh: PriceMillicents | None = None  # só bi-horário

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if (self.kind is TariffKind.bi_hourly) != (
            self.offpeak_price_millicents_per_kwh is not None
        ):
            raise ValueError("o preço de vazio existe só (e sempre) no bi-horário")
        return self


class TariffIn(Tariff):
    """`PUT …/tariff`: o senhorio define a tarifa do contrato (substitui a anterior)."""


class TariffSource(StrEnum):
    configured = "configured"  # definida pelo senhorio (`PUT …/tariff`)
    reference = "reference"  # preço de referência da casa (simples)
    last_bill = "last_bill"  # preço médio da última fatura fechada (simples)


class TariffStatus(ContractModel):
    """A tarifa usada nas estimativas e de onde veio; `tariff=None`: não há preço nenhum, e os
    custos estimados ficam desconhecidos (nunca 0 €)."""

    tariff: Tariff | None
    source: TariffSource | None


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


class BudgetLight(StrEnum):
    """Cor do orçamento na lâmpada do PRÓPRIO quarto (ALERT-06, v5.1 §22): âmbar aos 80 %,
    vermelho aos 100 %. Nunca na lâmpada de uma zona comum: o orçamento é pessoal."""

    green = "green"
    amber = "amber"
    red = "red"


class BudgetLightCue(ContractModel):
    """O que a lâmpada mostraria. `color` é um nome de `contracts.home.CORES` (o mesmo
    vocabulário das escritas MCP); `label` diz o mesmo em texto, para não depender da cor."""

    light: BudgetLight
    color: str
    rgb: tuple[int, int, int]
    label: str


_LIGHT = {
    BudgetLight.green: ("verde", (0, 255, 0), "Dentro do orçamento"),
    BudgetLight.amber: ("amarelo", (255, 200, 0), "Atenção: perto do limite do orçamento"),
    BudgetLight.red: ("vermelho", (255, 0, 0), "Orçamento ultrapassado"),
}


def budget_light(pct: int | None) -> BudgetLightCue | None:
    """Sem orçamento ou sem gasto conhecido não há cor (nunca «verde» por omissão)."""
    if pct is None:
        return None
    light = BudgetLight.red if pct >= 100 else BudgetLight.amber if pct >= 80 else BudgetLight.green
    color, rgb, label = _LIGHT[light]
    return BudgetLightCue(light=light, color=color, rgb=rgb, label=f"{label} ({pct} %)")


class BudgetForecast(ContractModel):
    """Previsão do gasto até ao fim do mês (ALERT-02): o gasto atual mais o ritmo observado
    (linear) nos dias que faltam, mais a base do mês inteiro. Só existe com pelo menos
    `observed_days >= 3` dias de dados no mês; `low_cents`–`high_cents` mostra a incerteza
    (variação entre dias). Sempre `estimated`."""

    cents: Cents
    low_cents: Cents
    high_cents: Cents
    observed_days: Annotated[int, Field(strict=True, ge=0)]

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.low_cents <= self.cents <= self.high_cents:
            raise ValueError("previsão fora do intervalo")
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
    light: BudgetLightCue | None = None  # ALERT-06: cor mostrada na app (lâmpada só com grant)
    forecast: BudgetForecast | None = None  # ALERT-02; None: dados insuficientes para prever
    final: bool
    provenance: Provenance | None
    as_of: UtcDatetime


class ContestationStatus(StrEnum):
    open = "open"
    accepted = "accepted"
    rejected = "rejected"


class Contestation(ContractModel):
    """Contestação do PRÓPRIO recibo (BILL-06). Só o senhorio decide, sempre com justificação.
    Aceitar reemite a fatura como nova revisão (a anterior fica `superseded`, com as suas
    parcelas): nunca se altera uma fatura fechada em silêncio. `before/after_cents`: a parcela
    de quem contestou antes e depois da decisão (iguais se rejeitada)."""

    id: UUID
    bill_id: UUID  # a revisão em vigor (passa para a nova se outra correção a substituir)
    allocation_id: UUID
    resident_id: UUID
    consumption_event_id: UUID | None = None  # «este consumo não é meu» (um dos meus)
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    status: ContestationStatus = ContestationStatus.open
    created_at: UtcDatetime
    resolved_at: UtcDatetime | None = None
    resolution: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    revision_bill_id: UUID | None = None  # a revisão criada ao aceitar
    before_cents: Cents | None = None
    after_cents: Cents | None = None

    @model_validator(mode="after")
    def _resolved(self) -> Self:
        open_ = self.status is ContestationStatus.open
        if open_ != (self.resolved_at is None) or open_ != (self.resolution is None):
            raise ValueError("resolved_at e resolution exatamente quando já não está aberta")
        if (self.status is ContestationStatus.accepted) != (self.revision_bill_id is not None):
            raise ValueError("revision_bill_id exatamente nas aceites")
        return self


class ContestationIn(ContractModel):
    """`POST …/bills/{id}/contestations` (inquilino). Sem `consumption_event_id`: contesta o
    recibo em geral (o senhorio pode corrigir os dados da fatura ao aceitar)."""

    reason: Annotated[str, Field(min_length=1, max_length=500)]
    consumption_event_id: UUID | None = None


class ContestationDecisionIn(ContractModel):
    """`POST …/contestations/{id}/decision` (senhorio). Aceitar com `consumption_event_id`
    passa esse consumo para a conta comum (por igual); `bill` corrige os dados da fatura."""

    status: Literal[ContestationStatus.accepted, ContestationStatus.rejected]
    resolution: Annotated[str, Field(min_length=1, max_length=500)]
    bill: BillIn | None = None

    @model_validator(mode="after")
    def _bill_only_when_accepted(self) -> Self:
        if self.bill is not None and self.status is not ContestationStatus.accepted:
            raise ValueError("só se corrige a fatura ao aceitar")
        return self


class LandlordContestationView(ContractModel):
    """O que o senhorio vê: o quarto, o motivo escrito pelo morador e a decisão. Nunca o
    consumo, o aparelho, horários nem presença; valores por quarto, como no resumo."""

    id: UUID
    bill_id: UUID
    room_id: UUID | None
    room_name: str | None
    reason: str
    contests_consumption: bool
    status: ContestationStatus
    created_at: UtcDatetime
    resolved_at: UtcDatetime | None
    resolution: str | None
    revision_bill_id: UUID | None
    before_cents: Cents | None
    after_cents: Cents | None


# --- explicação do recibo (BILL-05) -----------------------------------------------------------


class DecisionActor(StrEnum):
    """Quem decidiu uma atribuição, do ponto de vista de quem lê: nunca o id de outra pessoa."""

    system = "system"  # regra automática (quarto, prazo expirado)
    me = "me"
    housemates = "housemates"  # outro(s) morador(es), p. ex. por votação (D-32)


class ExplanationStage(StrEnum):
    measurement = "measurement"  # medição na tomada (ou estimativa/simulação)
    identification = "identification"  # assinatura do aparelho e confiança
    location = "location"  # quarto, zona comum ou desconhecida
    decision = "decision"  # regra/confirmação/votação/prazo
    correction = "correction"  # decisões anteriores substituídas
    allowance = "allowance"  # plafond solidário de aquecimento (BILL-03)
    share = "share"  # parcela no recibo


class ExplanationStep(ContractModel):
    stage: ExplanationStage
    text: Annotated[str, Field(min_length=1, max_length=300)]


class ExplainedConsumption(ContractModel):
    """Um consumo MEU (atribuído a mim) e porque me foi atribuído, da medição à parcela."""

    consumption_event_id: UUID
    started_at: UtcDatetime
    ended_at: UtcDatetime | None = None
    energy_wh: EnergyWh
    provenance: Provenance
    device_name: str | None = None  # tomada onde foi medido
    appliance_name: str | None = None  # None: aparelho não identificado
    match_outcome: MatchOutcome
    match_confidence: Confidence | None = None
    location: LocationKind
    room_name: str | None = None
    method: AttributionMethod
    decided_by: DecisionActor
    decided_at: UtcDatetime
    corrections: Annotated[int, Field(strict=True, ge=0)] = 0
    heating: bool = False  # aquecimento provado (BILL-03): aparelho `heating` no meu quarto
    covered_wh: EnergyWh = 0  # parte paga por todos pelo plafond solidário
    amount_cents: Cents  # só a parte que é minha (energy_wh − covered_wh)
    steps: list[ExplanationStep]


class ExplainedCommonGroup(ContractModel):
    """Consumos da conta comum agregados por aparelho e decisão: sem horas nem pessoas."""

    appliance_name: str | None = None
    location: LocationKind
    method: AttributionMethod
    provenance: Provenance
    consumptions: Annotated[int, Field(strict=True, ge=1)]
    energy_wh: EnergyWh  # total do grupo (toda a casa)
    my_energy_wh: EnergyWh  # a minha parte igual
    amount_cents: Cents


class ResidualExplanation(ContractModel):
    """Porque há consumo não atribuído: o que a fatura mede e as tomadas não explicam."""

    bill_wh: EnergyWh
    attributed_wh: EnergyWh  # Σ consumos com decisão (casa inteira, agregado)
    residual_wh: EnergyWh
    undecided_consumptions: Annotated[int, Field(strict=True, ge=0)]  # sem decisão no fecho
    undecided_wh: EnergyWh
    my_energy_wh: EnergyWh
    amount_cents: Cents
    provenance: Provenance


class AllowanceExplanation(ContractModel):
    """Plafond solidário (BILL-03) no meu quarto e a minha parte do da casa."""

    limit_wh: EnergyWh  # do meu quarto, neste período (proporcional aos meses)
    heating_wh: EnergyWh  # aquecimento provado no meu quarto
    covered_wh: EnergyWh  # dele, pago por todos (≤ limit_wh)
    unproven_consumptions: Annotated[int, Field(strict=True, ge=0)]  # sem aparelho identificado
    unproven_wh: EnergyWh
    house_covered_wh: EnergyWh  # Σ coberto na casa (agregado, sem quartos)
    my_share_wh: EnergyWh  # a minha parte igual de `house_covered_wh`
    amount_cents: Cents  # linha `heating_allowance` do meu recibo


class ReceiptExplanation(ContractModel):
    """«Porque pago isto?»: o recibo do morador explicado linha a linha.

    Reconcilia ao cêntimo com `BillAllocation`: Σ `own` = linhas `room`, Σ `common` = linhas
    `common`, `allowance` = linhas `heating_allowance`, `residual` = `residual_share_cents`.
    `evidence_available=False` quando a fatura foi fechada antes de haver evidência guardada
    (as listas vêm vazias; o recibo continua válido).
    """

    bill_id: UUID
    revision: int
    period: BillPeriod
    allocation_id: UUID
    amount_cents: Cents
    residents: Annotated[int, Field(strict=True, ge=1)]
    equal_split_cents: Cents  # o que pagaria com a divisão igual de hoje
    fixed_cents: Cents
    price_millicents_per_kwh: int  # preço médio da fatura (sem termo fixo)
    common_area_rule: CommonAreaRule  # regra em vigor no 1.º dia do período (HOUSE-04)
    evidence_available: bool
    own: list[ExplainedConsumption]
    common: list[ExplainedCommonGroup]
    residual: ResidualExplanation
    allowance: AllowanceExplanation | None = None  # None: o meu quarto não tem plafond


# --- regras da casa versionadas (HOUSE-04) ------------------------------------------------------


class PolicyVersion(ContractModel):
    """Uma versão das regras da casa. `effective_from=None`: a política inicial (desde a criação
    da casa, sem autor). As outras começam sempre num dia 1 (fuso da casa)."""

    effective_from: date | None
    policy: HouseholdPolicy
    created_by_resident_id: UUID | None = None
    created_at: UtcDatetime | None = None


class HouseRulesIn(ContractModel):
    """A regra a agendar para o dia 1 do mês seguinte (todos os campos explícitos)."""

    common_area_rule: CommonAreaRule
    ask_threshold_cents: Cents  # só se pergunta acima deste custo estimado
    ask_timeout_hours: Annotated[int, Field(strict=True, ge=1, le=168)]

    def policy(self) -> HouseholdPolicy:
        return HouseholdPolicy(**self.model_dump())


class RuleProposalStatus(StrEnum):
    open = "open"  # à espera de votos
    approved = "approved"  # maioria: agendada como versão (`HouseRulesView.upcoming`)
    rejected = "rejected"  # a maioria já não é possível
    withdrawn = "withdrawn"  # retirada por quem a propôs
    superseded = "superseded"  # substituída por outra proposta antes de decidida
    expired = "expired"  # chegou o mês sem maioria: não muda nada


class RuleProposal(ContractModel):
    """Proposta de mudança da regra da sala (HOUSE-04). Só vale com a aprovação de pelo menos
    metade dos moradores com contrato ativo (`needed`, como a D-32); quem propõe conta como «sim».
    Só contagens: quem votou o quê não sai daqui."""

    id: UUID
    household_id: UUID
    effective_from: date  # dia 1 do mês seguinte ao da proposta
    policy: HouseholdPolicy
    proposed_by_resident_id: UUID
    proposed_at: UtcDatetime
    status: RuleProposalStatus
    approvals: Annotated[int, Field(strict=True, ge=0)]
    rejections: Annotated[int, Field(strict=True, ge=0)]
    eligible: Annotated[int, Field(strict=True, ge=0)]  # moradores com contrato ativo
    needed: Annotated[int, Field(strict=True, ge=1)]  # ceil(eligible / 2), mínimo 1
    decided_at: UtcDatetime | None = None


class RuleProposalView(RuleProposal):
    """A proposta vista por um morador: `my_vote` = o meu voto (`None`: ainda não votei, ou não
    sou morador); `proposed_by_me`: só quem propôs a pode retirar."""

    my_vote: bool | None = None
    proposed_by_me: bool = False


class RuleVoteIn(ContractModel):
    """`POST …/rules/next/vote`: aprovar ou rejeitar a proposta aberta (pode mudar até decidir)."""

    approve: bool


class HouseRulesView(ContractModel):
    """Que regra vale hoje, que mudança está agendada e o que valeu antes.

    Uma mudança só vale a partir de `next_change_from` (o dia 1 do mês seguinte): nunca muda um
    mês que já começou, portanto nunca muda consumos já decididos nem faturas fechadas. Antes de
    ser agendada (`upcoming`), a mudança é uma `proposal` que a maioria dos moradores aprova.
    """

    current: PolicyVersion
    upcoming: PolicyVersion | None  # aprovada pela maioria, começa em `effective_from`
    history: list[PolicyVersion]  # versões que já valeram, mais recente primeiro (inclui current)
    next_change_from: date
    proposal: RuleProposalView | None = None  # a proposta aberta, se houver


# --- plafond solidário editado (BILL-03) --------------------------------------------------------


class RoomAllowanceIn(ContractModel):
    """`PUT …/room-allowances/{room_id}`: o novo plafond MENSAL do quarto (0 = sem plafond), a
    valer a partir do dia 1 do mês seguinte."""

    included_wh: EnergyWh


class RoomAllowanceView(ContractModel):
    """O plafond de um quarto: o que vale este mês e a mudança agendada, se houver."""

    room_id: UUID
    current_wh: EnergyWh  # 0 = sem plafond
    upcoming_wh: EnergyWh | None = None
    upcoming_from: date | None = None
