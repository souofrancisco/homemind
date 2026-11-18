from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from homemind.connectors import altice
from homemind.connectors.mcp_home import McpHome
from homemind.core.access import require_operator

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/tools", dependencies=[Depends(require_operator)])
async def tools(request: Request) -> list[dict[str, Any]]:
    """Descoberta (`tools/list`) para registar capacidades em docs/mcp-capabilities.md."""
    try:
        engine = getattr(request.app.state, "engine", None)
        if engine is not None and isinstance(engine.home, McpHome):
            # Reutiliza a sessão única (renovações OAuth não colidem).
            return await engine.home.listar_ferramentas()
        return await altice.list_tools()
    except Exception as e:  # indisponível/config em falta: sem detalhes (podem conter headers)
        raise HTTPException(502, "MCP Altice indisponível") from e
