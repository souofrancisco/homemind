from typing import Any

from fastapi import APIRouter, HTTPException

from homemind.connectors import altice
from homemind.features.auth.service import CurrentUser

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/tools")
async def tools(user: CurrentUser) -> list[dict[str, Any]]:
    """Descoberta (`tools/list`) para registar capacidades em docs/mcp-capabilities.md."""
    try:
        return await altice.list_tools()
    except Exception as e:  # indisponível/config em falta: sem detalhes (podem conter headers)
        raise HTTPException(502, "MCP Altice indisponível") from e
