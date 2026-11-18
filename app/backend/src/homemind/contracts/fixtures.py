"""Fixtures determinísticas dos contratos (Conta Certa). Tudo SIMULADO e ilustrativo.

Casa de demonstração: Ana, Bruno, Carla e Diogo (inquilinos), um senhorio e um operador.
O aquecedor do Bruno está na sala e é usado pela Carla (PDF §6.5, D-18). As faturas A, B e C
são os exemplos do PDF (120 €) e de arredondamento; valores do PDF, não resultados nossos.
IDs estáveis (uuid5): os testes e os outros módulos podem referi-los sem os criar.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from homemind.contracts import (
    agent,
    billing,
    devices,
    domain_events,
    energy,
    notification,
    safety,
    sensors,
)
from homemind.contracts import household as hh
from homemind.contracts import presence as pr
from homemind.contracts.common import (
    Audit,
    Origin,
    Provenance,
    ValueKind,
    cost_cents,
    stable_id,
)

T0 = datetime(2026, 11, 17, 19, 0, tzinfo=UTC)
PRICE_MILLICENTS = 16_000  # 0,16 €/kWh

SIM_MEASURED = Provenance(origin=Origin.simulated, kind=ValueKind.measured)
SIM_ESTIMATED = Provenance(origin=Origin.simulated, kind=ValueKind.estimated)
SIM_INFERRED = Provenance(origin=Origin.simulated, kind=ValueKind.inferred)

HOUSEHOLD = stable_id("household", "demo")
ROOM_SALA = stable_id("room", "sala")
ROOM_ANA, ROOM_BRUNO, ROOM_CARLA, ROOM_DIOGO = (
    stable_id("room", n) for n in ("ana", "bruno", "carla", "diogo")
)
ANA, BRUNO, CARLA, DIOGO, LANDLORD, OPERATOR = (
    stable_id("resident", n) for n in ("ana", "bruno", "carla", "diogo", "senhorio", "operador")
)
TENANTS = (ANA, BRUNO, CARLA, DIOGO)
SUBJECTS = {  # `sub` simulados do Authentik
    ANA: "sub-ana",
    BRUNO: "sub-bruno",
    CARLA: "sub-carla",
    DIOGO: "sub-diogo",
    LANDLORD: "sub-senhorio",
    OPERATOR: "sub-operador",
}
METER = stable_id("device", "main-meter")
LAMP = stable_id("device", "lamp")
HEATER = stable_id("appliance", "aquecedor-bruno")
KETTLE = stable_id("appliance", "chaleira-sala")
CONSUMPTION = stable_id("consumption", "aquecedor-sala")
NOTIFICATION = stable_id("notification", "aquecedor-sala")
CORRELATION = stable_id("correlation", "aquecedor-sala")
BILL_A, BILL_B, BILL_C = (stable_id("bill", n) for n in "abc")
WINDOW_SENSOR = stable_id("device", "janela-sala")
SMOKE_SENSOR = stable_id("device", "fumo-cozinha")

_NAMES = {ANA: "Ana", BRUNO: "Bruno", CARLA: "Carla", DIOGO: "Diogo"}
_ROOMS = {ANA: ROOM_ANA, BRUNO: ROOM_BRUNO, CARLA: ROOM_CARLA, DIOGO: ROOM_DIOGO}


# --- casa --------------------------------------------------------------------------------------


def household() -> hh.Household:
    return hh.Household(
        id=HOUSEHOLD,
        name="Casa da Rua Direita (demo)",
        settings=hh.HouseholdSettings(
            energy_price_millicents_per_kwh=PRICE_MILLICENTS, source_kind=hh.SourceKind.demo
        ),
        created_at=T0 - timedelta(days=30),
    )


def rooms() -> list[hh.Room]:
    beds = [
        hh.Room(
            id=_ROOMS[r],
            household_id=HOUSEHOLD,
            name=f"Quarto {_NAMES[r]}",
            kind=hh.RoomKind.bedroom,
            included_wh=30_000,
        )
        for r in TENANTS
    ]
    return [
        *beds,
        hh.Room(id=ROOM_SALA, household_id=HOUSEHOLD, name="Sala", kind=hh.RoomKind.common),
    ]


def residents() -> list[hh.Resident]:
    names = {**_NAMES, LANDLORD: "Sr. Silva", OPERATOR: "Operador"}
    return [hh.Resident(id=i, display_name=n, auth_subject=SUBJECTS[i]) for i, n in names.items()]


def memberships() -> list[hh.Membership]:
    start = date(2026, 9, 1)
    active = hh.MembershipStatus.active
    tenants = [
        hh.Membership(
            id=stable_id("membership", str(r)),
            household_id=HOUSEHOLD,
            resident_id=r,
            role=hh.MembershipRole.tenant,
            room_id=_ROOMS[r],
            starts_on=start,
            status=active,
        )
        for r in TENANTS
    ]
    staff = [
        hh.Membership(
            id=stable_id("membership", str(r)),
            household_id=HOUSEHOLD,
            resident_id=r,
            role=role,
            starts_on=start,
            status=active,
        )
        for r, role in (
            (LANDLORD, hh.MembershipRole.landlord),
            (OPERATOR, hh.MembershipRole.operator),
        )
    ]
    return [*tenants, *staff]


# --- dispositivos e aparelhos ---------------------------------------------------------------------


def meter() -> devices.Device:
    return devices.Device(
        id=METER,
        household_id=HOUSEHOLD,
        room_id=ROOM_SALA,
        name="Tomada da extensão",
        kind=devices.DeviceKind.plug,
        role=devices.DeviceRole.main_meter,
        source=devices.DeviceSource.fake,
        power_unit=devices.PowerUnit.W,
        online=True,
        last_seen_at=T0,
    )


def heater() -> devices.Appliance:
    """Aquecedor do Bruno: dono Bruno, vive no quarto dele; hoje está na sala."""
    return devices.Appliance(
        id=HEATER,
        household_id=HOUSEHOLD,
        name="Aquecedor do Bruno",
        category=devices.ApplianceCategory.heating,
        ownership=devices.ApplianceOwnership(
            scope=devices.ApplianceScope.personal, owner_resident_id=BRUNO, home_room_id=ROOM_BRUNO
        ),
        typical_watts=2000,
        registered_by_resident_id=BRUNO,
    )


def heater_signature() -> devices.ApplianceSignature:
    return devices.ApplianceSignature(
        id=stable_id("signature", "aquecedor-bruno"),
        appliance_id=HEATER,
        watts_mean=2000,
        watts_tolerance=150,
        pattern=devices.SignaturePattern.cyclic,
        samples=12,
        origin=devices.SignatureOrigin.simulated,
        updated_at=T0,
    )


# --- energia -------------------------------------------------------------------------------------


def reading(power_w: float = 2000.0, ts: datetime = T0) -> energy.EnergyReading:
    return energy.EnergyReading(
        id=stable_id("reading", ts.isoformat()),
        device_id=METER,
        ts=ts,
        observed_at=ts,
        status=energy.ReadingStatus.ok,
        power_w=power_w,
        raw_value=power_w,
        raw_unit=devices.PowerUnit.W,
        provenance=SIM_MEASURED,
    )


def step() -> energy.PowerStep:
    return energy.PowerStep(
        id=stable_id("step", "aquecedor"),
        device_id=METER,
        ts=T0,
        before_w=40.0,
        after_w=2040.0,
        provenance=SIM_MEASURED,
    )


def consumption(closed: bool = False) -> energy.ConsumptionEvent:
    """Aquecedor (probabilidade 0,9) ligado na sala: localização comum, aparelho do Bruno."""
    match = energy.ApplianceMatch(
        appliance_id=HEATER,
        confidence=0.9,
        candidates=[
            energy.ApplianceCandidate(appliance_id=HEATER, confidence=0.9),
            energy.ApplianceCandidate(appliance_id=KETTLE, confidence=0.2),
        ],
    )
    wh = 3000 if closed else 1000  # 1,5 h a 2 kW (fechado) / 30 min (a decorrer)
    return energy.ConsumptionEvent(
        id=CONSUMPTION,
        household_id=HOUSEHOLD,
        device_id=METER,
        match=match,
        started_at=T0,
        ended_at=T0 + timedelta(minutes=90) if closed else None,
        status=energy.ConsumptionStatus.closed if closed else energy.ConsumptionStatus.ongoing,
        peak_w=2040.0,
        energy_wh=wh,
        location=energy.LocationKind.common,
        room_id=ROOM_SALA,
        appliance_owner_resident_id=BRUNO,
        cost_estimate=energy.CostEstimate(
            cents=cost_cents(wh, PRICE_MILLICENTS), price_millicents_per_kwh=PRICE_MILLICENTS
        ),
        provenance=SIM_INFERRED,
    )


# --- presença ------------------------------------------------------------------------------------


def door_crossed() -> pr.DoorCrossed:
    """Passagem anónima: sem resident_id, sem imagem."""
    return pr.DoorCrossed(
        ts=T0, direction=pr.DoorDirection.entered, confidence=0.93, provenance=SIM_INFERRED
    )


def person_presence() -> pr.PersonPresence:
    return pr.PersonPresence(
        resident_id=CARLA,
        state=pr.PresenceState.home,
        since=T0,
        confidence=0.8,
        provenance=SIM_INFERRED,
        sources=[pr.PresenceSource.camera_door, pr.PresenceSource.wifi],
    )


def appliance_cue() -> pr.PresenceEvent:
    """O aquecedor do Bruno ligou: pista de que o Bruno está em casa (não de quem o usa)."""
    return pr.PresenceEvent(
        id=stable_id("cue", "aquecedor-bruno"),
        household_id=HOUSEHOLD,
        resident_id=BRUNO,
        ts=T0,
        state=pr.PresenceState.home,
        source=pr.PresenceSource.appliance,
        confidence=0.6,
        provenance=SIM_INFERRED,
        consumption_event_id=CONSUMPTION,
    )


def presence_confirmation() -> pr.PresenceConfirmationRequest:
    return pr.PresenceConfirmationRequest(
        id=stable_id("presence-check", "carla"),
        resident_id=CARLA,
        reason=pr.UncertainReason.conflicting_cues,
        expires_at=T0 + timedelta(minutes=30),
    )


def occupancy() -> pr.HouseOccupancy:
    """Três pessoas dentro: dois moradores e uma visita (só o número)."""
    return pr.HouseOccupancy(
        ts=T0,
        state=pr.OccupancyState.occupied,
        people_inside=3,
        visitors=1,
        residents_home=2,
        provenance=SIM_INFERRED,
    )


def presence_device() -> pr.PresenceDevice:
    return pr.PresenceDevice(
        id=stable_id("presence-device", "carla"),
        household_id=HOUSEHOLD,
        resident_id=CARLA,
        label="Telemóvel C.",
        match_key="sha256:" + "0" * 64,
        wifi_opt_in=True,
        consented_at=T0 - timedelta(days=1),
        created_at=T0 - timedelta(days=1),
    )


def camera_status() -> pr.CameraStatus:
    return pr.CameraStatus(
        source=pr.VideoSourceKind.clip,
        origin=Origin.simulated,
        camera_ok=True,
        fps=12.0,
        last_frame_at=T0,
        door_mask_configured=True,
    )


# --- sensores e segurança ------------------------------------------------------------------------


def window_open() -> sensors.SensorReading:
    return sensors.SensorReading(
        id=stable_id("sensor-reading", "janela-sala"),
        device_id=WINDOW_SENSOR,
        room_id=ROOM_SALA,
        ts=T0,
        kind=sensors.SensorKind.contact,
        status=sensors.SensorStatus.ok,
        contact=sensors.ContactState.open,
        provenance=SIM_MEASURED,
    )


def window_alert() -> safety.SafetyAlert:
    """Janela da sala aberta há 5 min com o aquecedor ligado: sugere desligar (com confirmação)."""
    return safety.SafetyAlert(
        id=stable_id("safety", "janela-sala"),
        household_id=HOUSEHOLD,
        kind=safety.SafetyAlertKind.window_open_heating,
        severity=notification.NotificationSeverity.warning,
        room_id=ROOM_SALA,
        sensor_device_id=WINDOW_SENSOR,
        consumption_event_id=CONSUMPTION,
        suggested_command=agent.DeviceCommand(
            target_device_id=METER, capability=agent.DeviceCapability.power, power=False
        ),
        started_at=T0 + timedelta(minutes=5),
        provenance=SIM_INFERRED,
    )


def smoke_alert() -> safety.SafetyAlert:
    return safety.SafetyAlert(
        id=stable_id("safety", "fumo-cozinha"),
        household_id=HOUSEHOLD,
        kind=safety.SafetyAlertKind.smoke,
        severity=notification.NotificationSeverity.critical,
        sensor_device_id=SMOKE_SENSOR,
        notify_landlord=True,
        started_at=T0,
        provenance=SIM_MEASURED,
    )


# --- confirmação e notificação -------------------------------------------------------------------


def confirmation_request() -> notification.ConfirmationRequest:
    return notification.ConfirmationRequest(
        consumption_event_id=CONSUMPTION,
        appliance_name="Aquecedor do Bruno",
        estimated_cost_cents=cost_cents(1000, PRICE_MILLICENTS),
        eligible_resident_ids=list(TENANTS),
        expires_at=T0 + timedelta(hours=24),
    )


def confirmation_notification() -> notification.Notification:
    """«De quem é esta conta?» para a casa; qualquer inquilino ativo pode responder."""
    req = confirmation_request()
    labels = {
        "mine": "É minha",
        "everyone": "É de todos",
        "unknown": "Não sei",
        "other": "É de outra pessoa",
    }
    return notification.Notification(
        id=NOTIFICATION,
        household_id=HOUSEHOLD,
        scope=notification.NotificationScope.household,
        responder_ids=req.eligible_resident_ids,
        kind=notification.NotificationKind.confirmation_request,
        severity=notification.NotificationSeverity.info,
        title="De quem é esta conta?",
        body="O aquecedor do Bruno está ligado na sala (SIMULADO).",
        origin=Origin.simulated,
        actions=[
            notification.NotificationAction(
                id=c.value,
                label=labels[c.value],
                style=notification.ActionStyle.primary
                if c.value == "mine"
                else notification.ActionStyle.neutral,
            )
            for c in req.options
        ],
        expires_at=req.expires_at,
        ref=notification.NotificationRef(
            type=notification.RefType.consumption_event, id=CONSUMPTION
        ),
        correlation_id=CORRELATION,
        created_at=T0 + timedelta(seconds=5),
    )


def carla_attribution() -> billing.Attribution:
    return billing.Attribution(
        id=stable_id("attribution", "carla"),
        household_id=HOUSEHOLD,
        consumption_event_id=CONSUMPTION,
        target_type=billing.AttributionTarget.resident,
        target_resident_id=CARLA,
        method=billing.AttributionMethod.confirmation,
        provenance=SIM_MEASURED,
        decided_by=Audit(at=T0 + timedelta(minutes=2), by_resident_id=CARLA),
    )


# --- faturas (PDF, 120 € = 24 € fixos + 600 kWh × 0,16 €) -----------------------------------------


def _bill(bill_id, total=12_000, fixed=2_400, total_wh=600_000) -> billing.ElectricityBill:
    return billing.ElectricityBill(
        id=bill_id,
        household_id=HOUSEHOLD,
        period=billing.BillPeriod(start=date(2026, 11, 1), end=date(2026, 11, 30)),
        total_cents=total,
        fixed_cents=fixed,
        total_wh=total_wh,
        source=billing.BillSource.manual,
        provenance=SIM_MEASURED,
        created_by=Audit(at=T0, by_resident_id=LANDLORD),
    )


def _allocations(bill_id, rows) -> list[billing.BillAllocation]:
    """`rows`: (resident, wh individual, fixo, resíduo) → individual = wh × 0,16 €/kWh."""
    out = []
    for resident, wh, fixed, residual in rows:
        individual = cost_cents(wh, PRICE_MILLICENTS)
        lines = [
            billing.BillBreakdownLine(
                kind=billing.BreakdownKind.fixed_share, label="Termo fixo", amount_cents=fixed
            ),
            billing.BillBreakdownLine(
                kind=billing.BreakdownKind.residual_share,
                label="Consumo não atribuído",
                amount_cents=residual,
            ),
            billing.BillBreakdownLine(
                kind=billing.BreakdownKind.room,
                label="Consumo individual (ilustrativo)",
                energy_wh=wh,
                amount_cents=individual,
                provenance=SIM_INFERRED,
            ),
        ]
        out.append(
            billing.BillAllocation(
                id=stable_id("allocation", str(bill_id), str(resident)),
                bill_id=bill_id,
                resident_id=resident,
                room_id=_ROOMS[resident],
                fixed_share_cents=fixed,
                residual_share_cents=residual,
                individual_cents=individual,
                amount_cents=fixed + residual + individual,
                attributed_wh=[energy.EnergyTotal(provenance=SIM_INFERRED, energy_wh=wh)],
                breakdown=lines,
            )
        )
    return out


def bill_a() -> tuple[billing.ElectricityBill, list[billing.BillAllocation]]:
    """Modelo do PDF §7.1 (MVP): 45,12 / 29,76 / 24,64 / 20,48 €."""
    rows = [(r, kwh * 1000, 600, 840) for r, kwh in zip(TENANTS, (192, 96, 64, 38), strict=True)]
    return _bill(BILL_A), _allocations(BILL_A, rows)


def bill_b() -> tuple[billing.ElectricityBill, list[billing.BillAllocation]]:
    """«Três regras» do sumário (só quartos): 46,80 / 27,60 / 24,40 / 21,20 €."""
    rows = [(r, kwh * 1000, 600, 1200) for r, kwh in zip(TENANTS, (180, 60, 40, 20), strict=True)]
    return _bill(BILL_B), _allocations(BILL_B, rows)


def bill_c() -> tuple[billing.ElectricityBill, list[billing.BillAllocation]]:
    """Arredondamento: 100 € por 3 moradores iguais → 33,34 / 33,33 / 33,33 €. O cêntimo extra
    vai a sorteio reproduzível (D-34, `billing.allocation.draw_order`): nesta fatura, a Carla."""
    bill = _bill(BILL_C, total=10_000, fixed=2_500, total_wh=468_750)
    rows = [(ANA, 0, 833, 2500), (BRUNO, 0, 833, 2500), (CARLA, 0, 834, 2500)]
    return bill, _allocations(BILL_C, rows)


def landlord_view() -> billing.LandlordBillView:
    bill, allocs = bill_a()
    return billing.LandlordBillView(
        bill_id=bill.id,
        period=bill.period,
        total_cents=bill.total_cents,
        status=bill.status,
        rooms=[
            billing.RoomTotal(
                room_id=a.room_id,
                room_name=f"Quarto {_NAMES[a.resident_id]}",
                amount_cents=a.amount_cents,
                energy_wh=a.attributed_total_wh,
            )
            for a in allocs
        ],
    )


def budget() -> billing.Budget:
    return billing.Budget(
        id=stable_id("budget", "carla"),
        household_id=HOUSEHOLD,
        kind=billing.BudgetKind.personal,
        resident_id=CARLA,
        period="2026-11",
        limit_cents=2500,
    )


# --- assistente e automações ---------------------------------------------------------------------


def tool_request() -> agent.AgentToolRequest:
    return agent.AgentToolRequest(
        id=stable_id("tool", "consumo"), tool=agent.AgentTool.consumption_summary, period="2026-11"
    )


def tool_result() -> agent.AgentToolResult:
    return agent.AgentToolResult(
        request_id=tool_request().id,
        tool=agent.AgentTool.consumption_summary,
        status=agent.OperationStatus.succeeded,
        provenance=SIM_ESTIMATED,
        energy_wh=64_000,
        cost_cents=cost_cents(64_000, PRICE_MILLICENTS),
    )


def proposed_action() -> agent.ProposedAction:
    return agent.ProposedAction(
        id=stable_id("action", "desligar"),
        household_id=HOUSEHOLD,
        proposed_for_resident_id=BRUNO,
        command=agent.DeviceCommand(
            target_device_id=METER, capability=agent.DeviceCapability.power, power=False
        ),
        rationale="O aquecedor continua ligado e saíste há 1 h.",
        proposed_at=T0,
        expires_at=T0 + timedelta(minutes=15),
    )


def uncertain_execution() -> agent.ActionExecutionResult:
    """`isError=false` sem releitura confirmativa: incerto, nunca repetir."""
    return agent.ActionExecutionResult(
        action_id=proposed_action().id,
        status=agent.ExecutionStatus.uncertain,
        mcp_is_error=False,
        executed_at=T0 + timedelta(minutes=1),
        code="readback_not_confirmed",
    )


def automation() -> agent.AutomationRule:
    return agent.AutomationRule(
        id=stable_id("automation", "pico"),
        household_id=HOUSEHOLD,
        name="Desligar tomada em pico",
        source=agent.AutomationSource.natural_language,
        nl_text="Se a sala passar de 1,5 kW, desliga.",
        trigger=agent.AutomationTrigger(
            kind=agent.TriggerKind.power_above, device_id=METER, threshold_w=1500, duration_s=1800
        ),
        actions=[
            agent.DeviceCommand(
                target_device_id=METER, capability=agent.DeviceCapability.power, power=False
            )
        ],
        created_by_resident_id=BRUNO,
    )


def notification_preferences() -> notification.NotificationPreferences:
    return notification.NotificationPreferences(resident_id=CARLA)


# --- uma amostra de cada tipo de evento ----------------------------------------------------------


def event_samples() -> list[domain_events.EventBase]:
    """Um evento válido por tipo (os testes garantem cobertura de `EVENT_TYPES`)."""
    e, d = domain_events, {"household_id": HOUSEHOLD, "ts": T0, "correlation_id": CORRELATION}
    attrib = carla_attribution()
    bill = bill_a()[0]
    resp = notification.NotificationResponse(
        notification_id=NOTIFICATION,
        action_id="mine",
        resident_id=CARLA,
        responded_at=T0 + timedelta(minutes=2),
    )
    ref = notification.NotificationRef(type=notification.RefType.consumption_event, id=CONSUMPTION)
    return [
        e.EnergyReadingRecorded(**d, provenance=SIM_MEASURED, data=reading()),
        e.EnergyStepDetected(**d, provenance=SIM_MEASURED, data=step()),
        e.EnergyConsumptionDetected(**d, provenance=SIM_INFERRED, data=consumption()),
        e.EnergyConsumptionClosed(**d, provenance=SIM_INFERRED, data=consumption(closed=True)),
        e.PresenceDoorCrossed(**d, provenance=SIM_INFERRED, data=door_crossed()),
        e.PresenceChanged(**d, provenance=SIM_INFERRED, data=person_presence()),
        e.PresenceCueRecorded(**d, provenance=SIM_INFERRED, data=appliance_cue()),
        e.PresenceConfirmationNeeded(**d, provenance=SIM_INFERRED, data=presence_confirmation()),
        e.PresenceOccupancyChanged(**d, provenance=SIM_INFERRED, data=occupancy()),
        e.SensorReadingRecorded(**d, provenance=SIM_MEASURED, data=window_open()),
        e.SafetyAlertRaised(**d, provenance=SIM_INFERRED, data=window_alert()),
        e.BillingConfirmationNeeded(**d, provenance=SIM_INFERRED, data=confirmation_request()),
        e.BillingAttributionChanged(**d, provenance=attrib.provenance, data=attrib),
        e.BillingBillCreated(**d, provenance=SIM_MEASURED, data=e.BillRef(bill_id=bill.id)),
        e.BillingBillFinalized(**d, provenance=SIM_MEASURED, data=e.BillRef(bill_id=bill.id)),
        e.BillingAllocationPublished(
            **d,
            provenance=SIM_MEASURED,
            data=e.AllocationPublished(
                bill_id=bill.id, allocation_id=bill_a()[1][0].id, resident_id=ANA
            ),
        ),
        e.NotificationCreated(
            **d,
            provenance=SIM_MEASURED,
            data=e.NotificationCreatedData(
                notification_id=NOTIFICATION,
                scope=notification.NotificationScope.household,
                kind=notification.NotificationKind.confirmation_request,
            ),
        ),
        e.NotificationResponded(
            **d, provenance=SIM_MEASURED, data=e.NotificationRespondedData(response=resp, ref=ref)
        ),
        e.AlertsThresholdCrossed(
            **d,
            provenance=SIM_ESTIMATED,
            data=billing.BudgetThreshold(
                budget_id=budget().id,
                resident_id=CARLA,
                period=budget().period,
                pct=80,
                spent_cents=2000,
                limit_cents=budget().limit_cents,
                forecast_cents=3100,
            ),
        ),
        e.AlertsAlertRaised(
            **d,
            provenance=SIM_INFERRED,
            data=e.AlertRaisedData(
                kind=e.AlertKind.peak, severity=notification.NotificationSeverity.warning, ref=ref
            ),
        ),
        e.AlertsColdRoom(
            **d,
            provenance=SIM_MEASURED,
            data=e.ColdRoomData(
                resident_id=ANA,
                room_id=ROOM_ANA,
                cold_nights=3,
                window_nights=7,
                threshold_c=18.0,
                coldest_night_c=15.5,
                last_night=date(2026, 11, 16),
            ),
        ),
        e.AgentActionProposed(**d, provenance=SIM_INFERRED, data=proposed_action()),
        e.AutomationProposed(**d, provenance=SIM_INFERRED, data=automation()),
        e.AutomationExecuted(
            **d,
            provenance=SIM_MEASURED,
            data=e.AutomationExecutedData(rule_id=automation().id, result=uncertain_execution()),
        ),
    ]
