"""Barramento de eventos persistente, dentro do processo FastAPI.

Semântica efetiva: **entrega pelo menos uma vez com efeitos idempotentes** (nunca «exactly
once» de ponta a ponta).

- `domain_event` é a fila e o registo imutável; um evento só existe depois do COMMIT.
- Cada consumidor tem um *loop* que lê da base os eventos que ainda não processou (`seq`
  crescente). Reiniciar não precisa de código de recuperação: o que ficou por entregar
  continua em falta na consulta.
- O handler corre SÍNCRONO dentro de `BEGIN IMMEDIATE`, na mesma transação que grava
  `processed_event(consumer, event_id)`. Se levantar, tudo faz ROLLBACK (efeito e registo):
  não há «efeito feito mas não registado» nem o inverso. Eventos que o handler devolve são
  gravados na mesma transação (padrão *outbox*) e só entregues depois do COMMIT.
- Falhas: tentativas limitadas (`event_failure`); ao esgotá-las o evento fica `dead` para esse
  consumidor e deixa de o bloquear. Um consumidor nunca afeta os outros.
- Ordem: `seq` global; cada consumidor vê os seus eventos por `seq`, mas um evento em *retry*
  pode ser ultrapassado por outros. Os handlers têm de tolerar chegadas fora de ordem.
- Um consumidor novo (nome nunca visto) processa TODO o histórico do seu `types`, a partir de
  `since_seq` (omissão 0).
"""

import asyncio
import json
import logging
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from homemind.contracts.domain_events import (
    EVENT_TYPES,
    DomainEvent,
    StoredEvent,
    domain_event_adapter,
)
from homemind.core.db import Database, DatabaseClosedError

log = logging.getLogger(__name__)

# (conn, evento) -> eventos de seguimento a gravar na mesma transação. Síncrono e rápido:
# corre numa thread com o lock da base de dados; sem I/O externo.
Handler = Callable[[sqlite3.Connection, StoredEvent], Iterable[DomainEvent] | None]


class EventStoreError(ValueError):
    pass


class EventConflictError(EventStoreError):
    """Mesmo `id` com conteúdo diferente."""


class UnknownHouseholdError(EventStoreError):
    pass


class SimulatedEventInRealHouseholdError(EventStoreError):
    """Eventos simulados nunca entram numa casa `real` (replay só em base isolada/demo)."""


# --- persistência de eventos ---------------------------------------------------------------------


def _from_row(row: sqlite3.Row) -> StoredEvent:
    return StoredEvent(
        seq=row["seq"],
        event=domain_event_adapter.validate_python(
            {
                "id": row["id"],
                "type": row["type"],
                "schema_version": row["schema_version"],
                "ts": row["ts"],
                "household_id": row["household_id"],
                "correlation_id": row["correlation_id"],
                "provenance": {"origin": row["origin"], "kind": row["kind"]},
                "data": json.loads(row["payload_json"]),
            }
        ),
    )


def append_event(conn: sqlite3.Connection, event: DomainEvent) -> StoredEvent:
    """Grava o evento (atribui `seq`). Idempotente por `id`: repetir o mesmo evento devolve o
    já gravado; o mesmo `id` com outro conteúdo é erro. Chamar dentro de uma transação."""
    if event.type not in EVENT_TYPES:
        raise EventStoreError("tipo de evento desconhecido")
    house = conn.execute(
        "SELECT source_kind FROM household WHERE id = ?", (str(event.household_id),)
    ).fetchone()
    if house is None:
        raise UnknownHouseholdError("casa desconhecida")
    if event.provenance.simulated and house["source_kind"] == "real":
        raise SimulatedEventInRealHouseholdError("evento simulado numa casa real")
    existing = conn.execute("SELECT * FROM domain_event WHERE id = ?", (str(event.id),)).fetchone()
    if existing is not None:
        stored = _from_row(existing)
        if stored.event != event:
            raise EventConflictError("o id do evento já existe com outro conteúdo")
        return stored
    cur = conn.execute(
        "INSERT INTO domain_event (id, type, schema_version, ts, household_id, correlation_id,"
        " origin, kind, payload_json, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(event.id),
            event.type,
            event.schema_version,
            event.ts.isoformat(),
            str(event.household_id),
            str(event.correlation_id),
            event.provenance.origin.value,
            event.provenance.kind.value,
            event.data.model_dump_json(),
            datetime.now(UTC).isoformat(),
        ),
    )
    return StoredEvent(seq=cur.lastrowid, event=event)


