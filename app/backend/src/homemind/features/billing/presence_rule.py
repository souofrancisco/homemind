"""Regra C da sala, «por quem estava em casa» (BILL-07), versão mínima e segura.

Um consumo de zona comum (ou sem localização) é atribuído a UM morador só quando a presença o
prova sem margem para dúvida durante TODO o consumo:
- esse morador esteve `em casa` e todos os outros inquilinos `fora`, cada estado com
  confiança ≥ `MIN_CONFIDENCE` e sem mudanças pelo meio;
- todos os inquilinos têm `presence_opt_in` em vigor (sem consentimento não há dados, e quem
  revogou não pode ficar com um «fora» antigo);
- a porta contou exatamente uma pessoa dentro e zero visitas durante todo o consumo.

Qualquer outra coisa (incerto, sem dados, visitas, contagem perdida, dois ou mais em casa,
ninguém em casa, consumo sem fim) → `None`: a conta comum, dividida por todos. «Quem estava
em casa» não é «quem usou» (v5.1 §20.4): nunca se cobra a um «suspeito» por inferência fraca.
Dividir só por um subconjunto de moradores (2 de 4 em casa) fica PLANEADO: exige um alvo
novo no contrato `Attribution`.

Billing guarda uma cópia mínima dos eventos públicos de presença (não importa a feature) e
apaga o que tem mais de `RETENTION`. Quem deixa de ter `presence_opt_in` em vigor (revogou ou saiu
da casa) perde a cópia na primeira mensagem de presença seguinte da casa (PRIV-03): a promessa «os
teus dados de presença são apagados» vale também aqui, sem esperar pelos 40 dias.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from homemind.contracts import domain_events as de
from homemind.contracts.presence import PresenceState

MIN_CONFIDENCE = 0.9
RETENTION = timedelta(days=40)


@dataclass(frozen=True)
class SoleOccupant:
    resident_id: UUID
    confidence: float  # a mais fraca das provas usadas
    simulated: bool


def _states(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, start: datetime, end: datetime
) -> list[sqlite3.Row] | None:
    """Estados em vigor em [start, end]: o último antes de `start` e os que mudaram pelo meio.
    `None` se não há estado nenhum no início."""
    h, r = str(household_id), str(resident_id)
    first = conn.execute(
        "SELECT * FROM billing_presence_state WHERE household_id = ? AND resident_id = ?"
        " AND since <= ? ORDER BY since DESC LIMIT 1",
        (h, r, start.isoformat()),
    ).fetchone()
    if first is None:
        return None
    later = conn.execute(
        "SELECT * FROM billing_presence_state WHERE household_id = ? AND resident_id = ?"
        " AND since > ? AND since <= ? ORDER BY since",
        (h, r, start.isoformat(), end.isoformat()),
    ).fetchall()
    return [first, *later]


def _occupancy(
    conn: sqlite3.Connection, household_id: UUID, start: datetime, end: datetime
) -> list[sqlite3.Row] | None:
    h = str(household_id)
    first = conn.execute(
        "SELECT * FROM billing_occupancy WHERE household_id = ? AND ts <= ?"
        " ORDER BY ts DESC LIMIT 1",
        (h, start.isoformat()),
    ).fetchone()
    if first is None:
        return None
    later = conn.execute(
        "SELECT * FROM billing_occupancy WHERE household_id = ? AND ts > ? AND ts <= ?"
        " ORDER BY ts",
        (h, start.isoformat(), end.isoformat()),
    ).fetchall()
    return [first, *later]


def _consented(conn: sqlite3.Connection, household_id: UUID, tenants: list[UUID]) -> bool:
    ok = conn.execute(
        "SELECT resident_id FROM membership WHERE household_id = ? AND role = 'tenant'"
        " AND status = 'active' AND presence_opt_in = 1",
        (str(household_id),),
    ).fetchall()
    return set(tenants) <= {UUID(r["resident_id"]) for r in ok}


def sole_occupant(
    conn: sqlite3.Connection,
    household_id: UUID,
    tenants: list[UUID],
    start: datetime,
    end: datetime | None,
) -> SoleOccupant | None:
    """O único morador em casa durante todo o consumo, se isso estiver provado; senão `None`."""
    if end is None or not tenants or not _consented(conn, household_id, tenants):
        return None
    home: list[UUID] = []
    weakest, simulated = 1.0, False
    for resident in tenants:
        rows = _states(conn, household_id, resident, start, end)
        if not rows or len({r["state"] for r in rows}) != 1:
            return None  # sem dados, ou mudou a meio do consumo
        if rows[0]["state"] == PresenceState.home.value:
            home.append(resident)
        elif rows[0]["state"] != PresenceState.away.value:
            return None  # incerto
        weakest = min([weakest, *(r["confidence"] for r in rows)])
        simulated = simulated or any(r["simulated"] for r in rows)
    if len(home) != 1 or weakest < MIN_CONFIDENCE:
        return None
    door = _occupancy(conn, household_id, start, end)
    if not door or any(r["people_inside"] != 1 or r["visitors"] != 0 for r in door):
        return None  # visitas, contagem perdida ou mais alguém dentro
    simulated = simulated or any(r["simulated"] for r in door)
    return SoleOccupant(home[0], round(weakest, 2), simulated)


# --- consumidor do barramento ------------------------------------------------------------------

# Nome PERMANENTE (chave de idempotência em `processed_event`).
CONSUMER = "billing.presence"
EVENT_TYPES = ("presence.changed", "presence.occupancy_changed")


def handle(conn: sqlite3.Connection, stored: de.StoredEvent) -> list[de.DomainEvent]:
    ev = stored.event
    h = str(ev.household_id)
    if isinstance(ev, de.PresenceChanged):
        p = ev.data
        conn.execute(
            "INSERT OR REPLACE INTO billing_presence_state (household_id, resident_id, since,"
            " state, confidence, simulated) VALUES (?,?,?,?,?,?)",
            (
                h,
                str(p.resident_id),
                p.since.isoformat(),
                p.state.value,
                p.confidence,
                int(p.provenance.simulated),
            ),
        )
        _prune(conn, "billing_presence_state", "since", h, ev.ts, "resident_id")
        _purge_unconsented(conn, h)
    elif isinstance(ev, de.PresenceOccupancyChanged):
        o = ev.data
        conn.execute(
            "INSERT OR REPLACE INTO billing_occupancy (household_id, ts, people_inside, visitors,"
            " simulated) VALUES (?,?,?,?,?)",
            (h, o.ts.isoformat(), o.people_inside, o.visitors, int(o.provenance.simulated)),
        )
        _prune(conn, "billing_occupancy", "ts", h, ev.ts)
        _purge_unconsented(conn, h)
    return []


def _purge_unconsented(conn: sqlite3.Connection, h: str) -> None:
    """Apaga os estados de quem já não tem `presence_opt_in` em vigor como inquilino ativo."""
    conn.execute(
        "DELETE FROM billing_presence_state WHERE household_id = ? AND resident_id NOT IN"
        " (SELECT resident_id FROM membership WHERE household_id = ? AND role = 'tenant'"
        " AND status = 'active' AND presence_opt_in = 1)",
        (h, h),
    )


def _prune(
    conn: sqlite3.Connection, table: str, col: str, h: str, now: datetime, by: str | None = None
) -> None:
    """Apaga o que tem mais de `RETENTION`, mantendo o último estado (ainda em vigor)."""
    group = f" AND t.{by} = {table}.{by}" if by else ""
    conn.execute(
        f"DELETE FROM {table} WHERE household_id = ? AND {col} < ?"
        f" AND EXISTS (SELECT 1 FROM {table} t WHERE t.household_id = {table}.household_id"
        f"{group} AND t.{col} > {table}.{col} AND t.{col} <= ?)",
        (h, (now - RETENTION).isoformat(), (now - RETENTION).isoformat()),
    )
