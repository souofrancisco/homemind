import asyncio
import logging
import threading
import time
from datetime import UTC, datetime

from homemind.contracts.eventos import Evento, ObjetoLevantado, Presenca
from homemind.contracts.visao import FrameDeteccoes
from homemind.features.gestos.ponte import PublicadorFila, PublicadorLista
from homemind.features.gestos.processador import ProcessadorObjectOS
from homemind.features.gestos.tests._fakes import (
    DetetorFalso,
    FonteVideoFalsa,
    ThreadVisaoFalsa,
    encadear,
    segmento,
    segmento_presenca,
)

HORA = datetime(2026, 1, 1, tzinfo=UTC)


def evento_n(n: int) -> Evento:
    """Alterna tipos; `n` vai na hora (microssegundos) para distinguir duplicados."""
    hora = HORA.replace(microsecond=n)
    if n % 2:
        return Presenca(ha_alguem=bool(n % 4 == 1), hora=hora)
    return ObjetoLevantado(classe="caneca", hora=hora)


class UmEventoPorFrame:
    """Processador de teste: um evento por frame (`indice` -> `evento_n`)."""

    def processar(self, frame: FrameDeteccoes) -> tuple[Evento, ...]:
        return (evento_n(frame.indice),)


def frames_vazios(n: int) -> list[FrameDeteccoes]:
    return segmento_presenca(n / 10, False)


def montar(n: int, publicador, processador, atraso_s: float = 0.0, frames=None):
    frames = frames if frames is not None else frames_vazios(n)
    return ThreadVisaoFalsa(
        FonteVideoFalsa(len(frames)), DetetorFalso(frames, atraso_s), processador, publicador
    )


def test_ordem_1000_eventos_sem_duplicados():
    async def main() -> list[Evento]:
        fila: asyncio.Queue[Evento] = asyncio.Queue()
        thread = montar(1000, PublicadorFila(asyncio.get_running_loop(), fila), UmEventoPorFrame())
        thread.iniciar()
        recebidos = [await asyncio.wait_for(fila.get(), 5) for _ in range(1000)]
        assert thread.esperar() and thread.erro is None
        await asyncio.sleep(0.05)
        assert fila.empty()  # nada a mais
        return recebidos

    assert asyncio.run(main()) == [evento_n(i) for i in range(1000)]


def test_inferencia_lenta_nao_bloqueia_o_loop():
    async def main() -> tuple[float, int]:
        fila: asyncio.Queue[Evento] = asyncio.Queue()
        thread = montar(
            4, PublicadorFila(asyncio.get_running_loop(), fila), UmEventoPorFrame(), 0.3
        )
        thread.iniciar()
        pior, fim = 0.0, time.monotonic() + 1.0
        while time.monotonic() < fim:  # no lugar do WS
            t = time.monotonic()
            await asyncio.sleep(0.01)
            pior = max(pior, time.monotonic() - t - 0.01)
        thread.parar.set()
        assert thread.esperar()
        return pior, fila.qsize()

    pior, n = asyncio.run(main())
    assert pior < 0.05
    assert n >= 2


def test_encerramento_do_loop_com_publicacoes_em_curso():
    fila_ref: list[asyncio.Queue[Evento]] = []

    async def main() -> ThreadVisaoFalsa:
        fila: asyncio.Queue[Evento] = asyncio.Queue()
        fila_ref.append(fila)
        # Mais frames do que dá tempo de consumir: ainda publica depois de o loop fechar.
        thread = montar(
            100_000, PublicadorFila(asyncio.get_running_loop(), fila), UmEventoPorFrame()
        )
        thread.iniciar()
        await asyncio.sleep(0.05)
        return thread

    thread = asyncio.run(main())  # o loop fecha com a thread a publicar
    time.sleep(0.05)  # a thread publica contra o loop fechado
    assert thread.erro is None
    t0 = time.monotonic()
    thread.parar.set()
    assert thread.esperar(1.0)
    assert time.monotonic() - t0 < 1.0
    assert thread.erro is None


