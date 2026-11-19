"""Contratos da fundação Conta Certa: invariantes, serialização e privacidade."""

import json
import math
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

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
from homemind.contracts import fixtures as fx
from homemind.contracts import household as hh
from homemind.contracts import presence as pr
from homemind.contracts.common import (
    Audit,
    InvalidTransitionError,
    Origin,
    Provenance,
    ValueKind,
    check_transition,
    cost_cents,
    measured,
    replace,
    stable_id,
)

T0 = fx.T0


def bad(model, **kw):
    with pytest.raises(ValidationError):
        model(**kw)


# --- comuns -----------------------------------------------------------------------------------


def test_every_fixture_builds_and_roundtrips_json():
    for obj in [
        fx.household(), *fx.rooms(), *fx.residents(), *fx.memberships(), fx.meter(), fx.heater(),
        fx.heater_signature(), fx.reading(), fx.step(), fx.consumption(), fx.consumption(True),
        fx.door_crossed(), fx.person_presence(), fx.confirmation_request(),
        fx.confirmation_notification(), fx.carla_attribution(), fx.landlord_view(), fx.budget(),
        fx.tool_request(), fx.tool_result(), fx.proposed_action(), fx.uncertain_execution(),
        fx.automation(), *fx.automation_votes(), fx.notification_preferences(),
        *fx.bill_a()[1], fx.bill_a()[0],
        fx.appliance_cue(), fx.presence_confirmation(), fx.occupancy(), fx.presence_device(),
        fx.camera_status(), fx.window_open(), fx.window_alert(), fx.smoke_alert(),
    ]:  # fmt: skip
        again = type(obj).model_validate_json(obj.model_dump_json())
        assert again == obj, type(obj).__name__


def test_unknown_fields_rejected():
    d = fx.door_crossed().model_dump()
    for extra in ("resident_id", "image", "frame", "track_id", "face_embedding"):
        bad(pr.DoorCrossed, **d, **{extra: "x"})


def test_naive_datetime_rejected_and_normalized_to_utc():
    d = fx.door_crossed().model_dump()
    bad(pr.DoorCrossed, **{**d, "ts": datetime(2026, 11, 17, 19, 0)})
    lisbon = timezone(timedelta(hours=1))
    c = pr.DoorCrossed(**{**d, "ts": datetime(2026, 11, 17, 20, 0, tzinfo=lisbon)})
    assert c.ts == T0 and c.ts.utcoffset() == timedelta(0)


@pytest.mark.parametrize("conf", [-0.01, 1.01, math.nan, math.inf])
def test_confidence_must_be_finite_in_unit_interval(conf):
    bad(pr.DoorCrossed, **{**fx.door_crossed().model_dump(), "confidence": conf})


@pytest.mark.parametrize("w", [-1.0, math.nan, math.inf, 100_001.0])
def test_power_must_be_physical(w):
    bad(energy.EnergyReading, **{**fx.reading().model_dump(), "power_w": w})


def test_zero_power_is_valid_and_missing_is_not_zero():
    assert fx.reading(0.0).usable and fx.reading(0.0).power_w == 0.0
    r = energy.EnergyReading(
        id=stable_id("r"), device_id=fx.METER, ts=T0, status=energy.ReadingStatus.missing,
        provenance=measured(),
    )  # fmt: skip
    assert r.power_w is None and not r.usable


def test_money_is_strict_nonnegative_integer_cents():
    d = fx.bill_a()[0].model_dump()
    for v in (-1, 1.5, "100", True, math.nan):
        bad(billing.ElectricityBill, **{**d, "total_cents": v})
    bad(billing.ElectricityBill, **{**d, "fixed_cents": d["total_cents"] + 1})
    bad(billing.ElectricityBill, **{**d, "total_wh": 0})


def test_ids_must_be_uuid():
    bad(hh.Room, id="nao-uuid", household_id=fx.HOUSEHOLD, name="Q", kind="bedroom")


def test_cost_cents_is_exact_and_rounds_once():
    assert cost_cents(192_000, 16_000) == 3072  # 192 kWh a 0,16 €
    assert cost_cents(0, 16_000) == 0
    assert (
        cost_cents(1, 16_000) == 0 and cost_cents(31, 16_000) == 0 and cost_cents(32, 16_000) == 1
    )


# --- proveniência -----------------------------------------------------------------------------


def test_provenance_keeps_origin_and_kind_separate():
    p = Provenance(origin=Origin.simulated, kind=ValueKind.inferred)
    assert p.simulated and p.kind is ValueKind.inferred
    assert Provenance.model_validate("simulated") == Provenance(
        origin=Origin.simulated, kind=ValueKind.measured
    )
    assert Provenance.model_validate("inferred").origin is Origin.real  # compatibilidade
    bad(Provenance, origin="real", kind="simulated")


def test_provenance_combine_takes_least_reliable():
    c = Provenance.combine(measured(), fx.SIM_ESTIMATED, fx.SIM_INFERRED)
    assert c.origin is Origin.simulated and c.kind is ValueKind.inferred
    assert Provenance.combine(measured(), measured()) == measured()
    with pytest.raises(ValueError):
        Provenance.combine()


# --- households -------------------------------------------------------------------------------


def test_membership_invariants():
    base = fx.memberships()[0].model_dump()
    bad(hh.Membership, **{**base, "ends_on": date(2026, 8, 1)})  # antes de starts_on
    bad(hh.Membership, **{**base, "room_id": None})  # inquilino ativo sem quarto
    bad(hh.Membership, **{**base, "status": "ended"})  # terminada sem ends_on
    landlord = fx.memberships()[4].model_dump()
    bad(hh.Membership, **{**landlord, "room_id": fx.ROOM_ANA})
    bad(hh.Membership, **{**landlord, "presence_opt_in": True})  # senhorio nunca opt-in
    bad(hh.Membership, **{**base, "role": "admin"})


