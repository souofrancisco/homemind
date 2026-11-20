"""Liga o `AutomationEngine` ao barramento e executa os disparos (SAFE-04, onda 3).

Duas metades, porque o handler do barramento é síncrono e dentro da transação (sem I/O externo)
e o executor é assíncrono:
1. `handle` (consumidor `automations`): lê as regras ativas, deixa o motor decidir e põe os
   disparos numa fila; não devolve eventos nem escreve nada;
2. um *worker* tira da fila, confirma outra vez que a regra continua ativa e aprovada (uma
   suspensão vale na hora), chama o executor UMA vez e grava `automation.executed` com o
   resultado REAL.

Execução:
- a confirmação humana é a votação já feita: a `ProposedAction` nasce `confirmed`, confirmada por
  quem deu o voto decisivo (`approved_by_resident_id`) com a justificação «aprovada por votação»;
  não se pede confirmação nova. Só corre se a regra está `active` E aprovada
  (`repo.active_rules`);
- executor por `select_executor`: casa de demonstração = SEMPRE o simulado (nunca hardware);
  casa real = o executor da porta `app.state.agent_action_executor` ou nenhum → `blocked`
  (`executor_unavailable`). `run_execution` chama o executor no máximo uma vez e nunca repete;
- `uncertain` bloqueia o dispositivo (`lockout_s`, no motor) e nunca se repete: um disparo é
  identificado por (regra, evento, dispositivo) e só entra uma vez na fila nem no registo;
- auditoria: o próprio evento `automation.executed` (id estável, só de acrescentar). Não há
  tabela nova: o `automation_log` só aceita os tipos da votação.

Estado reconstruível (`restore`): volta a dobrar, pela ordem do registo, os eventos já entregues
a este consumidor, e aplica os `automation.executed` (bloqueios por incerteza). Um disparo
decidido mas ainda não executado quando o processo morreu perde-se (o episódio fica marcado como
disparado): preferimos não executar a repetir.

Limitações conhecidas (preferimos sempre NÃO executar a repetir):
- janela mínima entre `_load` (a regra ainda está ativa) e a chamada ao executor: uma suspensão
  nesse intervalo não a pára. Só importa se um executor FÍSICO vier a ser ligado (P1/MCP-04); o
  simulado não tem efeito real. O bloqueio por incerteza, esse, volta a consultar-se mesmo antes
  de executar;
- se `bus.publish` falhar depois de executar, perde-se o registo `automation.executed` (o efeito
  já aconteceu; o episódio fica marcado como disparado e não repete);
- se `handle` levantar depois de mutar o motor, a reentrega devolve a decisão em cache só se o
  processo vive; num reinício o episódio fica marcado e o disparo perde-se;
- o `restore` só relê a janela recente de leituras (ver `_history`).

Limitação: o alvo físico real só existe com o executor da P1 (MCP-04, flag + grant); sem ele a
regra fica `blocked`.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from homemind.contracts import domain_events as de
from homemind.contracts.agent import (
    ActionConfirmation,
    ActionExecutionResult,
    ActionStatus,
    AutomationRule,
    DeviceCapability,
    DeviceCommand,
    ExecutionStatus,
    ProposedAction,
)
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.domain_events import StoredEvent
from homemind.core.db import Database
from homemind.core.events import EventBus, load_events
from homemind.features.agent.execution import run_execution, select_executor
from homemind.features.automations import repo
from homemind.features.automations.engine import (
    MAX_READING_GAP,
    UNCERTAIN_LOCKOUT,
    ActiveRule,
    AutomationEngine,
    Firing,
)

log = logging.getLogger(__name__)

CONSUMER = "automations"
INPUT_TYPES = (
    "energy.reading_recorded",
    "energy.consumption_closed",
    "presence.changed",
)
EXECUTED = "automation.executed"
PRESENCE = "presence.changed"
MAX_DURATION_S = 86_400  # `AutomationTrigger.duration_s` ≤ 24 h
_SEEN_MAX = 256


class AutomationRunner:
    def __init__(
        self,
        state: SimpleNamespace | object,
        *,
        clock: Callable[[], datetime],
        engine: AutomationEngine | None = None,
        timeout_s: float = 15.0,
        action_ttl_s: float = 600.0,
    ) -> None:
        self.state = state
        self.clock = clock
        self.engine = engine or AutomationEngine()
        self.timeout_s = timeout_s
        self.action_ttl_s = action_ttl_s
        self._lock = threading.Lock()  # o handler corre numa thread; o worker, no loop
        # Disparos por evento já visto: uma reentrega (a transação do barramento falhou depois do
        # handler) devolve a mesma decisão sem voltar a pôr nada na fila.
        self._decided: OrderedDict[UUID, list[Firing]] = OrderedDict()
        self._queued: set[tuple[UUID, UUID, UUID]] = set()
        self._db: Database | None = None
        self._bus: EventBus | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[Firing] | None = None
        self._task: asyncio.Task[None] | None = None

    # --- arranque ----------------------------------------------------------------------------

    def attach(self, bus: EventBus) -> None:
        """No lifespan (com o loop a correr): refaz o estado, subscreve e arranca o worker."""
        self._bus, self._db = bus, bus.db
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        bus.db.run_sync(self.restore)
        bus.subscribe(CONSUMER, self.handle, types=INPUT_TYPES)
        self._task = self._loop.create_task(self._worker(), name="automations:worker")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def idle(self) -> None:
        """Espera que a fila esvazie (testes e encerramento ordenado)."""
        assert self._queue is not None
        await self._queue.join()

    # --- metade síncrona ---------------------------------------------------------------------

    def handle(self, conn: sqlite3.Connection, stored: StoredEvent):
        event = stored.event
        with self._lock:
            if event.id not in self._decided:
                found = repo.active_rules(conn, event.household_id, event.ts)
                rules = [ActiveRule(r, since) for r, since in found]
                self._decided[event.id] = self.engine.on_event(event, rules)
                while len(self._decided) > _SEEN_MAX:
                    self._decided.popitem(last=False)
                for f in self._decided[event.id]:
                    self._enqueue(f)
            return []

    def _enqueue(self, f: Firing) -> None:
        key = (f.rule_id, f.trigger_event_id, f.device_id)
        if key in self._queued or self._loop is None or self._queue is None:
            return
        self._queued.add(key)
        self._loop.call_soon_threadsafe(self._queue.put_nowait, f)

    def restore(self, conn: sqlite3.Connection) -> int:
        """Refaz o estado do registo de eventos. Os disparos que a repetição produz descartam-se:
        o que tinha de ser executado já foi (ou perdeu-se; ver o docstring do módulo)."""
        done = {
            r[0]
            for r in conn.execute(
                "SELECT event_id FROM processed_event WHERE consumer = ?", (CONSUMER,)
            )
        }
        rules: dict[UUID, list[ActiveRule]] = {}
        devices: dict[UUID, list[UUID]] = {}
        n = 0
        for s in self._history(conn):
            ev = s.event
            if isinstance(ev, de.AutomationExecuted):
                if ev.data.result.status is ExecutionStatus.uncertain:
                    if ev.data.rule_id not in devices:
                        devices[ev.data.rule_id] = self._devices_of(conn, ev.data.rule_id)
                    for d in devices[ev.data.rule_id]:
                        self.engine.record_result(d, ev.data.result.status, ev.ts)
            elif str(ev.id) in done:
                if ev.household_id not in rules:
                    rules[ev.household_id] = [
                        ActiveRule(r, since)
                        for r, since in repo.active_rules(conn, ev.household_id, ev.ts)
                    ]
                self.engine.on_event(ev, rules[ev.household_id])
                n += 1
        return n

    def _history(self, conn: sqlite3.Connection) -> list[StoredEvent]:
        """Só o necessário para refazer o estado, pela ordem do registo: a presença toda (uma
        linha por mudança) e leituras, fechos e resultados da janela recente. A janela cobre a
        duração máxima de um gatilho (24 h), o intervalo máximo entre leituras, o bloqueio e o
        cooldown da regra, com margem; um episódio mais antigo já não pode voltar a disparar."""
        recent = (*(t for t in INPUT_TYPES if t != PRESENCE), EXECUTED)
        marks = ",".join("?" * len(recent))
        top = conn.execute(
            f"SELECT max(ts) FROM domain_event WHERE type IN ({marks})", recent
        ).fetchone()[0]
        if top is None:
            return load_events(conn, types=(PRESENCE,))
        window = (
            timedelta(seconds=MAX_DURATION_S)
            + MAX_READING_GAP
            + timedelta(seconds=self.engine.lockout_s + self.engine.rule_cooldown_s)
            + timedelta(minutes=10)
        )
        cutoff = (datetime.fromisoformat(top) - window).isoformat()
        first = conn.execute(
            f"SELECT min(seq) FROM domain_event WHERE type IN ({marks}) AND ts >= ?",
            (*recent, cutoff),
        ).fetchone()[0]
        found = load_events(conn, types=(PRESENCE,))
        if first is not None:
            found += load_events(conn, since_seq=first - 1, types=recent)
        return sorted(found, key=lambda s: s.seq)

    @staticmethod
    def _devices_of(conn: sqlite3.Connection, rule_id: UUID) -> list[UUID]:
        row = conn.execute(
            "SELECT json FROM automation_rule WHERE id = ?", (str(rule_id),)
        ).fetchone()
        if row is None:
            return []
        rule = AutomationRule.model_validate_json(row["json"])
        return [a.target_device_id for a in rule.actions]

    # --- metade assíncrona -------------------------------------------------------------------

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            f = await self._queue.get()
            try:
                await self._execute(f)
            except Exception as e:  # noqa: BLE001 - o worker não pode morrer; só o tipo vai ao log
                log.warning("automations: falha a executar (%s)", type(e).__name__)
            finally:
                # a deduplicação durável é o `automation.executed` (`_load`); isto só evita
                # que o conjunto cresça para sempre
                self._queued.discard((f.rule_id, f.trigger_event_id, f.device_id))
                self._queue.task_done()

    def _load(self, conn: sqlite3.Connection, f: Firing):
        """A regra tal como está AGORA, só se continua ativa e aprovada; e se este disparo ainda
        não foi registado. Devolve (regra, origem, tipo da casa) ou `None`."""
        done = conn.execute(
            "SELECT 1 FROM domain_event WHERE id = ?", (str(self._event_id(f)),)
        ).fetchone()
        row = repo.get_row(conn, f.household_id, f.rule_id)
        house = conn.execute(
            "SELECT source_kind FROM household WHERE id = ?", (str(f.household_id),)
        ).fetchone()
        if (
            done is not None
            or row is None
            or house is None
            or row["status"] != "active"
            or row["vote_open"]
            or row["approved_by_resident_id"] is None
            or (
                row["scope"] == "personal"  # o dono que saiu da casa já não tem regras a correr
                and UUID(row["owner_resident_id"])
                not in repo.active_tenants(conn, f.household_id, self.clock())
            )
        ):
            return None
        return repo.rule_of(row), Origin(row["origin"]), house["source_kind"]

    @staticmethod
    def _event_id(f: Firing) -> UUID:
        return stable_id(
            "automation.executed", str(f.rule_id), str(f.trigger_event_id), str(f.device_id)
        )

    async def _execute(self, f: Firing) -> None:
        assert self._db is not None and self._bus is not None
        loaded = await self._db.run(lambda c: self._load(c, f))
        if loaded is None:
            log.info("automations: disparo descartado (regra já não ativa ou já registado)")
            return
        rule, origin, source_kind = loaded
        assert rule.approved_by_resident_id is not None  # `active` exige aprovação
        now = self.clock()
        action = ProposedAction(
            id=stable_id(
                "automation.action", str(f.rule_id), str(f.trigger_event_id), str(f.device_id)
            ),
            household_id=f.household_id,
            proposed_for_resident_id=rule.approved_by_resident_id,
            command=DeviceCommand(
                target_device_id=f.device_id, capability=DeviceCapability.power, power=False
            ),
            rationale=f"Regra «{rule.name}» aprovada por votação dos moradores"[:300],
            status=ActionStatus.confirmed,  # a votação é a confirmação humana
            proposed_at=now,
            expires_at=now + timedelta(seconds=self.action_ttl_s),
        )
        blocked_code = f.blocked_code
        with self._lock:  # o bloqueio pode ter nascido depois de este disparo ser decidido
            if blocked_code is None and self.engine.is_locked(f.device_id, f.at):
                blocked_code = UNCERTAIN_LOCKOUT
        if blocked_code is not None:  # nada é tentado
            result = ActionExecutionResult(
                action_id=action.id, status=ExecutionStatus.blocked, executed_at=now,
                code=blocked_code,
            )  # fmt: skip
        else:
            confirmation = ActionConfirmation(
                action_id=action.id, resident_id=rule.approved_by_resident_id, accepted=True, at=now
            )
            executor = select_executor(self.state, f.household_id, source_kind, self.clock)
            result = await run_execution(
                executor, action, confirmation, timeout_s=self.timeout_s, clock=self.clock
            )
        with self._lock:
            self.engine.record_result(f.device_id, result.status, f.at)
        event = de.AutomationExecuted(
            id=self._event_id(f),
            ts=f.at,
            household_id=f.household_id,
            correlation_id=rule.id,
            provenance=Provenance(origin=origin, kind=ValueKind.measured),
            data=de.AutomationExecutedData(rule_id=rule.id, result=result),
        )
        await self._bus.publish(event)
        log.info(
            "automations: regra executada (%s%s)", result.status.value,
            f"/{result.code}" if result.code else "",
        )  # fmt: skip
