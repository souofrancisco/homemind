"""Interface `Home` (FakeHome | McpHome) e `EstadoCasa`, conforme frontend-api-contract (P3).

O motor só conhece este contrato, nunca o MCP. Sem IDs de dispositivos (ficam no backend).
"""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

Cor = Literal[
    "branco",
    "branco_quente",
    "branco_frio",
    "azul",
    "vermelho",
    "verde",
    "amarelo",
    "laranja",
    "roxo",
    "rosa",
]

# RGB de referência de cada nome (pré-visualização e tradução para o kit).
CORES: dict[str, tuple[int, int, int]] = {
    "branco": (255, 255, 255),
    "branco_quente": (255, 170, 90),
    "branco_frio": (200, 220, 255),
    "azul": (0, 0, 255),
    "vermelho": (255, 0, 0),
    "verde": (0, 255, 0),
    "amarelo": (255, 200, 0),
    "laranja": (255, 110, 0),
    "roxo": (140, 0, 255),
    "rosa": (255, 60, 150),
}

Backend = Literal["fake", "mcp"]


class EstadoLampada(BaseModel):
    """`None` = desconhecido (sem leitura). Nunca assumir desligado."""

    ligada: bool | None = None
    cor: Cor | None = None
    rgb: tuple[int, int, int] | None = None
    brilho: int | None = Field(None, ge=1, le=100)


class EstadoTomada(BaseModel):
    ligada: bool | None = None
    consumo_w: float | None = None  # None = indisponível/antigo; nunca 0 inventado
    consumo_lido_em: datetime | None = None


class EstadoCasa(BaseModel):
    backend: Backend
    mcp_ok: bool  # com backend "fake" é sempre False (não é erro)
    lampada: EstadoLampada
    tomada: EstadoTomada
    atualizado_em: datetime
    aviso: str | None = None


class Home(Protocol):
    """Escritas devolvem True só se o estado foi confirmado (no McpHome, após releitura).
    `cor`/`brilho` a None = manter o valor atual; com `ligada=False` são ignorados."""

    async def definir_lampada(
        self, ligada: bool, cor: Cor | None = None, brilho: int | None = None
    ) -> bool: ...

    async def definir_tomada(self, ligada: bool) -> bool: ...

    async def ler_consumo(self) -> float | None:
        """Watts da tomada (último valor em cache); None = indisponível."""
        ...

    async def estado(self) -> EstadoCasa: ...
