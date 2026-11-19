"""Sessão FakeKit SIMULADA: exercita a ligação de produção sem hardware/rede.

Origin.real é a configuração exigida à ligação de produção sob teste; estes dados
continuam a ser cenários inventados, numa BD de teste isolada.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from homemind.connectors.fake_home import FakeHome
from homemind.connectors.fake_mcp import FakeKit
from homemind.connectors.mcp_home import McpHome
from homemind.contracts.common import Origin
from homemind.core.config import Settings
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus, load_events
from homemind.features.appliances.repo import SqliteApplianceCatalog
from homemind.features.energy.kit import attach_kit_collectors

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)


@pytest.fixture
def kit_setup(tmp_path):
    db = Database(tmp_path / "kit.sqlite3")
    db.open()
    migrate(db)
    house = uuid4()
    db.run_sync(
        lambda conn: conn.execute(
            "INSERT INTO household (id,name,timezone,source_kind,created_at)"
            " VALUES (?,'Kit de teste','Europe/Lisbon','demo',?)",
            (str(house), NOW.isoformat()),
        )
    )
    settings = Settings(
        _env_file=None,
        home_backend="mcp",
        energy_household_id=house,
        mcp_instantpower_unit="W",
        mcp_lamp_id="",
        mcp_plug_id="",
        enable_physical_writes=False,
    )
    kit = FakeKit(clock=lambda: NOW)
    home = McpHome(settings, kit.session_factory, simulated=True)
    catalog = Mock(wraps=SqliteApplianceCatalog())
    bus = EventBus(db)
    with asyncio.Runner() as runner:
        runner.run(bus.start())
        context = SimpleNamespace(
            db=db,
            house=house,
            settings=settings,
            kit=kit,
            home=home,
            catalog=catalog,
            bus=bus,
            run=runner.run,
        )
        try:
            yield context
        finally:
            runner.run(context.home.parar())
            runner.run(bus.stop())
            db.close()
    assert not kit.writes()


def attach(ctx):
    ctx.run(
        attach_kit_collectors(
            ctx.home,
            settings=ctx.settings,
            db=ctx.db,
            bus=ctx.bus,
            catalog=ctx.catalog,
            clock=lambda: NOW,
        )
    )


def devices(ctx):
    return ctx.db.run_sync(lambda conn: conn.execute("SELECT * FROM device").fetchall())


def events(ctx):
    return [stored.event for stored in ctx.db.run_sync(load_events)]


def assert_private(ctx, caplog):
    serialized = " ".join(event.model_dump_json() for event in events(ctx))
    for ref in ctx.kit.dev:
        assert ref not in serialized
        assert ref not in caplog.text


def test_lazy_registration_readings_and_internal_ids(kit_setup, caplog):
    ctx = kit_setup
    # Tal como no engine: primeira leitura antes de ligar os collectors.
    ctx.run(ctx.home._refrescar())
    attach(ctx)
    assert devices(ctx) == []
    assert events(ctx) == []
    for _ in range(3):
        ctx.run(ctx.home._refrescar())
    rows = devices(ctx)
    assert len(rows) == ctx.catalog.register_device.call_count == 3
    by_ref = {row["external_ref"]: row for row in rows}
    assert set(by_ref) == {ctx.kit.PLUG, ctx.kit.CONTACT, ctx.kit.CLIMATE}
    plug = by_ref[ctx.kit.PLUG]
    assert (plug["kind"], plug["role"], plug["source"], plug["power_unit"]) == (
        "plug",
        "main_meter",
        "mcp",
        "W",
    )
    for ref in (ctx.kit.CONTACT, ctx.kit.CLIMATE):
        row = by_ref[ref]
        assert (row["kind"], row["role"], row["power_unit"], row["room_id"]) == (
            "sensor",
            "none",
            "unknown",
            None,
        )
    recorded = events(ctx)
    assert len(recorded) == 4  # energia, contacto, temperatura, humidade; sem duplicados
    assert {event.type for event in recorded} == {
        "energy.reading_recorded",
        "sensor.reading_recorded",
    }
    assert {event.data.device_id for event in recorded} == {UUID(row["id"]) for row in rows}
    for event in recorded:
        assert event.household_id == ctx.house
        assert event.provenance.origin is Origin.real
        if event.type == "energy.reading_recorded":
            assert event.data.device_id == UUID(plug["id"])
        else:
            assert event.data.room_id is None
    ctx.kit.set_load(120)
    ctx.kit.open_contact()
    ctx.kit.set_climate(22, 60)
    ctx.run(ctx.home._refrescar())
    assert len(events(ctx)) == 8
    assert ctx.catalog.register_device.call_count == 3
    assert_private(ctx, caplog)


@pytest.mark.parametrize("missing", [False, True])
def test_no_configured_or_existing_house(kit_setup, missing, caplog):
    ctx = kit_setup
    ctx.settings.energy_household_id = uuid4() if missing else None
    attach(ctx)
    assert ctx.home.coletor is ctx.home.sensores is None
    ctx.run(ctx.home._refrescar())
    assert ctx.home._lido_em is not None  # o McpHome continua a ler normalmente
    assert devices(ctx) == events(ctx) == []
    ctx.catalog.register_device.assert_not_called()
    assert "Collectors do kit desligados" in caplog.text
    assert_private(ctx, caplog)


@pytest.mark.parametrize("fake_home", [False, True])
def test_fake_backend_or_fake_home_does_not_attach(kit_setup, fake_home):
    ctx = kit_setup
    if fake_home:
        ctx.home = FakeHome()
    else:
        ctx.settings.home_backend = "fake"
    attach(ctx)
    assert getattr(ctx.home, "coletor", None) is None
    assert getattr(ctx.home, "sensores", None) is None
    assert devices(ctx) == events(ctx) == []
    ctx.catalog.register_device.assert_not_called()
    # A limpeza da fixture espera McpHome.parar(). FakeHome não possui recursos.
    if fake_home:
        ctx.home = McpHome(ctx.settings, ctx.kit.session_factory, simulated=True)


def test_restart_reuses_catalog_uuids(kit_setup, caplog):
    ctx = kit_setup
    attach(ctx)
    ctx.run(ctx.home._refrescar())
    before = {row["external_ref"]: row["id"] for row in devices(ctx)}
    ctx.run(ctx.home.parar())
    ctx.home = McpHome(ctx.settings, ctx.kit.session_factory, simulated=True)
    attach(ctx)
    ctx.run(ctx.home._refrescar())
    assert {row["external_ref"]: row["id"] for row in devices(ctx)} == before
    assert ctx.catalog.register_device.call_count == 6
    assert {str(event.data.device_id) for event in events(ctx)} == set(before.values())
    assert_private(ctx, caplog)


def test_registration_failure_isolated_and_retried(kit_setup, caplog):
    ctx = kit_setup
    # Mensagem deliberadamente sensível: só o tipo pode sair para os logs.
    ctx.catalog.register_device.side_effect = RuntimeError(ctx.kit.PLUG)
    attach(ctx)
    ctx.run(ctx.home._refrescar())
    assert ctx.home._lido_em is not None
    assert devices(ctx) == events(ctx) == []
    assert ctx.catalog.register_device.call_count == 3
    assert "Registo do kit falhou (RuntimeError)" in caplog.text
    ctx.catalog.register_device.side_effect = None
    ctx.run(ctx.home._refrescar())
    assert len(devices(ctx)) == 3
    assert len(events(ctx)) == 4
    assert_private(ctx, caplog)


def test_unknown_power_unit_and_unsupported_sensor(kit_setup, caplog):
    ctx = kit_setup
    ctx.settings.mcp_instantpower_unit = ""
    ctx.kit.dev["sim-smoke-1"] = {
        "id": "sim-smoke-1",
        "type": "smokeSensor",
        "capabilities": [],
    }
    attach(ctx)
    ctx.run(ctx.home._refrescar())
    assert len(devices(ctx)) == 3
    assert ctx.catalog.register_device.call_count == 3
    energy = next(event for event in events(ctx) if event.type == "energy.reading_recorded")
    assert energy.data.status.value == "unit_unknown"
    assert energy.data.power_w is None
    assert all(row["power_unit"] == "unknown" for row in devices(ctx))
    ctx.home.coletor.unavailable()
    ctx.home.sensores.unavailable()
    ctx.run(ctx.home._refrescar())
    assert ctx.catalog.register_device.call_count == 3
    assert_private(ctx, caplog)


def test_settings_load_energy_household_from_environment(monkeypatch):
    house = uuid4()
    monkeypatch.setenv("ENERGY_HOUSEHOLD_ID", str(house))
    assert Settings(_env_file=None).energy_household_id == house
    monkeypatch.delenv("ENERGY_HOUSEHOLD_ID")
    assert Settings(_env_file=None).energy_household_id is None


def test_lampada_do_kit_gera_consumo_estimado_simulado(kit_setup, monkeypatch):
    """#248 F3: estado da lâmpada lido pelo McpHome → sessão estimada nos eventos de domínio."""
    ctx = kit_setup
    now = {"t": datetime(2026, 11, 18, 20, tzinfo=UTC)}
    monkeypatch.setattr(ctx.home, "_agora", lambda: now["t"])
    ctx.run(ctx.home._refrescar())
    attach(ctx)
    bulb = ctx.kit._caps(ctx.kit.BULB)

    def refresh(minutes):
        now["t"] += timedelta(minutes=minutes)
        ctx.run(ctx.home._refrescar())

    bulb["power"]["value"] = "on"
    bulb["brightness"]["value"] = 100
    refresh(0)
    refresh(60)  # 1 h a 100 %
    bulb["brightness"]["value"] = 50
    refresh(0)
    refresh(120)  # 2 h a 50 %
    bulb["power"]["value"] = "off"
    refresh(0)
    consumos = [e for e in events(ctx) if e.type.startswith("energy.consumption")]
    assert [e.type for e in consumos] == [
        "energy.consumption_detected",
        "energy.consumption_closed",
    ]
    closed = consumos[-1].data
    assert closed.energy_wh == 18  # 9 Wh + 9 Wh
    assert closed.provenance.origin is Origin.simulated
    assert closed.provenance.kind.value == "estimated"
    lamp = next(r for r in devices(ctx) if r["external_ref"] == ctx.kit.BULB)
    assert UUID(lamp["id"]) == closed.device_id and lamp["kind"] == "bulb"
