"""Alertas de conforto e segurança (SAFE-01, SAFE-03) e AWAY simulado (SAFE-02). Dono: P2.

Entrega: P3.

safety deteta (sensores + consumos) e emite `SafetyAlert`; nunca escreve no MCP. Uma ação
sugerida (`suggested_command`) é só uma sugestão: P3 transforma-a numa `ProposedAction`, que
exige confirmação humana, e P1 executa com grant e releitura. Fumo nunca sugere cortes
(desligar à pressa pode ser inseguro) e o sistema não substitui um detetor certificado.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
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


class AwayStatus(StrEnum):
    away = "away"  # casa vazia (candidato); só uma proposta de armar, nunca execução
    home = "home"  # há alguém: saiu de AWAY
    unknown = "unknown"  # sem sinal fiável (`uncertain`); nunca é AWAY


class AwayState(ContractModel):
    """Estado AWAY da casa (SAFE-02, PROPOSTA, SIMULADO). Derivado de `HouseOccupancy`; anónimo
    (sem pessoas nem horários por pessoa) e nunca visível ao senhorio. `arm_proposed` é só o
    registo de que armar seria proposto: `executed` é sempre falso (sem MCP nem escrita física)."""

    id: UUID
    household_id: UUID
    status: AwayStatus
    since: UtcDatetime  # `ts` do evento de ocupação que causou a mudança
    arm_proposed: bool = False
    executed: Literal[False] = False
    provenance: Provenance

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.arm_proposed != (self.status is AwayStatus.away):
            raise ValueError("a proposta de armar existe exatamente em AWAY")
        if self.arm_proposed and not self.provenance.simulated:
            raise ValueError("armar é só uma proposta SIMULADA (SAFE-02)")
        return self


class SecurityPanelStatus(StrEnum):
    armed = "armed"
    disarmed = "disarmed"
    unknown = "unknown"  # sem leitura fiável: nunca se assume armado nem desarmado


class SecurityPanelState(ContractModel):
    """Estado do painel de segurança SIMULADO (SAFE-02, PROPOSTA). Só existe fonte simulada:
    não há leitura real do alarme (MCP-04/SAFE-04 PLANEADOS, D-07/P-01). Anónimo."""

    id: UUID
    household_id: UUID
    status: SecurityPanelStatus
    since: UtcDatetime
    provenance: Provenance

    @model_validator(mode="after")
    def _simulated_only(self) -> Self:
        if not self.provenance.simulated:
            raise ValueError("o painel de segurança só tem fonte SIMULADA (sem leitura real)")
        return self


class SecurityActionKind(StrEnum):
    arm = "arm"
    disarm = "disarm"


class SecurityActionStatus(StrEnum):
    proposed = "proposed"  # à espera de confirmação humana explícita
    confirmed = "confirmed"  # confirmada: só o painel SIMULADO muda de estado
    cancelled = "cancelled"


class SecurityAction(ContractModel):
    """Proposta de armar/desarmar (SAFE-02, PROPOSTA, SIMULADA): o mesmo `id` em `proposed` e
    depois `confirmed`/`cancelled`. Nunca é execução física: `executed` é sempre falso e a
    proveniência sempre simulada. `decided_by` é interno (auditoria), nunca vai para a API.
    Uma proposta não confirmada caduca em `expires_at` (calculado na leitura, sem evento)."""

    id: UUID
    household_id: UUID
    kind: SecurityActionKind
    status: SecurityActionStatus = SecurityActionStatus.proposed
    proposed_at: UtcDatetime
    expires_at: UtcDatetime
    decided_at: UtcDatetime | None = None
    decided_by: UUID | None = None
    executed: Literal[False] = False
    provenance: Provenance

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if not self.provenance.simulated:
            raise ValueError("armar/desarmar é só SIMULADO (sem MCP nem escrita física)")
        if self.expires_at <= self.proposed_at:
            raise ValueError("expires_at anterior a proposed_at")
        decided = self.status is not SecurityActionStatus.proposed
        if decided != (self.decided_at is not None and self.decided_by is not None):
            raise ValueError("decided_at/decided_by exatamente nas propostas decididas")
        if self.decided_at is not None and self.decided_at < self.proposed_at:
            raise ValueError("decided_at anterior a proposed_at")
        return self
