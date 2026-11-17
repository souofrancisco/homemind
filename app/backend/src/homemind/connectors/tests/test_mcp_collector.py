from datetime import timedelta
from uuid import uuid4

from homemind.connectors.mcp_collector import EnergyCollector
from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, ValueKind
from homemind.contracts.energy import ReadingStatus
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus, load_events
from homemind.features.households.repo import seed_demo


def plug(at, unit="W"):
    return {
        "lastCommunicationTime": int(at.timestamp() * 1000),
        "capabilities": [{"type": "instantPower", "value": 55, "unit": unit}],
    }


def test_deduplication_staleness_and_recovery():
    now = [fx.T0]
    events = []
    collector = EnergyCollector(
        household_id=fx.HOUSEHOLD,
        device_id=fx.reading().device_id,
        publish=events.append,
        clock=lambda: now[0],
    )
    assert collector.ingest(None) is None and collector.last_reading is None
    sample = plug(now[0])
    for _ in range(5):
        assert collector.ingest(sample).status is ReadingStatus.ok
    assert len(events) == 1
    now[0] += timedelta(seconds=30)
    sample = plug(now[0])
    collector.ingest(sample)
    assert len(events) == 2
    now[0] += timedelta(seconds=91)
    for _ in range(3):
        assert collector.ingest(sample).status is ReadingStatus.stale
    assert len(events) == 3 and events[-1].data.power_w is None
    collector.ingest(None)
    assert len(events) == 3 and collector.last_reading is not None
    collector.unavailable()
    assert collector.last_reading is None
    collector.ingest(sample)
    assert len(events) == 4


def test_publish_failure_retries_and_unknown_unit(caplog):
    events = []

    def publish(event):
        events.append(event)
        if len(events) == 1:
            raise RuntimeError("secret payload")

    collector = EnergyCollector(
        household_id=fx.HOUSEHOLD,
        device_id=fx.reading().device_id,
        publish=publish,
        clock=lambda: fx.T0,
    )
    reading = collector.ingest(plug(fx.T0, ""))
    assert reading.status is ReadingStatus.unit_unknown and reading.power_w is None
    collector.ingest(plug(fx.T0, ""))
    assert len(events) == 2 and events[-1].data.power_w is None
    assert "secret payload" not in caplog.text


def test_persists_event_with_provenance(tmp_path):
    db = Database(tmp_path / "collector.sqlite3")
    db.open()
    try:
        migrate(db)
        db.run_sync(seed_demo)
        bus = EventBus(db)
        collector = EnergyCollector(
            household_id=fx.HOUSEHOLD,
            device_id=fx.reading().device_id,
            publish=bus.publish_threadsafe,
            clock=lambda: fx.T0,
        )
        reading = collector.ingest(plug(fx.T0))
        events = db.run_sync(load_events)
        assert len(events) == 1
        event = events[0].event
        assert event.type == "energy.reading_recorded"
        assert event.data == reading and event.provenance == reading.provenance
        assert event.provenance.origin is Origin.real
        assert event.provenance.kind is ValueKind.measured
    finally:
        db.close()


def test_settings_default_empty_unit_means_unknown_not_a_crash():
    """`Settings.mcp_instantpower_unit` é "" por omissão: o collector não pode rebentar."""
    events = []
    collector = EnergyCollector(
        household_id=fx.household().id,
        device_id=uuid4(),
        unit="",
        publish=events.append,
    )
    reading = collector.ingest({"capabilities": [{"type": "instantPower", "value": 55}]})
    assert reading is not None
    assert reading.status is ReadingStatus.unit_unknown
    assert reading.power_w is None
    assert len(events) == 1
