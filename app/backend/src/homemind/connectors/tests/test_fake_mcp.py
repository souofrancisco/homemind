"""SIMULADO: sessão, payloads e collectors MCP sem hardware nem rede."""

import ast
import asyncio
import inspect
import socket
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from homemind.connectors import fake_mcp
from homemind.connectors.altice_auth import OAuthReauthRequired
from homemind.connectors.fake_mcp import FakeKit
from homemind.connectors.mcp_collector import EnergyCollector
from homemind.connectors.mcp_home import (
    McpHome,
    _capabilities,
    _find_devices,
    _payload,
    _validate_tools,
)
from homemind.connectors.mcp_sensor_collector import SensorBinding, SensorCollector
from homemind.connectors.write_policy import Decision, WriteOutcome
from homemind.contracts.common import Origin, ValueKind
from homemind.contracts.energy import ReadingStatus
from homemind.contracts.sensors import ContactState, SensorKind, SensorStatus
from homemind.core.config import Settings


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 17, 12, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def setup(monkeypatch):
    clock = Clock()
    kit = FakeKit(clock)
    settings = Settings(
        _env_file=None,
        mcp_instantpower_unit="W",
        mcp_lamp_id="",
        mcp_plug_id="",
        enable_physical_writes=True,
    )
    # Só autorização em memória; não se cria grant nem qualquer ficheiro no repositório.
    monkeypatch.setattr(
        "homemind.connectors.mcp_home.read_grant",
        lambda *args: SimpleNamespace(roles=("lamp", "plug")),
    )
    monkeypatch.setattr("homemind.connectors.mcp_home._READBACK_GAP_S", 0)
    home = McpHome(settings, kit.session_factory)
    monkeypatch.setattr(home, "_agora", clock)
    energy_events, sensor_events = [], []
    home.coletor = EnergyCollector(
        household_id=UUID(int=1),
        device_id=UUID(int=2),
        unit=settings.mcp_instantpower_unit,
        origin=Origin.simulated,
        clock=clock,
        publish=energy_events.append,
    )
    home.sensores = SensorCollector(
        household_id=UUID(int=1),
        bindings={
            kit.CONTACT: SensorBinding(UUID(int=3)),
            kit.CLIMATE: SensorBinding(UUID(int=4)),
        },
        origin=Origin.simulated,
        clock=clock,
        publish=sensor_events.append,
    )
    with asyncio.Runner() as runner:
        runner.get_loop()
        yield SimpleNamespace(
            kit=kit,
            clock=clock,
            home=home,
            run=runner.run,
            energy_events=energy_events,
            sensor_events=sensor_events,
        )
        runner.run(home.parar())


async def read(kit, device=None):
    async with kit.session_factory() as session:
        if device is None:
            return _payload(await session.call_tool("get_home_devices", {}))
        return _payload(await session.call_tool("get_device_details", {"deviceId": device}))


def test_real_payload_shape_and_discovery(setup):
    s = setup
    payload = s.run(read(s.kit))
    lamp, plug, warning = _find_devices(payload)
    assert warning is None
    assert (lamp["id"], plug["id"]) == (s.kit.BULB, s.kit.PLUG)
    contact = next(d for d in payload["devices"] if d["id"] == s.kit.CONTACT)
    assert contact["categories"] == ["security"]
    # Mesmo com capabilities de tomada, security fica excluído.
    disguised = {**plug, "id": s.kit.CONTACT, "categories": ["energy", "security"]}
    assert _find_devices({"devices": [lamp, plug, disguised]})[1] == plug
    for device in payload["devices"]:
        assert device == s.run(read(s.kit, device["id"]))
        assert device["id"].startswith("sim-")
        assert device["lastCommunicationTime"] == int(s.clock().timestamp() * 1000)
        assert isinstance(device["capabilities"], list)
    assert _capabilities(plug)["instantPower"] == {
        "type": "instantPower",
        "value": 0,
        "min": 0,
        "max": 50000,
    }

    async def tools():
        async with s.kit.session_factory() as session:
            catalog = (await session.list_tools()).tools
            _validate_tools(catalog)
            assert len(catalog) == 3

    s.run(tools())
    assert len(s.run(s.home.listar_ferramentas())) == 3
    s.run(s.home._refrescar())
    state = s.run(s.home.estado())
    assert state.mcp_ok is True
    assert state.tomada.ligada is True
    assert state.lampada.ligada is False
    assert state.lampada.brilho == 100


