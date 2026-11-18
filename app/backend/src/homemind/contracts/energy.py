"""Leituras, degraus, identificação provável e episódios de consumo. Dono: energy (P1).

`None` significa «sem dado» (nunca `0`): potência 0 W é uma leitura válida. O estado de
atribuição (quem paga) NÃO vive aqui: é de billing (`Attribution`).
"""

from __future__ import annotations

import math
from datetime import date
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from homemind.contracts.common import (
    Cents,
    Confidence,
    ContractModel,
    EnergyWh,
    PowerW,
    Provenance,
    UtcDatetime,
    ValueKind,
    check_transition,
    cost_cents,
)
from homemind.contracts.devices import PowerUnit


class ReadingStatus(StrEnum):
    ok = "ok"
    missing = "missing"  # o dispositivo não devolveu potência
    unit_unknown = "unit_unknown"  # há valor bruto mas não se sabe a unidade: não se converte
    stale = "stale"  # último contacto do dispositivo demasiado antigo; não integrar


class EnergyReading(ContractModel):
    id: UUID
    device_id: UUID
    ts: UtcDatetime  # quando lemos
    observed_at: UtcDatetime | None = None  # último contacto do dispositivo (se conhecido)
    status: ReadingStatus
    power_w: PowerW | None = None
    raw_value: Annotated[float, Field(allow_inf_nan=False)] | None = None
    raw_unit: PowerUnit = PowerUnit.unknown
    provenance: Provenance

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.status is ReadingStatus.ok:
            if self.power_w is None:
                raise ValueError("leitura ok exige power_w")
            if self.raw_unit is PowerUnit.unknown and self.provenance.kind is ValueKind.measured:
                raise ValueError("unidade desconhecida não pode ser `measured`")
        if self.status in (ReadingStatus.missing, ReadingStatus.unit_unknown):
            if self.power_w is not None:
                raise ValueError(f"{self.status.value}: power_w tem de ser None")
        if self.status is ReadingStatus.unit_unknown and self.raw_unit is not PowerUnit.unknown:
            raise ValueError("unit_unknown exige raw_unit=unknown")
        if self.observed_at is not None and self.observed_at > self.ts:
            raise ValueError("observed_at posterior a ts")
        return self

    @property
    def usable(self) -> bool:
        """Pode ser integrada/comparada: `ok` e com potência."""
        return self.status is ReadingStatus.ok and self.power_w is not None


class PowerStep(ContractModel):
    """Variação brusca de potência num dispositivo. Interna a energy; billing não a consome."""

    id: UUID
    device_id: UUID
    ts: UtcDatetime
    before_w: PowerW
    after_w: PowerW
    provenance: Provenance

    @model_validator(mode="after")
    def _real_step(self) -> Self:
        if math.isclose(self.before_w, self.after_w):
            raise ValueError("degrau sem variação")
        return self

    @property
    def delta_w(self) -> float:
        return self.after_w - self.before_w

    @property
    def direction(self) -> str:
        return "up" if self.delta_w > 0 else "down"


class ApplianceCandidate(ContractModel):
    appliance_id: UUID
    confidence: Confidence


class MatchOutcome(StrEnum):
    identified = "identified"
    ambiguous = "ambiguous"  # vários candidatos sem vencedor claro
    unknown = "unknown"


