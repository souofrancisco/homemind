"""Interface `Home` (Pessoa 3) usada pelo motor (Pessoa 4). Assinaturas do plano §3.

`FakeHome` e `McpHome` implementam o mesmo Protocol. Só lâmpada e tomada; nada de
alarme/segurança.
"""

from typing import Protocol

from pydantic import Field

from homemind.contracts.base import Contrato

BRILHO_MIN, BRILHO_MAX = 0, 100


class EstadoLampada(Contrato):
    ligada: bool
    cor: str | None = None  # nome de cor; valores aceites dependem das capacidades reais (P3)
    brilho: int | None = Field(default=None, ge=BRILHO_MIN, le=BRILHO_MAX)  # percentagem


class EstadoTomada(Contrato):
    ligada: bool


class EstadoCasa(Contrato):
    lampada: EstadoLampada
    tomada: EstadoTomada
    consumo_w: float | None = None  # última leitura em W; None se ainda não houver
    simulado: bool  # True em FakeHome: a UI tem de distinguir SIMULADO de REAL


class Home(Protocol):
    """Os métodos `definir_*` devolvem True só se a ação foi aplicada e confirmada.

    `cor`/`brilho` a None significam «não alterar».
    """

    async def definir_lampada(self, ligada: bool, cor: str | None, brilho: int | None) -> bool: ...

    async def definir_tomada(self, ligada: bool) -> bool: ...

    async def ler_consumo(self) -> float:
        """Último consumo conhecido da tomada, em W."""
        ...

    async def estado(self) -> EstadoCasa: ...