def test_complete_simulated_path(setup):
    s = setup
    s.kit.set_load(2000)
    s.kit.open_contact()
    s.kit.set_climate(23.5, 65)
    s.run(s.home._refrescar())
    energy = s.home.coletor.last_reading
    assert energy.status is ReadingStatus.ok and energy.power_w == 2000
    assert (energy.provenance.origin, energy.provenance.kind) == (
        Origin.simulated,
        ValueKind.measured,
    )
    readings = {r.kind: r for r in s.home.sensores.last_readings.values()}
    assert readings[SensorKind.contact].contact is ContactState.open
    assert readings[SensorKind.contact].status is SensorStatus.ok
    assert readings[SensorKind.temperature].temperature_c == 23.5
    assert readings[SensorKind.humidity].humidity_pct == 65
    assert all(r.provenance.origin is Origin.simulated for r in readings.values())
    assert all(e.provenance.origin is Origin.simulated for e in s.energy_events + s.sensor_events)
    caps = _capabilities(s.run(read(s.kit, s.kit.PLUG)))
    assert caps["instantVoltage"]["value"] == 230
    assert caps["instantCurrent"]["value"] == round(2000 / 230 * 1000)


def test_unknown_unit_and_optional_declaration(setup):
    s = setup
    s.home._settings.mcp_instantpower_unit = ""
    s.home.coletor = EnergyCollector(
        household_id=UUID(int=1),
        device_id=UUID(int=2),
        clock=s.clock,
        publish=s.energy_events.append,
        origin=Origin.simulated,
    )
    s.kit.set_load(2000)
    s.run(s.home._refrescar())
    reading = s.home.coletor.last_reading
    assert reading.status is ReadingStatus.unit_unknown and reading.power_w is None
    assert s.run(s.home.estado()).tomada.consumo_w is None
    assert reading.provenance.origin is Origin.simulated
    assert reading.provenance.kind is ValueKind.estimated
    s.kit.declare_unit("W")
    s.run(s.home._refrescar())
    assert s.home.coletor.last_reading.power_w == 2000
    s.kit.declare_unit(None)
    assert "unit" not in _capabilities(s.run(read(s.kit, s.kit.PLUG)))["instantPower"]


def test_heartbeat_and_immediate_load_reports(setup):
    s = setup
    initial = s.run(read(s.kit, s.kit.PLUG))
    s.clock.advance(29)
    assert s.run(read(s.kit, s.kit.PLUG)) == initial
    s.clock.advance(1)
    beat = s.run(read(s.kit, s.kit.PLUG))
    assert beat["lastCommunicationTime"] == initial["lastCommunicationTime"] + 30000
    s.clock.advance(2)
    s.kit.set_load(123)
    changed = s.run(read(s.kit, s.kit.PLUG))
    assert changed["lastCommunicationTime"] == beat["lastCommunicationTime"] + 2000
    assert _capabilities(changed)["instantPower"]["value"] == 123
    s.clock.advance(1)
    s.kit.set_load(123)
    assert s.run(read(s.kit, s.kit.PLUG)) == changed


def test_sensors_only_report_changes(setup):
    s = setup
    initial = s.run(read(s.kit))
    before = {d["id"]: d for d in initial["devices"]}
    s.clock.advance(3600)
    s.kit.close_contact()
    s.kit.set_climate(20, 50)
    assert s.run(read(s.kit, s.kit.CONTACT)) == before[s.kit.CONTACT]
    assert s.run(read(s.kit, s.kit.CLIMATE)) == before[s.kit.CLIMATE]
    s.kit.open_contact()
    s.kit.set_climate(21, 55)
    for device in (s.kit.CONTACT, s.kit.CLIMATE):
        assert s.run(read(s.kit, device))["lastCommunicationTime"] == int(
            s.clock().timestamp() * 1000
        )
    s.clock.advance(1)
    s.kit.close_contact()
    assert _capabilities(s.run(read(s.kit, s.kit.CONTACT)))["sensorState"]["value"] == "normal"


