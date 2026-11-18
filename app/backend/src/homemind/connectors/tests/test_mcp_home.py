"""McpHome contra um servidor MCP falso: autorização, whitelist, verificação e recuperação."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from homemind.connectors.altice_auth import OAuthReauthRequired
from homemind.connectors.fake_home import FakeHome
from homemind.connectors.mcp_home import McpHome, _rgb_confere, cor_verificavel
from homemind.connectors.mcp_verify import verify_lamp
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
        self.ignore_writes = False
        self.brightness_resets_color = False  # escrever o brilho anula a cor enviada antes
        self.fail_reads = 0  # falhas transitórias de get_device_details (a sessão fecha)
        self.die_after_write = False  # o transporte cai logo após a 1.ª escrita
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
            if self.fail_reads > 0:
                self.fail_reads -= 1
                raise ConnectionError("transitório")
            return ok(self.dev[args["deviceId"]])
        if self.explicit_error:
            return SimpleNamespace(isError=True, structuredContent=None, content=[])
        if self.ignore_writes:  # observado no MCP real: «device updated» sem efeito
            return ok({"message": "device updated"})
        dev = self.dev[args["deviceId"]]
        caps = {c["type"]: c for c in dev["capabilities"]}
        body = dict(args["body"])
        kind = body.pop("type")
        if kind == "color_rgb":
            dev["base"] = (body["redValue"], body["greenValue"], body["blueValue"])
        else:
            caps[kind].update(body)
            if kind == "brightness" and self.brightness_resets_color:
                # observado no kit real (2026-11-18): o brilho repõe a cor anterior
                dev["base"] = (255, 255, 255)
        if "base" in dev:  # lâmpada real: color_rgb devolvido = cor × brilho/100
            b = caps["brightness"]["value"]
            for k, c in zip(("redValue", "greenValue", "blueValue"), dev["base"], strict=True):
                caps["color_rgb"][k] = round(c * b / 100)
        if self.die_after_write:
            self.down = True
        return ok({})

    def writes(self):
        return [c for c in self.calls if c[0] == "update_device_capabilities"]


def make(tmp_path, mcp=None, writes=True, grant=("lamp", "plug"), minutes=10, power_unit=""):
    mcp = mcp or FakeMcp()
    s = Settings(
        mcp_instantpower_unit=power_unit,
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


def test_lamp_brightness_is_written_before_color(tmp_path):
    # Kit real (2026-11-18): escrever o brilho DEPOIS da cor anula a cor e repõe a anterior.
    home, mcp, _ = make(tmp_path)
    mcp.brightness_resets_color = True
    assert run(home.definir_lampada(True, "vermelho", 50)) is True
    lamp = run(home.estado()).lampada
    assert (lamp.rgb, lamp.brilho) == ((255, 0, 0), 50)
    tipos = [a["body"]["type"] for _, a in mcp.writes()]
    assert tipos.index("brightness") < tipos.index("color_rgb")


def _lamp_json(rgb, brilho):
    r, g, b = rgb
    return {
        "type": "bulb",
        "capabilities": _caps(
            ("brightness", {"value": brilho}),
            ("color_rgb", {"redValue": r, "greenValue": g, "blueValue": b}),
        ),
    }


def test_color_check_is_not_fooled_at_low_brightness():
    # a 1 % o RGB lido (0–3) cabia todo na tolerância: vermelho passava por branco-azulado
    vermelho_a_1 = _lamp_json((3, 0, 0), 1)
    assert cor_verificavel((200, 200, 255), 1) is False
    assert _rgb_confere(vermelho_a_1, (200, 200, 255)) is False
    assert _rgb_confere(vermelho_a_1, (255, 0, 0)) is False  # não verificável: nunca «confere»
    # com brilho suficiente a cor distingue-se
    assert cor_verificavel((200, 200, 255), 40) is True
    assert _rgb_confere(_lamp_json((102, 0, 0), 40), (200, 200, 255)) is False
    assert _rgb_confere(_lamp_json((80, 80, 102), 40), (200, 200, 255)) is True


def test_verify_lamp_applies_and_restores_color_in_the_safe_order(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _="": "AUTORIZO LAMPADA")
    home, mcp, _ = make(tmp_path, grant=("lamp",))
    mcp.brightness_resets_color = True
    mcp.dev["L0"]["capabilities"][0]["value"] = "on"
    r = run(verify_lamp(home))
    assert r["applied_confirmed"] is True and r["restored_confirmed"] is True
    assert r["restored_color_verified"] is True
    final = r["final"]
    assert (final["ligada"], final["brilho"]) == (True, 30)
    assert all(abs(c - 255) <= 3 for c in final["rgb"])  # normalizado a 30 %: arredonda
    tipos = [a["body"]["type"] for _, a in mcp.writes()]
    assert tipos == ["power", "brightness", "color_rgb", "brightness", "color_rgb", "power"]


def test_verify_lamp_flags_unverifiable_color_when_restoring_to_dim(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _="": "AUTORIZO LAMPADA")
    home, mcp, _ = make(tmp_path, grant=("lamp",))
    mcp.dev["L0"]["capabilities"][0]["value"] = "on"
    mcp.dev["L0"]["capabilities"][1]["value"] = 1  # brilho inicial 1 %
    r = run(verify_lamp(home))
    assert r["restored_color_verified"] is False  # só ligada e brilho foram confirmados
    assert r["restored_confirmed"] is True


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


def test_request_during_session_close_uses_new_session():
    """Regressão: um pedido feito enquanto a sessão falhada fecha não pode ficar órfão."""
    from homemind.connectors.mcp_home import _Conexao

    opens = 0

    @asynccontextmanager
    async def factory():
        nonlocal opens
        opens += 1
        try:
            yield opens
        finally:
            await asyncio.sleep(0.05)  # fecho lento, como o transporte real

    async def falha(_):
        raise ConnectionError("x")

    async def ok(session):
        return session

    async def cenario():
        con = _Conexao(factory, lambda: None)
        try:
            await con.executar(falha, 1)
        except ConnectionError:
            pass
        try:
            return await asyncio.wait_for(con.executar(ok, 1), 0.5)
        finally:
            await con.fechar()

    assert run(cenario()) == 2


def test_abandoned_request_never_runs_later():
    """Um pedido cujo chamador desistiu (timeout) não pode ser executado mais tarde."""
    from homemind.connectors.mcp_home import _Conexao

    executados = []

    @asynccontextmanager
    async def factory():
        yield None

    async def cenario():
        con = _Conexao(factory, lambda: None)
        desistiu = asyncio.get_running_loop().create_future()
        desistiu.cancel()

        async def escrita_antiga(_):
            executados.append("antiga")

        async def nova(_):
            executados.append("nova")

        con._fila.put_nowait((escrita_antiga, desistiu, 1))
        await con.executar(nova, 1)
        await con.fechar()

    run(cenario())
    assert executados == ["nova"]


def test_accepted_but_unapplied_write_is_failure_without_retry(tmp_path, monkeypatch):
    """MCP responde sucesso mas o dispositivo não muda: falha, 1 só escrita, com diagnóstico."""
    import time

    from homemind.connectors import mcp_home

    monkeypatch.setattr(mcp_home, "_READBACK_GAP_S", 0)
    fake = FakeMcp()
    fake.ignore_writes = True
    fake.dev["L0"]["lastCommunicationTime"] = int((time.time() - 20 * 60) * 1000)
    home, _, _ = make(tmp_path, fake, grant=("lamp",))
    assert run(home.definir_lampada(False)) is True  # já estava desligada: confirmado
    fake.calls.clear()
    assert run(home.definir_lampada(True)) is False
    assert len(fake.writes()) == 1
    assert "não corresponde" in home.ultima_falha
    assert "sem contactar a cloud há 2" in home.ultima_falha


# ---- B2: OAuth expirado na tarefa filha do SDK ------------------------------------------------


def test_reauth_in_sdk_child_task_reports_login(tmp_path):
    """Regressão: o aviso tem de mandar fazer `make mcp-login`, não «ConnectionError»."""

    @asynccontextmanager
    async def factory():
        async def filha():
            await asyncio.sleep(0.05)
            raise OAuthReauthRequired("refresh expirado")

        async with asyncio.TaskGroup() as tg:  # como o transporte do SDK: o filho mata o pai
            tg.create_task(filha())
            yield SessionLenta()

    class SessionLenta(FakeMcp):
        async def list_tools(self):
            await asyncio.sleep(0.3)
            return await super().list_tools()

    s = Settings(mcp_write_grant_path=tmp_path / "grant.json")
    home = McpHome(s, factory)
    run(home._refrescar())
    casa = run(home.estado())
    assert casa.mcp_ok is False
    assert "make mcp-login" in casa.aviso and "ConnectionError" not in casa.aviso
    run(home.parar())


# ---- B3: escrita enviada e transporte caído -------------------------------------------------


def test_sent_write_with_dead_transport_leaves_unknown_state(tmp_path):
    home, mcp, _ = make(tmp_path)
    run(home._refrescar())
    assert run(home.estado()).lampada.ligada is False
    mcp.die_after_write = True
    assert run(home.definir_lampada(True)) is False
    casa = run(home.estado())
    assert mcp.writes()  # a escrita chegou a ser enviada (e nunca é repetida)
    assert len(mcp.writes()) == 1
    assert casa.mcp_ok is False and casa.lampada.ligada is None and casa.tomada.ligada is None


# ---- B4: unidade de instantPower ------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "declared", "esperado"),
    [
        ("", None, None),  # sem unidade conhecida: desconhecido, nunca inventado
        ("W", None, 55.0),
        ("dW", None, 5.5),
        ("mW", None, 0.055),
        ("W", "mW", 0.055),  # a unidade declarada pelo dispositivo tem prioridade
    ],
)
def test_instantpower_unit_override(tmp_path, unit, declared, esperado):
    home, _, _ = make(tmp_path, FakeMcp(unit=declared), power_unit=unit)
    run(home._refrescar())
    consumo = run(home.ler_consumo())
    if esperado is None:
        assert consumo is None
        assert run(home.estado()).tomada.consumo_w is None
    else:
        assert consumo == pytest.approx(esperado)
        assert run(home.estado()).tomada.consumo_w == pytest.approx(esperado)


# ---- B5: uma falha de leitura isolada não apaga o estado ----------------------------------


def test_single_poll_failure_keeps_state_two_in_a_row_clear_it(tmp_path):
    home, mcp, _ = make(tmp_path)
    run(home._refrescar())
    mcp.fail_reads = 1
    run(home._refrescar())  # falha 1× e a repetição (sessão nova) funciona
    casa = run(home.estado())
    assert casa.mcp_ok is True and casa.tomada.ligada is True and casa.lampada.brilho == 30
    assert mcp.opens == 2
    mcp.fail_reads = 4  # a leitura de lâmpada e tomada é paralela: 2 falhas por tentativa
    run(home._refrescar())  # duas tentativas falhadas seguidas
    casa = run(home.estado())
    assert casa.mcp_ok is False and casa.lampada.ligada is None and "indisponível" in casa.aviso


# ---- B6: power on nunca é omitido -----------------------------------------------------------


def test_power_on_sent_even_if_cache_says_on(tmp_path):
    home, mcp, _ = make(tmp_path)
    mcp.dev["L0"]["capabilities"][0]["value"] = "on"
    run(home._refrescar())
    assert run(home.estado()).lampada.ligada is True  # cache fresca: ligada
    mcp.dev["L0"]["capabilities"][0]["value"] = "off"  # apagada na app da Altice entretanto
    assert run(home.definir_lampada(True)) is True
    assert {"type": "power", "value": "on"} in [a["body"] for _, a in mcp.writes()]
    assert run(home.estado()).lampada.ligada is True


# ---- B7 e conformidade com o contrato Home -----------------------------------------------------


def test_fake_home_ignores_brightness_when_off():
    fake = FakeHome()
    assert run(fake.definir_lampada(False, None, 999)) is True
    assert run(fake.definir_lampada(True, None, 999)) is False


def _fake(tmp_path):
    return FakeHome(), None


def _mcp(tmp_path):
    home, mcp, _ = make(tmp_path)
    run(home._refrescar())
    return home, mcp


@pytest.mark.parametrize("criar", [_fake, _mcp], ids=["fake", "mcp"])
def test_home_contract_conformance(tmp_path, criar):
    home, _ = criar(tmp_path)
    for brilho, esperado in ((0, False), (1, True), (100, True), (101, False)):
        assert run(home.definir_lampada(True, "azul", brilho)) is esperado, brilho
    assert run(home.definir_lampada(True, "azul", 40)) is True
    # com ligada=False cor e brilho são ignorados (mesmo inválidos)
    assert run(home.definir_lampada(False, "vermelho", 999)) is True
    assert run(home.estado()).lampada.ligada is False
    assert run(home.definir_lampada(True, None, None)) is True  # None = manter
    assert run(home.definir_tomada(True)) is True
    consumo = run(home.ler_consumo())
    assert consumo is None or isinstance(consumo, float)
    casa = run(home.estado())
    if isinstance(home, FakeHome):
        assert (casa.backend, casa.mcp_ok) == ("fake", False)
    else:
        assert (casa.backend, casa.mcp_ok) == ("mcp", True)
    assert casa.lampada.ligada is True and casa.tomada.ligada is True


# ---- Integração: motor real sobre McpHome (servidor MCP falso) --------------------------------


def test_engine_over_mcp_home_gesture_outage_and_recovery(tmp_path):
    from homemind.contracts.eventos import ObjetoLevantado
    from homemind.features.engine.engine import Engine, Estado, Tempos
    from homemind.features.engine.eventlog import EventLog
    from homemind.features.engine.rules import RulesStore

    async def cenario():
        home, mcp, _ = make(tmp_path)
        regras = RulesStore(tmp_path / "rules.json")
        regras.carregar()
        engine = Engine(home, regras, EventLog(tmp_path / "e.jsonl", "mcp"), Tempos())
        await home._refrescar()
        await engine.iniciar()
        await engine.processar(ObjetoLevantado(classe="livro", hora=datetime.now(UTC)))
        assert engine.estado == Estado.ATIVO
        casa = engine.home_state().casa
        assert (casa.lampada.ligada, casa.lampada.brilho) == (True, 40)
        assert casa.tomada.ligada is True

        mcp.down = True  # MCP em baixo
        res = await engine.desligar_tudo()
        assert res.success is False and res.code == "mcp_unavailable"
        assert res.devices.lampada == "unknown" and res.devices.tomada == "unknown"
        await home._refrescar()
        assert engine.home_state().mcp_ok is False

        mcp.down = False  # recuperação
        await home._refrescar()
        assert engine.home_state().mcp_ok is True
        res = await engine.desligar_tudo()
        assert res.success is True and res.code is None
        await home.parar()

    run(cenario())


@pytest.mark.parametrize("failures,expected", [(0, 5), (1, 10), (2, 20), (3, 40), (10000, 60)])
def test_next_poll_delay(failures, expected):
    from homemind.connectors.mcp_home import _next_poll_delay

    assert _next_poll_delay(5, failures, 60) == expected


def test_collector_receives_readings_and_failure(tmp_path):
    home, mcp, _ = make(tmp_path)
    calls = []
    home.coletor = SimpleNamespace(
        ingest=lambda plug: calls.append(("ingest", plug)),
        unavailable=lambda: calls.append(("unavailable", None)),
    )
    run(home._refrescar())
    assert calls == [("ingest", mcp.dev["P0"])]
    mcp.down = True
    run(home._refrescar())
    assert calls[-1] == ("unavailable", None)
    assert home._falhas_consecutivas == 1
    mcp.down = False
    run(home._refrescar())
    assert home._falhas_consecutivas == 0
    home.coletor = None
    run(home._refrescar())
    run(home.parar())


def test_collector_failure_does_not_affect_home(tmp_path):
    home, mcp, _ = make(tmp_path, FakeMcp(unit="W"))

    def fail(*args):
        raise RuntimeError("secret")

    home.coletor = SimpleNamespace(ingest=fail, unavailable=fail)
    run(home._refrescar())
    assert run(home.ler_consumo()) == 55
    mcp.down = True
    run(home._refrescar())
    assert not run(home.estado()).mcp_ok
    run(home.parar())


def test_sensor_collector_read_only_and_failure(tmp_path):
    home, mcp, _ = make(tmp_path)
    mcp.dev["S0"] = {
        "id": "S0",
        "type": "contactSensor",
        "categories": ["security"],
        "capabilities": _caps(("sensorState", {"value": "normal"})),
    }
    calls = []
    home.sensores = SimpleNamespace(
        ingest=lambda devices: calls.append(("ingest", devices)),
        unavailable=lambda: calls.append(("unavailable", None)),
    )
    run(home._refrescar())
    assert calls == [("ingest", list(mcp.dev.values()))]
    assert [name for name, _ in mcp.calls].count("get_home_devices") == 2
    mcp.down = True
    run(home._refrescar())
    assert calls[-1] == ("unavailable", None)
    assert mcp.writes() == []
    run(home.parar())


def test_no_sensor_collector_no_extra_inventory(tmp_path):
    home, mcp, _ = make(tmp_path)
    run(home._refrescar())
    run(home._refrescar())
    assert [name for name, _ in mcp.calls].count("get_home_devices") == 1
    assert mcp.writes() == []
    run(home.parar())


def test_sensor_collector_failure_does_not_affect_home(tmp_path, caplog):
    home, mcp, _ = make(tmp_path)

    def fail(*args):
        raise RuntimeError("secret")

    home.sensores = SimpleNamespace(ingest=fail, unavailable=fail)
    run(home._refrescar())
    assert run(home.estado()).mcp_ok
    mcp.down = True
    run(home._refrescar())
    assert not run(home.estado()).mcp_ok
    assert "secret" not in caplog.text
    assert mcp.writes() == []
    run(home.parar())


def test_rule_refusals_and_safe_reasons(tmp_path):
    from homemind.connectors.write_policy import Decision, WriteOutcome

    now = datetime.now(UTC)
    valid = Decision("rule", "operator", now - timedelta(seconds=1), now + timedelta(hours=1))
    expired = Decision("rule", "operator", now - timedelta(hours=2), now - timedelta(hours=1))
    for writes, grant, decision in (
        (True, ("plug",), None),
        (True, ("plug",), expired),
        (False, ("plug",), valid),
        (True, None, valid),
        (True, ("lamp",), valid),
    ):
        home, mcp, _ = make(tmp_path, writes=writes, grant=grant)
        if grant is None:
            home._settings.mcp_write_grant_path.unlink(missing_ok=True)
        result = run(home.tomada_por_regra(False, decision))
        assert result.outcome is WriteOutcome.refused and not mcp.writes()
        assert "P0" not in result.reason and "L0" not in result.reason
    home, mcp, _ = make(tmp_path)
    result = run(
        home._escrever_regra("plug", [{"type": "brightness", "value": 5}], lambda d: True, valid)
    )
    assert result.outcome is WriteOutcome.refused and not mcp.writes()


def test_rule_confirmed_unapplied_and_uncertain(tmp_path, monkeypatch):
    import time

    from homemind.connectors import mcp_home
    from homemind.connectors.write_policy import Decision, WriteOutcome

    monkeypatch.setattr(mcp_home, "_READBACK_GAP_S", 0)
    now = datetime.now(UTC)
    decision = Decision("rule", "operator", now - timedelta(seconds=1), now + timedelta(hours=1))
    home, mcp, _ = make(tmp_path)
    home._agora = lambda: now
    result = run(home.lampada_por_regra(True, decision=decision))
    assert result.ok and len(mcp.writes()) == 1 and result.reason is None
    for stale, expected in ((False, WriteOutcome.failed), (True, WriteOutcome.unknown)):
        fake = FakeMcp()
        fake.ignore_writes = True
        if stale:
            fake.dev["L0"]["lastCommunicationTime"] = int((time.time() - 1200) * 1000)
        home, _, _ = make(tmp_path, fake)
        result = run(home.lampada_por_regra(True, decision=decision))
        assert result.outcome is expected and len(fake.writes()) == 1
        assert "L0" not in result.reason and "P0" not in result.reason
    home, fake, _ = make(tmp_path)
    home._agora = lambda: now
    fake.die_after_write = True
    result = run(home.lampada_por_regra(True, decision=decision))
    assert result.outcome is WriteOutcome.unknown
    assert "L0" not in result.reason and "P0" not in result.reason
    assert run(home.lampada_por_regra(True, decision=decision)).outcome is WriteOutcome.refused
    assert len(fake.writes()) == 1


def test_rule_write_failing_before_send_is_failed_not_unknown(tmp_path, monkeypatch):
    """Nada enviado => `failed` (não `unknown`): não bloqueia as regras como uma escrita incerta."""
    from homemind.connectors import mcp_home
    from homemind.connectors.write_policy import Decision, WriteOutcome

    monkeypatch.setattr(mcp_home, "_READBACK_GAP_S", 0)
    now = datetime.now(UTC)
    decision = Decision("rule", "operator", now - timedelta(seconds=1), now + timedelta(hours=1))
    fake = FakeMcp()
    fake.down = True  # a ligação falha ANTES de qualquer escrita
    home, _, _ = make(tmp_path, fake)
    home._agora = lambda: now
    result = run(home.lampada_por_regra(True, decision=decision))
    assert result.outcome is WriteOutcome.failed
    assert len(fake.writes()) == 0
    assert "L0" not in (result.reason or "") and "P0" not in (result.reason or "")
    # Ligação de volta e passado o cooldown: a regra pode escrever (não há bloqueio de incerteza).
    fake.down = False
    home._agora = lambda: now + timedelta(seconds=61)
    again = run(home.lampada_por_regra(True, decision=decision))
    assert again.outcome is WriteOutcome.confirmed and len(fake.writes()) == 1
