"""Cliente MCP (Streamable HTTP) do Connected Home da Altice. Único módulo que importa o SDK MCP."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from homemind.core.config import get_settings


@asynccontextmanager
async def altice_session() -> AsyncIterator[ClientSession]:
    s = get_settings()
    if not s.mcp_endpoint or not s.mcp_api_key:
        raise RuntimeError("MCP_ENDPOINT e MCP_API_KEY têm de estar definidos")
    headers = {"X-API-Key": s.mcp_api_key, "X-Client-Type": s.mcp_client_type}
    # shortcut: sem OAuth interativo (Keycloak); token já obtido vai em MCP_AUTH_TOKEN.
    if s.mcp_auth_token:
        headers["Authorization"] = f"Bearer {s.mcp_auth_token}"
    async with streamablehttp_client(s.mcp_endpoint, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
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
        raise RuntimeError(f"tool {name} falhou: {res.content}")
    return res.structuredContent or [c.model_dump(mode="json") for c in res.content]
