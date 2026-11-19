"""Leitura SÓ DE LEITURA do estado do alarme a partir do MCP (SAFE-02, #115).

Nada aqui chama o MCP nem importa conectores: recebe as respostas já lidas e devolve um
`SecurityPanelState` REAL. Falha sempre para `unknown`: dispositivo ou ferramenta ausente,
capability não suportada, valor não reconhecido, resposta malformada, leitura velha ou fontes
contraditórias. Nunca se infere `armed`/`disarmed`.

Fontes (por ordem de fiabilidade):
- `get_home_security_status`: leitura REAL de 2026-11-19 devolveu `{"status": "DISARMED",
  "isAlarmed": false}`. `DISARMED` observado (o estado físico do alarme nesse momento não foi
  confirmado por uma pessoa); `ARMED` é um FORMATO ASSUMIDO, por confirmar com o alarme armado.
  Qualquer outro `status` (ex.: variantes «armed home/away») = `unknown`.
- `get_home_devices`, capability `alarmState` do `gateway`: FORMATO ASSUMIDO (`armed`/`disarmed`).
  A leitura real mostrou `alarmState = "normal"`, o estado de disparo e não o de armamento, logo
  `unknown`. Fonte secundária.
Duas fontes frescas que discordem => `unknown`. Sem escrita: `patch_home_security_status` nunca
é chamada (D-07/P-01: leitura permitida por decisão do utilizador, a rever pela equipa).
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

# `get_home_security_status`: `DISARMED` observado; `ARMED` ASSUMIDO, por confirmar.
_STATUS_VALUES = {"ARMED": SecurityPanelStatus.armed, "DISARMED": SecurityPanelStatus.disarmed}


def panel_status_from_security_status(payload: Any) -> SecurityPanelStatus:
    """Resposta de `get_home_security_status`. `isAlarmed` tem de ser booleano; um alarme
    disparado com o painel «desarmado» é contraditório e fica `unknown`."""
    try:
        if not isinstance(payload, dict):
            return SecurityPanelStatus.unknown
        value, alarmed = payload.get("status"), payload.get("isAlarmed")
        if not isinstance(value, str) or not isinstance(alarmed, bool):
            return SecurityPanelStatus.unknown
        status = _STATUS_VALUES.get(value, SecurityPanelStatus.unknown)
        if alarmed and status is SecurityPanelStatus.disarmed:
            return SecurityPanelStatus.unknown
        return status
    except Exception:  # noqa: BLE001
        return SecurityPanelStatus.unknown


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
    """Última leitura REAL do painel da casa configurada. Alimentada pelo polling do `McpHome`
    (`ingest` com a lista de `get_home_devices`, `ingest_status` com `get_home_security_status`,
    `unavailable` em falha); só em memória: nada se persiste nem se publica. Lida pelo router,
    que nunca chama o MCP."""

    def __init__(
        self, household_id: UUID, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self.household_id = household_id
        self._clock = clock
        self._lock = threading.Lock()
        # fonte -> (estado, desde quando se mantém, quando foi lido)
        self._src: dict[str, tuple[SecurityPanelStatus, datetime, datetime]] = {}

    def _put(self, source: str, status: SecurityPanelStatus) -> SecurityPanelStatus:
        now = self._clock()
        with self._lock:
            prev = self._src.get(source)
            since = prev[1] if prev and prev[0] == status else now
            self._src[source] = (status, since, now)
        return status

    def ingest(self, devices: Any) -> SecurityPanelStatus:
        return self._put("devices", panel_status_from_devices(devices))

    def ingest_status(self, payload: Any) -> SecurityPanelStatus:
        return self._put("status", panel_status_from_security_status(payload))

    def unavailable(self) -> None:
        with self._lock:
            self._src.clear()

    def unavailable_status(self) -> None:
        with self._lock:
            self._src.pop("status", None)

    def read(self, household_id: UUID, now: datetime) -> SecurityPanelState | None:
        """`None` se a leitura não é desta casa; `unknown` se não há leitura fresca e conhecida
        ou se as fontes discordam."""
        if household_id != self.household_id:
            return None
        with self._lock:
            known = [
                (st, since)
                for st, since, seen in self._src.values()
                if now - seen <= STALE_AFTER and st is not SecurityPanelStatus.unknown
            ]
        values = {st for st, _ in known}
        if len(values) != 1:
            return panel_state(household_id, SecurityPanelStatus.unknown, now)
        return panel_state(household_id, values.pop(), max(since for _, since in known))
