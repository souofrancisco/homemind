"""Regras de conforto e segurança (SAFE-01 janela, SAFE-03 fumo, SAFE-02 AWAY simulado). Pura.

Dobra eventos de domínio e devolve `safety.alert_raised`. Não escreve no MCP, não executa nada
e não lê o relógio: o «agora» é o `ts` do evento que está a ser processado (determinístico e
reprodutível). O estado é só o que as regras precisam (início do episódio, alerta ativo) e
reconstrói-se do registo de eventos (`service.restore`), sem tabelas próprias.

Princípios:
- `unknown`/`stale` nunca disparam, nem fecham um alerta: só uma leitura `ok` decide.
- Um alerta por episódio (`id` estável); a resolução reutiliza o `id` com `status=resolved`.
- A sugestão (`power=false`) é só proposta; a confirmação humana e a execução são de P3/P1.
- Fumo é sempre crítico e nunca sugere cortes.
- AWAY (SAFE-02): só `likely_empty` leva a AWAY; `occupied` sai; `uncertain` ou ausência de
  sinais é `unknown`, nunca AWAY. «Armar» é só o registo SIMULADO de uma proposta
  (`arm_proposed`, `executed=False`): nada é armado, executado nem enviado a conectores.
  Só emite `safety.away_changed` quando o estado muda.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from homemind.contracts import domain_events as de
from homemind.contracts.agent import DeviceCapability, DeviceCommand
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.energy import ConsumptionEvent, ConsumptionStatus
from homemind.contracts.notification import NotificationSeverity
from homemind.contracts.presence import OccupancyState
from homemind.contracts.safety import (
    AwayState,
    AwayStatus,
    SafetyAlert,
    SafetyAlertKind,
    SafetyAlertStatus,
)
from homemind.contracts.sensors import ContactState, SensorKind, SensorReading, SensorStatus

WINDOW_OPEN_MIN = timedelta(minutes=5)

# appliance_id -> é aquecimento? Vem do catálogo de aparelhos (ENERGY-03, PLANEADO).
HeatingResolver = Callable[[UUID], bool]


def no_heating_known(_appliance_id: UUID) -> bool:
    return False


@dataclass
class _Window:
    open_since: datetime | None = None
    # desde quando janela aberta E aquecimento a decorrer coincidem (os 5 min contam daqui)
    coincident_since: datetime | None = None
    room_id: UUID | None = None
    prov: Provenance | None = None
    alert: SafetyAlert | None = None  # alerta ativo deste episódio


@dataclass
class _Smoke:
    alert: SafetyAlert | None = None


@dataclass
class _House:
    windows: dict[UUID, _Window] = field(default_factory=dict)  # por sensor
    smoke: dict[UUID, _Smoke] = field(default_factory=dict)
    heaters: dict[UUID, ConsumptionEvent] = field(default_factory=dict)  # consumos a decorrer
    sensors: dict[tuple[SensorKind, UUID], SensorStatus] = field(default_factory=dict)
    away: AwayState | None = None  # None: sem sinais (equivale a `unknown`)


class SafetyEngine:
    def __init__(
        self, is_heating: HeatingResolver = no_heating_known, notify_landlord: bool = False
    ) -> None:
        self._is_heating = is_heating
        # Só fumo, e só se a casa autorizar (sem política no contrato: desligado por omissão).
        self._notify_landlord = notify_landlord
        self._houses: dict[UUID, _House] = {}

    def _house(self, household_id: UUID) -> _House:
        return self._houses.setdefault(household_id, _House())

    # entrada ------------------------------------------------------------------------------

    def on_event(self, event: de.EventBase) -> list[de.SafetyAlertRaised | de.SafetyAwayChanged]:
        if isinstance(event, de.PresenceOccupancyChanged):
            return self._on_occupancy(event)
        if isinstance(event, de.SensorReadingRecorded):
            return self._on_reading(event)
        if isinstance(event, de.EnergyConsumptionDetected):
            return self._on_consumption(event, on=True)
        if isinstance(event, de.EnergyConsumptionClosed):
            return self._on_consumption(event, on=False)
        return []

    def away_status(self, household_id: UUID) -> AwayStatus:
        house = self._houses.get(household_id)
        return house.away.status if house and house.away else AwayStatus.unknown

    def coverage(self, household_id: UUID) -> dict[SensorKind, str]:
        """Estado dos sensores de segurança para a UI: `ok`, `unknown`, `stale` ou `absent`
        (nunca visto). Ausência identificada, nunca assumida como «sem fumo»/«janela fechada»."""
        house = self._houses.get(household_id, _House())
        out: dict[SensorKind, str] = {}
        for kind in (SensorKind.contact, SensorKind.smoke):
            states = [s for (k, _), s in house.sensors.items() if k is kind]
            if not states:
                out[kind] = "absent"
            elif SensorStatus.ok in states:
                out[kind] = "ok"
            else:
                out[kind] = states[-1].value
        return out

    # casa vazia (SAFE-02, SIMULADO) --------------------------------------------------------

    _AWAY_OF = {
        OccupancyState.likely_empty: AwayStatus.away,
        OccupancyState.occupied: AwayStatus.home,
        OccupancyState.uncertain: AwayStatus.unknown,
    }

    def _on_occupancy(self, ev: de.PresenceOccupancyChanged) -> list[de.SafetyAwayChanged]:
        house = self._house(ev.household_id)
        status = self._AWAY_OF[ev.data.state]
        current = house.away
        if current is None and status is AwayStatus.unknown:
            return []  # sem sinais é já `unknown`: nada a registar
        if current is not None and (status is current.status or ev.ts < current.since):
            return []  # sem mudança (idempotente) ou evento atrasado
        away = status is AwayStatus.away
        # Armar é sempre uma proposta SIMULADA, mesmo que a ocupação venha de dados reais.
        sim = Provenance(origin=Origin.simulated, kind=ValueKind.inferred)
        prov = Provenance.combine(ev.data.provenance, sim)
        house.away = AwayState(
            id=stable_id("safety", "away", str(ev.household_id), ev.ts.isoformat(), status.value),
            household_id=ev.household_id,
            status=status,
            since=ev.ts,
            arm_proposed=away,
            provenance=prov if away else ev.data.provenance,
        )
        return [
            de.SafetyAwayChanged(
                id=stable_id("safety-event", str(house.away.id)),
                ts=ev.ts,
                household_id=ev.household_id,
                correlation_id=ev.correlation_id,
                provenance=house.away.provenance,
                data=house.away,
            )
        ]

    # sensores -----------------------------------------------------------------------------

    def _on_reading(self, ev: de.SensorReadingRecorded) -> list[de.SafetyAlertRaised]:
        r = ev.data
        house = self._house(ev.household_id)
        house.sensors[(r.kind, r.device_id)] = r.status
        if r.kind is SensorKind.smoke:
            return self._smoke(ev, house, r)
        if r.kind is SensorKind.contact:
            return self._window(ev, house, r)
        return []

    def _window(self, ev, house: _House, r: SensorReading) -> list[de.SafetyAlertRaised]:
        w = house.windows.setdefault(r.device_id, _Window())
        w.room_id = r.room_id or w.room_id
        if not r.usable:
            if w.alert is None:  # sem certeza de continuidade: o episódio recomeça
                w.open_since = w.coincident_since = None
            return []  # nunca dispara nem resolve com unknown/stale
        if r.contact is ContactState.closed:
            w.open_since = w.coincident_since = None
            return self._resolve_window(ev, w)
        if w.open_since is None:
            w.open_since = r.ts
        w.prov = r.provenance
        return self._evaluate(ev, house, r.device_id)

    def _smoke(self, ev, house: _House, r: SensorReading) -> list[de.SafetyAlertRaised]:
        s = house.smoke.setdefault(r.device_id, _Smoke())
        if not r.usable:
            return []  # sensor sem valor: nem alerta falso nem «tudo bem»
        if r.smoke_detected and s.alert is None:
            s.alert = SafetyAlert(
                id=stable_id("safety", "smoke", str(r.device_id), r.ts.isoformat()),
                household_id=ev.household_id,
                kind=SafetyAlertKind.smoke,
                severity=NotificationSeverity.critical,
                room_id=r.room_id,
                sensor_device_id=r.device_id,
                notify_landlord=self._notify_landlord,
                started_at=r.ts,
                provenance=r.provenance,
            )
            return [self._wrap(ev, s.alert, r.ts)]
        if r.smoke_detected is False and s.alert is not None:
            done = s.alert.model_copy(
                update={"status": SafetyAlertStatus.resolved, "resolved_at": r.ts}
            )
            s.alert = None
            return [self._wrap(ev, done, r.ts)]
        return []

    # aquecimento --------------------------------------------------------------------------

    def _on_consumption(self, ev, on: bool) -> list[de.SafetyAlertRaised]:
        c = ev.data
        house = self._house(ev.household_id)
        heating = c.match.appliance_id is not None and self._is_heating(c.match.appliance_id)
        out: list[de.SafetyAlertRaised] = []
        if on and heating and c.status is ConsumptionStatus.ongoing:
            house.heaters[c.id] = c
        else:
            house.heaters.pop(c.id, None)
        for sensor_id, w in house.windows.items():
            if not on and w.alert is not None and not self._heaters_in(house, w.room_id):
                out += self._resolve_window(ev, w)  # o aquecedor desligou
            out += self._evaluate(ev, house, sensor_id, now=ev.ts)
        return out

    @staticmethod
    def _heaters_in(house: _House, room_id: UUID | None) -> list[ConsumptionEvent]:
        if room_id is None:
            return []
        found = [c for c in house.heaters.values() if c.room_id == room_id]
        return sorted(found, key=lambda c: (c.started_at, str(c.id)))

    def _evaluate(self, ev, house: _House, sensor_id: UUID, now: datetime | None = None):
        w = house.windows[sensor_id]
        now = now or ev.ts
        heaters = self._heaters_in(house, w.room_id)
        if w.open_since is None or not heaters:
            w.coincident_since = None  # a coincidência quebrou: o relógio recomeça
            return []  # sem aquecimento (ou sensor sem quarto): nada a avisar
        if w.coincident_since is None:
            w.coincident_since = now
        if w.alert is not None or w.prov is None:
            return []
        if now - w.coincident_since < WINDOW_OPEN_MIN:
            return []
        c = heaters[0]
        w.alert = SafetyAlert(
            id=stable_id(
                "safety",
                "window",
                str(sensor_id),
                w.coincident_since.isoformat(),
                str(c.id),
                now.isoformat(),
            ),
            household_id=ev.household_id,
            kind=SafetyAlertKind.window_open_heating,
            severity=NotificationSeverity.warning,
            room_id=w.room_id,
            sensor_device_id=sensor_id,
            consumption_event_id=c.id,
            suggested_command=DeviceCommand(
                target_device_id=c.device_id, capability=DeviceCapability.power, power=False
            ),
            started_at=now,
            provenance=Provenance.combine(w.prov, c.provenance),
        )
        return [self._wrap(ev, w.alert, now)]

    def _resolve_window(self, ev, w: _Window) -> list[de.SafetyAlertRaised]:
        if w.alert is None:
            return []
        done = w.alert.model_copy(
            update={
                "status": SafetyAlertStatus.resolved,
                "resolved_at": max(ev.ts, w.alert.started_at),
            }
        )
        w.alert = None
        return [self._wrap(ev, done, done.resolved_at)]

    @staticmethod
    def _wrap(ev, alert: SafetyAlert, ts: datetime) -> de.SafetyAlertRaised:
        # id do evento determinístico: reprocessar o mesmo gatilho não duplica (idempotência).
        return de.SafetyAlertRaised(
            id=stable_id("safety-event", str(alert.id), alert.status.value),
            ts=ts,
            household_id=alert.household_id,
            correlation_id=ev.correlation_id,
            provenance=alert.provenance,
            data=alert,
        )
