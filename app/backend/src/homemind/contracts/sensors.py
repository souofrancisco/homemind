"""Sensores de contacto, fumo e clima (só leitura). Dono: P1 (MCP-03); consumidor: P2 (SAFE).

Valor desconhecido é `status=unknown` e todos os valores `None`, nunca um valor por omissão:
um sensor que o MCP não suporta não diz «janela fechada» nem «sem fumo».
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from homemind.contracts.common import ContractModel, Provenance, UtcDatetime


class SensorKind(StrEnum):
    contact = "contact"  # janela/porta
    smoke = "smoke"
    temperature = "temperature"
    humidity = "humidity"


class SensorStatus(StrEnum):
    ok = "ok"
    unknown = "unknown"  # não suportado / sem valor
    stale = "stale"  # último contacto demasiado antigo; não decidir com ele


class ContactState(StrEnum):
    open = "open"
    closed = "closed"


_VALUE_FIELD = {
    SensorKind.contact: "contact",
    SensorKind.smoke: "smoke_detected",
    SensorKind.temperature: "temperature_c",
    SensorKind.humidity: "humidity_pct",
}


class SensorReading(ContractModel):
    id: UUID
    device_id: UUID
    room_id: UUID | None = None  # onde está o sensor (para cruzar janela ↔ aquecedor)
    ts: UtcDatetime  # quando lemos
    observed_at: UtcDatetime | None = None  # último contacto do sensor (se conhecido)
    kind: SensorKind
    status: SensorStatus
    contact: ContactState | None = None
    smoke_detected: bool | None = None
    temperature_c: Annotated[float, Field(ge=-40, le=85, allow_inf_nan=False)] | None = None
    humidity_pct: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        expected = _VALUE_FIELD[self.kind]
        for name in _VALUE_FIELD.values():
            value = getattr(self, name)
            if name != expected and value is not None:
                raise ValueError(f"`{name}` não pertence a um sensor {self.kind.value}")
        value = getattr(self, expected)
        if self.status is SensorStatus.ok and value is None:
            raise ValueError(f"leitura ok exige `{expected}`")
        if self.status is not SensorStatus.ok and value is not None:
            raise ValueError("leitura sem estado ok não tem valor")
        return self

    @property
    def usable(self) -> bool:
        return self.status is SensorStatus.ok
