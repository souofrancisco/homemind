"""Ciclo de vida do `Home` do kit: antes vivia no lifespan do motor ObjectOS (BASE-04 #74)."""

import asyncio
from types import SimpleNamespace

import pytest

from homemind.core.config import Settings
from homemind.features.energy import home_runtime as hr


class _Home:
    """Dublê de `McpHome`: regista o ciclo de vida, sem rede nem hardware."""

    def __init__(self):
        self.iniciado = False
        self.parado = False

    async def iniciar(self):
        self.iniciado = True

    async def parar(self):
        self.parado = True


def _app():
    return SimpleNamespace(
        state=SimpleNamespace(db="db", bus="bus", appliance_catalog="catalogo"),
        dependency_overrides={},
    )


def _run(coro):
    return asyncio.run(coro)


def _patch(monkeypatch, settings, home=None):
    chamadas = {"coletores": None, "atuador": None}
    monkeypatch.setattr(hr, "get_settings", lambda: settings)
    monkeypatch.setattr(hr, "criar_home", lambda s: home)

    async def coletores(h, **kw):
        chamadas["coletores"] = (h, kw)

    def atuador(state, h, **kw):
        chamadas["atuador"] = (state, h, kw)
        return True

    monkeypatch.setattr(hr, "attach_kit_collectors", coletores)
    monkeypatch.setattr(hr, "attach_kit_actuators", atuador)
    return chamadas


def test_fake_nao_cria_home_nem_liga_o_kit(monkeypatch):
    chamadas = _patch(monkeypatch, Settings(home_backend="fake"), home=None)
    app = _app()

    async def corre():
        async with hr.home_runtime(app):
            assert app.state.home is None

    _run(corre())
    assert chamadas == {"coletores": None, "atuador": None}


def test_criar_home_so_com_mcp():
    assert hr.criar_home(Settings(home_backend="fake")) is None


def test_mcp_inicia_liga_coletores_e_atuador_e_para(monkeypatch):
    settings = Settings(home_backend="mcp")
    home = _Home()
    chamadas = _patch(monkeypatch, settings, home=home)
    app = _app()

    async def corre():
        async with hr.home_runtime(app):
            assert app.state.home is home and home.iniciado and not home.parado
            h, kw = chamadas["coletores"]
            assert h is home and kw["db"] == "db" and kw["bus"] == "bus"
            assert kw["catalog"] == "catalogo" and kw["settings"] is settings
            state, h2, kw2 = chamadas["atuador"]
            assert state is app.state and h2 is home and kw2["settings"] is settings

    _run(corre())
    assert home.parado


def test_mcp_para_o_home_mesmo_com_erro(monkeypatch):
    home = _Home()
    _patch(monkeypatch, Settings(home_backend="mcp"), home=home)

    async def corre():
        async with hr.home_runtime(_app()):
            raise RuntimeError("falha no arranque")

    with pytest.raises(RuntimeError):
        _run(corre())
    assert home.iniciado and home.parado