def test_membership_active_on_respects_dates_and_status():
    m = fx.memberships()[0]
    assert m.active_on(date(2026, 11, 17)) and not m.active_on(date(2026, 8, 31))
    ended = replace(m, status="ended", ends_on=date(2026, 11, 10))
    assert not ended.active_on(date(2026, 11, 17)) and not ended.active_on(date(2026, 11, 10))
    stale = replace(m, ends_on=date(2026, 11, 10))  # status ainda `active`, mas já expirou
    assert stale.active_on(date(2026, 11, 10)) and not stale.active_on(date(2026, 11, 11))


def test_room_must_belong_to_same_household_and_be_a_bedroom():
    m, rooms = fx.memberships()[0], {r.id: r for r in fx.rooms()}
    hh.check_membership_room(m, rooms[fx.ROOM_ANA])
    with pytest.raises(ValueError, match="outra casa"):
        hh.check_membership_room(m, replace(rooms[fx.ROOM_ANA], household_id=stable_id("outra")))
    with pytest.raises(ValueError, match="zona comum"):
        hh.check_membership_room(replace(m, room_id=fx.ROOM_SALA), rooms[fx.ROOM_SALA])


def test_room_allowance_only_in_bedrooms_and_timezone_validated():
    bad(hh.Room, id=fx.ROOM_SALA, household_id=fx.HOUSEHOLD, name="S", kind="common", included_wh=1)
    bad(hh.HouseholdSettings, timezone="Mars/Olympus", source_kind="demo")


def test_resident_auth_subject_is_distinct_and_hidden_from_repr():
    r = fx.residents()[0]
    assert str(r.id) != r.auth_subject and "sub-ana" not in repr(r)
    assert set(hh.ResidentView.model_fields) == {"id", "display_name"}
    assert "presence_opt_in" not in hh.MemberView.model_fields
    assert "auth_subject" not in hh.MemberView.model_fields


# --- devices ----------------------------------------------------------------------------------


def test_device_external_ref_never_in_view_or_repr():
    d = replace(fx.meter(), source="mcp", external_ref="mcp-secret-123")
    assert "mcp-secret-123" not in repr(d)
    view = devices.DeviceView.of(d)
    assert "external_ref" not in devices.DeviceView.model_fields
    assert "mcp-secret-123" not in view.model_dump_json()
    bad(devices.Device, **{**fx.meter().model_dump(), "source": "mcp", "external_ref": None})


def test_device_is_not_appliance_and_ownership_rules():
    assert "ownership" in devices.Appliance.model_fields and "kind" in devices.Device.model_fields
    bad(devices.ApplianceOwnership, scope="personal")  # pessoal exige dono
    bad(devices.ApplianceOwnership, scope="common", owner_resident_id=fx.ANA)
    h = fx.heater()  # dono Bruno; quem o usa é irrelevante para o contrato
    assert h.ownership.owner_resident_id == fx.BRUNO
    bad(devices.Device, **{**fx.meter().model_dump(), "kind": "bulb", "role": "main_meter"})
    bad(devices.Device, **{**fx.meter().model_dump(), "role": "room_meter", "room_id": None})


def test_signature_tolerance_below_mean():
    bad(
        devices.ApplianceSignature,
        **{**fx.heater_signature().model_dump(), "watts_tolerance": 2500},
    )


# --- energia ----------------------------------------------------------------------------------


def test_reading_status_rules():
    d = fx.reading().model_dump()
    bad(energy.EnergyReading, **{**d, "status": "ok", "power_w": None})
    bad(energy.EnergyReading, **{**d, "status": "unit_unknown"})  # tem power_w e unidade conhecida
    bad(energy.EnergyReading, **{**d, "status": "missing"})
    bad(energy.EnergyReading, **{**d, "raw_unit": "unknown"})  # measured com unidade desconhecida
    bad(energy.EnergyReading, **{**d, "observed_at": T0 + timedelta(seconds=1)})
    unk = energy.EnergyReading(
        id=stable_id("u"), device_id=fx.METER, ts=T0, status="unit_unknown", raw_value=8.0,
        provenance=measured(),
    )  # fmt: skip
    assert unk.power_w is None and not unk.usable  # nunca se converte sem unidade
    stale = energy.EnergyReading(**{**d, "status": "stale"})
    assert not stale.usable


def test_power_step_direction_and_negative_delta():
    up, down = (
        fx.step(),
        energy.PowerStep(**{**fx.step().model_dump(), "before_w": 2040.0, "after_w": 40.0}),
    )
    assert (up.direction, up.delta_w) == ("up", 2000.0) and down.direction == "down"
    assert down.delta_w == -2000.0
    bad(energy.PowerStep, **{**fx.step().model_dump(), "after_w": 40.0})  # sem variação


def test_appliance_match_outcomes():
    a, b = stable_id("a"), stable_id("b")
    cand = energy.ApplianceCandidate
    unknown = energy.ApplianceMatch()
    ambiguous = energy.ApplianceMatch(
        candidates=[cand(appliance_id=a, confidence=0.5), cand(appliance_id=b, confidence=0.48)]
    )
    identified = energy.ApplianceMatch(
        appliance_id=a, confidence=0.9, candidates=[cand(appliance_id=a, confidence=0.9)]
    )
    assert (unknown.outcome, ambiguous.outcome, identified.outcome) == (
        "unknown",
        "ambiguous",
        "identified",
    )
    bad(energy.ApplianceMatch, appliance_id=a)  # sem confiança
    bad(energy.ApplianceMatch, confidence=0.5)  # confiança sem aparelho
    bad(
        energy.ApplianceMatch,
        candidates=[cand(appliance_id=a, confidence=0.1), cand(appliance_id=b, confidence=0.9)],
    )
    bad(energy.ApplianceMatch, candidates=[cand(appliance_id=a, confidence=0.5)] * 2)


