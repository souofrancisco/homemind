"""Casas, quartos, moradores e memberships.

Entidades persistidas (`Household`, `Room`, `Resident`, `Membership`) têm `auth_subject` e
`presence_opt_in`; nunca saem na API. A API devolve as `*View` (um DTO por finalidade).
Dono: households (P5). Os outros módulos só leem.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from homemind.contracts.common import (
    Cents,
    ContractModel,
    EnergyWh,
    ShortText,
    UtcDatetime,
)


class MembershipRole(StrEnum):
    landlord = "landlord"
    tenant = "tenant"
    operator = "operator"


class MembershipStatus(StrEnum):
    invited = "invited"
    active = "active"
    ended = "ended"


class RoomKind(StrEnum):
    bedroom = "bedroom"
    common = "common"


class CommonAreaRule(StrEnum):
    equal = "equal"  # A: por igual
    ask = "ask"  # B: perguntar (omissão)
    presence = "presence"  # C: por presença


class SourceKind(StrEnum):
    demo = "demo"  # aceita dados reais e simulados (o MVP mistura-os)
    real = "real"  # nunca aceita eventos simulados


class HouseholdPolicy(ContractModel):
    common_area_rule: CommonAreaRule = CommonAreaRule.ask
    ask_threshold_cents: Cents = 50  # só se pergunta acima deste custo estimado
    ask_timeout_hours: Annotated[int, Field(strict=True, ge=1, le=168)] = 24


class HouseholdSettings(ContractModel):
    timezone: str = "Europe/Lisbon"
    # Preço de referência para estimativas (nunca para a fatura, que vem do total real).
    # 1 cêntimo = 1000 milicêntimos: 0,16 €/kWh = 16000.
    energy_price_millicents_per_kwh: Annotated[int, Field(strict=True, gt=0)] | None = None
    source_kind: SourceKind

    @field_validator("timezone")
    @classmethod
    def _known_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("fuso horário desconhecido") from None
        return v


class Household(ContractModel):
    id: UUID
    name: ShortText
    settings: HouseholdSettings
    policy: HouseholdPolicy = HouseholdPolicy()
    created_at: UtcDatetime


class Room(ContractModel):
    id: UUID
    household_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=80)]
    kind: RoomKind
    # Plafond solidário (aquecimento básico incluído), só em quartos.
    included_wh: EnergyWh | None = None

    @model_validator(mode="after")
    def _allowance_only_bedroom(self) -> Self:
        if self.included_wh is not None and self.kind is not RoomKind.bedroom:
            raise ValueError("included_wh só existe em quartos")
        return self


class Resident(ContractModel):
    id: UUID
    display_name: Annotated[str, Field(min_length=1, max_length=80)]
    # `sub` do Authentik: identidade de login, distinta de `id`. Vazio até aceitar o convite.
    auth_subject: str | None = Field(default=None, min_length=1, max_length=255, repr=False)


class Membership(ContractModel):
    id: UUID
    household_id: UUID
    resident_id: UUID
    role: MembershipRole
    room_id: UUID | None = None
    starts_on: date
    ends_on: date | None = None
    status: MembershipStatus
    presence_opt_in: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.ends_on is not None and self.ends_on < self.starts_on:
            raise ValueError("ends_on anterior a starts_on")
        if self.status is MembershipStatus.ended and self.ends_on is None:
            raise ValueError("membership terminada exige ends_on")
        if self.role is MembershipRole.tenant:
            if self.status is not MembershipStatus.invited and self.room_id is None:
                raise ValueError("inquilino ativo ou terminado exige quarto")
        elif self.room_id is not None or self.presence_opt_in:
            raise ValueError("só inquilinos têm quarto e presence_opt_in")
        return self

    def active_on(self, day: date) -> bool:
        """Vale nesta data? `ends_on` inclusivo; `invited` e `ended` antes do fim não contam."""
        return (
            self.status is MembershipStatus.active
            and self.starts_on <= day
            and (self.ends_on is None or day <= self.ends_on)
        )


def check_membership_room(membership: Membership, room: Room | None) -> None:
    """Invariante entre entidades: o quarto é da mesma casa e é um quarto (não a sala)."""
    if membership.room_id is None:
        return
    if room is None or room.id != membership.room_id:
        raise ValueError("quarto inexistente")
    if room.household_id != membership.household_id:
        raise ValueError("o quarto pertence a outra casa")
    if room.kind is not RoomKind.bedroom:
        raise ValueError("um inquilino ocupa um quarto, não uma zona comum")


def tenants_active_on(memberships: list[Membership], day: date) -> list[Membership]:
    return [m for m in memberships if m.role is MembershipRole.tenant and m.active_on(day)]


# --- DTOs (resposta) ---------------------------------------------------------------------------


class HouseholdView(ContractModel):
    id: UUID
    name: ShortText
    timezone: str
    source_kind: SourceKind
    policy: HouseholdPolicy


class RoomView(ContractModel):
    id: UUID
    name: str
    kind: RoomKind
    # Plafond solidário mensal (BILL-03): visível a quem vê a casa, antes e depois da adesão.
    included_wh: EnergyWh | None = None


class ResidentView(ContractModel):
    id: UUID
    display_name: str


class MembershipSelfView(ContractModel):
    """As memberships de quem pergunta (inclui o seu próprio `presence_opt_in`)."""

    id: UUID
    household_id: UUID
    role: MembershipRole
    room_id: UUID | None
    starts_on: date
    ends_on: date | None
    status: MembershipStatus
    presence_opt_in: bool


class MemberView(ContractModel):
    """Um membro visto por outro: sem `presence_opt_in`, `auth_subject` nem contactos."""

    membership_id: UUID
    resident_id: UUID
    display_name: str
    role: MembershipRole
    room_id: UUID | None
    starts_on: date
    ends_on: date | None
    status: MembershipStatus


class MeContext(ContractModel):
    """Resposta a «quem sou eu aqui»: o residente ligado ao `sub` e as suas memberships."""

    resident: ResidentView | None
    memberships: list[MembershipSelfView]
