from datetime import timedelta
from uuid import uuid4

from homemind.connectors.mcp_sensor_collector import SensorBinding, SensorCollector
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, ValueKind
from homemind.contracts.sensors import SensorKind, SensorStatus
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus, load_events
from homemind.features.households.repo import seed_demo


def device(kind, at, caps, ident="sensor"):
    return {
        "id": ident,
        "type": kind,
        "lastCommunicationTime": int(at.timestamp() * 1000),
        "capabilities": [{"type": k, "value": v} for k, v in caps.items()],
    }


def test_contact_deduplication_stale_and_recovery():
    now = [fx.T0]
    events = []
    ident, room = uuid4(), uuid4()
    collector = SensorCollector(
        household_id=fx.HOUSEHOLD,
        bindings={"sensor": SensorBinding(ident, room)},
        publish=events.append,
        clock=lambda: now[0],
        stale_after={SensorKind.contact: timedelta(minutes=3)},
    )
    sample = device("contactSensor", now[0], {"sensorState": "normal"})
    for _ in range(5):
        readings = collector.ingest([sample])
    assert len(events) == 1 and readings[0].room_id == room
    now[0] += timedelta(seconds=60)
    sample = device("contactSensor", now[0], {"sensorState": "normal"})
    collector.ingest([sample])
    assert len(events) == 1
    sample["capabilities"][0]["value"] = "alarm"
    collector.ingest([sample])
    sample["capabilities"][0]["value"] = "normal"
    collector.ingest([sample])
    assert len(events) == 3
    now[0] += timedelta(minutes=4)
    for _ in range(3):
        assert collector.ingest([sample])[0].status is SensorStatus.stale
    assert len(events) == 4
    copy = collector.last_readings
    copy.clear()
    assert collector.last_readings
    collector.unavailable()
    assert not collector.last_readings
    collector.ingest([sample])
    assert len(events) == 5


def test_climate_samples_invalid_items_and_unknown():
    now = [fx.T0]
    events = []
    collector = SensorCollector(
        household_id=fx.HOUSEHOLD,
        bindings={"sensor": SensorBinding(uuid4())},
        publish=events.append,
        clock=lambda: now[0],
    )
    sample = device("temperatureSensor", now[0], {"temperatureValue": 20, "humidityValue": 50})
    collector.ingest([sample])
    collector.ingest([sample])
    assert len(events) == 2
    now[0] += timedelta(minutes=1)
    sample = device("temperatureSensor", now[0], {"temperatureValue": 20, "humidityValue": 50})
    collector.ingest([sample])
    assert len(events) == 4
    assert collector.ingest(None) == []
    assert (
        collector.ingest([None, {}, {"id": []}, device("contactSensor", now[0], {}, "other")]) == []
    )
    unknown = collector.ingest([device("contactSensor", now[0], {"sensorState": "invalid"})])
    assert unknown[0].status is SensorStatus.unknown and unknown[0].contact is None


def test_publish_failure_retries_without_secrets(caplog):
    calls = []

    def publish(event):
        calls.append(event)
        if len(calls) == 1:
            raise RuntimeError("secret payload")

    collector = SensorCollector(
        household_id=fx.HOUSEHOLD,
        bindings={"secret-id": SensorBinding(uuid4())},
        publish=publish,
        clock=lambda: fx.T0,
    )
    sample = device("contactSensor", fx.T0, {"sensorState": "normal"}, "secret-id")
    collector.ingest([sample])
    collector.ingest([sample])
    collector.ingest([sample])
    assert len(calls) == 2
    assert "secret" not in caplog.text
    assert "secret-id" not in repr(calls)


def test_persists_event_with_provenance(tmp_path):
    db = Database(tmp_path / "sensors.sqlite3")
    db.open()
    try:
        migrate(db)
        db.run_sync(seed_demo)
        bus = EventBus(db)
        collector = SensorCollector(
            household_id=fx.HOUSEHOLD,
            bindings={"sensor": SensorBinding(uuid4())},
            publish=bus.publish_threadsafe,
            clock=lambda: fx.T0,
        )
        readings = collector.ingest([device("contactSensor", fx.T0, {"sensorState": "normal"})])
        events = db.run_sync(load_events)
        assert len(events) == 1
        event = events[0].event
        assert event.type == "sensor.reading_recorded"
        assert event.data == readings[0] and event.provenance == readings[0].provenance
        assert event.provenance.origin is Origin.real
        assert event.provenance.kind is ValueKind.measured
    finally:
        db.close()