def load_events(
    conn: sqlite3.Connection,
    since_seq: int = 0,
    types: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[StoredEvent]:
    sql, args = "SELECT * FROM domain_event WHERE seq > ?", [since_seq]
    if types is not None:
        wanted = list(types)
        sql += f" AND type IN ({','.join('?' * len(wanted))})"
        args += wanted
    sql += " ORDER BY seq" + (" LIMIT ?" if limit else "")
    if limit:
        args.append(limit)
    return [_from_row(r) for r in conn.execute(sql, args)]


# --- barramento -----------------------------------------------------------------------------------


@dataclass
class _Subscription:
    consumer: str
    handler: Handler
    types: tuple[str, ...] | None
    since_seq: int
    wake: asyncio.Event = field(default_factory=asyncio.Event)


class EventBus:
    def __init__(
        self,
        db: Database,
        *,
        max_attempts: int = 5,
        retry_delay_s: float = 0.5,
        batch_size: int = 100,
    ) -> None:
        self.db = db
        self.max_attempts = max_attempts
        self.retry_delay_s = retry_delay_s
        self.batch_size = batch_size
        self._subs: dict[str, _Subscription] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    # registo ----------------------------------------------------------------------------------

    def subscribe(
        self,
        consumer: str,
        handler: Handler,
        types: Iterable[str] | None = None,
        since_seq: int = 0,
    ) -> None:
        """No lifespan do módulo (depois de o core arrancar) ou antes de `start()`. `consumer`
        identifica o consumidor para sempre (é a chave de idempotência): renomeá-lo faz-lhe
        reprocessar o histórico."""
        if consumer in self._subs:
            raise ValueError(f"consumidor repetido: {consumer}")
        wanted = tuple(types) if types is not None else None
        if wanted is not None and (unknown := set(wanted) - set(EVENT_TYPES)):
            raise ValueError(f"tipos de evento desconhecidos: {sorted(unknown)}")
        sub = self._subs[consumer] = _Subscription(consumer, handler, wanted, since_seq)
        if self._loop is not None:  # barramento já a correr: arranca já (loop thread)
            self._launch(sub)

    def _launch(self, sub: _Subscription) -> None:
        self._tasks.append(asyncio.create_task(self._run(sub), name=f"bus:{sub.consumer}"))
        sub.wake.set()  # recuperação: o que ficou por entregar antes do arranque

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        for sub in self._subs.values():
            self._launch(sub)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._loop = None

    # publicação -------------------------------------------------------------------------------

    async def publish(self, event: DomainEvent) -> StoredEvent:
        stored = await self.db.run(lambda c: append_event(c, event))
        self._wake()
        return stored

    def publish_threadsafe(self, event: DomainEvent) -> StoredEvent:
        """Para produtores fora do event loop (ex.: a thread de visão)."""
        stored = self.db.run_sync(lambda c: append_event(c, event))
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._wake_local)
            except RuntimeError:  # loop já fechado (shutdown): o evento está gravado
                pass
        return stored

    def _wake(self) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._wake_local)
        except RuntimeError:  # loop já fechado; o evento persiste e será lido no próximo arranque
            pass

    def _wake_local(self) -> None:
        """Acorda os consumidores no loop dono do barramento."""
        for sub in self._subs.values():
            sub.wake.set()

    # entrega ----------------------------------------------------------------------------------

    async def deliver(self, consumer: str, stored: StoredEvent) -> bool:
        """Entrega um evento a um consumidor numa transação. `False` se já estava processado
        (efeito não repetido). Levanta se o handler falhar (nada fica gravado)."""
        sub = self._subs[consumer]

        def process(conn: sqlite3.Connection) -> bool:
            try:
                conn.execute(
                    "INSERT INTO processed_event (consumer, event_id, processed_at) VALUES (?,?,?)",
                    (consumer, str(stored.event.id), datetime.now(UTC).isoformat()),
                )
            except sqlite3.IntegrityError:
                return False
            for follow_up in sub.handler(conn, stored) or ():
                append_event(conn, follow_up)
            return True

        ran = await self.db.run(process)
        if ran:
            self._wake()  # eventos de seguimento já estão gravados
        return ran

    def _pending(self, conn: sqlite3.Connection, sub: _Subscription) -> list[sqlite3.Row]:
        # Linhas em bruto: uma que já não valida (contrato apertado, base de dev antiga) tem de
        # falhar POR EVENTO, dentro do `try` do consumidor, e não matar o consumidor.
        # shortcut: relê tudo o que falta desde `since_seq` a cada acordar (NOT EXISTS indexado
        # pela PK de processed_event); trocar por um *high-water mark* por consumidor quando
        # o histórico passar de ~100 mil eventos.
        sql = (
            "SELECT d.* FROM domain_event d WHERE d.seq > ? "
            "AND NOT EXISTS (SELECT 1 FROM processed_event p"
            " WHERE p.consumer = ? AND p.event_id = d.id) "
            "AND NOT EXISTS (SELECT 1 FROM event_failure f"
            " WHERE f.consumer = ? AND f.event_id = d.id AND f.dead = 1)"
        )
        args: list[object] = [sub.since_seq, sub.consumer, sub.consumer]
        if sub.types is not None:
            sql += f" AND d.type IN ({','.join('?' * len(sub.types))})"
            args += sub.types
        return conn.execute(sql + " ORDER BY d.seq LIMIT ?", [*args, self.batch_size]).fetchall()

    def _record_failure(
        self, conn: sqlite3.Connection, consumer: str, event_id: str, err: str
    ) -> int:
        conn.execute(
            "INSERT INTO event_failure"
            " (consumer, event_id, attempts, last_error_type, dead, updated_at)"
            " VALUES (?,?,1,?,?,?) ON CONFLICT (consumer, event_id) DO UPDATE SET"
            " attempts = attempts + 1, last_error_type = excluded.last_error_type,"
            " dead = (attempts + 1 >= ?), updated_at = excluded.updated_at",
            (
                consumer,
                event_id,
                err,
                int(self.max_attempts <= 1),
                datetime.now(UTC).isoformat(),
                self.max_attempts,
            ),
        )
        return conn.execute(
            "SELECT attempts FROM event_failure WHERE consumer = ? AND event_id = ?",
            (consumer, event_id),
        ).fetchone()[0]

    async def _run(self, sub: _Subscription) -> None:
        """Um consumidor nunca morre por uma falha de leitura ou de um evento: regista, espera
        e continua. Só termina ao ser cancelado (shutdown) ou com a base de dados fechada."""
        loop = asyncio.get_running_loop()
        not_before: dict[str, float] = {}  # evento -> instante (loop.time) do próximo retry
        while True:
            try:
                await self._drain_once(sub, loop, not_before)
            except DatabaseClosedError:
                return
            except Exception as e:  # noqa: BLE001 - o consumidor não pode morrer em silêncio
                log.error("consumidor %s: erro no ciclo (%s)", sub.consumer, type(e).__name__)
                await asyncio.sleep(self.retry_delay_s)

    async def _drain_once(
        self, sub: _Subscription, loop: asyncio.AbstractEventLoop, not_before: dict[str, float]
    ) -> None:
        sub.wake.clear()  # antes de ler: um publish durante o processamento volta a acordar
        batch = await self.db.run(lambda c: self._pending(c, sub))
        now = loop.time()
        progressed = False
        for row in batch:
            eid = row["id"]
            if not_before.get(eid, 0.0) > now:
                continue
            try:
                await self.deliver(sub.consumer, _from_row(row))  # validar também é por evento
                not_before.pop(eid, None)
                progressed = True
            except Exception as e:  # noqa: BLE001 - isolar o handler; só o tipo vai para o log
                attempts = await self.db.run(
                    lambda c, eid=eid, e=e: self._record_failure(
                        c, sub.consumer, eid, type(e).__name__
                    )
                )
                log.warning(
                    "consumidor %s falhou em %s seq=%d (%s) tentativa %d/%d%s",
                    sub.consumer, row["type"], row["seq"], type(e).__name__,
                    attempts, self.max_attempts,
                    " — desistiu" if attempts >= self.max_attempts else "",
                )  # fmt: skip
                not_before[eid] = loop.time() + self.retry_delay_s * attempts
        if progressed or len(batch) >= self.batch_size:
            return  # pode haver mais: volta já a ler
        timeout = None
        if not_before:
            timeout = max(0.0, min(not_before.values()) - loop.time())
        try:
            await asyncio.wait_for(sub.wake.wait(), timeout)
        except TimeoutError:
            pass


async def replay(events: Iterable[StoredEvent], bus: EventBus) -> list[StoredEvent]:
    """Republica eventos (por `seq`) noutro barramento, **numa base isolada** (demo/testes).
    Os ids mantêm-se: se já existirem com o mesmo conteúdo, nada é duplicado. Eventos
    simulados nunca entram numa casa `real` (ver `append_event`)."""
    return [await bus.publish(s.event) for s in sorted(events, key=lambda s: s.seq)]
