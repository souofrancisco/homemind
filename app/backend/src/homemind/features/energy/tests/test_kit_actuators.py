"""ALERT-06 / AGENT-03b: lâmpada REAL do kit nas ações confirmadas, testada só com o FakeMcp.

Nenhum teste toca em hardware: o `McpHome` fala com um MCP falso em memória."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from homemind.connectors.tests.test_mcp_home import FakeMcp, make, run
from homemind.contracts import fixtures as fx
from homemind.contracts.agent import (
    ActionConfirmation,
    DeviceCapability,
    DeviceCommand,
    ExecutionStatus,
    ProposedAction,
    RgbColor,
)
from homemind.contracts.devices import DeviceKind
from homemind.core.config import Settings
from homemind.features.energy.kit_actuators import (
    DIRECTORY_ATTR,
    EXECUTOR_ATTR,
    KitLampDirectory,
    KitLampExecutor,
    attach_kit_actuators,
    lamp_device_id,
)

NOW = datetime.now(UTC)


def _home(tmp_path, **kw):
    home, mcp, s = make(tmp_path, **kw)
    run(home._refrescar())  # descoberta (como no arranque)
    return home, mcp


def _action(device, **command):
    return ProposedAction(
        id=uuid4(),
        household_id=fx.HOUSEHOLD,
        proposed_for_resident_id=fx.ANA,
        command=DeviceCommand(target_device_id=device, **command),
        rationale="Orçamento a 80 %: lâmpada em amarelo.",
        proposed_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def _go(home, action, accepted=True):
    ex = KitLampExecutor(home, lambda: datetime.now(UTC))
    conf = ActionConfirmation(
        action_id=action.id, resident_id=fx.ANA, accepted=accepted, at=datetime.now(UTC)
    )
    return run(ex.execute(action, conf))


AMARELO = {"capability": DeviceCapability.color_rgb, "color_rgb": RgbColor(r=255, g=200, b=0)}


def test_diretorio_so_na_casa_do_kit_e_depois_da_descoberta(tmp_path):
    home, _, _ = make(tmp_path)
    d = KitLampDirectory(home, fx.HOUSEHOLD, fx.ROOM_SALA)
    assert d.actuators(fx.HOUSEHOLD) == []  # ainda não descobriu a lâmpada
    run(home._refrescar())
    [lamp] = d.actuators(fx.HOUSEHOLD)
    assert (lamp.kind, lamp.simulated, lamp.room_id) == (DeviceKind.bulb, False, fx.ROOM_SALA)
    assert lamp.id == lamp_device_id("L0") and "L0" not in lamp.name  # o id MCP não sai
    assert d.actuators(uuid4()) == []  # outra casa
    assert KitLampDirectory(home, fx.HOUSEHOLD, None).actuators(fx.HOUSEHOLD)[0].room_id is None


def test_cor_confirmada_com_releitura(tmp_path):
    home, mcp = _home(tmp_path)
    r = _go(home, _action(lamp_device_id("L0"), **AMARELO))
    assert (r.status, r.readback_confirmed, r.code) == (ExecutionStatus.confirmed, True, None)
    assert len(mcp.writes()) == 2  # power on + color_rgb, uma vez cada


def test_sem_flag_ou_grant_fica_bloqueada_sem_chamar_o_mcp(tmp_path):
    for kw in ({"writes": False}, {"grant": None}):
        home, mcp = _home(tmp_path, **kw)
        r = _go(home, _action(lamp_device_id("L0"), **AMARELO))
        assert (r.status, r.code, r.mcp_is_error) == (
            ExecutionStatus.blocked,
            "write_refused",
            None,
        )
        assert mcp.writes() == []
        (tmp_path / "grant.json").unlink(missing_ok=True)


def test_sem_confirmacao_dispositivo_errado_ou_cor_fora_do_vocabulario(tmp_path):
    home, mcp = _home(tmp_path)
    lamp = lamp_device_id("L0")
    assert _go(home, _action(lamp, **AMARELO), accepted=False).code == "not_confirmed"
    assert _go(home, _action(uuid4(), **AMARELO)).code == "unknown_device"
    odd = {"capability": DeviceCapability.color_rgb, "color_rgb": RgbColor(r=1, g=2, b=3)}
    assert _go(home, _action(lamp, **odd)).code == "color_not_supported"
    zero = {"capability": DeviceCapability.brightness, "brightness": 0}
    assert _go(home, _action(lamp, **zero)).code == "invalid_brightness"
    assert mcp.writes() == []


def test_erro_do_mcp_falha_e_sem_releitura_fica_incerto(tmp_path):
    mcp = FakeMcp()
    mcp.explicit_error = True
    home, _ = _home(tmp_path, mcp=mcp)
    r = _go(home, _action(lamp_device_id("L0"), **AMARELO))
    assert (r.status, r.code, r.mcp_is_error) == (ExecutionStatus.failed, "mcp_error", True)
    mcp2 = FakeMcp()
    mcp2.ignore_writes = True  # «device updated» sem efeito: nunca é sucesso
    home2, _ = _home(tmp_path, mcp=mcp2)
    r = _go(home2, _action(lamp_device_id("L0"), **AMARELO))
    assert r.status is ExecutionStatus.uncertain and not r.may_retry


def test_regista_so_com_backend_mcp_e_casa(tmp_path):
    home, _, _ = make(tmp_path)
    state = SimpleNamespace()
    base = {"energy_household_id": fx.HOUSEHOLD}
    clock = lambda: NOW  # noqa: E731
    assert not attach_kit_actuators(state, home, settings=Settings(**base), clock=clock)
    assert not attach_kit_actuators(state, home, settings=Settings(home_backend="mcp"), clock=clock)
    assert not hasattr(state, EXECUTOR_ATTR)
    s = Settings(home_backend="mcp", **base)
    assert attach_kit_actuators(state, home, settings=s, clock=clock)
    assert isinstance(getattr(state, EXECUTOR_ATTR), KitLampExecutor)
    assert isinstance(getattr(state, DIRECTORY_ATTR), KitLampDirectory)