def test_consumption_event_lifecycle_and_optional_fields():
    ongoing, closed = fx.consumption(), fx.consumption(True)
    assert ongoing.ended_at is None and closed.energy_wh == 3000
    d = ongoing.model_dump()
    bad(energy.ConsumptionEvent, **{**d, "ended_at": T0 + timedelta(hours=1)})  # a decorrer
    bad(energy.ConsumptionEvent, **{**closed.model_dump(), "energy_wh": None})
    bad(energy.ConsumptionEvent, **{**closed.model_dump(), "ended_at": T0 - timedelta(seconds=1)})
    bad(energy.ConsumptionEvent, **{**d, "location": "room", "room_id": None})
    bad(energy.ConsumptionEvent, **{**d, "location": "unknown"})  # unknown com room_id
    bad(energy.ConsumptionEvent, **{**d, "energy_wh": None})  # custo sem energia
    bad(
        energy.ConsumptionEvent,
        **{**d, "cost_estimate": {"cents": 99, "price_millicents_per_kwh": 16000}},
    )
    no_cost = energy.ConsumptionEvent(**{**d, "cost_estimate": None, "energy_wh": None})
    assert no_cost.cost_estimate is None and no_cost.energy_wh is None  # sem custo inventado
    unknown_loc = energy.ConsumptionEvent(**{**d, "location": "unknown", "room_id": None})
    assert unknown_loc.match.appliance_id is not None


def test_consumption_status_transitions():
    ongoing = fx.consumption()
    ongoing.transition(energy.ConsumptionStatus.closed)
    ongoing.transition(energy.ConsumptionStatus.discarded)
    with pytest.raises(InvalidTransitionError):
        fx.consumption(True).transition(energy.ConsumptionStatus.ongoing)
    with pytest.raises(InvalidTransitionError):
        fx.consumption(True).transition(energy.ConsumptionStatus.discarded)


def test_attribution_state_does_not_live_in_consumption():
    assert "attribution" not in " ".join(energy.ConsumptionStatus.__members__)
    assert {s.value for s in energy.ConsumptionStatus} == {"ongoing", "closed", "discarded"}


# --- presença ---------------------------------------------------------------------------------


def test_presence_rules():
    assert {s.value for s in pr.PresenceState} == {"in", "out", "uncertain"}
    cue = dict(id=stable_id("p"), household_id=fx.HOUSEHOLD, resident_id=fx.CARLA, ts=T0,
               confidence=0.5, provenance=fx.SIM_INFERRED)  # fmt: skip
    pr.PresenceEvent(**cue, state="in", source="wifi")
    bad(pr.PresenceEvent, **cue, state="out", source="wifi")  # sem Wi-Fi não é ausência
    pr.PresenceEvent(**cue, state="out", source="manual")
    bad(pr.PresenceEvent, **cue, state="in", source="camera_door")  # a câmara não identifica
    p = fx.person_presence().model_dump()
    bad(pr.PersonPresence, **{**p, "state": "uncertain"})  # sem motivo
    bad(pr.PersonPresence, **{**p, "reason": "conflicting_cues"})  # motivo sem incerteza
    unsure = pr.PersonPresence(
        **{**p, "state": "uncertain", "reason": "conflicting_cues", "confidence": 0.4}
    )
    assert unsure.state is pr.PresenceState.uncertain
    bad(pr.PersonPresence, **{**p, "sources": ["wifi", "wifi"]})


def test_door_crossed_is_anonymous():
    fields = set(pr.DoorCrossed.model_fields)
    assert fields == {"ts", "direction", "confidence", "provenance"}


def test_presence_cue_rules():
    cue = fx.appliance_cue().model_dump()
    bad(pr.PresenceEvent, **{**cue, "state": "out"})  # um aparelho não prova ausência
    bad(pr.PresenceEvent, **{**cue, "consumption_event_id": None})
    bad(pr.PresenceEvent, **{**cue, "source": "manual"})  # manual não aponta para um consumo
    bad(pr.PresenceEvent, **{**cue, "state": "uncertain"})  # a dúvida é da fusão
    manual = {**cue, "source": "manual", "consumption_event_id": None}
    assert pr.PresenceEvent(**{**manual, "state": "out"}).state is pr.PresenceState.away
    pr.PresenceMeIn(state="in")
    pr.PresenceMeIn(state="out")
    bad(pr.PresenceMeIn, state="uncertain")


def test_consumption_owner_only_with_identified_appliance():
    c = fx.consumption().model_dump()
    assert c["appliance_owner_resident_id"] == fx.BRUNO
    unknown = energy.ApplianceMatch().model_dump()
    bad(energy.ConsumptionEvent, **{**c, "match": unknown})
    energy.ConsumptionEvent(**{**c, "match": unknown, "appliance_owner_resident_id": None})


def test_presence_confirmation_becomes_a_personal_presence_check():
    req = fx.presence_confirmation()
    assert pr.PRESENCE_CONFIRMATION_ACTIONS == ("in", "out")
    n = fx.confirmation_notification().model_dump()
    check = {
        **n,
        "scope": "personal",
        "recipient_resident_id": req.resident_id,
        "responder_ids": [req.resident_id],
        "kind": "presence_check",
        "actions": [{"id": a, "label": a} for a in pr.PRESENCE_CONFIRMATION_ACTIONS],
        "ref": {"type": "presence_check", "id": req.id},
        "expires_at": req.expires_at,
    }
    notification.Notification(**check)
    bad(notification.Notification, **{**check, "expires_at": None})
    bad(
        notification.Notification,
        **{**check, "scope": "household", "recipient_resident_id": None},
    )


