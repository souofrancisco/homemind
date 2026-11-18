"""Motor das regras da casa (SAFE-04). Lógica pura: sem I/O, sem relógio do sistema e sem
dispositivos. Dobra eventos de domínio e devolve `Firing` (decisões de desligar uma tomada); quem
executa é o `runner.py`. O «agora» é sempre o `ts` do evento em processamento, por isso o
resultado é determinístico e reproduzível (restore = voltar a dobrar os eventos).

Gatilhos (os únicos do contrato):
- `power_above`: leituras `energy.reading_recorded` do dispositivo do gatilho com potência
  ESTRITAMENTE acima de `threshold_w`, sem interrupção, durante pelo menos `duration_s`. Usa-se a
  leitura e não o `ConsumptionEvent` porque este só traz `peak_w`/`energy_wh` (não prova que a
  potência se manteve). Uma leitura sem potência utilizável, um intervalo maior do que
  `MAX_READING_GAP` entre leituras ou uma leitura não acima do limiar quebram a sequência; o fecho
  do consumo (`energy.consumption_closed`) também. Leituras fora de ordem ignoram-se.
- `presence_changed`: só transições in↔out face ao estado IMEDIATAMENTE anterior do morador. A
  primeira observação e qualquer transição que envolva `uncertain` só registam o estado.

Invariantes:
- só regras `active` aprovadas, e só eventos desde a ativação (`active_since`): um evento anterior
  nunca dispara uma regra;
- um disparo por episódio: enquanto a condição se mantém não volta a disparar;
- cooldown por regra e por dispositivo; duas regras sobre o mesmo dispositivo no mesmo evento
  originam UM só `Firing` (a regra de menor id lidera, as outras vêm em `covered`);
- um dispositivo com resultado `uncertain` fica bloqueado `lockout_s`: o disparo sai marcado
  `blocked_code="uncertain_lockout"` (regista-se, mas não se executa);
- só desliga: nunca liga nada. A lâmpada nunca é alvo (o contrato só admite `power=False`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from homemind.contracts import domain_events as de
from homemind.contracts.agent import (
    AutomationRule,
    DeviceCapability,
    ExecutionStatus,
    TriggerKind,
)
from homemind.contracts.energy import ReadingStatus
from homemind.contracts.presence import PresenceState

MAX_READING_GAP = timedelta(minutes=5)  # mais do que isto sem leituras: não se prova continuidade

RULE_COOLDOWN = "rule_cooldown"
DEVICE_COOLDOWN = "device_cooldown"
UNCERTAIN_LOCKOUT = "uncertain_lockout"


@dataclass(frozen=True)
class ActiveRule:
    """Regra `active` (aprovada) e o instante em que ficou ativa."""

    rule: AutomationRule
    active_since: datetime


@dataclass(frozen=True)
class Firing:
    """Um disparo: desligar `device_id` por causa de `rule_id` no evento `trigger_event_id`.
    `blocked_code` preenchido = não executar, só registar o bloqueio."""

    rule_id: UUID
    household_id: UUID
    device_id: UUID
    trigger_event_id: UUID
    at: datetime
    cause: TriggerKind
    covered: tuple[UUID, ...] = ()
    blocked_code: str | None = None


@dataclass
class _Run:
    above_since: datetime | None = None
    last_ts: datetime | None = None
    fired: bool = False


@dataclass
class AutomationEngine:
    device_cooldown_s: float = 60.0
    rule_cooldown_s: float = 3600.0
    lockout_s: float = 300.0
    _runs: dict[tuple[UUID, UUID], _Run] = field(default_factory=dict)  # (casa, regra)
    _presence: dict[tuple[UUID, UUID], PresenceState] = field(default_factory=dict)
    _rule_last: dict[UUID, datetime] = field(default_factory=dict)
    _device_last: dict[UUID, datetime] = field(default_factory=dict)
    _locked_at: dict[UUID, datetime] = field(default_factory=dict)

    # entrada ------------------------------------------------------------------------------

    def on_event(self, event: de.EventBase, rules: list[ActiveRule]) -> list[Firing]:
        """`rules` são as regras ativas da casa do evento neste instante."""
        hid = event.household_id
        live = [r for r in rules if r.rule.household_id == hid and event.ts >= r.active_since]
        self._prune(hid, {r.rule.id for r in rules})
        hits: list[tuple[AutomationRule, TriggerKind]] = []
        if isinstance(event, de.EnergyReadingRecorded):
            hits = self._on_reading(event, live)
        elif isinstance(event, de.EnergyConsumptionClosed):
            self._on_closed(event, live)
        elif isinstance(event, de.PresenceChanged):
            hits = self._on_presence(event, live)
        return self._decide(event, hits)

    def record_result(self, device_id: UUID, status: ExecutionStatus, at: datetime) -> None:
        """Um resultado `uncertain` bloqueia o dispositivo (nunca se repete às cegas)."""
        if status is ExecutionStatus.uncertain:
            self._locked_at[device_id] = at

    def is_locked(self, device_id: UUID, now: datetime) -> bool:
        """Dispositivo bloqueado por um resultado `uncertain` ainda dentro do bloqueio."""
        locked = self._locked_at.get(device_id)
        return locked is not None and (now - locked).total_seconds() < self.lockout_s

    # gatilhos -----------------------------------------------------------------------------

    def _prune(self, household_id: UUID, active_ids: set[UUID]) -> None:
        """Uma regra suspensa deixa de ter sequência: ao reativar recomeça do zero."""
        for key in [k for k in self._runs if k[0] == household_id and k[1] not in active_ids]:
            del self._runs[key]

    def _on_reading(
        self, event: de.EnergyReadingRecorded, rules: list[ActiveRule]
    ) -> list[tuple[AutomationRule, TriggerKind]]:
        reading, now, hits = event.data, event.ts, []
        for ar in rules:
            rule, trig = ar.rule, ar.rule.trigger
            if trig.kind is not TriggerKind.power_above or trig.device_id != reading.device_id:
                continue
            run = self._runs.setdefault((rule.household_id, rule.id), _Run())
            if run.last_ts is not None and run.last_ts < ar.active_since:
                run.above_since, run.last_ts, run.fired = None, None, False  # ativação anterior
            if run.last_ts is not None and now <= run.last_ts:
                continue  # fora de ordem ou repetida
            gap = run.last_ts is not None and now - run.last_ts > MAX_READING_GAP
            run.last_ts = now
            if reading.status is not ReadingStatus.ok or reading.power_w is None:
                run.above_since = None  # sem potência utilizável não se prova nada
                continue
            assert trig.threshold_w is not None and trig.duration_s is not None
            if reading.power_w <= trig.threshold_w:
                run.above_since, run.fired = None, False  # condição quebrada: novo episódio
                continue
            if run.above_since is None or gap:
                run.above_since = now
            if not run.fired and (now - run.above_since).total_seconds() >= trig.duration_s:
                run.fired = True
                hits.append((rule, TriggerKind.power_above))
        return hits

    def _on_closed(self, event: de.EnergyConsumptionClosed, rules: list[ActiveRule]) -> None:
        for ar in rules:
            trig = ar.rule.trigger
            if trig.kind is TriggerKind.power_above and trig.device_id == event.data.device_id:
                run = self._runs.get((ar.rule.household_id, ar.rule.id))
                if run is not None:
                    run.above_since, run.fired = None, False

    def _on_presence(
        self, event: de.PresenceChanged, rules: list[ActiveRule]
    ) -> list[tuple[AutomationRule, TriggerKind]]:
        key = (event.household_id, event.data.resident_id)
        before = self._presence.get(key)
        self._presence[key] = event.data.state
        clear = (PresenceState.home, PresenceState.away)
        # só in↔out: qualquer transição que envolva `uncertain` regista o estado e não dispara
        if before not in clear or event.data.state not in clear or before is event.data.state:
            return []
        return [
            (ar.rule, TriggerKind.presence_changed)
            for ar in rules
            if ar.rule.trigger.kind is TriggerKind.presence_changed
        ]

    # decisão ------------------------------------------------------------------------------

    def _decide(
        self, event: de.EventBase, hits: list[tuple[AutomationRule, TriggerKind]]
    ) -> list[Firing]:
        """Um `Firing` por dispositivo, com cooldowns e bloqueio por incerteza."""
        now = event.ts
        by_device: dict[UUID, list[tuple[AutomationRule, TriggerKind]]] = {}
        for rule, cause in sorted(hits, key=lambda h: str(h[0].id)):
            for action in rule.actions:  # o contrato só admite «desligar a tomada»
                assert action.capability is DeviceCapability.power and action.power is False
                by_device.setdefault(action.target_device_id, []).append((rule, cause))
        out: list[Firing] = []
        for device, group in by_device.items():
            lead, cause = group[0]
            covered = tuple(r.id for r, _ in group[1:])

            def firing(code: str | None, lead=lead, cause=cause, device=device, covered=covered):
                return Firing(
                    lead.id, lead.household_id, device, event.id, now, cause, covered, code
                )

            if self.is_locked(device, now):
                out.append(firing(UNCERTAIN_LOCKOUT))
                continue
            if any(
                self._within(self._rule_last.get(r.id), now, self.rule_cooldown_s) for r, _ in group
            ):
                out.append(firing(RULE_COOLDOWN))
                continue
            if self._within(self._device_last.get(device), now, self.device_cooldown_s):
                out.append(firing(DEVICE_COOLDOWN))
                continue
            self._device_last[device] = now
            for r, _ in group:
                self._rule_last[r.id] = now
            out.append(firing(None))
        return out

    @staticmethod
    def _within(last: datetime | None, now: datetime, seconds: float) -> bool:
        return last is not None and (now - last).total_seconds() < seconds
