"""Estimativa da lâmpada do kit: 9 W × tempo × brilho (v5.1 §6.3; D-04 `estimated`).

A lâmpada não mede. A partir do estado lido pelo MCP (ligada + brilho) este estimador abre uma
sessão ao ligar e fecha-a ao desligar, e publica os mesmos eventos de domínio que as sessões da
tomada (`energy.consumption_detected/closed`) para o atribuidor os tratar como qualquer consumo.

- Energia por troços: cada intervalo entre observações conta ao brilho da observação anterior
  (o estado mantém-se até se observar outro). Brilho desconhecido com a lâmpada ligada conta 100 %.
- Sem leitura (lâmpada indisponível) a sessão fecha no ÚLTIMO instante observado e fica marcada
  em `fechadas_sem_leitura`: nunca se inventa tempo em que ninguém a viu ligada.
- Puro e síncrono: instantes e origem vêm de quem chama; sem I/O, threads nem escritas físicas.
  Ids derivados do dispositivo e do início: a mesma sequência produz os mesmos eventos (D-19).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.domain_events import (
    DomainEvent,
    EnergyConsumptionClosed,
    EnergyConsumptionDetected,
)
from homemind.contracts.energy import (
    ApplianceMatch,
    ConsumptionEvent,
    ConsumptionStatus,
    LocationKind,
)

log = logging.getLogger(__name__)

LAMP_WATTS = 9  # potência nominal assumida a 100 % de brilho (v5.1 §6.3)


@dataclass
class _Session:
    id: UUID
    device_id: UUID
    started_at: datetime
    last_at: datetime
    brightness: int
    watt_seconds: Decimal
    peak_w: float
    location: LocationKind
    room_id: UUID | None
    origin: Origin


class LampEstimator:
    def __init__(
        self,
        household_id: UUID,
        *,
        register: Callable[[], UUID],
        locate: Callable[[UUID], tuple[LocationKind, UUID | None]],
        publish: Callable[[DomainEvent], object],
    ) -> None:
        """`register()` devolve o id interno da lâmpada (chamado ao ligar); `locate(id)` a sua
        localização medida/configurada (ver `locate.py`)."""
        self.household_id = household_id
        self._register, self._locate, self._publish = register, locate, publish
        self._session: _Session | None = None
        self.fechadas_sem_leitura: list[UUID] = []

    def observe(
        self, ligada: bool | None, brilho: int | None, at: datetime, origin: Origin
    ) -> None:
        """`ligada=None` = lâmpada indisponível/desconhecida. Instantes anteriores ignoram-se."""
        s = self._session
        if s is not None and at < s.last_at:
            return
        if ligada is None:
            if s is not None:
                self._close(s, s.last_at, unavailable=True)
            return
        if not ligada:
            if s is not None:
                self._accrue(s, at)
                self._close(s, at)
            return
        brightness = brilho or 100
        if s is None:
            self._open(at, brightness, origin)
            return
        self._accrue(s, at)
        s.brightness = brightness
        s.peak_w = max(s.peak_w, LAMP_WATTS * brightness / 100)

    @staticmethod
    def _accrue(s: _Session, at: datetime) -> None:
        seconds = Decimal(str((at - s.last_at).total_seconds()))
        s.watt_seconds += Decimal(LAMP_WATTS * s.brightness) / 100 * seconds
        s.last_at = at

    def _open(self, at: datetime, brightness: int, origin: Origin) -> None:
        device_id = self._register()
        location, room_id = self._locate(device_id)
        s = _Session(
            id=stable_id("energy.lamp", "session", str(device_id), at.isoformat()),
            device_id=device_id,
            started_at=at,
            last_at=at,
            brightness=brightness,
            watt_seconds=Decimal(0),
            peak_w=LAMP_WATTS * brightness / 100,
            location=location,
            room_id=room_id,
            origin=origin,
        )
        self._session = s
        data = self._data(s)
        self._publish(
            EnergyConsumptionDetected(
                id=stable_id("energy.lamp", "detected", str(s.id)),
                ts=at,
                household_id=self.household_id,
                correlation_id=s.id,
                provenance=data.provenance,
                data=data,
            )
        )

    def _close(self, s: _Session, at: datetime, *, unavailable: bool = False) -> None:
        self._session = None
        if unavailable:
            self.fechadas_sem_leitura.append(s.id)
            log.warning("lâmpada sem leitura: sessão estimada fechada no último instante observado")
        data = self._data(s, closed_at=at)
        self._publish(
            EnergyConsumptionClosed(
                id=stable_id("energy.lamp", "closed", str(s.id)),
                ts=at,
                household_id=self.household_id,
                correlation_id=s.id,
                provenance=data.provenance,
                data=data,
            )
        )

    def _data(self, s: _Session, closed_at: datetime | None = None) -> ConsumptionEvent:
        return ConsumptionEvent(
            id=s.id,
            household_id=self.household_id,
            device_id=s.device_id,
            match=ApplianceMatch(),
            started_at=s.started_at,
            ended_at=closed_at,
            status=ConsumptionStatus.closed if closed_at else ConsumptionStatus.ongoing,
            peak_w=s.peak_w,
            energy_wh=int(round(s.watt_seconds / Decimal(3600))),
            location=s.location,
            room_id=s.room_id,
            provenance=Provenance(origin=s.origin, kind=ValueKind.estimated),
        )
