import threading
import time

import numpy as np

from homemind.features.video.fonte import FonteRtsp


class CapturaFalsa:
    """Entrega um frame por cada `libertar()`; sem frame, `read()` falha como uma câmara muda."""

    def __init__(self) -> None:
        self._pendentes = threading.Semaphore(0)
        self.n = 0
        self.libertada = False

    def libertar(self, quantos: int = 1) -> None:
        for _ in range(quantos):
            self._pendentes.release()

    def read(self):
        if not self._pendentes.acquire(timeout=0.01):
            return False, None
        self.n += 1
        return True, np.full((4, 6, 3), self.n, dtype=np.uint8)

    def release(self) -> None:
        self.libertada = True


class Relogio:
    def __init__(self) -> None:
        self.agora = 100.0

    def __call__(self) -> float:
        return self.agora


def esperar(condicao, limite_s: float = 2.0) -> None:
    fim = time.monotonic() + limite_s
    while not condicao():
        assert time.monotonic() < fim, "condição não atingida a tempo"
        time.sleep(0.005)


def criar(relogio=None):
    captura = CapturaFalsa()
    relogio = relogio or Relogio()
    fonte = FonteRtsp(
        "rtsp://falso", sem_frame_s=3.0, abrir=lambda _: captura, relogio=relogio, pausa_falha_s=0
    )
    return fonte, captura, relogio


def test_sem_frames_devolve_none_e_camara_nao_ok():
    fonte, _, _ = criar()
    fonte.iniciar()
    try:
        assert fonte.ultimo_frame() is None
        assert fonte.camara_ok is False
    finally:
        fonte.parar()


def test_so_o_frame_mais_recente_fica_guardado():
    fonte, captura, _ = criar()
    fonte.iniciar()
    try:
        captura.libertar(5)
        esperar(lambda: (f := fonte.ultimo_frame()) is not None and f.indice == 5)
        frame = fonte.ultimo_frame()
        assert frame.imagem[0, 0, 0] == 5  # o conteúdo é o do último frame lido
        assert frame.imagem.shape == (4, 6, 3)
    finally:
        fonte.parar()


def test_camara_ok_cai_apos_3s_sem_frames_e_recupera():
    fonte, captura, relogio = criar()
    fonte.iniciar()
    try:
        captura.libertar()
        esperar(lambda: fonte.ultimo_frame() is not None)
        assert fonte.camara_ok is True
        relogio.agora += 2.9
        assert fonte.camara_ok is True
        relogio.agora += 0.2
        assert fonte.camara_ok is False
        captura.libertar()
        esperar(lambda: fonte.ultimo_frame().indice == 2)
        assert fonte.camara_ok is True
    finally:
        fonte.parar()


def test_parar_termina_a_thread_e_liberta_a_captura():
    fonte, captura, _ = criar()
    fonte.iniciar()
    fonte.iniciar()  # idempotente: não cria segunda thread
    assert sum(t.name == "fonte-video" for t in threading.enumerate()) == 1
    fonte.parar()
    assert captura.libertada is True
    assert all(t.name != "fonte-video" for t in threading.enumerate())
