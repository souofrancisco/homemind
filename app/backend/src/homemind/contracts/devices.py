"""Dispositivos (físicos) e aparelhos (consumidores).

Uma tomada é um `Device`; um aquecedor é um `Appliance`. Uma tomada pode medir vários
aparelhos e uma assinatura sugere um aparelho, não garante identidade nem localização.
Dono: energy (P1). `Device` tem `external_ref` (id MCP): é interno, a API devolve `DeviceView`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from homemind.contracts.common import ContractModel, PowerW, ShortText, UtcDatetime


class DeviceKind(StrEnum):
    plug = "plug"
    bulb = "bulb"
    camera = "camera"
    sensor = "sensor"


class DeviceRole(StrEnum):
    main_meter = "main_meter"  # MVP: a tomada da extensão faz de contador
    room_meter = "room_meter"
    actuator = "actuator"
    none = "none"


class DeviceSource(StrEnum):
    mcp = "mcp"
    fake = "fake"
    replay = "replay"


class PowerUnit(StrEnum):
    W = "W"
    dW = "dW"
    mW = "mW"
    unknown = "unknown"  # impede leituras `measured`


class Device(ContractModel):
    """Interno (persistência e conectores). Nunca devolver diretamente na API."""

    id: UUID
    household_id: UUID
    room_id: UUID | None = None
    name: ShortText
    kind: DeviceKind
    role: DeviceRole = DeviceRole.none
    source: DeviceSource
    # Id no MCP: segredo operacional. Fora de logs, repr, eventos e DTOs.
    external_ref: str | None = Field(default=None, min_length=1, max_length=200, repr=False)
    power_unit: PowerUnit = PowerUnit.unknown
    last_seen_at: UtcDatetime | None = None
    online: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.role in (DeviceRole.main_meter, DeviceRole.room_meter) and (
            self.kind is not DeviceKind.plug
        ):
            raise ValueError("um contador é uma tomada")
        if self.role is DeviceRole.room_meter and self.room_id is None:
            raise ValueError("room_meter exige room_id")
        if self.role is DeviceRole.actuator and self.kind not in (DeviceKind.plug, DeviceKind.bulb):
            raise ValueError("só tomadas e lâmpadas são atuadores")
        if self.source is DeviceSource.mcp and self.external_ref is None:
            raise ValueError("dispositivo MCP exige external_ref")
        return self


class DeviceView(ContractModel):
    id: UUID
    household_id: UUID
    room_id: UUID | None
    name: str
    kind: DeviceKind
    role: DeviceRole
    source: DeviceSource
    power_unit: PowerUnit
    last_seen_at: UtcDatetime | None
    online: bool

    @classmethod
    def of(cls, d: Device) -> DeviceView:
        return cls(**d.model_dump(exclude={"external_ref"}))


class ApplianceCategory(StrEnum):
    heating = "heating"
    cooling = "cooling"
    kitchen = "kitchen"
    laundry = "laundry"
    electronics = "electronics"
    lighting = "lighting"
    other = "other"


class ApplianceScope(StrEnum):
    personal = "personal"  # de um morador
    shared = "shared"  # de um morador, partilhado por acordo
    common = "common"  # da casa


class ApplianceStatus(StrEnum):
    active = "active"
    retired = "retired"


class ApplianceOwnership(ContractModel):
    """Quem é o dono e onde «vive». O dono não é necessariamente quem o usa agora."""

    scope: ApplianceScope
    owner_resident_id: UUID | None = None
    home_room_id: UUID | None = None

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.scope is ApplianceScope.personal and self.owner_resident_id is None:
            raise ValueError("aparelho pessoal exige dono")
        if self.scope is ApplianceScope.common and self.owner_resident_id is not None:
            raise ValueError("aparelho comum não tem dono")
        return self


class Appliance(ContractModel):
    id: UUID
    household_id: UUID
    name: ShortText
    category: ApplianceCategory
    ownership: ApplianceOwnership
    typical_watts: Annotated[PowerW, Field(gt=0)] | None = None
    status: ApplianceStatus = ApplianceStatus.active
    registered_by_resident_id: UUID


class SignaturePattern(StrEnum):
    continuous = "continuous"
    cyclic = "cyclic"
    short = "short"
    decaying = "decaying"


class SignatureOrigin(StrEnum):
    registered = "registered"
    learned = "learned"
    simulated = "simulated"


class ApplianceSignature(ContractModel):
    """Padrão elétrico típico. Vários por aparelho; sugere, não decide quem paga."""

    id: UUID
    appliance_id: UUID
    watts_mean: Annotated[PowerW, Field(gt=0)]
    watts_tolerance: PowerW
    duration_typical_s: Annotated[int, Field(strict=True, gt=0)] | None = None
    pattern: SignaturePattern
    typical_hours: list[Annotated[int, Field(strict=True, ge=0, le=23)]] | None = None
    samples: Annotated[int, Field(strict=True, ge=0)] = 0
    origin: SignatureOrigin
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _tolerance(self) -> Self:
        if self.watts_tolerance >= self.watts_mean:
            raise ValueError("tolerância tem de ser menor do que a média")
        return self