def test_offline_energy_is_stale_and_recovers(setup):
    s = setup
    s.kit.set_load(2000)
    initial = s.run(read(s.kit, s.kit.PLUG))
    s.kit.device_offline(s.kit.PLUG)
    s.clock.advance(91)
    s.kit.set_load(1000)
    s.run(s.home._refrescar())
    assert s.run(read(s.kit, s.kit.PLUG)) == initial
    reading = s.home.coletor.last_reading
    assert reading.status is ReadingStatus.stale and reading.power_w is None
    s.kit.device_offline(s.kit.PLUG, False)
    s.clock.advance(30)
    s.run(s.home._refrescar())
    assert s.home.coletor.last_reading.status is ReadingStatus.ok
    assert s.home.coletor.last_reading.power_w == 1000


@pytest.mark.parametrize(
    "fault,exception",
    [("session_down", ConnectionError), ("oauth_expired", OAuthReauthRequired)],
)
def test_connection_faults_at_open_and_on_existing_session(setup, fault, exception):
    s = setup

    async def existing():
        async with s.kit.session_factory() as session:
            setattr(s.kit, fault, True)
            with pytest.raises(exception):
                await session.list_tools()
            with pytest.raises(exception):
                await session.call_tool("get_home_devices", {})
        with pytest.raises(exception):
            async with s.kit.session_factory():
                pytest.fail("fault must prevent opening")

    s.run(s.home._refrescar())
    assert s.home.coletor.last_reading is not None
    s.run(existing())
    s.run(s.home._refrescar())
    state = s.run(s.home.estado())
    assert state.mcp_ok is False
    assert state.tomada.ligada is None and state.tomada.consumo_w is None
    assert state.lampada.ligada is None
    assert s.home.coletor.last_reading is None and not s.home.sensores.last_readings
    setattr(s.kit, fault, False)
    s.run(s.home._refrescar())
    assert s.run(s.home.estado()).mcp_ok is True


def test_write_rejected_including_rule(setup):
    s = setup
    s.kit.write_rejected = True
    assert s.run(s.home.definir_tomada(False)) is False
    assert s.home.ultimo_resultado.outcome is WriteOutcome.failed
    decision = Decision("sim-rule", "sim-operator", s.clock(), s.clock() + timedelta(minutes=5))
    result = s.run(s.home.tomada_por_regra(False, decision))
    assert result.outcome is WriteOutcome.failed
    assert len(s.kit.writes()) == 2
    s.kit.write_rejected = False
    assert s.run(s.home.definir_tomada(False)) is True


def test_ignored_write_never_confirmed(setup):
    s = setup
    before = s.run(read(s.kit, s.kit.BULB))
    s.kit.write_ignored = True
    assert s.run(s.home.definir_lampada(True, "vermelho", 50)) is False
    assert s.home.ultimo_resultado.outcome is not WriteOutcome.confirmed
    assert s.run(read(s.kit, s.kit.BULB)) == before
    assert len(s.kit.writes()) == 3
    s.kit.write_ignored = False
    assert s.run(s.home.definir_lampada(True, "vermelho", 50)) is True
    lamp = s.run(s.home.estado()).lampada
    assert (lamp.rgb, lamp.brilho) == ((255, 0, 0), 50)
    caps = _capabilities(s.run(read(s.kit, s.kit.BULB)))
    assert (caps["color_rgb"]["redValue"], caps["color_rgb"]["value"]) == (128, "128,0,0")


def test_transport_dies_after_write_without_retry(setup):
    s = setup
    s.kit.set_load(2000)
    s.clock.advance(2)
    s.kit.die_after_write = True
    assert s.run(s.home.definir_tomada(False)) is False
    assert s.home.ultimo_resultado.outcome is WriteOutcome.unknown
    assert len(s.kit.writes()) == 1
    assert s.kit.opens == 2  # só releitura numa nova sessão
    plug = s.run(read(s.kit, s.kit.PLUG))
    assert plug["lastCommunicationTime"] == int(s.clock().timestamp() * 1000)
    caps = _capabilities(plug)
    assert caps["power"]["value"] == "off" and caps["instantPower"]["value"] == 0
    assert caps["instantCurrent"]["value"] == 0
    s.kit.die_after_write = False
    assert s.run(s.home.definir_tomada(True)) is True
    assert s.run(s.home.estado()).tomada.consumo_w == 2000


