"""Gasto anormal nas zonas comuns (ALERT-03, 2.ª parte): o dia de hoje muito acima do habitual.

Complementa os picos (`peaks.py`): um pico é potência alta agora; uma anomalia é energia a mais
no dia, mesmo sem nenhum pico (ex.: um aparelho comum que ficou ligado toda a tarde).

Regra (determinística, sem relógio próprio; o «agora» é o instante da leitura):
- Só tomadas registadas numa **zona comum**. Quartos (privados), contadores gerais e tomadas sem
  divisão ficam de fora: um gasto diário de uma tomada que pode estar num quarto não se mostra
  à casa. Severidade `warning`, como os picos: o senhorio não recebe estes avisos (só vê
  totais mensais), só os moradores.
- Energia do dia = Σ potência × tempo entre leituras `ok` consecutivas (potência da anterior),
  só quando o intervalo é ≤ `peaks.MAX_GAP`; uma lacuna não é preenchida. Guarda-se também o
  tempo coberto por leituras, para distinguir «gastou pouco» de «não sabemos».
- Habitual = mediana dos dias com ≥ `MIN_COVERED` de leituras nos `WINDOW_DAYS` anteriores;
  com menos de `MIN_DAYS` dias assim não há habitual e não se avisa (não se inventa base).
- Avisa quando o gasto de hoje (até agora) ≥ `FACTOR` × habitual **e** excede o habitual em
  pelo menos `MIN_EXCESS_WH`; no máximo um aviso por tomada e dia (local, fuso da casa).

Ids de evento derivados de (tomada, dia): reentregas não duplicam.
"""

import sqlite3
import statistics
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts import domain_events as de
from homemind.contracts.common import stable_id
from homemind.contracts.energy import EnergyReading
from homemind.contracts.notification import NotificationSeverity
from homemind.features.billing.peaks import MAX_GAP

FACTOR = 2
MIN_EXCESS_WH = 1_000
WINDOW_DAYS = 7
MIN_DAYS = 3
MIN_COVERED = timedelta(hours=20)

# Nome PERMANENTE (chave de idempotência em `processed_event`).
CONSUMER = "billing.anomalies"
EVENT_TYPES = ("energy.reading_recorded",)


def _common_plug(conn: sqlite3.Connection, household_id: UUID, device_id: UUID):
    """(fuso da casa, zona comum) da tomada, ou `None` se não é uma tomada de zona comum."""
    row = conn.execute(
        "SELECT h.timezone, d.room_id, d.role, r.kind FROM device d"
        " JOIN household h ON h.id = d.household_id"
        " LEFT JOIN room r ON r.household_id = d.household_id AND r.id = d.room_id"
        " WHERE d.household_id = ? AND d.id = ?",
        (str(household_id), str(device_id)),
    ).fetchone()
    if row is None or row["role"] == "main_meter" or row["kind"] != "common":
        return None
    return ZoneInfo(row["timezone"]), UUID(row["room_id"])


def observe(
    conn: sqlite3.Connection, household_id: UUID, reading: EnergyReading
) -> list[de.DomainEvent]:
    """Soma a leitura ao dia da tomada; devolve o aviso de gasto anormal, se nasceu agora."""
    if not reading.usable:
        return []
    plug = _common_plug(conn, household_id, reading.device_id)
    if plug is None:
        return []
    tz, room_id = plug
    assert reading.power_w is not None  # `usable`
    at = reading.observed_at or reading.ts
    key = (str(household_id), str(reading.device_id))
    state = conn.execute(
        "SELECT last_ok_at, last_power_w, alerted_day FROM alerts_anomaly_state"
        " WHERE household_id = ? AND device_id = ?",
        key,
    ).fetchone()
    alerted = state["alerted_day"] if state else None
    if state is not None:
        last = datetime.fromisoformat(state["last_ok_at"])
        if at <= last:
            return []  # repetida ou fora de ordem
        if at - last <= MAX_GAP:
            seconds = (at - last).total_seconds()
            conn.execute(
                "INSERT INTO alerts_device_day (household_id, device_id, day, energy_wh,"
                " covered_s) VALUES (?,?,?,?,?) ON CONFLICT DO UPDATE SET"
                " energy_wh = energy_wh + excluded.energy_wh,"
                " covered_s = covered_s + excluded.covered_s",
                (
                    *key,
                    last.astimezone(tz).date().isoformat(),
                    state["last_power_w"] * seconds / 3600,
                    round(seconds),
                ),
            )

    today = at.astimezone(tz).date()
    events = (
        []
        if alerted == today.isoformat()
        else _evaluate(conn, household_id, room_id, reading, today)
    )
    if events:
        alerted = today.isoformat()
    conn.execute(
        "INSERT INTO alerts_anomaly_state (household_id, device_id, last_ok_at, last_power_w,"
        " alerted_day) VALUES (?,?,?,?,?) ON CONFLICT DO UPDATE SET"
        " last_ok_at = excluded.last_ok_at, last_power_w = excluded.last_power_w,"
        " alerted_day = excluded.alerted_day",
        (*key, at.isoformat(), reading.power_w, alerted),
    )
    return events


def baseline(conn: sqlite3.Connection, household_id: UUID, device_id: UUID, today: date):
    """Mediana dos dias anteriores bem cobertos (Wh), ou `None` se não há dias suficientes."""
    rows = conn.execute(
        "SELECT energy_wh FROM alerts_device_day WHERE household_id = ? AND device_id = ?"
        " AND day >= ? AND day < ? AND covered_s >= ?",
        (
            str(household_id),
            str(device_id),
            (today - timedelta(days=WINDOW_DAYS)).isoformat(),
            today.isoformat(),
            int(MIN_COVERED.total_seconds()),
        ),
    ).fetchall()
    if len(rows) < MIN_DAYS:
        return None
    return round(statistics.median(r["energy_wh"] for r in rows))


def _evaluate(
    conn: sqlite3.Connection,
    household_id: UUID,
    room_id: UUID,
    reading: EnergyReading,
    today: date,
) -> list[de.DomainEvent]:
    usual = baseline(conn, household_id, reading.device_id, today)
    if usual is None:
        return []
    row = conn.execute(
        "SELECT energy_wh FROM alerts_device_day WHERE household_id = ? AND device_id = ?"
        " AND day = ?",
        (str(household_id), str(reading.device_id), today.isoformat()),
    ).fetchone()
    spent = round(row["energy_wh"]) if row else 0
    if spent < FACTOR * usual or spent - usual < MIN_EXCESS_WH:
        return []
    key = (str(reading.device_id), today.isoformat())
    return [
        de.AlertsAlertRaised(
            id=stable_id("alerts.anomaly", *key),
            ts=reading.observed_at or reading.ts,
            household_id=household_id,
            correlation_id=stable_id("correlation", "anomaly", *key),
            provenance=reading.provenance,
            data=de.AlertRaisedData(
                kind=de.AlertKind.anomaly,
                severity=NotificationSeverity.warning,
                device_id=reading.device_id,
                room_id=room_id,
                day=today,
                energy_wh=spent,
                baseline_wh=usual,
            ),
        )
    ]


def handle(conn: sqlite3.Connection, stored: de.StoredEvent) -> list[de.DomainEvent]:
    ev = stored.event
    if not isinstance(ev, de.EnergyReadingRecorded):
        return []
    return observe(conn, ev.household_id, ev.data)
