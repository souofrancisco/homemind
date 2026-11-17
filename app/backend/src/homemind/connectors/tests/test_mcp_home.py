"""McpHome contra um servidor MCP falso: autorização, whitelist, verificação e recuperação."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from homemind.connectors.mcp_home import McpHome
from homemind.connectors.write_grant import read_grant, write_grant
from homemind.core.config import Settings

_LOOP = asyncio.new_event_loop()  # a sessão persistente do McpHome vive entre chamadas


def run(coro):
    return _LOOP.run_until_complete(coro)


def _caps(*pairs):
    return [{"type": t, **v} for t, v in pairs]


class FakeMcp:
    """Mantém o estado dos dispositivos e regista as chamadas feitas."""

    def __init__(self, lamps=1, plugs=1, unit=None):
        self.down = False
        self.explicit_error = False
        self.list_calls = 0
        self.opens = 0
        self.calls: list[tuple[str, dict]] = []
        pw = {"value": 55, **({"unit": unit} if unit else {})}
        self.dev = {}
        for i in range(lamps):
            self.dev[f"L{i}"] = {
                "id": f"L{i}",
                "type": "bulb",
                "capabilities": _caps(
                    ("power", {"value": "off"}),
                    ("brightness", {"value": 30}),
                    ("color_rgb", {"redValue": 255, "greenValue": 255, "blueValue": 255}),
                ),
            }
        for i in range(plugs):
            self.dev[f"P{i}"] = {
                "id": f"P{i}",
                "type": "plug",
                "categories": ["energy"],
                "capabilities": _caps(("power", {"value": "on"}), ("instantPower", pw)),
            }

    @asynccontextmanager
    async def __call__(self):
        if self.down:
            raise ConnectionError("down")
        self.opens += 1
        yield self

    async def list_tools(self):
        if self.down:
            raise ConnectionError("down")
        self.list_calls += 1
        body = {
            "oneOf": [
                {"properties": {"type": {"enum": [k]}}}
                for k in ("power", "brightness", "color_rgb", "temperature")
            ]
        }
        tools = [
            SimpleNamespace(name="get_home_devices", inputSchema={}),
            SimpleNamespace(
                name="get_device_details",
                inputSchema={"required": ["deviceId"], "properties": {"deviceId": {}}},
            ),
            SimpleNamespace(
                name="update_device_capabilities",
                inputSchema={"properties": {"deviceId": {}, "body": body}},
            ),
        ]
        return SimpleNamespace(tools=tools)

    async def call_tool(self, name, args):
        if self.down:
            raise ConnectionError("down")
        self.calls.append((name, args))
        ok = lambda data: SimpleNamespace(isError=False, structuredContent=data, content=[])  # noqa: E731
        if name == "get_home_devices":
            return ok({"devices": list(self.dev.values())})
        if name == "get_device_details":
            return ok(self.dev[args["deviceId"]])
        if self.explicit_error:
            return SimpleNamespace(isError=True, structuredContent=None, content=[])
        dev = self.dev[args["deviceId"]]
        caps = {c["type"]: c for c in dev["capabilities"]}
        body = dict(args["body"])
        kind = body.pop("type")
        if kind == "color_rgb":
            dev["base"] = (body["redValue"], body["greenValue"], body["blueValue"])
        else:
            caps[kind].update(body)
        if "base" in dev:  # lâmpada real: color_rgb devolvido = cor × brilho/100
            b = caps["brightness"]["value"]
            for k, c in zip(("redValue", "greenValue", "blueValue"), dev["base"], strict=True):
                caps["color_rgb"][k] = round(c * b / 100)
        return ok({})

    def writes(self):
        return [c for c in self.calls if c[0] == "update_device_capabilities"]


def make(tmp_path, mcp=None, writes=True, grant=("lamp", "plug"), minutes=10):
    mcp = mcp or FakeMcp()
    s = Settings(
        enable_physical_writes=writes,
        mcp_write_grant_path=tmp_path / "grant.json",
        mcp_write_max_minutes=60,
    )
    if grant:
        write_grant(s.mcp_write_grant_path, minutes, tuple(grant), 60)
    return McpHome(s, mcp), mcp, s


def test_writes_blocked_by_default(tmp_path):
    home, mcp, _ = make(tmp_path, writes=False)
    assert run(home.definir_lampada(True, "vermelho", 50)) is False
    assert "desativadas" in home.ultima_falha
    assert mcp.calls == []


def test_flag_without_grant_blocked(tmp_path):
    home, mcp, _ = make(tmp_path, grant=None)
    assert run(home.definir_tomada(False)) is False
    assert "autorizada" in home.ultima_falha
    assert mcp.writes() == []


def test_grant_limited_to_roles_and_revocable(tmp_path):
    home, mcp, s = make(tmp_path, grant=("lamp",))
    assert run(home.definir_tomada(False)) is False  # tomada fora da autorização
    assert run(home.definir_lampada(True)) is True
    s.mcp_write_grant_path.unlink()  # revogação imediata
    assert run(home.definir_lampada(False)) is False


def test_grant_expiry_and_ttl_cap(tmp_path):
    p = tmp_path / "g.json"
    write_grant(p, 5, ("lamp",), 60)
    now = datetime.now(UTC)
    assert read_grant(p, 60, now) is not None
    assert read_grant(p, 60, now + timedelta(minutes=6)) is None  # expirou
    assert read_grant(p, 2, now) is None  # TTL acima do limite = adulterado


def test_lamp_write_confirmed_and_tools_cached(tmp_path):
    home, mcp, _ = make(tmp_path)
    assert run(home.definir_lampada(True, "vermelho", 50)) is True
    assert run(home.definir_lampada(False, "azul", 80)) is True  # cor/brilho ignorados ao desligar
    assert mcp.list_calls == 1 and mcp.opens == 1  # catálogo em cache, sessão reutilizada
    bodies = [a["body"] for _, a in mcp.writes()]
    assert {b["type"] for b in bodies} <= {"power", "brightness", "color_rgb"}
    assert all(set(a) == {"deviceId", "body"} for _, a in mcp.writes())
    assert run(home.estado()).lampada.ligada is False


def test_readback_reflects_device_values(tmp_path):
    home, mcp, _ = make(tmp_path)
    run(home.definir_lampada(True, "vermelho", 50))
    lamp = run(home.estado()).lampada
    # RGB devolvido (128,0,0) a 50% normaliza para a cor pedida; o nome é derivado dele
    assert (lamp.ligada, lamp.rgb, lamp.brilho, lamp.cor) == (True, (255, 0, 0), 50, "vermelho")


def test_explicit_mcp_error_is_failure(tmp_path):
    home, mcp, _ = make(tmp_path)
    mcp.explicit_error = True
    assert run(home.definir_lampada(False)) is False
    assert "recusou" in home.ultima_falha


def test_unknown_power_state_is_unknown(tmp_path):
    home, mcp, _ = make(tmp_path)
    mcp.dev["P0"]["capabilities"][0]["value"] = "standby"
    assert run(home._refrescar()) is None
    assert run(home.estado()).tomada.ligada is None  # desconhecido, não "off"


def test_ambiguous_devices_never_guessed(tmp_path):
    home, mcp, _ = make(tmp_path, FakeMcp(lamps=2))
    assert run(home.definir_lampada(True)) is False
    assert mcp.writes() == []
    assert run(home.estado()).lampada.ligada is None


def test_plug_cannot_receive_lamp_capabilities(tmp_path):
    home, mcp, _ = make(tmp_path)
    assert (
        run(home._escrever("plug", [{"type": "brightness", "value": 10}], lambda d: True)) is False
    )
    assert (
        run(home._escrever("lamp", [{"type": "temperature", "value": 10}], lambda d: True)) is False
    )
    assert mcp.writes() == []


def test_consumption_needs_declared_unit(tmp_path):
    home, _, _ = make(tmp_path)
    run(home._refrescar())
    assert run(home.ler_consumo()) is None
    home2, _, _ = make(tmp_path, FakeMcp(unit="mW"))
    run(home2._refrescar())
    assert run(home2.ler_consumo()) == 0.055


def test_poll_failure_then_recovery_notifies(tmp_path):
    home, mcp, _ = make(tmp_path)
    vistos: list[tuple[bool, bool]] = []
    home.ao_estado = lambda casa, mudou: vistos.append((casa.mcp_ok, mudou))
    run(home._refrescar())
    mcp.down = True
    run(home._refrescar())
    casa = run(home.estado())
    assert casa.mcp_ok is False and casa.lampada.ligada is None and "indisponível" in casa.aviso
    mcp.down = False
    run(home._refrescar())
    assert run(home.estado()).mcp_ok is True
    assert vistos == [(True, True), (False, True), (True, True)]
