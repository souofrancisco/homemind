"""Expurgo de retenção (PRIV-04): apaga só o que a política marca como apagável e já expirou.

- Eventos: só os tipos `telemetry` (a base de dados recusa qualquer outro), com `ts` anterior a
  `now - days`. Um evento que um consumidor ainda está a tentar processar (falha não morta) não
  se apaga. As marcas `processed_event`/`event_failure` desses eventos saem com eles.
- Agregados diários dos alertas: dias anteriores ao corte.
- Em lotes de `BATCH`, cada um na sua transação: nunca bloqueia o barramento muito tempo.
Determinístico: o «agora» vem de fora (relógio injetado).
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from homemind.features.retention.policy import DAILY_AGGREGATE_TABLES, PURGEABLE_EVENT_TYPES

BATCH = 5_000


@dataclass(frozen=True)
class Purged:
    events: int = 0
    aggregates: int = 0


def cutoff(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


def purge_events(conn: sqlite3.Connection, before: datetime, limit: int = BATCH) -> int:
    """Um lote de telemetria expirada; devolve quantos eventos apagou."""
    marks = ",".join("?" * len(PURGEABLE_EVENT_TYPES))
    ids = [
        (r["id"],)
        for r in conn.execute(
            f"SELECT d.id FROM domain_event d WHERE d.type IN ({marks})"
            " AND julianday(d.ts) < julianday(?)"
            " AND NOT EXISTS (SELECT 1 FROM event_failure f"
            " WHERE f.event_id = d.id AND f.dead = 0)"
            " ORDER BY d.seq LIMIT ?",
            (*PURGEABLE_EVENT_TYPES, before.isoformat(), limit),
        )
    ]
    if ids:
        conn.executemany("DELETE FROM processed_event WHERE event_id = ?", ids)
        conn.executemany("DELETE FROM event_failure WHERE event_id = ?", ids)
        conn.executemany("DELETE FROM domain_event WHERE id = ?", ids)
    return len(ids)


def purge_aggregates(conn: sqlite3.Connection, before: datetime) -> int:
    day = before.date().isoformat()
    removed = 0
    for table, column in DAILY_AGGREGATE_TABLES:
        removed += conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (day,)).rowcount
    return removed


def purge(run, now: datetime, days: int) -> Purged:
    """Expurgo completo, lote a lote. `run(fn)` executa `fn(conn)` numa transação.
    `days == 0`: retenção desligada, nada se apaga."""
    if days <= 0:
        return Purged()
    before = cutoff(now, days)
    events = 0
    while True:
        n = run(lambda conn: purge_events(conn, before))
        events += n
        if n < BATCH:
            break
    return Purged(events=events, aggregates=run(lambda conn: purge_aggregates(conn, before)))
