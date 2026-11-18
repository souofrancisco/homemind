import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta

from homemind.contracts.eventos import Evento, Presenca
from homemind.features.gestos.ponte import PublicadorFila, PublicadorLista

HORA = datetime(2026, 1, 1, tzinfo=UTC)


def evento_n(n: int) -> Evento:
    return Presenca(ha_alguem=bool(n % 2), hora=HORA + timedelta(microseconds=n))


def test_fila_preserva_ordem_de_publicacoes_de_outra_thread():
    recebidos: list[Evento] = []

    async def cenario() -> None:
        loop = asyncio.get_running_loop()
        fila: asyncio.Queue[Evento] = asyncio.Queue()
        publicador = PublicadorFila(loop, fila)
        esperados = [evento_n(n) for n in range(50)]
        thread = threading.Thread(target=lambda: [publicador.publicar(e) for e in esperados])
        thread.start()
        for _ in esperados:
            recebidos.append(await asyncio.wait_for(fila.get(), timeout=2))
        thread.join()
        assert fila.empty()

    asyncio.run(cenario())
    assert recebidos == [evento_n(n) for n in range(50)]


def test_fila_cheia_descarta_com_warning_sem_conteudo(caplog):
    async def cenario() -> asyncio.Queue[Evento]:
        fila: asyncio.Queue[Evento] = asyncio.Queue(maxsize=2)
        publicador = PublicadorFila(asyncio.get_running_loop(), fila)
        for i in range(4):
            publicador.publicar(evento_n(i))
        await asyncio.sleep(0.05)
        return fila

    with caplog.at_level(logging.DEBUG, logger="homemind.features.gestos.ponte"):
        fila = asyncio.run(cenario())
    assert [fila.get_nowait(), fila.get_nowait()] == [evento_n(0), evento_n(1)]
    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(avisos) == 2
    assert all("fila cheia" in r.getMessage() for r in avisos)
    assert "2026" not in caplog.text


def test_publicar_com_loop_fechado_so_debug(caplog):
    loop = asyncio.new_event_loop()
    pub = PublicadorFila(loop, asyncio.Queue())
    loop.close()
    with caplog.at_level(logging.DEBUG, logger="homemind.features.gestos.ponte"):
        pub.publicar(evento_n(0))
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]


def test_publicador_lista_thread_safe():
    pub = PublicadorLista()
    por_thread, n_threads = 200, 8

    def escrever(k: int) -> None:
        for i in range(por_thread):
            pub.publicar(evento_n(k * por_thread + i))

    threads = [threading.Thread(target=escrever, args=(k,)) for k in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    eventos = pub.eventos
    assert isinstance(eventos, tuple)
    assert len(eventos) == por_thread * n_threads
    assert set(eventos) == {evento_n(i) for i in range(por_thread * n_threads)}