def test_reset_is_idempotent_and_responses_are_copies(setup):
    s = setup
    initial = s.run(read(s.kit))
    s.kit.set_load(1000)
    s.kit.open_contact()
    s.kit.set_climate(25, 60)
    s.kit.declare_unit("W")
    s.kit.device_offline(s.kit.PLUG)
    for fault in (
        "session_down",
        "oauth_expired",
        "write_rejected",
        "write_ignored",
        "die_after_write",
    ):
        setattr(s.kit, fault, True)
    s.kit.reset()
    first = s.run(read(s.kit))
    s.kit.reset()
    assert s.kit.calls == [] and s.kit.writes() == []
    assert s.run(read(s.kit)) == first == initial
    first["devices"].clear()
    assert len(s.run(read(s.kit))["devices"]) == 4
    s.clock.advance(100)
    s.kit.reset()
    first = s.run(read(s.kit))
    s.kit.reset()
    assert s.run(read(s.kit)) == first


def test_no_network_or_http_client_imports(setup, monkeypatch):
    imports = []
    for node in ast.walk(ast.parse(inspect.getsource(fake_mcp))):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module)
    assert not {"socket", "httpx", "requests", "aiohttp", "urllib", "http"} & {
        name.split(".")[0] for name in imports
    }

    def forbidden(*args, **kwargs):
        pytest.fail("simulator attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    s = setup
    s.run(s.home._refrescar())
    assert s.run(s.home.definir_lampada(True, "azul", 75)) is True
    assert s.run(s.home.definir_tomada(False)) is True
    assert s.run(s.home.estado()).mcp_ok is True


def test_power_factor_and_write_whitelist(setup):
    s = setup
    kit = FakeKit(s.clock, power_factor=0.5)
    kit.set_load(230)
    assert _capabilities(s.run(read(kit, kit.PLUG)))["instantCurrent"]["value"] == 2000

    async def rejected():
        async with kit.session_factory() as session:
            for device, body in (
                (kit.CONTACT, {"type": "power", "value": "off"}),
                (kit.PLUG, {"type": "brightness", "value": 50}),
                (kit.BULB, {"type": "workMode", "value": "white"}),
                (kit.BULB, {"type": "brightness", "value": 0}),
            ):
                result = await session.call_tool(
                    "update_device_capabilities", {"deviceId": device, "body": body}
                )
                assert result.isError is True

    s.run(rejected())


def test_multipower_has_the_real_kit_shape_and_follows_power():
    """Formato observado no kit real: lista com um interruptor `switch_1` (multiplugSwitch)."""
    kit = FakeKit()
    caps = kit._caps(FakeKit.PLUG)
    [switch] = caps["multiPower"]["value"]
    assert switch == {
        "id": "1",
        "name": "switch_1",
        "order": 1,
        "partnerType": "switch_1",
        "type": "multiplugSwitch",
        "value": "on",
    }
    caps["power"]["value"] = "off"
    kit._report_load()
    assert caps["multiPower"]["value"][0]["value"] == "off"


def test_mcphome_over_simulator_reports_fake_backend_never_real():
    """Com o simulador, a UI tem de ver SIMULADO: `backend="fake"` e `mcp_ok` sempre False."""
    kit = FakeKit()
    real_like = McpHome(Settings(), kit.session_factory)
    sim = McpHome(Settings(), kit.session_factory, simulated=True)

    async def read(home):
        await home._refrescar()
        estado = await home.estado()
        await home.parar()
        return estado

    assert asyncio.run(read(real_like)).backend == "mcp"
    estado = asyncio.run(read(sim))
    assert estado.backend == "fake"
    assert estado.mcp_ok is False


def test_tomada_offline_nao_devolve_consumo_antigo_como_atual(setup):
    """#248 F1: sem `lastCommunicationTime` novo, o consumo deixa de ser «atual»."""
    s = setup
    s.kit.set_load(2000)
    s.run(s.home._refrescar())
    assert s.run(s.home.estado()).tomada.consumo_w == 2000.0
    s.kit.device_offline(s.kit.PLUG)
    s.clock.advance(600)
    s.run(s.home._refrescar())
    tomada = s.run(s.home.estado()).tomada
    assert tomada.consumo_w is None
    assert tomada.consumo_lido_em is None


def test_tomada_viva_com_carga_constante_nao_passa_a_none(setup):
    s = setup
    s.kit.set_load(2000)
    for _ in range(10):
        s.clock.advance(10)
        s.run(s.home._refrescar())
        tomada = s.run(s.home.estado()).tomada
        assert tomada.consumo_w == 2000.0
        assert (s.clock() - tomada.consumo_lido_em).total_seconds() <= 30