def test_occupancy_is_anonymous_and_conservative():
    o = fx.occupancy().model_dump()
    assert not {"resident_id", "resident_ids", "visitor_ids"} & set(o)
    bad(pr.HouseOccupancy, **{**o, "people_inside": None})  # contagem perdida não é «ocupada»
    pr.HouseOccupancy(**{**o, "people_inside": None, "visitors": None, "state": "uncertain"})
    bad(pr.HouseOccupancy, **{**o, "state": "likely_empty"})
    empty = {**o, "state": "likely_empty", "people_inside": 0, "visitors": 0, "residents_home": 0}
    pr.HouseOccupancy(**empty)
    bad(pr.HouseOccupancy, **{**empty, "state": "occupied"})
    bad(pr.HouseOccupancy, **{**o, "visitors": 4})


def test_presence_device_consent_and_hidden_key():
    d = fx.presence_device()
    assert "match_key" not in repr(d)
    assert "match_key" not in pr.PresenceDeviceView.of(d).model_dump()
    raw = d.model_dump()
    bad(pr.PresenceDevice, **{**raw, "consented_at": None})
    bad(pr.PresenceDevice, **{**raw, "revoked_at": T0})  # revogado mas ainda opt-in
    pr.PresenceDevice(**{**raw, "wifi_opt_in": False, "revoked_at": T0})
    bad(pr.PresenceDevice, **{**raw, "wifi_opt_in": False, "revoked_at": T0 - timedelta(days=2)})
    bad(pr.PresenceDevice, **{**raw, "match_key": "aa:bb"})


def test_camera_status_labels_fallback_as_simulated():
    s = fx.camera_status().model_dump()
    bad(pr.CameraStatus, **{**s, "origin": "real"})  # clip nunca é o feed real
    pr.CameraStatus(**{**s, "source": "rtsp", "origin": "real"})
    bad(pr.CameraStatus, **{**s, "camera_ok": False})  # falha com fps
    pr.CameraStatus(**{**s, "camera_ok": False, "fps": None})


# --- sensores e segurança -------------------------------------------------------------------------


def test_sensor_reading_values_match_kind_and_unknown_has_no_value():
    r = fx.window_open().model_dump()
    assert fx.window_open().usable
    bad(sensors.SensorReading, **{**r, "contact": None})
    bad(sensors.SensorReading, **{**r, "smoke_detected": False})
    unknown = sensors.SensorReading(**{**r, "status": "unknown", "contact": None})
    assert not unknown.usable
    bad(sensors.SensorReading, **{**r, "status": "stale"})  # stale com valor
    smoke = {**r, "kind": "smoke", "contact": None}
    sensors.SensorReading(**{**smoke, "smoke_detected": False})
    bad(sensors.SensorReading, **{**r, "kind": "temperature", "contact": None, "temperature_c": 99})


def test_safety_alert_guards():
    w = fx.window_alert().model_dump()
    bad(safety.SafetyAlert, **{**w, "notify_landlord": True})
    bad(safety.SafetyAlert, **{**w, "consumption_event_id": None})
    on = {**w["suggested_command"], "power": True}
    bad(safety.SafetyAlert, **{**w, "suggested_command": on})  # nunca sugere ligar
    bad(safety.SafetyAlert, **{**w, "status": "resolved"})  # sem resolved_at
    safety.SafetyAlert(**{**w, "status": "resolved", "resolved_at": T0 + timedelta(minutes=9)})
    s = fx.smoke_alert().model_dump()
    bad(safety.SafetyAlert, **{**s, "severity": "warning"})
    bad(safety.SafetyAlert, **{**s, "suggested_command": w["suggested_command"]})


# --- atribuição e faturação ---------------------------------------------------------------------


def test_attribution_invariants_and_supersede():
    a = fx.carla_attribution()
    bad(billing.Attribution, **{**a.model_dump(), "target_resident_id": None})
    bad(billing.Attribution, **{**a.model_dump(), "target_type": "common"})
    bad(billing.Attribution, **{**a.model_dump(), "confidence": 0.9})  # não-inferida com confiança
    bad(billing.Attribution, **{**a.model_dump(), "provenance": fx.SIM_INFERRED})  # inferida sem
    bad(billing.Attribution, **{**a.model_dump(),
        "decided_by": Audit(at=T0, by_system="billing")})  # fmt: skip
    new = billing.Attribution(**{
        **a.model_dump(), "id": stable_id("attr2"), "target_type": "common",
        "target_resident_id": None,
        "method": "equal_fallback", "decided_by": Audit(at=T0, by_system="billing"),
        "supersedes_id": a.id,
    })  # fmt: skip
    old, cur = billing.supersede(a, new)
    assert old.status is billing.AttributionStatus.superseded and cur.status.value == "active"
    billing.assert_single_active([old, cur])
    with pytest.raises(billing.AttributionConflictError):
        billing.assert_single_active([a, new])  # duas ativas para o mesmo consumo
    with pytest.raises(billing.AttributionConflictError):
        billing.supersede(old, new)  # já substituída


@pytest.mark.parametrize("make", [fx.bill_a, fx.bill_b, fx.bill_c])
def test_pdf_fixtures_sum_exactly(make):
    bill, allocs = make()
    billing.validate_allocations(bill, allocs)
    assert sum(a.amount_cents for a in allocs) == bill.total_cents == 12_000 or make is fx.bill_c