def test_fila_cheia_descarta_com_warning_sem_conteudo(caplog):
    async def main() -> asyncio.Queue[Evento]:
        fila: asyncio.Queue[Evento] = asyncio.Queue(maxsize=2)
        pub = PublicadorFila(asyncio.get_running_loop(), fila)
        for i in range(4):
            pub.publicar(evento_n(i))
        await asyncio.sleep(0.05)
        return fila

    with caplog.at_level(logging.DEBUG, logger="homemind.features.gestos.ponte"):
        fila = asyncio.run(main())
    assert [fila.get_nowait(), fila.get_nowait()] == [evento_n(0), evento_n(1)]
    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(avisos) == 2
    texto = " ".join(r.getMessage() for r in avisos)
    assert "fila cheia" in texto
    assert "caneca" not in texto and "2026" not in texto


def test_publicar_com_loop_fechado_so_debug(caplog):
    loop = asyncio.new_event_loop()
    pub = PublicadorFila(loop, asyncio.Queue())
    loop.close()
    with caplog.at_level(logging.DEBUG, logger="homemind.features.gestos.ponte"):
        pub.publicar(evento_n(0))  # não lança
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]
    assert "caneca" not in caplog.text


def test_publicador_lista_thread_safe():
    pub = PublicadorLista()
    por_thread, n_threads = 200, 8

    def escrever(k: int) -> None:
        for i in range(por_thread):
            pub.publicar(evento_n(k * por_thread + i))

    threads = [threading.Thread(target=escrever, args=(k,)) for k in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    eventos = pub.eventos
    assert isinstance(eventos, tuple)
    assert len(eventos) == por_thread * n_threads
    assert set(eventos) == {evento_n(i) for i in range(por_thread * n_threads)}
    for k in range(n_threads):  # ordem preservada dentro de cada thread
        esperados = [evento_n(k * por_thread + i) for i in range(por_thread)]
        conjunto = set(esperados)
        assert [e for e in eventos if e in conjunto] == esperados


def test_ponta_a_ponta_presenca_antes_do_gesto():
    frames = list(
        encadear(
            segmento(1.5, "levantado", "caneca"),
            segmento(1.0, "repouso", "caneca", t0=1.5, indice0=15),
            segmento_presenca(3.2, False, t0=2.5, indice0=25),
        )
    )

    async def main() -> list[Evento]:
        fila: asyncio.Queue[Evento] = asyncio.Queue()
        thread = montar(
            0,
            PublicadorFila(asyncio.get_running_loop(), fila),
            ProcessadorObjectOS(),
            frames=frames,
        )
        thread.iniciar()
        recebidos = [await asyncio.wait_for(fila.get(), 5) for _ in range(3)]
        assert thread.esperar() and thread.erro is None
        assert fila.empty()
        return recebidos

    eventos = asyncio.run(main())
    assert [type(e) for e in eventos] == [Presenca, ObjetoLevantado, Presenca]
    assert [getattr(e, "ha_alguem", None) for e in eventos] == [True, None, False]
    assert eventos[1].classe == "caneca"


def test_fila_e_loop_criados_como_o_motor_os_cria():
    """O motor cria `asyncio.Queue()` (sem limite) e guarda `get_running_loop()` em `iniciar()`."""
    recebidos: list[Evento] = []

    async def cenario() -> None:
        loop = asyncio.get_running_loop()
        fila: asyncio.Queue[Evento] = asyncio.Queue()
        publicador = PublicadorFila(loop, fila)
        esperados = [evento_n(n) for n in range(50)]
        th = threading.Thread(target=lambda: [publicador.publicar(e) for e in esperados])
        th.start()
        for _ in esperados:
            recebidos.append(await asyncio.wait_for(fila.get(), timeout=2))
        th.join()
        assert recebidos == esperados
        assert fila.empty()

    asyncio.run(cenario())
