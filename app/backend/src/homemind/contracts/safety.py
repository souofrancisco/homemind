"""Alertas de conforto e segurança (SAFE-01, SAFE-03). Dono: P2; entrega: P3.

safety deteta (sensores + consumos) e emite `SafetyAlert`; nunca escreve no MCP. Uma ação
sugerida (`suggested_command`) é só uma sugestão: P3 transforma-a numa `ProposedAction`, que
exige confirmação humana, e P1 executa com grant e releitura. Fumo nunca sugere cortes
(desligar à pressa pode ser inseguro) e o sistema não substitui um detetor certificado.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import model_validator

from homemind.contracts.agent import DeviceCapability, DeviceCommand
from homemind.contracts.common import ContractModel, Provenance, UtcDatetime
from homemind.contracts.notification import NotificationSeverity


class SafetyAlertKind(StrEnum):
    window_open_heating = "window_open_heating"  # janela aberta > 5 min com aquecimento ligado
    smoke = "smoke"


class SafetyAlertStatus(StrEnum):
    active = "active"
    resolved = "resolved"


class SafetyAlert(ContractModel):
    """Um alerta por situação: o mesmo `id` em `active` e depois `resolved` (deduplicação)."""

    id: UUID
    household_id: UUID
    kind: SafetyAlertKind
    severity: NotificationSeverity
    status: SafetyAlertStatus = SafetyAlertStatus.active
    room_id: UUID | None = None
    sensor_device_id: UUID | None = None  # None: sensor ausente (simulado ou sem leitura)
    consumption_event_id: UUID | None = None  # o aquecimento em causa
    suggested_command: DeviceCommand | None = None
    notify_landlord: bool = False  # só fumo, e só se a casa o autorizou
    started_at: UtcDatetime
    resolved_at: UtcDatetime | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if (self.status is SafetyAlertStatus.resolved) != (self.resolved_at is not None):
            raise ValueError("resolved_at exatamente nos alertas resolvidos")
        if self.resolved_at is not None and self.resolved_at < self.started_at:
            raise ValueError("resolved_at anterior a started_at")
        if self.kind is SafetyAlertKind.smoke:
            if self.severity is not NotificationSeverity.critical:
                raise ValueError("fumo é sempre crítico")
            if self.suggested_command is not None:
                raise ValueError("fumo nunca sugere cortes de energia")
        else:
            if self.notify_landlord:
                raise ValueError("só o fumo pode chegar ao senhorio")
            if self.consumption_event_id is None:
                raise ValueError("janela aberta com aquecimento exige o consumo em causa")
            cmd = self.suggested_command
            if cmd is not None and (cmd.capability is not DeviceCapability.power or cmd.power):
                raise ValueError("a única sugestão é desligar a tomada")
        return self