class ApplianceMatch(ContractModel):
    """`appliance_id` só quando há um vencedor claro; senão fica `None` e os candidatos explicam."""

    appliance_id: UUID | None = None
    confidence: Confidence | None = None
    candidates: Annotated[list[ApplianceCandidate], Field(max_length=5)] = []

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        ids = [c.appliance_id for c in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("candidatos repetidos")
        scores = [c.confidence for c in self.candidates]
        if scores != sorted(scores, reverse=True):
            raise ValueError("candidatos por confiança decrescente")
        if self.appliance_id is None:
            if self.confidence is not None:
                raise ValueError("sem aparelho identificado não há confiança do vencedor")
        else:
            if self.confidence is None:
                raise ValueError("aparelho identificado exige confidence")
            if self.candidates and self.candidates[0].appliance_id != self.appliance_id:
                raise ValueError("o vencedor tem de ser o primeiro candidato")
        return self

    @property
    def outcome(self) -> MatchOutcome:
        if self.appliance_id is not None:
            return MatchOutcome.identified
        return MatchOutcome.ambiguous if len(self.candidates) > 1 else MatchOutcome.unknown


class ConsumptionStatus(StrEnum):
    ongoing = "ongoing"
    closed = "closed"
    discarded = "discarded"  # ruído / falso positivo; não entra em contas


CONSUMPTION_TRANSITIONS = {
    ConsumptionStatus.ongoing: frozenset({ConsumptionStatus.closed, ConsumptionStatus.discarded}),
    ConsumptionStatus.closed: frozenset(),
    ConsumptionStatus.discarded: frozenset(),
}


class LocationKind(StrEnum):
    room = "room"
    common = "common"
    unknown = "unknown"  # nunca assumir quarto por omissão


class CostEstimate(ContractModel):
    """Custo estimado a um preço de referência. Ausente quando falta energia ou preço."""

    cents: Cents
    price_millicents_per_kwh: Annotated[int, Field(strict=True, gt=0)]


class ConsumptionEvent(ContractModel):
    id: UUID
    household_id: UUID
    device_id: UUID
    match: ApplianceMatch
    started_at: UtcDatetime
    ended_at: UtcDatetime | None = None
    status: ConsumptionStatus
    peak_w: PowerW
    # Acumulado até agora (`ongoing`) ou final (`closed`); `None` = sem leituras utilizáveis.
    energy_wh: EnergyWh | None = None
    location: LocationKind
    room_id: UUID | None = None
    cost_estimate: CostEstimate | None = None
    # Dono do aparelho identificado (copiado de `Appliance.ownership`): presence usa-o como pista
    # «o aparelho pessoal dele ligou». Só com aparelho identificado; não decide quem paga.
    appliance_owner_resident_id: UUID | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.appliance_owner_resident_id is not None and self.match.appliance_id is None:
            raise ValueError("dono do aparelho sem aparelho identificado")
        if self.status is ConsumptionStatus.ongoing:
            if self.ended_at is not None:
                raise ValueError("consumo a decorrer não tem ended_at")
        else:
            if self.ended_at is None:
                raise ValueError(f"consumo {self.status.value} exige ended_at")
            if self.ended_at < self.started_at:
                raise ValueError("ended_at anterior a started_at")
        if self.status is ConsumptionStatus.closed and self.energy_wh is None:
            raise ValueError("consumo fechado exige energy_wh")
        if self.location is LocationKind.room and self.room_id is None:
            raise ValueError("localização `room` exige room_id")
        if self.location is LocationKind.unknown and self.room_id is not None:
            raise ValueError("localização desconhecida não tem room_id")
        if self.cost_estimate is not None:
            if self.energy_wh is None:
                raise ValueError("custo sem energia")
            expected = cost_cents(self.energy_wh, self.cost_estimate.price_millicents_per_kwh)
            if expected != self.cost_estimate.cents:
                raise ValueError("custo inconsistente com energia e preço")
        return self

    def transition(self, new: ConsumptionStatus) -> None:
        check_transition(CONSUMPTION_TRANSITIONS, self.status, new)


class EnergyTotal(ContractModel):
    """Energia por proveniência (listas, não dicts: chaves estruturadas não são JSON)."""

    provenance: Provenance
    energy_wh: EnergyWh


class EnergySummary(ContractModel):
    household_id: UUID
    period_start: date
    period_end: date
    room_id: UUID | None = None
    totals: list[EnergyTotal]
    cost_cents: Cents | None = None  # None: sem preço de referência

    @model_validator(mode="after")
    def _period(self) -> Self:
        if self.period_end < self.period_start:
            raise ValueError("período invertido")
        keys = [t.provenance for t in self.totals]
        if len(set(keys)) != len(keys):
            raise ValueError("proveniência repetida nos totais")
        return self


# --- aprendizagem por confirmação (ENERGY-04) ----------------------------------------------------


class IdentificationChoice(StrEnum):
    """Respostas a «O que é este aparelho?». «É meu» é sempre de quem responde."""

    mine = "mine"  # aparelho pessoal de quem respondeu
    household = "household"  # aparelho comum da casa
    ignore = "ignore"  # não perguntar deste grupo durante 7 dias


APPLIANCE_IDENTIFICATION_ACTIONS = tuple(c.value for c in IdentificationChoice)


def approx_power_w(power_w: float) -> int:
    """Potência arredondada aos 50 W (mínimo 50): o «~800 W» da pergunta e do nome genérico."""
    return max(50, int(round(power_w / 50)) * 50)


class ApplianceIdentificationRequest(ContractModel):
    """Emitido pela energia quando um consumo desconhecido se repete (3.ª vez em 7 dias).

    P3 transforma-o numa `Notification` da casa (`kind=appliance_identification`,
    `ref={type: appliance_identification, id}`) para os inquilinos ativos (nunca o senhorio),
    com as ações de `APPLIANCE_IDENTIFICATION_ACTIONS`. A primeira resposta fecha (não é
    votação); a resposta volta em `notification.responded` e é a energia que a trata.
    Sem nomes de pessoas nem ids externos: só potência, duração e hora local aproximadas.
    """

    id: UUID
    device_id: UUID  # tomada (id interno) da ocorrência que fez perguntar
    power_w: Annotated[PowerW, Field(gt=0)]  # média do grupo (acima da base)
    duration_s: Annotated[int, Field(strict=True, gt=0)]  # duração média do grupo
    hour_local: Annotated[int, Field(strict=True, ge=0, le=23)]  # hora habitual (fuso da casa)
    occurrences: Annotated[int, Field(strict=True, ge=1)]  # ocorrências nos últimos 7 dias
    expires_at: UtcDatetime
    provenance: Provenance

    @property
    def approx_power_w(self) -> int:
        return approx_power_w(self.power_w)
