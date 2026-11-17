"""HOUSE-04: decisões de atribuição (não contém dinheiro nem cálculo de faturas).

O alvo é quem suporta o consumo, nunca o dono do aparelho. Uma decisão pendente
não é uma Attribution: BILL-02 só persiste Attribution para decisões resolvidas.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from homemind.contracts.billing import AttributionMethod, AttributionTarget
from homemind.contracts.common import (
    Cents,
    ContractModel,
    Provenance,
    UtcDatetime,
)
from homemind.contracts.household import CommonAreaRule
from homemind.contracts.notification import ConfirmationRequest


class PolicyStatus(StrEnum):
    automatic = "automatic"
    confirmed = "confirmed"
    pending = "pending"
    fallback = "fallback"


class PolicyReason(StrEnum):
    room_contract = "room_contract"
    room_occupancy_unknown = "room_occupancy_unknown"
    location_unverified = "location_unverified"
    consumption_ongoing = "consumption_ongoing"
    consumption_discarded = "consumption_discarded"
    equal_rule = "equal_rule"
    below_threshold = "below_threshold"
    cost_unknown = "cost_unknown"
    awaiting_confirmation = "awaiting_confirmation"
    response_mine = "response_mine"
    response_everyone = "response_everyone"
    response_unknown = "response_unknown"
    confirmation_timeout = "confirmation_timeout"
    presence_deferred = "presence_deferred"
    no_eligible_residents = "no_eligible_residents"


class PolicyVersion(ContractModel):
    """Snapshot imutável da regra aplicável desde valid_from (UTC, inclusivo).

    Fallback do MVP é SEMPRE equal. C continua modelada como regra funcional
    mas não pode cobrar por presença antes do módulo F2.
    """

    household_id: UUID
    version: Annotated[int, Field(strict=True, ge=1)]
    valid_from: UtcDatetime
    common_area_rule: CommonAreaRule
    ask_threshold_cents: Cents = 50
    ask_timeout_hours: Annotated[int, Field(strict=True, ge=1, le=168)] = 24
    fallback_rule: Annotated[str, Field(pattern="^equal$")] = "equal"


class PolicyDecision(ContractModel):
    household_id: UUID
    consumption_event_id: UUID
    policy_version: Annotated[int, Field(strict=True, ge=1)]
    status: PolicyStatus
    reason: PolicyReason
    decided_at: UtcDatetime
    provenance: Provenance
    target_type: AttributionTarget | None = None
    target_resident_id: UUID | None = None
    method: AttributionMethod | None = None
    confirmation_request: ConfirmationRequest | None = None
    expires_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        resolved = self.status is not PolicyStatus.pending
        if resolved != (self.target_type is not None and self.method is not None):
            raise ValueError("decisão resolvida exige alvo e método; pendente não os tem")
        if (self.target_type is AttributionTarget.resident) != (
            self.target_resident_id is not None
        ):
            raise ValueError("alvo individual exige exatamente um residente")
        if self.status is PolicyStatus.pending and self.target_resident_id is not None:
            raise ValueError("pendente não pode atribuir a uma pessoa")
        if self.confirmation_request is not None:
            if self.status is not PolicyStatus.pending:
                raise ValueError("só decisões pendentes pedem confirmação")
            if self.confirmation_request.consumption_event_id != self.consumption_event_id:
                raise ValueError("pedido de outro consumo")
            if self.confirmation_request.expires_at != self.expires_at:
                raise ValueError("prazo divergente")
        if self.status is PolicyStatus.fallback and self.method is not AttributionMethod.equal_fallback:
            raise ValueError("fallback MVP tem de ser equal_fallback")
        return self
