"""Retenção, compactação e eliminação dos dados de presença (PRIV-03 #51). Funções síncronas
sobre `run(fn)` (= `Database.run_sync`); o relógio vem de fora. Prazos: PROPOSTA (P-08).

Inventário (o que existe e quanto tempo fica):
- `domain_event` `presence.cue_recorded|door_crossed|changed|occupancy_changed|
  confirmation_needed`: brutos até `PRESENCE_RETENTION_DAYS` (omissão 30, PROPOSTA); depois
  passam a agregados diários e apagam-se.
- `presence_confirmation`: apagada com os brutos (o pedido expira em 30 min; só serve a
  idempotência da resposta).
- `presence_state`, `presence_device`: dados em vigor; apagam-se quando o morador revoga o
  `presence_opt_in` ou deixa a casa (ver `erase_unconsented`).
- `presence_daily` (por morador e dia) e `presence_door_daily` (por casa e dia): agregados SEM
  horários nem MAC. Os do morador apagam-se com a revogação; os da porta são anónimos.
- `presence_retention_log`: auditoria (só contagens, motivo e ids internos).

Garantias: só se apagam tipos `presence.*` (o trigger da base recusa o resto, migração 0201);
cada dia compacta-se numa única transação (agregados + remoção das marcas `processed_event`/
`event_failure` + eventos), por isso uma falha a meio não deixa nem perda nem contagem a dobrar.
Nunca se apaga o que a fusão (48 h) ou a ocupação (24 h) leem: só dias locais inteiros anteriores
a `agora - N`, com N ≥ 2 dias. Um evento que um consumidor ainda tenta processar não se apaga.
Reexecutar é inofensivo. Usar os agregados para estatística ou calibração é finalidade nova
(P-23): PLANEADO, não implementado.
"""

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.features.presence import repo

MIN_DAYS = 2  # nunca abaixo das janelas de leitura (fusão 48 h, ocupação 24 h)
PRESENCE_EVENT_TYPES = (
    "presence.cue_recorded",
    "presence.door_crossed",
    "presence.changed",
    "presence.occupancy_changed",
    "presence.confirmation_needed",
)
# Eventos cujo payload tem `resident_id` (dados pessoais do morador).
PERSONAL_EVENT_TYPES = (
    "presence.cue_recorded",
    "presence.changed",
    "presence.confirmation_needed",
)
_STATES = ("in", "out", "uncertain")
_TYPES_SQL = ",".join(f"'{t}'" for t in PRESENCE_EVENT_TYPES)
_PERSONAL_SQL = ",".join(f"'{t}'" for t in PERSONAL_EVENT_TYPES)
_LIVE_FAILURE = "NOT EXISTS (SELECT 1 FROM event_failure f WHERE f.event_id = d.id AND f.dead = 0)"


@dataclass
class Compacted:
    days: int = 0
    events: int = 0
    confirmations: int = 0
    aggregates: int = 0

    def __bool__(self) -> bool:
        return bool(self.events or self.confirmations or self.aggregates)


@dataclass
class Erased:
    residents: int = 0
    events: int = 0
    rows: int = 0


def _bounds(day, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


def _delete_events(conn: sqlite3.Connection, ids: list[str]) -> None:
    rows = [(i,) for i in ids]
    conn.executemany("DELETE FROM processed_event WHERE event_id = ?", rows)
    conn.executemany("DELETE FROM event_failure WHERE event_id = ?", rows)
    conn.executemany("DELETE FROM domain_event WHERE id = ?", rows)


def _log(conn, now, action, hid, rid, reason, counts: dict) -> None:
    conn.execute(
        "INSERT INTO presence_retention_log (at, action, household_id, resident_id, reason,"
        " counts_json) VALUES (?,?,?,?,?,?)",
        (now.isoformat(), action, hid, rid, reason, json.dumps(counts, sort_keys=True)),
    )


# --- compactação -----------------------------------------------------------------------------


def _next_day(conn, hid: str, tz: ZoneInfo, limit_day):
    """Próximo dia local a compactar (< `limit_day`), ou None. Continua a partir do último
    agregado: os dias sem eventos também contam horas (o estado mantém-se)."""
    first = conn.execute(
        "SELECT MIN(d.ts) FROM domain_event d WHERE d.household_id = ?"
        f" AND d.type IN ({_TYPES_SQL})"
        f" AND {_LIVE_FAILURE}",
        (hid,),
    ).fetchone()[0]
    last_row = conn.execute(
        "SELECT MAX(day) FROM presence_daily WHERE household_id = ?", (hid,)
    ).fetchone()[0]
    candidates = []
    if first:
        candidates.append(datetime.fromisoformat(first).astimezone(tz).date())
    if last_row:
        candidates.append(datetime.fromisoformat(last_row).date() + timedelta(days=1))
    if not candidates:
        return None
    day = min(candidates)
    return day if day < limit_day else None


def _carry(conn, hid: str, day_iso: str) -> dict[str, str]:
    """Estado em que cada morador acabou o último dia já agregado antes de `day_iso`."""
    rows = conn.execute(
        "SELECT p.resident_id, p.end_state FROM presence_daily p WHERE p.household_id = ?"
        " AND p.day = (SELECT MAX(q.day) FROM presence_daily q"
        " WHERE q.household_id = p.household_id"
        " AND q.resident_id = p.resident_id AND q.day < ?)",
        (hid, day_iso),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


@dataclass
class _Person:
    state: str
    t: datetime
    seconds: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_STATES, 0))
    cues: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    asks: int = 0

    def advance(self, to: datetime, state: str | None = None) -> None:
        self.seconds[self.state] += max(0, round((to - self.t).total_seconds()))
        self.t = max(self.t, to)
        if state is not None:
            self.state = state


