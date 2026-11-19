"""Leitura SÓ DE LEITURA do estado do alarme a partir de `get_home_devices` (SAFE-02, #115).

Nada aqui chama o MCP nem importa conectores: recebe uma lista de dispositivos tal como vem de
`get_home_devices` e devolve um `SecurityPanelState` REAL. Falha sempre para `unknown`: dispositivo
ausente, capability não suportada, valor não reconhecido, formato malformado, leitura velha ou
valores contraditórios. Nunca se infere `armed`/`disarmed`.

FORMATO ASSUMIDO, POR CONFIRMAR: o alarme é lido da capability `alarmState` do dispositivo
`gateway` (categoria `security`), com os valores `armed`/`disarmed`. A leitura real de 2026-11-19
(só leitura) mostrou `alarmState = "normal"` no gateway com o alarme em repouso: é o estado de
disparo (como `sensorState` `normal`/`alarm`), não o de armamento, e por isso é `unknown`. O estado
armado/desarmado deverá vir de `get_home_security_status`, fora da whitelist (D-07/P-01): PLANEADO.
Sem escrita: `patch_home_security_status` nunca é chamada.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.safety import SecurityPanelState, SecurityPanelStatus

GATEWAY_TYPE = "gateway"
ALARM_CAPABILITY = "alarmState"
# FORMATO ASSUMIDO, por confirmar com uma resposta real em que o alarme esteja armado.
_ASSUMED_VALUES = {"armed": SecurityPanelStatus.armed, "disarmed": SecurityPanelStatus.disarmed}
# O polling é de 5 s; sem leitura nova durante este tempo o estado deixa de ser devolvido.
STALE_AFTER = timedelta(seconds=90)


def _status_of(device: Any) -> SecurityPanelStatus:
    try:
        if not isinstance(device, dict) or device.get("type") != GATEWAY_TYPE:
            return SecurityPanelStatus.unknown
        categories = device.get("categories")
        if not isinstance(categories, list) or "security" not in categories:
            return SecurityPanelStatus.unknown
        caps = [
            c
            for c in device.get("capabilities") or []
            if isinstance(c, dict) and c.get("type") == ALARM_CAPABILITY
        ]
        value = caps[0].get("value") if len(caps) == 1 else None
        return (
            _ASSUMED_VALUES.get(value, SecurityPanelStatus.unknown)
            if isinstance(value, str)
            else SecurityPanelStatus.unknown
        )
    except Exception:  # noqa: BLE001 - formato inesperado nunca rebenta o polling
        return SecurityPanelStatus.unknown


def panel_status_from_devices(devices: Any) -> SecurityPanelStatus:
    """`armed`/`disarmed` só se houver gateways e TODOS concordarem; senão `unknown`."""
    if not isinstance(devices, list):
        return SecurityPanelStatus.unknown
    found = {
        _status_of(d) for d in devices if isinstance(d, dict) and d.get("type") == GATEWAY_TYPE
    }
    return found.pop() if len(found) == 1 else SecurityPanelStatus.unknown


def panel_state(
    household_id: UUID, status: SecurityPanelStatus, since: datetime
) -> SecurityPanelState:
    known = status is not SecurityPanelStatus.unknown
    return SecurityPanelState(
        id=stable_id("safety", "panel-real", str(household_id)),
        household_id=household_id,
        status=status,
        since=since,
        provenance=Provenance(
            origin=Origin.real, kind=ValueKind.measured if known else ValueKind.estimated
        ),
    )


class SecurityPanelCache:
    """Última leitura REAL do painel da casa configurada. Alimentada por quem entregar a lista de
    dispositivos (`ingest`/`unavailable`); HOJE NINGUÉM a alimenta em produção: o `McpHome` (P1)
    descarta a lista fora do `sensores.ingest` e ligá-lo exige acordo da P1; só em memória: nada se
    persiste nem se publica. Lida pelo router, que nunca chama o MCP."""

    def __init__(
        self, household_id: UUID, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self.household_id = household_id
        self._clock = clock
        self._lock = threading.Lock()
        self._status = SecurityPanelStatus.unknown
        self._since: datetime | None = None
        self._seen: datetime | None = None

    def ingest(self, devices: Any) -> SecurityPanelStatus:
        status, now = panel_status_from_devices(devices), self._clock()
        with self._lock:
            if status != self._status or self._since is None:
                self._since = now
            self._status, self._seen = status, now
        return status

    def unavailable(self) -> None:
        with self._lock:
            self._status, self._since, self._seen = SecurityPanelStatus.unknown, None, None

    def read(self, household_id: UUID, now: datetime) -> SecurityPanelState | None:
        """`None` se a leitura não é desta casa; `unknown` se não há leitura ou é velha."""
        if household_id != self.household_id:
            return None
        with self._lock:
            fresh = self._seen is not None and now - self._seen <= STALE_AFTER
            status = self._status if fresh else SecurityPanelStatus.unknown
            since = (self._since if fresh and self._since else None) or now
        return panel_state(household_id, status, since)
