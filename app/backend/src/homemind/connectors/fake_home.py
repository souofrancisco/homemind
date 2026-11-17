"""FakeHome: casa em memória (SIMULADO), sem rede. Sempre `backend="fake"`, `mcp_ok=False`."""

from datetime import UTC, datetime

from homemind.contracts.home import CORES, Cor, EstadoCasa, EstadoLampada, EstadoTomada


class FakeHome:
    def __init__(self, watts_tomada: float = 60.0) -> None:
        self.watts_tomada = watts_tomada
        self.lampada = EstadoLampada(ligada=False, cor="branco_quente", brilho=100)
        self.tomada = EstadoTomada(ligada=False)

    async def definir_lampada(
        self, ligada: bool, cor: Cor | None = None, brilho: int | None = None
    ) -> bool:
        if brilho is not None and not 1 <= brilho <= 100:
            return False
        mudar: dict = {"ligada": ligada}
        if ligada and cor is not None:
            mudar["cor"] = cor
        if ligada and brilho is not None:
            mudar["brilho"] = brilho
        self.lampada = self.lampada.model_copy(update=mudar)
        return True

    async def definir_tomada(self, ligada: bool) -> bool:
        self.tomada = EstadoTomada(ligada=ligada)
        return True

    async def ler_consumo(self) -> float | None:
        return self.watts_tomada if self.tomada.ligada else 0.0

    async def estado(self) -> EstadoCasa:
        agora = datetime.now(UTC)
        lamp = self.lampada
        rgb = CORES[lamp.cor] if lamp.cor else None
        return EstadoCasa(
            backend="fake",
            mcp_ok=False,
            lampada=lamp.model_copy(update={"rgb": rgb}),
            tomada=self.tomada.model_copy(
                update={"consumo_w": await self.ler_consumo(), "consumo_lido_em": agora}
            ),
            atualizado_em=agora,
        )
