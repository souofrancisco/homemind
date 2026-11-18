"""Picos de potência nas zonas comuns (ALERT-03). Lógica determinística, sem relógio próprio.

Regra (v5.1 §6.9, RA-04): uma tomada de zona comum acima de 1,5 kW durante mais de 30 min
gera um `alerts.alert_raised` (`kind=peak`) para a casa. O «agora» é o instante da leitura.

- Só leituras utilizáveis (`ok` com potência) contam; `missing`/`stale` não abrem nem fecham
  nada. Uma lacuna maior do que `MAX_GAP` recomeça a contagem: não se afirma um pico contínuo
  sem leituras que o provem. Leituras fora de ordem são ignoradas.
- Um aviso por incidente: depois de avisar, o pico só volta a ser avisado se tiver estado
  abaixo do limite (ou sem leituras) mais de `REARM`. Um aquecedor com termóstato que oscila
  à volta do limite não gera spam.
- Onde: tomada registada numa zona comum -> `room_id`; tomada sem divisão ou desconhecida ->
  `room_id=None` («pico de consumo por identificar»). Tomadas de quarto e contadores gerais
  (`main_meter`) nunca avisam: o quarto é do morador e o total da casa não diz onde é.
- Aparelho só se houver exatamente um consumo a decorrer nessa tomada identificado com
  confiança >= `MIN_CONFIDENCE` e o aparelho for comum (o nome de um pessoal identifica o dono).

Estado por tomada em `billing_peak_state` (sobrevive a reinícios); ids de evento derivados do
início do episódio (reentregas idempotentes).
"""

import sqlite3
from datetime import datetime, timedelta
from uuid import UUID

from homemind.contracts import domain_events as de
from homemind.contracts.common import stable_id
from homemind.contracts.energy import ConsumptionEvent, EnergyReading
from homemind.contracts.notification import NotificationSeverity

PEAK_THRESHOLD_W = 1500.0
MIN_DURATION = timedelta(minutes=30)
MAX_GAP = timedelta(minutes=10)
REARM = timedelta(minutes=30)
MIN_CONFIDENCE = 0.8

_SKIP = object()  # tomada que nunca avisa (quarto ou contador geral)


def _place(conn: sqlite3.Connection, household_id: UUID, device_id: UUID) -> object:
    """`room_id` de zona comum, `None` se a localização é desconhecida, ou `_SKIP`."""
    row = conn.execute(
        "SELECT d.role, d.room_id, r.kind FROM device d"
        " LEFT JOIN room r ON r.household_id = d.household_id AND r.id = d.room_id"
        " WHERE d.household_id = ? AND d.id = ?",
        (str(household_id), str(device_id)),
    ).fetchone()
    if row is None or row["room_id"] is None:
        return None
    if row["role"] == "main_meter" or row["kind"] != "common":
        return _SKIP
    return UUID(row["room_id"])


def _appliance(conn: sqlite3.Connection, household_id: UUID, device_id: UUID) -> UUID | None:
    rows = conn.execute(
        "SELECT json FROM billing_consumption WHERE household_id = ? AND status = 'ongoing'"
        " AND json_extract(json, '$.device_id') = ?",
        (str(household_id), str(device_id)),
    ).fetchall()
    found = set()
    for r in rows:
        m = ConsumptionEvent.model_validate_json(r["json"]).match
        if m.appliance_id is not None and m.confidence is not None:
            if m.confidence >= MIN_CONFIDENCE:
                found.add(m.appliance_id)
    if len(found) != 1:
        return None
    [appliance_id] = found
    common = conn.execute(
        "SELECT 1 FROM appliance_state WHERE household_id = ? AND appliance_id = ?"
        " AND valid_to IS NULL AND scope = 'common'",
        (str(household_id), str(appliance_id)),
    ).fetchone()
    return appliance_id if common else None


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def observe(
    conn: sqlite3.Connection, household_id: UUID, reading: EnergyReading
) -> list[de.DomainEvent]:
    """Dobra uma leitura no estado da tomada; devolve o aviso de pico, se nasceu agora."""
    if not reading.usable:
        return []
    place = _place(conn, household_id, reading.device_id)
    if place is _SKIP:
        return []
    at = reading.observed_at or reading.ts
    row = conn.execute(
        "SELECT * FROM billing_peak_state WHERE device_id = ?", (str(reading.device_id),)
    ).fetchone()
    last_ok = _ts(row["last_ok_at"]) if row else None
    above_since = _ts(row["above_since"]) if row else None
    alerted = _ts(row["alerted_last_above"]) if row else None
    if last_ok is not None and at <= last_ok:
        return []  # repetida ou fora de ordem
    if last_ok is not None and at - last_ok > MAX_GAP:
        above_since = None

    events: list[de.DomainEvent] = []
    assert reading.power_w is not None  # `usable`
    if reading.power_w > PEAK_THRESHOLD_W:
        above_since = above_since or at
        if alerted is not None and at - alerted <= REARM:
            alerted = at  # o mesmo incidente continua: não se repete o aviso
        elif at - above_since > MIN_DURATION:
            alerted = at
            events.append(_alert(conn, household_id, reading, place, above_since, at))
    else:
        above_since = None

    conn.execute(
        "INSERT INTO billing_peak_state (device_id, household_id, last_ok_at, above_since,"
        " alerted_last_above, updated_at) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(device_id) DO UPDATE SET last_ok_at = excluded.last_ok_at,"
        " above_since = excluded.above_since, alerted_last_above = excluded.alerted_last_above,"
        " updated_at = excluded.updated_at",
        (
            str(reading.device_id),
            str(household_id),
            at.isoformat(),
            above_since.isoformat() if above_since else None,
            alerted.isoformat() if alerted else None,
            at.isoformat(),
        ),
    )
    return events


def _alert(
    conn: sqlite3.Connection,
    household_id: UUID,
    reading: EnergyReading,
    room_id: object,
    since: datetime,
    at: datetime,
) -> de.AlertsAlertRaised:
    assert room_id is None or isinstance(room_id, UUID)
    key = (str(reading.device_id), since.isoformat())
    return de.AlertsAlertRaised(
        id=stable_id("alerts.peak", *key),
        ts=at,
        household_id=household_id,
        correlation_id=stable_id("correlation", "peak", *key),
        provenance=reading.provenance,
        data=de.AlertRaisedData(
            kind=de.AlertKind.peak,
            severity=NotificationSeverity.warning,
            device_id=reading.device_id,
            room_id=room_id,
            appliance_id=_appliance(conn, household_id, reading.device_id) if room_id else None,
            power_w=reading.power_w,
            since=since,
        ),
    )


# --- consumidor do barramento ------------------------------------------------------------------

# Nome PERMANENTE (chave de idempotência em `processed_event`).
CONSUMER = "billing.peaks"
EVENT_TYPES = ("energy.reading_recorded",)


def handle(conn: sqlite3.Connection, stored: de.StoredEvent) -> list[de.DomainEvent]:
    ev = stored.event
    if not isinstance(ev, de.EnergyReadingRecorded):
        return []
    return observe(conn, ev.household_id, ev.data)