def test_fixture_amounts_match_the_pdf():
    assert [a.amount_cents for a in fx.bill_a()[1]] == [4512, 2976, 2464, 2048]
    assert [a.amount_cents for a in fx.bill_b()[1]] == [4680, 2760, 2440, 2120]
    assert [a.amount_cents for a in fx.bill_c()[1]] == [
        3333,
        3333,
        3334,
    ]  # Ana, Bruno, Carla (D-34)
    assert fx.bill_a()[0].energy_cents == 9600


def test_allocations_validation_catches_inconsistencies():
    bill, allocs = fx.bill_a()
    with pytest.raises(billing.BillInconsistentError, match="soma"):
        billing.validate_allocations(bill, allocs[:3])
    with pytest.raises(billing.BillInconsistentError, match="repetido"):
        billing.validate_allocations(bill, [*allocs[:3], allocs[0]])
    other, _ = fx.bill_b()
    with pytest.raises(billing.BillInconsistentError, match="outra fatura"):
        billing.validate_allocations(other, allocs)
    small = replace(bill, total_wh=100_000)  # kWh atribuídos acima da fatura
    with pytest.raises(billing.BillInconsistentError, match="kWh"):
        billing.validate_allocations(small, allocs)
    a = allocs[0].model_dump()
    bad(billing.BillAllocation, **{**a, "amount_cents": a["amount_cents"] + 1})
    bad(billing.BillAllocation, **{**a, "breakdown": a["breakdown"][:2]})


def test_breakdown_negative_only_adjustment():
    ok = dict(label="Plafond", amount_cents=-100)
    billing.BillBreakdownLine(kind="adjustment", **ok)
    bad(billing.BillBreakdownLine, kind="room", **ok)


def test_bill_state_machine_and_revisions():
    bill = fx.bill_a()[0]
    bill.transition(billing.BillStatus.finalized)
    fin = replace(bill, status="finalized")
    fin.transition(billing.BillStatus.superseded)
    with pytest.raises(InvalidTransitionError):
        fin.transition(billing.BillStatus.draft)  # finalizada não volta a rascunho
    with pytest.raises(InvalidTransitionError):
        fin.transition(billing.BillStatus.finalized)
    bad(billing.ElectricityBill, **{**bill.model_dump(), "revision": 2})  # sem supersedes_id
    replace(bill, revision=2, supersedes_id=bill.id)
    bad(billing.BillPeriod, start=date(2026, 11, 30), end=date(2026, 11, 1))
    assert billing.BillPeriod(start=date(2026, 11, 1), end=date(2026, 11, 30)).days == 30


def test_landlord_view_has_only_room_totals():
    v = fx.landlord_view()
    assert sum(r.amount_cents for r in v.rooms) == v.total_cents
    dumped = v.model_dump_json()
    for forbidden in ("resident", "appliance", "presence", "device"):
        assert forbidden not in dumped


def test_budget_rules():
    b = fx.budget()
    assert b.thresholds == [50, 80, 100]
    d = b.model_dump()
    bad(billing.Budget, **{**d, "thresholds": [80, 50]})
    bad(billing.Budget, **{**d, "last_threshold_notified": 90})
    bad(billing.Budget, **{**d, "period": "2026-13"})
    bad(billing.Budget, **{**d, "limit_cents": None})
    bad(billing.Budget, **{**d, "kind": "room_allowance"})


def fx_bill_in():
    return billing.BillIn(
        period=billing.BillPeriod(start=date(2026, 11, 1), end=date(2026, 11, 30)),
        total_cents=12_000, fixed_cents=2_400, total_wh=600_000,
    )  # fmt: skip


def test_contestation_state():
    base = dict(id=stable_id("c"), bill_id=stable_id("b"), allocation_id=stable_id("al"),
                resident_id=fx.CARLA, reason="x", created_at=T0)  # fmt: skip
    billing.Contestation(**base)
    bad(billing.Contestation, **base, status="accepted")  # sem resolved_at
    bad(billing.Contestation, **base, resolved_at=T0)  # aberta com resolved_at
    done = dict(resolved_at=T0, resolution="ok")
    billing.Contestation(**base, status="rejected", **done)
    bad(billing.Contestation, **base, status="rejected", resolved_at=T0)  # sem justificação
    bad(billing.Contestation, **base, status="accepted", **done)  # aceite sem revisão
    billing.Contestation(**base, status="accepted", revision_bill_id=stable_id("b2"), **done)
    bad(billing.ContestationDecisionIn, status="rejected", resolution="x", bill=fx_bill_in())


# --- notificações -------------------------------------------------------------------------------

NOW = T0 + timedelta(minutes=2)


def test_notification_respond_first_wins_and_records_author():
    n = fx.confirmation_notification()
    assert n.can_respond(fx.CARLA, NOW) and not n.can_respond(fx.LANDLORD, NOW)
    done = n.respond(fx.CARLA, "mine", NOW)
    assert done.status is notification.NotificationStatus.actioned
    assert done.response.resident_id == fx.CARLA and done.response.responded_at == NOW
    with pytest.raises(notification.AlreadyRespondedError):
        done.respond(fx.ANA, "everyone", NOW)  # concorrente tardio
    with pytest.raises(notification.AlreadyRespondedError):
        done.respond(fx.CARLA, "mine", NOW)  # repetição
    assert not done.can_respond(fx.CARLA, NOW)


def test_notification_respond_guards():
    n = fx.confirmation_notification()
    with pytest.raises(notification.NotAllowedToRespondError):
        n.respond(fx.LANDLORD, "mine", NOW)  # o senhorio nunca responde
    with pytest.raises(notification.UnknownActionError):
        n.respond(fx.CARLA, "delete_everything", NOW)
    late = n.expires_at + timedelta(seconds=1)
    assert n.is_expired(late) and not n.can_respond(fx.CARLA, late)
    with pytest.raises(notification.NotificationExpiredError):
        n.respond(fx.CARLA, "mine", late)
    # o original (imutável) não foi alterado
    assert n.status is notification.NotificationStatus.unread and n.response is None