def _compact_day(conn, hid: str, tz: ZoneInfo, day, now: datetime) -> tuple[int, int]:
    """Agrega e apaga os eventos de presença anteriores ao fim de `day`. Devolve (eventos,
    linhas de agregado)."""
    start, end = _bounds(day, tz)
    day_iso = day.isoformat()
    rows = conn.execute(
        f"SELECT d.seq, d.id, d.type, d.ts, d.payload_json FROM domain_event d"
        f" WHERE d.household_id = ? AND d.type IN ({_TYPES_SQL})"
        f" AND julianday(d.ts) < julianday(?) AND {_LIVE_FAILURE}",
        (hid, end.isoformat()),
    ).fetchall()
    events = sorted(
        (
            (
                datetime.fromisoformat(r["ts"]),
                r["seq"],
                r["id"],
                r["type"],
                json.loads(r["payload_json"]),
            )
            for r in rows
        ),
        key=lambda e: (e[0], e[1]),
    )
    consent: dict[str, bool] = {}

    def consenting(rid: str) -> bool:
        if rid not in consent:
            consent[rid] = repo.has_presence_opt_in(conn, UUID(hid), UUID(rid), now)
        return consent[rid]

    people: dict[str, _Person] = {
        rid: _Person(state=state, t=start)
        for rid, state in _carry(conn, hid, day_iso).items()
        if consenting(rid)
    }
    entered = left = 0
    for ts, _seq, _id, kind, data in events:
        if kind == "presence.door_crossed":
            if data.get("direction") == "in":
                entered += 1
            elif data.get("direction") == "out":
                left += 1
            continue
        rid = data.get("resident_id")
        if rid is None or not consenting(rid):
            continue  # ocupação (anónima, sem agregado) ou morador sem opt-in: só se apaga
        # Um morador novo começa «incerto» (sem estado conhecido) no início do dia.
        person = people.setdefault(rid, _Person(state="uncertain", t=start))
        if kind == "presence.changed":
            person.advance(max(ts, start), data["state"])
        elif kind == "presence.cue_recorded":
            person.cues[data["source"]] += 1
        elif kind == "presence.confirmation_needed":
            person.asks += 1
    written = 0
    for rid, p in sorted(people.items()):
        p.advance(end)
        conn.execute(
            "INSERT INTO presence_daily (household_id, resident_id, day, seconds_in, seconds_out,"
            " seconds_uncertain, end_state, cues_wifi, cues_manual, cues_appliance,"
            " confirmation_requests) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (household_id, resident_id, day) DO UPDATE SET"
            " cues_wifi = cues_wifi + excluded.cues_wifi,"
            " cues_manual = cues_manual + excluded.cues_manual,"
            " cues_appliance = cues_appliance + excluded.cues_appliance,"
            " confirmation_requests = confirmation_requests + excluded.confirmation_requests",
            (
                hid, rid, day_iso, p.seconds["in"], p.seconds["out"], p.seconds["uncertain"],
                p.state, p.cues["wifi"], p.cues["manual"], p.cues["appliance"], p.asks,
            ),
        )  # fmt: skip
        written += 1
    if entered or left:
        conn.execute(
            "INSERT INTO presence_door_daily (household_id, day, entered, left) VALUES (?,?,?,?)"
            " ON CONFLICT (household_id, day) DO UPDATE SET"
            " entered = entered + excluded.entered, left = left + excluded.left",
            (hid, day_iso, entered, left),
        )
        written += 1
    _delete_events(conn, [e[2] for e in events])
    return len(events), written


