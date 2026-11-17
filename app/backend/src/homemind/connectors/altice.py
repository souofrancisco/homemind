"""Cliente MCP (Streamable HTTP) do Connected Home da Altice. Único módulo que importa o SDK MCP."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession

from homemind.connectors.altice_auth import altice_session as oauth_altice_session


@asynccontextmanager
async def altice_session() -> AsyncIterator[ClientSession]:
    async with oauth_altice_session() as session:
        yield session


async def list_tools() -> list[dict[str, Any]]:
    async with altice_session() as session:
        res = await session.list_tools()
    return [t.model_dump(mode="json", exclude_none=True) for t in res.tools]


async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Uma tentativa, sem retry (escritas). Quem chama decide autorização e releitura."""
    async with altice_session() as session:
        res = await session.call_tool(name, arguments)
    if res.isError:
        raise RuntimeError(f"tool {name} falhou")
    return res.structuredContent or [c.model_dump(mode="json") for c in res.content]
