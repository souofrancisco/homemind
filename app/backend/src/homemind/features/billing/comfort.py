"""Quartos frios (ALERT-06, v5.1 §15/§22): aviso PRIVADO a quem passa várias noites abaixo de
18 °C, para que a divisão justa não incentive ninguém a passar frio.

Só usa leituras `ok` do sensor de clima com quarto conhecido; sensor ausente, `unknown` ou
`stale` não gera inferências. Uma noite (22:00–08:00, fuso da casa) é fria se a média das suas
leituras fica abaixo de `THRESHOLD_C`. Avisa-se quando há `COLD_NIGHTS` noites frias nas últimas
`WINDOW_NIGHTS` noites completas, e no máximo uma vez por janela e quarto. Zonas comuns ficam
de fora (não são de ninguém). O senhorio nunca recebe estes avisos. O aviso leva o plafond
solidário que o quarto ainda tem nesse mês (`budgets.allowance_left`), se o quarto o tiver.
"""

import sqlite3
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts import domain_events as de
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.sensors import SensorKind
from homemind.features.billing import budgets

THRESHOLD_C = 18.0
COLD_NIGHTS = 3
WINDOW_NIGHTS = 7
NIGHT_START_H, NIGHT_END_H = 22, 8

# Nome PERMANENTE (chave de idempotência em `processed_event`).
CONSUMER = "billing.cold_rooms"
EVENT_TYPES = ("sensor.reading_recorded",)


def night_of(local: datetime) -> date | None:
    """A noite (data local do seu início) a que pertence uma hora local; `None` de dia."""
    if local.hour >= NIGHT_START_H:
        return local.date()
    if local.hour < NIGHT_END_H:
        return local.date() - timedelta(days=1)
    return None


def last_complete_night(local: datetime) -> date:
    """A noite mais recente já terminada (às 08:00 do dia seguinte ao seu início)."""
    return local.date() - timedelta(days=1 if local.hour >= NIGHT_END_H else 2)


def handle(conn: sqlite3.Connection, stored: de.StoredEvent) -> list[de.DomainEvent]:
    ev = stored.event
    if not isinstance(ev, de.SensorReadingRecorded):
        return []
    r = ev.data
    if r.kind is not SensorKind.temperature or not r.usable or r.room_id is None:
        return []
    house = conn.execute(
        "SELECT h.timezone, r.kind FROM household h JOIN room r ON r.household_id = h.id"
        " WHERE h.id = ? AND r.id = ?",
        (str(ev.household_id), str(r.room_id)),
    ).fetchone()
    if house is None or house["kind"] != "bedroom":
        return []
    local = (r.observed_at or r.ts).astimezone(ZoneInfo(house["timezone"]))
    night = night_of(local)
    if night is not None:
        assert r.temperature_c is not None
        conn.execute(
            "INSERT INTO alerts_room_night (household_id, room_id, night, sum_c, readings,"
            " simulated) VALUES (?,?,?,?,1,?) ON CONFLICT DO UPDATE SET"
            " sum_c = sum_c + excluded.sum_c, readings = readings + 1,"
            " simulated = max(simulated, excluded.simulated)",
            (
                str(ev.household_id),
                str(r.room_id),
                night.isoformat(),
                r.temperature_c,
                int(r.provenance.simulated),
            ),
        )
    return evaluate(conn, ev.household_id, r.room_id, local, ev.ts)


def evaluate(
    conn: sqlite3.Connection, household_id: UUID, room_id: UUID, local: datetime, ts: datetime
) -> list[de.DomainEvent]:
    last = last_complete_night(local)
    first = last - timedelta(days=WINDOW_NIGHTS - 1)
    nights = conn.execute(
        "SELECT night, sum_c / readings AS avg_c, simulated FROM alerts_room_night"
        " WHERE household_id = ? AND room_id = ? AND night BETWEEN ? AND ?",
        (str(household_id), str(room_id), first.isoformat(), last.isoformat()),
    ).fetchall()
    cold = [n for n in nights if n["avg_c"] < THRESHOLD_C]
    if len(cold) < COLD_NIGHTS:
        return []
    notice = conn.execute(
        "SELECT last_night FROM alerts_cold_room_notice WHERE household_id = ? AND room_id = ?",
        (str(household_id), str(room_id)),
    ).fetchone()
    if notice is not None and date.fromisoformat(notice["last_night"]) >= first:
        return []  # já avisado nesta janela
    tenants = [
        UUID(t["resident_id"])
        for t in conn.execute(
            "SELECT resident_id FROM membership WHERE household_id = ? AND room_id = ?"
            " AND role = 'tenant' AND status = 'active' AND starts_on <= ?"
            " AND (ends_on IS NULL OR ends_on >= ?) ORDER BY resident_id",
            (str(household_id), str(room_id), local.date().isoformat(), local.date().isoformat()),
        )
    ]
    if not tenants:
        return []
    conn.execute(
        "INSERT INTO alerts_cold_room_notice (household_id, room_id, last_night) VALUES (?,?,?)"
        " ON CONFLICT DO UPDATE SET last_night = excluded.last_night",
        (str(household_id), str(room_id), last.isoformat()),
    )
    simulated = any(n["simulated"] for n in cold)
    provenance = Provenance(
        origin=Origin.simulated if simulated else Origin.real, kind=ValueKind.measured
    )
    coldest = round(min(n["avg_c"] for n in cold), 1)
    # «Ainda tens X kWh do plafond»: para ninguém passar frio por causa da conta (BILL-03).
    left = budgets.allowance_left(conn, household_id, room_id, last.strftime("%Y-%m"))
    return [
        de.AlertsColdRoom(
            id=stable_id("alerts.cold_room", str(room_id), str(resident), last.isoformat()),
            ts=ts,
            household_id=household_id,
            correlation_id=stable_id("correlation", "cold_room", str(room_id)),
            provenance=provenance,
            data=de.ColdRoomData(
                resident_id=resident,
                room_id=room_id,
                cold_nights=len(cold),
                window_nights=WINDOW_NIGHTS,
                threshold_c=THRESHOLD_C,
                coldest_night_c=coldest,
                last_night=last,
                allowance_left_wh=left,
            ),
        )
        for resident in tenants
    ]