def test_notification_structure_rules():
    d = fx.confirmation_notification().model_dump()
    bad(notification.Notification, **{**d, "scope": "personal"})  # sem destinatário
    bad(notification.Notification, **{**d, "responder_ids": []})  # ações sem quem responda
    bad(notification.Notification, **{**d, "expires_at": None})  # pedido sem prazo
    bad(notification.Notification, **{**d, "status": "actioned"})  # sem response
    bad(notification.Notification, **{**d, "actions": d["actions"] * 2})
    personal = {
        **d,
        "scope": "personal",
        "recipient_resident_id": fx.CARLA,
        "responder_ids": [fx.ANA],
    }
    bad(notification.Notification, **personal)
    bad(notification.NotificationAction, id="Não Sei!", label="x")


def test_notification_status_transitions():
    n = fx.confirmation_notification()
    n.transition(notification.NotificationStatus.read)
    for terminal in (
        notification.NotificationStatus.actioned,
        notification.NotificationStatus.expired,
    ):
        done = (
            replace(n, status=terminal, response=None)
            if terminal is notification.NotificationStatus.expired
            else None
        )
        if done:
            with pytest.raises(InvalidTransitionError):
                done.transition(notification.NotificationStatus.read)
    with pytest.raises(InvalidTransitionError):
        check_transition(
            notification.NOTIFICATION_TRANSITIONS,
            notification.NotificationStatus.read,
            notification.NotificationStatus.unread,
        )


def test_notification_view_hides_other_residents():
    n = fx.confirmation_notification().respond(fx.CARLA, "mine", NOW)
    mine = notification.NotificationView.for_resident(n, fx.CARLA, NOW)
    theirs = notification.NotificationView.for_resident(n, fx.ANA, NOW)
    assert mine.response.by_me and not theirs.response.by_me and not theirs.can_respond
    assert str(fx.CARLA) not in theirs.model_dump_json()
    assert notification.NotificationView.for_resident(
        fx.confirmation_notification(), fx.ANA, T0 + timedelta(days=2)
    ).status is notification.NotificationStatus.expired  # fmt: skip


def test_preferences_and_confirmation_request():
    bad(
        notification.NotificationPreferences,
        resident_id=fx.CARLA,
        disabled_kinds=["security_alert"],
    )
    r = fx.confirmation_request().model_dump()
    bad(notification.ConfirmationRequest, **{**r, "eligible_resident_ids": []})
    bad(notification.ConfirmationRequest, **{**r, "options": ["mine", "mine"]})
    assert (
        notification.ConfirmationRequest(**{**r, "estimated_cost_cents": None}).estimated_cost_cents
        is None
    )


# --- agente e automações ------------------------------------------------------------------------


def test_agent_tool_arguments_and_results():
    bad(agent.AgentToolRequest, id=stable_id("t"), tool="receipt", period="2026-11")
    bad(agent.AgentToolRequest, id=stable_id("t"), tool="consumption_summary")
    agent.AgentToolRequest(id=stable_id("t"), tool="receipt", bill_id=fx.BILL_A)
    r = fx.tool_result().model_dump()
    bad(agent.AgentToolResult, **{**r, "provenance": None})  # números sem proveniência
    bad(agent.AgentToolResult, **{**r, "status": "failed", "error_code": "x"})
    ok = agent.AgentToolResult(
        request_id=stable_id("t"), tool="budget_status", status="failed", error_code="no_data"
    )
    assert ok.energy_wh is None  # sem dados: «não sei», nunca 0


def test_device_command_is_typed_and_minimal():
    dev = fx.METER
    agent.DeviceCommand(target_device_id=dev, capability="brightness", brightness=40)
    bad(agent.DeviceCommand, target_device_id=dev, capability="power")
    bad(agent.DeviceCommand, target_device_id=dev, capability="power", power=True, brightness=10)
    bad(agent.DeviceCommand, target_device_id=dev, capability="brightness", brightness=101)
    bad(
        agent.DeviceCommand, target_device_id=dev, capability="alarm", power=True
    )  # fora da política


def test_execution_result_never_claims_success_without_readback():
    base = dict(action_id=stable_id("a"), executed_at=T0)
    bad(agent.ActionExecutionResult, **base, status="confirmed", mcp_is_error=False)
    ok = agent.ActionExecutionResult(
        **base, status="confirmed", mcp_is_error=False, readback_confirmed=True
    )
    assert not ok.may_retry
    unc = fx.uncertain_execution()
    assert unc.status is agent.ExecutionStatus.uncertain and not unc.may_retry  # nunca repetir
    blocked = agent.ActionExecutionResult(**base, status="blocked", code="writes_disabled")
    assert blocked.may_retry
    bad(agent.ActionExecutionResult, **base, status="blocked", code="x", mcp_is_error=False)
    bad(agent.ActionExecutionResult, **base, status="failed", readback_confirmed=True, code="x")
    bad(agent.ActionExecutionResult, **base, status="failed")  # sem code


def test_proposed_action_always_needs_confirmation():
    a = fx.proposed_action()
    assert a.requires_confirmation is True
    bad(agent.ProposedAction, **{**a.model_dump(), "requires_confirmation": False})
    bad(agent.ProposedAction, **{**a.model_dump(), "expires_at": a.proposed_at})
    a.transition(agent.ActionStatus.confirmed)
    with pytest.raises(InvalidTransitionError):
        replace(a, status="rejected").transition(agent.ActionStatus.confirmed)


