"""Ciclo de vida do `Home` do kit (MCP) no arranque da app.

Antes vivia no `lifespan` do motor ObjectOS (`features/engine`); passou para aqui na BASE-04
(#74) para o motor poder sair. Só existe `Home` com `HOME_BACKEND=mcp`: com `fake` não há nada a
ligar (os coletores e o atuador do kit só ativam sobre `McpHome`, e a demo SIMULADA usa o
`FakeKit` por baixo da mesma sessão MCP).

Publica `app.state.home` (o `McpHome`, ou `None`) para quem precisar da sessão única, por exemplo
`/api/mcp/tools` (renovações OAuth não colidem). As guardas de escrita física continuam dentro
do `McpHome` (grant temporário, whitelist, releitura); este módulo não escreve nada.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from homemind.connectors.mcp_home import McpHome
from homemind.core.access import get_clock
from homemind.core.config import Settings, get_settings
from homemind.features.energy.kit import attach_kit_collectors
from homemind.features.energy.kit_actuators import attach_kit_actuators


def criar_home(settings: Settings) -> McpHome | None:
    """`McpHome` com `HOME_BACKEND=mcp`; senão `None` (nada a ligar)."""
    return McpHome() if settings.home_backend == "mcp" else None


@asynccontextmanager
async def home_runtime(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    home = criar_home(settings)
    app.state.home = home
    if home is None:
        yield
        return
    try:
        iniciar = getattr(home, "iniciar", None)
        if iniciar is not None:
            await iniciar()
        await attach_kit_collectors(
            home,
            settings=settings,
            db=app.state.db,
            bus=app.state.bus,
            # Publicado por `appliances` em app.state (arranca antes: ordem alfabética das
            # features); sem importar a feature.
            catalog=getattr(app.state, "appliance_catalog", None),
        )
        # ALERT-06/AGENT-03b: a lâmpada real nas ações confirmadas (só com HOME_BACKEND=mcp).
        attach_kit_actuators(
            app.state,
            home,
            settings=settings,
            clock=app.dependency_overrides.get(get_clock, get_clock)(),
        )
        yield
    finally:
        parar = getattr(home, "parar", None)
        if parar is not None:
            await parar()
