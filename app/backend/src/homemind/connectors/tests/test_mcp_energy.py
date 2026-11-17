from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from homemind.connectors.mcp_energy import reading_from_device
from homemind.contracts.common import Origin, ValueKind
from homemind.contracts.devices import PowerUnit
from homemind.contracts.energy import ReadingStatus

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
DEVICE_ID = uuid4()


def device(value=1500, unit="W", observed_ms=None):
    result = {"capabilities": [{"type": "instantPower", "value": value, "unit": unit}]}
    if observed_ms is not None:
        result["lastCommunicationTime"] = observed_ms
    return result


def read(payload, override=PowerUnit.unknown):
    return reading_from_device(payload, device_id=DEVICE_ID, now=NOW, unit_override=override)


@pytest.mark.parametrize(
    ("unit", "raw", "expected"), [("W", 15, 15.0), ("dW", 1500, 150.0), ("mW", 1500, 1.5)]
)
def test_known_units_convert_to_usable_watts(unit, raw, expected):
    result = read(device(raw, unit))
    assert result.status is ReadingStatus.ok
    assert result.power_w == expected
    assert result.usable
    assert result.raw_value == raw
    assert result.raw_unit is PowerUnit(unit)
    assert result.provenance.kind is ValueKind.measured


def test_declared_unit_precedes_override():
    result = read(device(1500, "dW"), PowerUnit.W)
    assert result.power_w == 150.0


def test_unknown_unit_retains_raw_value():
    result = read(device(12, "kW"))
    assert result.status is ReadingStatus.unit_unknown
    assert result.power_w is None
    assert result.raw_value == 12
    assert result.raw_unit is PowerUnit.unknown


@pytest.mark.parametrize(
    "payload",
    [
        {"capabilities": []},
        {"capabilities": [{"type": "instantPower", "value": None, "unit": "W"}]},
        device("4"),
        device(True),
        device(float("nan")),
        device(float("inf")),
        device(-1),
    ],
)
def test_invalid_or_absent_value_is_missing(payload):
    result = read(payload)
    assert result.status is ReadingStatus.missing
    assert result.power_w is None
    assert result.raw_value is None
    assert result.raw_unit is PowerUnit.unknown


def test_zero_is_a_valid_reading():
    result = read(device(0))
    assert result.status is ReadingStatus.ok
    assert result.power_w == 0.0


def test_old_observation_is_stale():
    old = NOW - timedelta(seconds=91)
    result = read(device(10, "W", old.timestamp() * 1000))
    assert result.status is ReadingStatus.stale
    assert result.power_w is None
    assert result.raw_value == 10
    assert result.raw_unit is PowerUnit.W


def test_missing_observation_is_not_stale():
    assert read(device(10)).status is ReadingStatus.ok


def test_future_observation_is_discarded():
    future = NOW + timedelta(seconds=1)
    result = read(device(10, "W", future.timestamp() * 1000))
    assert result.observed_at is None
    assert result.status is ReadingStatus.ok


def test_conversion_above_power_limit_is_missing():
    result = read(device(100_001, "W"))
    assert result.status is ReadingStatus.missing
    assert result.power_w is None
    assert result.raw_value is None


@pytest.mark.parametrize(
    ("result", "kind"),
    [
        (device(1, "W"), ValueKind.measured),
        (device(1, "unknown"), ValueKind.estimated),
        ({"capabilities": []}, ValueKind.estimated),
        (device(1, "W", (NOW - timedelta(minutes=5)).timestamp() * 1000), ValueKind.estimated),
    ],
)
def test_provenance_matches_reading_status(result, kind):
    reading = read(result)
    assert reading.provenance.origin is Origin.real
    assert reading.provenance.kind is kind
    assert reading.usable is (reading.status is ReadingStatus.ok)


def test_milliwatt_declared_unit_is_converted_like_mcp_home():
    result = read(device(1500, unit="milliwatt"))
    assert result.status is ReadingStatus.ok
    assert result.power_w == 1.5
    assert result.raw_unit is PowerUnit.mW


def test_override_accepts_plain_string_from_settings():
    payload = {"capabilities": [{"type": "instantPower", "value": 150}]}
    assert read(payload, override="W").power_w == 150.0
    assert read(payload, override="").status is ReadingStatus.unit_unknown
