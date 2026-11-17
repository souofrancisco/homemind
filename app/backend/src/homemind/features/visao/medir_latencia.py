"""Mede a latência gesto -> luz (critério da demo: < 4 s):

    python -m homemind.features.visao.medir_latencia --detetor modulo:Classe [--video clip.mp4]

Monta fonte + detetor + `ProcessadorObjectOS` + motor com `FakeHome` (SIMULADO) e conta, para cada
`objeto_levantado`, o tempo desde `ev.hora` (hora do frame) até `definir_lampada(ligada=True)`
devolver. Só números no ecrã: não grava frames nem imprime o URL da fonte. Com FakeHome mede o
pipeline de software; o tempo real da lâmpada (MCP) mede-se à parte.
"""

import argparse
import asyncio
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from homemind.connectors.fake_home import FakeHome
from homemind.contracts.eventos import Evento, ObjetoLevantado
from homemind.contracts.video import FonteVideo
from homemind.core.config import get_settings
from homemind.features.engine.engine import Engine, Tempos
from homemind.features.engine.eventlog import EventLog
from homemind.features.engine.rules import RulesStore
from homemind.features.gestos.ponte import PublicadorFila
from homemind.features.gestos.processador import ProcessadorObjectOS
from homemind.features.video.fonte import criar_fonte
from homemind.features.visao.thread import ThreadVisao, carregar_detetor

LIMITE_S = 4.0


class HomeTemporizada(FakeHome):
    """FakeHome que regista o instante em que cada `definir_lampada(ligada=True)` termina."""

    def __init__(self) -> None:
        super().__init__()
        self.ligacoes: list[datetime] = []

    async def definir_lampada(self, ligada, cor=None, brilho=None) -> bool:
        ok = await super().definir_lampada(ligada, cor, brilho)
        if ligada and ok:
            self.ligacoes.append(datetime.now(UTC))
        return ok


class _PublicadorMedido:
    """Regista a hora de cada gesto e delega no publicador real."""

    def __init__(self, destino: PublicadorFila) -> None:
        self._destino = destino
        self.gestos: list[datetime] = []

    def publicar(self, evento: Evento) -> None:
        if isinstance(evento, ObjetoLevantado):
            self.gestos.append(evento.hora)
        self._destino.publicar(evento)


def latencias(gestos: list[datetime], ligacoes: list[datetime]) -> list[float]:
    """Emparelha cada gesto com a ligação seguinte (por ordem). Gestos sem luz (modo já ativo)
    não contam."""
    resultado: list[float] = []
    i = 0
    for hora in gestos:
        while i < len(ligacoes) and ligacoes[i] < hora:
            i += 1
        if i == len(ligacoes):
            break
        resultado.append((ligacoes[i] - hora).total_seconds())
        i += 1
    return resultado


async def medir(
    fonte: FonteVideo,
    detetor,
    processador: ProcessadorObjectOS,
    *,
    duracao_s: float,
    gestos_max: int,
    dados: Path,
) -> list[float]:
    regras = RulesStore(dados / "rules.json")
    regras.carregar()
    home = HomeTemporizada()
    engine = Engine(home, regras, EventLog(dados / "events.jsonl"), Tempos())
    await engine.iniciar()
    consumidor = asyncio.create_task(engine.consumir())
    publicador = _PublicadorMedido(PublicadorFila(engine.loop, engine.fila))
    thread = ThreadVisao(fonte, detetor, processador, publicador)
    thread.iniciar()
    try:
        fim = time.monotonic() + duracao_s
        while time.monotonic() < fim and len(home.ligacoes) < gestos_max:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)  # deixa o motor terminar o último gesto
    finally:
        thread.parar()
        consumidor.cancel()
        await engine.parar()
    return latencias(publicador.gestos, home.ligacoes)


def resumo(valores: list[float]) -> str:
    if not valores:
        return "Sem gestos que acendam a luz (nada medido)."
    abaixo = sum(v < LIMITE_S for v in valores)
    media = sum(valores) / len(valores)
    return (
        f"{len(valores)} gestos: min {min(valores):.2f} s, média {media:.2f} s, "
        f"máx {max(valores):.2f} s; {abaixo}/{len(valores)} abaixo de {LIMITE_S:.0f} s"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detetor", required=True, help="modulo:Classe (como VISAO_DETETOR)")
    parser.add_argument("--video", help="clip ou RTSP; por omissão VIDEO_SOURCE")
    parser.add_argument("--duracao", type=float, default=60.0, help="segundos máximos")
    parser.add_argument("--gestos", type=int, default=10, help="parar após N luzes acesas")
    args = parser.parse_args()

    settings = get_settings()
    if args.video:
        settings = settings.model_copy(update={"video_source": args.video})
    if not settings.video_source:
        raise SystemExit("Falta --video ou VIDEO_SOURCE.")

    detetor = carregar_detetor(args.detetor)
    fonte = criar_fonte(settings)
    fonte.iniciar()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            valores = asyncio.run(
                medir(
                    fonte,
                    detetor,
                    ProcessadorObjectOS.de_settings(settings),
                    duracao_s=args.duracao,
                    gestos_max=args.gestos,
                    dados=Path(tmp),
                )
            )
    finally:
        fonte.parar()
    print(resumo(valores))
    raise SystemExit(0 if valores and all(v < LIMITE_S for v in valores) else 1)


if __name__ == "__main__":
    main()
