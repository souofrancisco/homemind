from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from homemind.connectors.mcp_energy import observed_at_from_device
from homemind.connectors.mcp_sensors import sensor_readings_from_device
from homemind.contracts.common import Origin, ValueKind
from homemind.contracts.sensors import ContactState, SensorKind, SensorStatus

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
DEVICE_ID = uuid4()


def device(kind, **caps):
    return {
        "type": kind,
        "capabilities": [{"type": name, "value": value} for name, value in caps.items()],
    }


def readings(payload, **kwargs):
    return sensor_readings_from_device(payload, device_id=DEVICE_ID, now=NOW, **kwargs)


@pytest.mark.parametrize(
    ("state", "expected"), [("alarm", ContactState.open), ("normal", ContactState.closed)]
)
def test_contact_state_translation(state, expected):
    reading = readings(device("contactSensor", sensorState=state))[0]
    assert reading.kind is SensorKind.contact
    assert reading.status is SensorStatus.ok
    assert reading.contact is expected
    assert reading.provenance.kind is ValueKind.measured
    assert reading.provenance.origin is Origin.real


@pytest.mark.parametrize("state", [None, "unknown", 4, True])
def test_contact_missing_or_unrecognized_is_unknown(state):
    payload = (
        device("contactSensor") if state is None else device("contactSensor", sensorState=state)
    )
    reading = readings(payload)[0]
    assert reading.status is SensorStatus.unknown
    assert reading.contact is None
    assert reading.provenance.kind is ValueKind.estimated


def test_contact_stale_and_missing_timestamp():
    old = (NOW - timedelta(hours=2, seconds=1)).timestamp() * 1000
    stale = readings(
        {**device("contactSensor", sensorState="normal"), "lastCommunicationTime": old}
    )[0]
    missing = readings(device("contactSensor", sensorState="normal"))[0]
    assert stale.status is SensorStatus.stale and stale.contact is None
    assert stale.provenance.kind is ValueKind.estimated
    assert missing.status is SensorStatus.ok


def test_climate_returns_independent_temperature_then_humidity():
    temperature, humidity = readings(
        device("temperatureSensor", temperatureValue=25.3, humidityValue=61.2)
    )
    assert (temperature.kind, humidity.kind) == (SensorKind.temperature, SensorKind.humidity)
    assert (temperature.temperature_c, humidity.humidity_pct) == (25.3, 61.2)


@pytest.mark.parametrize(
    ("capability", "bad"),
    [
        ("temperatureValue", -40.1),
        ("temperatureValue", 85.1),
        ("humidityValue", -0.1),
        ("humidityValue", 100.1),
        ("temperatureValue", True),
        ("humidityValue", False),
        ("temperatureValue", float("nan")),
        ("humidityValue", float("nan")),
    ],
)
def test_invalid_climate_values_are_unknown(capability, bad):
    temp, humidity = (
        readings(device("temperatureSensor", **{capability: bad}))[0:1]
        + readings(device("temperatureSensor", **{capability: bad}))[1:2]
    )
    reading = temp if capability == "temperatureValue" else humidity
    assert reading.status is SensorStatus.unknown
    assert reading.temperature_c is None and reading.humidity_pct is None


def test_absent_values_and_independent_valid_humidity():
    temperature, humidity = readings(device("temperatureSensor", humidityValue=55))
    assert temperature.status is SensorStatus.unknown
    assert humidity.status is SensorStatus.ok and humidity.humidity_pct == 55
    assert readings(device("temperatureSensor"))[1].status is SensorStatus.unknown


def test_climate_stale_and_custom_stale_threshold():
    payload = {
        **device("temperatureSensor", temperatureValue=20, humidityValue=50),
        "lastCommunicationTime": (NOW - timedelta(hours=2, minutes=1)).timestamp() * 1000,
    }
    temp, humidity = readings(payload)
    assert temp.status is humidity.status is SensorStatus.stale
    fresh = readings(
        payload,
        stale_after={
            SensorKind.temperature: timedelta(hours=3),
            SensorKind.humidity: timedelta(hours=3),
        },
    )
    assert all(item.status is SensorStatus.ok for item in fresh)


@pytest.mark.parametrize(
    "payload", [device("smokeSensor", smokeState="alarm"), device("gateway"), device("plug"), {}]
)
def test_unsupported_device_types_return_empty(payload):
    assert readings(payload) == []


def test_future_timestamp_is_discarded():
    future = {"lastCommunicationTime": (NOW + timedelta(seconds=1)).timestamp() * 1000}
    assert observed_at_from_device(future, NOW) is None


def test_every_returned_reading_satisfies_contract():
    result = readings(
        device("temperatureSensor", temperatureValue=22, humidityValue=40), room_id=uuid4()
    )
    assert len(result) == 2
    assert all(item.device_id == DEVICE_ID and item.ts == NOW for item in result)


def test_non_string_device_type_never_raises():
    for weird in (["contactSensor"], {"a": 1}, 7, None):
        assert sensor_readings_from_device({"type": weird}, device_id=uuid4(), now=NOW) == []


def test_static_contact_sensor_silent_for_minutes_is_still_usable():
    """O contacto reporta por evento: 6 min sem reportar (visto no kit real) NÃO é stale."""
    quiet = (NOW - timedelta(minutes=6)).timestamp() * 1000
    reading = readings(
        {**device("contactSensor", sensorState="normal"), "lastCommunicationTime": quiet}
    )[0]
    assert reading.status is SensorStatus.ok
    assert reading.contact is ContactState.closed