def compact(run, now: datetime, days: int) -> Compacted:
    """Passa a agregados diários, dia local a dia local (uma transação por dia), os eventos
    brutos de presença de dias inteiros anteriores a `now - days`. `days == 0`: desligado."""
    if days <= 0:
        return Compacted()
    days = max(days, MIN_DAYS)
    out = Compacted()
    houses = run(
        lambda c: c.execute(
            f"SELECT h.id, h.timezone FROM household h WHERE EXISTS (SELECT 1 FROM domain_event d"
            f" WHERE d.household_id = h.id AND d.type IN ({_TYPES_SQL}))"
            " OR EXISTS (SELECT 1 FROM presence_daily p WHERE p.household_id = h.id)"
            " OR EXISTS (SELECT 1 FROM presence_confirmation x WHERE x.household_id = h.id)"
            " ORDER BY h.id"
        ).fetchall()
    )
    for house in houses:
        hid, tz = house["id"], ZoneInfo(house["timezone"])
        limit_day = (now - timedelta(days=days)).astimezone(tz).date()
        n_events = n_rows = n_days = 0
        while True:
            day = run(lambda c, hid=hid, tz=tz, ld=limit_day: _next_day(c, hid, tz, ld))
            if day is None:
                break
            ev, rows = run(lambda c, hid=hid, tz=tz, day=day: _compact_day(c, hid, tz, day, now))
            if ev == 0 and rows == 0:
                break  # nada a agregar (ninguém com opt-in a continuar): não andar em círculos
            n_events, n_rows, n_days = n_events + ev, n_rows + rows, n_days + 1
        limit_start = _bounds(limit_day, tz)[0]
        n_conf = run(
            lambda c, hid=hid, ls=limit_start: c.execute(
                "DELETE FROM presence_confirmation WHERE household_id = ?"
                " AND julianday(created_at) < julianday(?)",
                (hid, ls.isoformat()),
            ).rowcount
        )
        if n_events or n_conf:
            run(
                lambda c, hid=hid, n=(n_days, n_events, n_rows, n_conf): _log(
                    c, now, "compact", hid, None, None,
                    {"days": n[0], "events": n[1], "aggregate_rows": n[2], "confirmations": n[3]},
                )
            )  # fmt: skip
        out.days += n_days
        out.events += n_events
        out.aggregates += n_rows
        out.confirmations += n_conf
    return out


# --- eliminação ao revogar ou sair da casa ----------------------------------------------------


def _people_with_data(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for table in ("presence_state", "presence_device", "presence_confirmation", "presence_daily"):
        pairs.update(
            (r[0], r[1]) for r in conn.execute(f"SELECT household_id, resident_id FROM {table}")
        )  # noqa: S608
    pairs.update(  # fontes ainda ligadas (mesmo sem outros dados): têm de se desligar com o opt-in
        (r[0], r[1])
        for r in conn.execute(
            "SELECT household_id, resident_id FROM presence_source_consent WHERE enabled = 1"
        )
    )
    pairs.update(
        (r[0], r[1])
        for r in conn.execute(
            f"SELECT DISTINCT household_id, json_extract(payload_json, '$.resident_id')"
            f" FROM domain_event WHERE type IN ({_PERSONAL_SQL})"
        )
        if r[1]
    )
    return pairs


def erase_resident(
    conn: sqlite3.Connection, hid: str, rid: str, reason: str, now: datetime
) -> tuple[int, int]:
    """Apaga TODOS os dados de presença deste morador nesta casa, numa transação: pistas,
    mudanças de estado e pedidos (eventos `presence.*` do próprio), estado, telemóveis, pedidos
    de confirmação e agregados diários. Não toca em nada financeiro nem em dados de outros.
    Devolve (eventos, linhas)."""
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT d.id FROM domain_event d WHERE d.household_id = ?"
            f" AND d.type IN ({_PERSONAL_SQL})"
            " AND json_extract(d.payload_json, '$.resident_id') = ?",
            (hid, rid),
        )
    ]
    _delete_events(conn, ids)
    rows = 0
    for table in ("presence_state", "presence_device", "presence_confirmation", "presence_daily"):
        rows += conn.execute(  # noqa: S608 - nomes do esquema
            f"DELETE FROM {table} WHERE household_id = ? AND resident_id = ?", (hid, rid)
        ).rowcount
    from homemind.contracts.presence import ConsentReason
    from homemind.features.presence import consent  # local: consent importa este módulo

    # as fontes ficam desligadas (um novo opt-in não as reativa em silêncio) e fica registado
    consent.revoke_all_flags(conn, UUID(hid), UUID(rid), now, ConsentReason(reason))
    _log(conn, now, "erase", hid, rid, reason, {"events": len(ids), "rows": rows})
    return len(ids), rows


def _reason(conn: sqlite3.Connection, hid: str, rid: str) -> str:
    revoked = conn.execute(
        "SELECT 1 FROM membership WHERE household_id = ? AND resident_id = ? AND role = 'tenant'"
        " AND status = 'active' AND presence_opt_in = 0",
        (hid, rid),
    ).fetchone()
    return "opt_in_revoked" if revoked else "left_household"


def erase_unconsented(run, now: datetime) -> Erased:
    """Elimina os dados de quem já não tem opt-in em vigor (revogou, ou deixou a casa: membership
    terminada ou fora de datas). Cada morador numa transação; reconfirma lá dentro (uma
    reativação entretanto não perde dados). Idempotente."""
    out = Erased()
    pairs = sorted(run(_people_with_data))
    for hid, rid in pairs:

        def one(conn, hid=hid, rid=rid):
            if repo.has_presence_opt_in(conn, UUID(hid), UUID(rid), now):
                return None
            return erase_resident(conn, hid, rid, _reason(conn, hid, rid), now)

        done = run(one)
        if done is not None:
            out.residents += 1
            out.events += done[0]
            out.rows += done[1]
    return out