def test_automation_rules_and_transitions():
    r = fx.automation()
    bad(agent.AutomationRule, **{**r.model_dump(), "status": "active"})  # sem aprovação
    bad(agent.AutomationRule, **{**r.model_dump(), "requires_confirmation": False})
    bad(agent.AutomationRule, **{**r.model_dump(), "actions": []})
    bad(agent.AutomationRule, **{**r.model_dump(), "nl_text": None})
    r.transition(agent.AutomationStatus.proposed)
    with pytest.raises(InvalidTransitionError):
        r.transition(agent.AutomationStatus.active)  # tem de passar por `proposed`
    bad(agent.AutomationTrigger, kind="power_above")


def _rule_with(command: dict):
    return {**fx.automation().model_dump(), "actions": [command]}


def test_automation_rule_only_turns_a_plug_off():
    plug = fx.PLUG_SALA
    ok = agent.AutomationRule(
        **_rule_with({"target_device_id": plug, "capability": "power", "power": False})
    )
    assert ok.actions[0].power is False
    bad(
        agent.AutomationRule,
        **_rule_with({"target_device_id": plug, "capability": "power", "power": True}),
    )
    for cap, extra in (
        ("brightness", {"brightness": 50}),
        ("color_rgb", {"color_rgb": {"r": 1, "g": 2, "b": 3}}),
    ):
        bad(
            agent.AutomationRule,
            **_rule_with({"target_device_id": plug, "capability": cap, **extra}),
        )
    two = [
        *fx.automation().actions,
        agent.DeviceCommand(target_device_id=plug, capability="power", power=True),
    ]
    bad(agent.AutomationRule, **{**fx.automation().model_dump(), "actions": two})
    # continua a exigir aprovação para estar ativa
    bad(agent.AutomationRule, **{**fx.automation().model_dump(), "status": "active"})
    agent.AutomationRule(
        **{**fx.automation().model_dump(), "status": "active", "approved_by_resident_id": fx.ANA}
    )


def _votes(*pairs: tuple[UUID, bool]) -> list[agent.AutomationVote]:
    return [
        agent.AutomationVote(resident_id=r, approve=a, at=T0 + timedelta(minutes=i))
        for i, (r, a) in enumerate(pairs)
    ]


@pytest.mark.parametrize(("n", "majority"), [(1, 1), (2, 2), (3, 2), (4, 3), (5, 3)])
def test_absolute_majority_is_more_than_half(n, majority):
    assert agent.absolute_majority(n) == majority
    ids = [stable_id("m", str(i)) for i in range(n)]
    out = agent.rule_approval_outcome(_votes(*[(r, True) for r in ids[: majority - 1]]), ids)
    assert out.verdict is agent.RuleVerdict.pending or majority == 1
    out = agent.rule_approval_outcome(_votes(*[(r, True) for r in ids[:majority]]), ids)
    assert out.verdict is agent.RuleVerdict.approved and out.majority == majority and out.decided


def test_rule_outcome_rejects_as_soon_as_majority_is_impossible():
    ids = [stable_id("m", str(i)) for i in range(4)]  # maioria 3: 2 contra chegam
    one = agent.rule_approval_outcome(_votes((ids[0], False)), ids)
    assert one.verdict is agent.RuleVerdict.pending
    two = agent.rule_approval_outcome(_votes((ids[0], False), (ids[1], False)), ids)
    assert two.verdict is agent.RuleVerdict.rejected and (two.votes_for, two.votes_against) == (
        0,
        2,
    )
    ids2 = ids[:2]  # maioria 2: um contra chega
    assert (
        agent.rule_approval_outcome(_votes((ids2[0], False)), ids2).verdict
        is agent.RuleVerdict.rejected
    )
    ids3 = ids[:3]  # maioria 2: um contra não chega, dois sim
    assert (
        agent.rule_approval_outcome(_votes((ids3[0], False)), ids3).verdict
        is agent.RuleVerdict.pending
    )
    assert (
        agent.rule_approval_outcome(_votes((ids3[0], False), (ids3[1], False)), ids3).verdict
        is agent.RuleVerdict.rejected
    )


def test_rule_outcome_expiry_without_majority_rejects_but_majority_still_wins():
    ids = [stable_id("m", str(i)) for i in range(5)]  # maioria 3
    short = _votes((ids[0], True), (ids[1], True))
    assert agent.rule_approval_outcome(short, ids).verdict is agent.RuleVerdict.pending
    assert (
        agent.rule_approval_outcome(short, ids, expired=True).verdict is agent.RuleVerdict.rejected
    )
    assert agent.rule_approval_outcome([], ids, expired=True).verdict is agent.RuleVerdict.rejected
    full = _votes((ids[0], True), (ids[1], True), (ids[2], True))
    assert (
        agent.rule_approval_outcome(full, ids, expired=True).verdict is agent.RuleVerdict.approved
    )


def test_rule_outcome_with_fixture_votes_and_invalid_votes():
    four = [fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO]
    out = agent.rule_approval_outcome(fx.automation_votes(), four)
    assert (out.verdict, out.votes_for, out.votes_against, out.majority) == (
        agent.RuleVerdict.pending,
        2,
        1,
        3,
    )  # 2 a favor < maioria de 3
    with pytest.raises(ValueError):
        agent.rule_approval_outcome(_votes((fx.ANA, True), (fx.ANA, False)), four)
    with pytest.raises(ValueError):
        agent.rule_approval_outcome(_votes((stable_id("intruso"), True)), four)
    with pytest.raises(ValueError):
        agent.rule_approval_outcome([], [])
    with pytest.raises(ValueError):
        agent.rule_approval_outcome([], [fx.ANA, fx.ANA])


