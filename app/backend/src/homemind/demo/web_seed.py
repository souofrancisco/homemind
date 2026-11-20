"""Histórico rico exclusivo da demo web; nenhum valor representa uma medição real."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta
from uuid import UUID

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import (
    Attribution,
    AttributionMethod,
    AttributionTarget,
    BillIn,
    BillPeriod,
)
from homemind.contracts.common import Audit, Origin, Provenance, ValueKind, stable_id
from homemind.contracts.devices import (
    Appliance,
    ApplianceCategory,
    ApplianceOwnership,
    ApplianceScope,
    ApplianceSignature,
    SignatureOrigin,
    SignaturePattern,
)
from homemind.contracts.energy import (
    ApplianceMatch,
    ConsumptionEvent,
    ConsumptionStatus,
    CostEstimate,
    LocationKind,
)
from homemind.contracts.household import RoomKind
from homemind.contracts.notification import (
    ConfirmationRequest,
    Notification,
    NotificationKind,
    NotificationScope,
    NotificationSeverity,
    NotificationStatus,
    confirmation_outcome,
)
from homemind.features.appliances import repo as appliance_repo
from homemind.features.billing import attribution as attribution_service
from homemind.features.billing import bills, budgets, closing, rules, tariff
from homemind.features.notifications.compose import (
    compose_budget_alert,
    compose_confirmation,
    compose_peak_alert,
)
from homemind.features.notifications.sqlite import SqliteNotificationRepository

SIM_MEASURED = Provenance(origin=Origin.simulated, kind=ValueKind.measured)
SIM_ESTIMATED = Provenance(origin=Origin.simulated, kind=ValueKind.estimated)
TENANTS = (fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO)
ROOMS = {
    fx.ANA: fx.ROOM_ANA,
    fx.BRUNO: fx.ROOM_BRUNO,
    fx.CARLA: fx.ROOM_CARLA,
    fx.DIOGO: fx.ROOM_DIOGO,
}


def seed_history(conn: sqlite3.Connection, at: datetime) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS demo_web_history_seed (id INTEGER PRIMARY KEY CHECK (id = 1))"
    )
    if conn.execute("SELECT 1 FROM demo_web_history_seed WHERE id=1").fetchone():
        return
    _appliances(conn, at)
    period = budgets.current_period(conn, fx.HOUSEHOLD, at)
    for resident, euros in zip(TENANTS, (25, 30, 25, 20), strict=True):
        budgets.set_personal(conn, fx.HOUSEHOLD, resident, period, euros * 100, [50, 80, 100], at)
    _sessions(conn, at)
    _confirmations(conn, at)
    _notices(conn, at)
    _last_bill(conn, at)
    conn.execute("INSERT INTO demo_web_history_seed (id) VALUES (1)")


def _appliances(conn: sqlite3.Connection, at: datetime) -> None:
    kitchen = stable_id("demo-web-room", "cozinha")
    catalog = (
        (
            "microondas",
            "Micro-ondas",
            ApplianceCategory.kitchen,
            ApplianceScope.common,
            None,
            kitchen,
            1200,
            1200,
            120,
        ),
        (
            "lavadora",
            "Máquina de lavar roupa",
            ApplianceCategory.laundry,
            ApplianceScope.common,
            None,
            None,
            1800,
            500,
            3600,
        ),
        (
            "frigorifico",
            "Frigorífico",
            ApplianceCategory.kitchen,
            ApplianceScope.common,
            None,
            kitchen,
            120,
            120,
            3600,
        ),
        (
            "secador",
            "Secador de cabelo",
            ApplianceCategory.other,
            ApplianceScope.personal,
            fx.CARLA,
            fx.ROOM_CARLA,
            1800,
            1600,
            600,
        ),
        (
            "computador",
            "Computador e monitor",
            ApplianceCategory.electronics,
            ApplianceScope.personal,
            fx.DIOGO,
            fx.ROOM_DIOGO,
            280,
            240,
            14400,
        ),
        (
            "lampada-rgb",
            "Lâmpada RGB da sala",
            ApplianceCategory.lighting,
            ApplianceScope.common,
            None,
            fx.ROOM_SALA,
            9,
            9,
            3600,
        ),
    )
    for key, name, category, scope, owner, room, watts, mean, duration in catalog:
        appliance_id = stable_id("demo-web-appliance", key)
        appliance = Appliance(
            id=appliance_id,
            household_id=fx.HOUSEHOLD,
            name=name,
            category=category,
            ownership=ApplianceOwnership(scope=scope, owner_resident_id=owner, home_room_id=room),
            typical_watts=watts,
            registered_by_resident_id=owner or fx.ANA,
        )
        appliance_repo.register_appliance(conn, appliance, at)
        signature = ApplianceSignature(
            id=stable_id("demo-web-signature", key),
            appliance_id=appliance_id,
            watts_mean=mean,
            watts_tolerance=max(1, mean // 10),
            duration_typical_s=duration,
            pattern=SignaturePattern.continuous if key == "frigorifico" else SignaturePattern.short,
            samples=0,
            origin=SignatureOrigin.simulated,
            updated_at=at,
        )
        appliance_repo.save_appliance_signature(conn, fx.HOUSEHOLD, signature)
        # O frigorífico fica no catálogo, sempre ligado, sem episódios artificiais de uso.


def _sessions(conn: sqlite3.Connection, at: datetime) -> None:
    month_start = at.date().replace(day=1)
    first = (
        max(month_start, at.date() - timedelta(days=11))
        if at.date().day > 3
        else at.date() - timedelta(days=11)
    )
    tariff_status = tariff.load(conn, fx.HOUSEHOLD)
    assert tariff_status.tariff is not None
    tz = budgets.household_tz(conn, fx.HOUSEHOLD)
    plug = stable_id("demo-web-device", "extensao-sala")
    ids = {
        key: stable_id("demo-web-appliance", key)
        for key in ("microondas", "lavadora", "secador", "computador", "lampada-rgb")
    }
    # O histórico tem 45 sessões distribuídas pelos 12 dias; o frigorífico não cria sessões.
    rows: list[tuple[date, int, str, UUID | None, int, int, UUID | None]] = []
    previous_end = month_start - timedelta(days=1)
    for offset, sample in enumerate(
        (
            ("dryer", ids["secador"], 1600, 3600, fx.CARLA),
            ("heater", fx.HEATER, 2040, 9000, fx.BRUNO),
            ("computer", ids["computador"], 240, 21600, fx.DIOGO),
            ("kettle", fx.KETTLE, 1800, 180, None),
            ("lamp", ids["lampada-rgb"], 9, 14400, None),
            ("unidentified", None, 2000, 2700, None),
        )
    ):
        sample_day = previous_end - timedelta(days=offset)
        rows.append((sample_day, 9 + offset, *sample))
    day = first
    while day <= at.date():
        index = (day - first).days
        rows.append((day, 7, "kettle", fx.KETTLE, 1800, 180, None))
        if index < 7:
            rows.append((day, 15, "kettle", fx.KETTLE, 1800, 180, None))
        if index == 0:
            rows.append((day, 12, "microondas", ids["microondas"], 1200, 420, None))
        if index % 2 == 0:
            rows.append((day, 20, "heater", fx.HEATER, 2040, 32400, fx.BRUNO))
        if index % 2 == 1:
            rows.append((day, 8, "dryer", ids["secador"], 1600, 6600, fx.CARLA))
        if index % 3 == 0:
            rows.append((day, 9, "washer", ids["lavadora"], 500, 5400, None))
        if index % 2 == 0:
            rows.append((day, 18, "unidentified", None, 2040, 10800, fx.ANA))
        if index % 3 == 1:
            rows.append((day, 15, "computer", ids["computador"], 240, 21600, fx.DIOGO))
        if index == 0:
            rows.append((day, 21, "lamp", ids["lampada-rgb"], 9, 14400, None))
        day += timedelta(days=1)
    # Quarenta e cinco registos no máximo; a variedade mantém a apresentação legível.
    rows = rows[:45]
    rows = [
        row
        for row in rows
        if datetime.combine(row[0], time(row[1]), tzinfo=tz) + timedelta(seconds=row[5]) <= at
    ]
    for index, (day, hour, key, appliance_id, watts, seconds, resident) in enumerate(rows):
        start = datetime.combine(day, time(hour), tzinfo=tz)
        end = start + timedelta(seconds=seconds)
        energy_wh = max(1, round(watts * seconds / 3600))
        estimated = key == "lamp"
        if estimated:
            energy_wh = max(1, round(9 * seconds * 0.7 / 3600))  # brilho simulado a 70 %
        price = tariff_status.tariff.price_millicents_per_kwh
        cost = tariff.cents(
            tariff.value_millicents(tariff_status.tariff, tz, energy_wh, start, end)
        )
        event_id = stable_id("demo-web-consumption", day.isoformat(), str(index), key)
        event = ConsumptionEvent(
            id=event_id,
            household_id=fx.HOUSEHOLD,
            device_id=plug,
            match=ApplianceMatch(appliance_id=appliance_id, confidence=0.97)
            if appliance_id
            else ApplianceMatch(),
            started_at=start,
            ended_at=end,
            status=ConsumptionStatus.closed,
            peak_w=watts,
            energy_wh=energy_wh,
            location=LocationKind.room if resident else LocationKind.common,
            room_id=ROOMS[resident]
            if resident
            else (fx.ROOM_SALA if key == "lamp" else stable_id("demo-web-room", "cozinha")),
            cost_estimate=CostEstimate(cents=cost, price_millicents_per_kwh=price),
            appliance_owner_resident_id=resident if appliance_id and resident else None,
            provenance=SIM_ESTIMATED if estimated else SIM_MEASURED,
        )
        conn.execute(
            "INSERT INTO billing_consumption (id, household_id, status, started_at, energy_wh, "
            "json, updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "json=excluded.json, energy_wh=excluded.energy_wh, updated_at=excluded.updated_at",
            (
                str(event.id),
                str(fx.HOUSEHOLD),
                event.status.value,
                event.started_at.isoformat(),
                event.energy_wh,
                event.model_dump_json(),
                at.isoformat(),
            ),
        )
        decision = attribution_service.decide(
            event,
            rules.policy_on(conn, fx.HOUSEHOLD, day),
            {room: resident for resident, room in ROOMS.items()},
            TENANTS,
            at,
            appliance_name=key if appliance_id else None,
        )
        if decision.attribution:
            _save_attribution(conn, decision.attribution, at)
        elif decision.confirmation:
            _confirmation(
                conn,
                event.id,
                at,
                pending=True,
                request=decision.confirmation,
            )


def _save_attribution(conn: sqlite3.Connection, attribution: Attribution, at: datetime) -> None:
    conn.execute(
        "INSERT INTO billing_attribution (id, household_id, consumption_event_id, status, "
        "json, created_at) VALUES (?,?,?,'active',?,?)",
        (
            str(attribution.id),
            str(attribution.household_id),
            str(attribution.consumption_event_id),
            attribution.model_dump_json(),
            at.isoformat(),
        ),
    )


def _confirmations(conn: sqlite3.Connection, at: datetime) -> None:
    open_items = [stable_id("demo-web-consumption", "vote", str(r)) for r in TENANTS]
    previous_day = at.date().replace(day=1) - timedelta(days=1)
    event_at = datetime.combine(previous_day, time(12), tzinfo=at.tzinfo)
    for i, event_id in enumerate(open_items):
        _confirmation(
            conn,
            event_id,
            at - timedelta(minutes=i * 3),
            pending=True,
            prior_voter=TENANTS[(i + 1) % len(TENANTS)] if i == 0 else None,
            event_at=event_at,
        )
    for i, choice in enumerate(("mine", "mine", "everyone")):
        event_id = stable_id("demo-web-consumption", "decided", str(i))
        _confirmation(
            conn,
            event_id,
            at - timedelta(days=2, hours=i),
            pending=False,
            decision=choice,
            event_at=event_at,
        )
    expired_id = stable_id("demo-web-consumption", "expired")
    _confirmation(
        conn,
        expired_id,
        at - timedelta(hours=25),
        pending=False,
        expired=True,
        event_at=event_at,
    )


def _confirmation(
    conn,
    event_id: UUID,
    created: datetime,
    *,
    pending: bool,
    prior_voter=None,
    decision=None,
    expired=False,
    request: ConfirmationRequest | None = None,
    event_at: datetime | None = None,
):
    if request is None:
        expiry = created + timedelta(hours=24)
        request = ConfirmationRequest(
            consumption_event_id=event_id,
            estimated_cost_cents=92,
            appliance_name="Aparelho comum",
            eligible_resident_ids=list(TENANTS),
            expires_at=expiry,
        )
        session_start = event_at or created
        event = ConsumptionEvent(
            id=event_id,
            household_id=fx.HOUSEHOLD,
            device_id=stable_id("demo-web-device", "extensao-sala"),
            match=ApplianceMatch(),
            started_at=session_start,
            ended_at=session_start + timedelta(minutes=25),
            status=ConsumptionStatus.closed,
            peak_w=800,
            energy_wh=5750,
            location=LocationKind.unknown,
            cost_estimate=CostEstimate(cents=92, price_millicents_per_kwh=16000),
            provenance=SIM_ESTIMATED,
        )
        conn.execute(
            "INSERT OR IGNORE INTO billing_consumption (id, household_id, status, started_at, "
            "energy_wh, json, updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                str(event.id),
                str(fx.HOUSEHOLD),
                event.status.value,
                event.started_at.isoformat(),
                event.energy_wh,
                event.model_dump_json(),
                created.isoformat(),
            ),
        )
    expiry = request.expires_at
    event_id = request.consumption_event_id
    conn.execute(
        "INSERT INTO billing_confirmation (consumption_event_id, household_id, expires_at, "
        "status, created_at) VALUES (?,?,?,?,?)",
        (
            str(event_id),
            str(fx.HOUSEHOLD),
            expiry.isoformat(),
            "expired" if expired else "pending" if pending else "resolved",
            created.isoformat(),
        ),
    )
    item = compose_confirmation(
        request,
        household_id=fx.HOUSEHOLD,
        responder_ids=request.eligible_resident_ids,
        origin=Origin.simulated,
        correlation_id=stable_id("demo-web-correlation", str(event_id)),
        source_event_id=event_id,
        now=created,
    )
    if expired:
        item = item.model_copy(update={"status": NotificationStatus.expired})
    if prior_voter is not None:
        item = item.respond(prior_voter, "unknown", created + timedelta(minutes=1))
    if decision:
        if decision == "everyone":
            for j, resident in enumerate(TENANTS):
                item = item.respond(resident, "unknown", created + timedelta(minutes=j + 1))
        else:
            item = item.respond(TENANTS[0], decision, created + timedelta(minutes=1))
    elif expired:
        # A notificação mostra a expiração; confirmation_outcome aplica a decisão «por todos».
        confirmation_outcome(item.responses, item.responder_ids, expired=True)
    _save_notification(conn, item, created)
    if decision or expired:
        outcome = confirmation_outcome(item.responses, item.responder_ids, expired=expired)
        last_vote = item.responses[-1] if item.responses else None
        attribution = Attribution(
            id=stable_id("demo-web-attribution", str(event_id), "confirmation"),
            household_id=fx.HOUSEHOLD,
            consumption_event_id=event_id,
            target_type=(
                AttributionTarget.resident if outcome.resident_ids else AttributionTarget.common
            ),
            target_resident_id=outcome.resident_ids[0] if outcome.resident_ids else None,
            method=AttributionMethod.equal_fallback if expired else AttributionMethod.confirmation,
            provenance=SIM_MEASURED,
            decided_by=(
                Audit(at=expiry, by_system="billing")
                if expired
                else Audit(at=last_vote.responded_at, by_resident_id=last_vote.resident_id)
            ),
        )
        _save_attribution(conn, attribution, created)


def _save_notification(conn, item: Notification, updated: datetime) -> None:
    SqliteNotificationRepository(conn).insert(item)
    # O repositório não recebe relógio; fixar updated_at mantém a semente reproduzível.
    conn.execute(
        "UPDATE notification SET updated_at = ? WHERE id = ?",
        (updated.isoformat(), str(item.id)),
    )


def _notices(conn: sqlite3.Connection, at: datetime) -> None:
    samples = (
        (
            fx.ANA,
            NotificationKind.budget_alert,
            "Orçamento a 50 %",
            "Já utilizaste metade do orçamento mensal simulado.",
        ),
        (
            fx.BRUNO,
            NotificationKind.budget_alert,
            "Orçamento a 80 %",
            "O consumo deste mês aproxima-se do limite simulado.",
        ),
        (
            None,
            NotificationKind.peak_alert,
            "Pico de consumo na zona comum",
            "Foi registado um pico simulado acima de 1,5 kW durante mais de 30 minutos.",
        ),
        (
            fx.CARLA,
            NotificationKind.info,
            "Consumo registado",
            "O consumo simulado do secador foi acrescentado ao mês.",
        ),
        (
            fx.DIOGO,
            NotificationKind.info,
            "Consumo registado",
            "O consumo simulado do computador foi acrescentado ao mês.",
        ),
    )
    for i, (recipient, kind, title, body) in enumerate(samples):
        source_event_id = stable_id("demo-web-notification-source", str(i))
        correlation_id = stable_id("demo-web-notification-correlation", str(i))
        created = at - timedelta(minutes=i + 1)
        if kind is NotificationKind.budget_alert:
            pct = 50 if recipient == fx.ANA else 80
            item = compose_budget_alert(
                household_id=fx.HOUSEHOLD,
                resident_id=recipient,
                budget_id=stable_id(
                    "budget", str(fx.HOUSEHOLD), str(recipient), at.strftime("%Y-%m")
                ),
                pct=pct,
                spent_cents=1250 if pct == 50 else 2400,
                limit_cents=2500 if recipient == fx.ANA else 3000,
                forecast_cents=2600 if pct == 50 else 3200,
                origin=Origin.simulated,
                correlation_id=correlation_id,
                source_event_id=source_event_id,
                now=created,
            )
            _save_notification(conn, item, at)
            continue
        if kind is NotificationKind.peak_alert:
            item = compose_peak_alert(
                source_event_id=source_event_id,
                household_id=fx.HOUSEHOLD,
                room=("Sala", RoomKind.common),
                appliance_name=None,
                power_w=2000,
                minutes=45,
                origin=Origin.simulated,
                correlation_id=correlation_id,
                now=created,
            )
            _save_notification(conn, item, at)
            continue
        item = Notification(
            id=stable_id("demo-web-notification", str(i)),
            household_id=fx.HOUSEHOLD,
            scope=NotificationScope.personal if recipient else NotificationScope.household,
            recipient_resident_id=recipient,
            responder_ids=[recipient] if recipient else [],
            kind=kind,
            severity=NotificationSeverity.warning
            if kind is NotificationKind.budget_alert
            else NotificationSeverity.info,
            title=title,
            body=body,
            origin=Origin.simulated,
            correlation_id=correlation_id,
            created_at=created,
        )
        _save_notification(conn, item, at)


def _last_bill(conn: sqlite3.Connection, at: datetime) -> None:
    current = at.date().replace(day=1)
    end = current - timedelta(days=1)
    start = end.replace(day=1)
    bill_in = BillIn(
        period=BillPeriod(start=start, end=end),
        total_cents=5800,
        fixed_cents=1200,
        total_wh=287500,
        price_millicents_per_kwh=16000,
        origin=Origin.simulated,
    )
    bill = bills.new_bill(
        stable_id("demo-web-bill", start.isoformat()), fx.HOUSEHOLD, bill_in, fx.LANDLORD, at
    )
    bills.insert_bill(conn, bill, bill_in.price_millicents_per_kwh)
    closing.finalize(conn, fx.HOUSEHOLD, bill.id, at)