def test_vote_events_carry_only_counts():
    decided = next(s for s in fx.event_samples() if s.type == "automation.vote_decided")
    assert set(decided.data.model_dump()) == {
        "rule_id", "verdict", "votes_for", "votes_against", "eligible", "expired",
    }  # fmt: skip
    bad(
        domain_events.AutomationVoteDecidedData,
        **{**decided.data.model_dump(), "verdict": "pending"},
    )
    changed = next(s for s in fx.event_samples() if s.type == "automation.status_changed")
    bad(
        domain_events.AutomationStatusChangedData,
        **{**changed.data.model_dump(), "to_status": "active"},
    )


# --- eventos de domínio ---------------------------------------------------------------------------


def test_every_event_type_has_a_sample_and_roundtrips_json():
    samples = fx.event_samples()
    assert {s.type for s in samples} == set(domain_events.EVENT_TYPES) and len(samples) == 30
    for s in samples:
        wire = s.model_dump_json()
        back = domain_events.domain_event_adapter.validate_json(wire)
        assert back == s and type(back) is type(s)
        assert json.loads(wire)["schema_version"] == 1


def test_event_types_cover_the_documented_list():
    documented = {
        "energy.reading_recorded", "energy.step_detected", "energy.consumption_detected",
        "energy.consumption_closed", "energy.identification_needed",
        "presence.door_crossed", "presence.changed",
        "presence.cue_recorded", "presence.confirmation_needed", "presence.occupancy_changed",
        "sensor.reading_recorded", "safety.alert_raised", "safety.away_changed",
        "billing.confirmation_needed", "billing.attribution_changed", "billing.bill_created",
        "billing.bill_finalized", "billing.allocation_published", "billing.contestation_changed",
        "billing.rules_proposal_changed",
        "notification.created",
        "notification.responded", "alerts.threshold_crossed", "alerts.alert_raised",
        "alerts.cold_room",
        "agent.action_proposed", "automation.proposed", "automation.executed",
        "automation.vote_decided", "automation.status_changed",
    }  # fmt: skip
    assert set(domain_events.EVENT_TYPES) == documented


def test_event_rejects_bad_input():
    adapter = domain_events.domain_event_adapter
    wire = json.loads(fx.event_samples()[0].model_dump_json())
    with pytest.raises(ValidationError):
        adapter.validate_python({**wire, "type": "energy.nope"})
    with pytest.raises(ValidationError):
        adapter.validate_python({**wire, "type": "presence.changed"})  # payload de outro tipo
    with pytest.raises(ValidationError):
        adapter.validate_python({**wire, "schema_version": 2})
    with pytest.raises(ValidationError):
        adapter.validate_python({**wire, "seq": 7})  # o produtor não define seq
    with pytest.raises(ValidationError):
        adapter.validate_python({**wire, "ts": "2026-11-17T19:00:00"})  # sem fuso
    with pytest.raises(ValidationError):
        adapter.validate_python({**wire, "id": "x"})
    with pytest.raises(ValidationError):
        adapter.validate_python({**wire, "data": {**wire["data"], "token": "x"}})


def test_event_provenance_and_household_must_match_payload():
    s = fx.event_samples()[0]
    d = s.model_dump()
    with pytest.raises(ValidationError, match="proveniência"):
        domain_events.EnergyReadingRecorded(**{**d, "provenance": measured()})  # real vs simulada
    other = stable_id("outra-casa")
    c = fx.event_samples()[2].model_dump()
    with pytest.raises(ValidationError, match="outra casa"):
        domain_events.EnergyConsumptionDetected(**{**c, "household_id": other})


def test_consumption_event_types_match_status():
    c = fx.event_samples()[2].model_dump()
    with pytest.raises(ValidationError):
        domain_events.EnergyConsumptionDetected(**{**c, "data": fx.consumption(True).model_dump()})
    with pytest.raises(ValidationError):
        domain_events.EnergyConsumptionClosed(**{**c, "type": "energy.consumption_closed"})


def test_events_are_immutable_and_ids_stable():
    s = fx.event_samples()[0]
    with pytest.raises(ValidationError):
        s.id = stable_id("x")  # type: ignore[misc]
    a = domain_events.BillingBillCreated(
        ts=T0,
        household_id=fx.HOUSEHOLD,
        provenance=fx.SIM_MEASURED,
        data=domain_events.BillRef(bill_id=fx.BILL_A),
    )
    b = domain_events.BillingBillCreated(
        ts=T0,
        household_id=fx.HOUSEHOLD,
        provenance=fx.SIM_MEASURED,
        data=domain_events.BillRef(bill_id=fx.BILL_A),
    )
    assert a.id != b.id and a.correlation_id != b.correlation_id  # novos por omissão


def test_stored_event_carries_seq_from_persistence():
    s = domain_events.StoredEvent(seq=1, event=fx.event_samples()[3])
    assert domain_events.StoredEvent.model_validate_json(s.model_dump_json()) == s
    bad(domain_events.StoredEvent, seq=0, event=fx.event_samples()[0])


def test_no_event_payload_can_carry_images_or_external_ids():
    banned = {
        "image",
        "frame",
        "frames",
        "jpeg",
        "external_ref",
        "token",
        "access_token",
        "api_key",
    }
    seen: set[str] = set()

    def walk(model, depth=0):
        if depth > 6:
            return
        for name, f in model.model_fields.items():
            seen.add(name)
            for t in _types(f.annotation):
                if hasattr(t, "model_fields"):
                    walk(t, depth + 1)

    for cls in domain_events.EVENT_TYPES.values():
        walk(cls)
    assert not (banned & seen)


def _types(ann):
    from typing import get_args

    args = get_args(ann)
    return [ann, *[x for a in args for x in _types(a)]] if args else [ann]
