import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from homemind.features.video.fonte import FonteClip, FonteRtsp, criar_fonte


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

    def get(self, propriedade: int) -> float:
        return 0.0

    def release(self) -> None:
        self.libertada = True


class CapturaGuiao:
    """Dá `frames` frames seguidos e depois falha sempre (rede em baixo ou fim de ficheiro)."""

    def __init__(self, frames: int = 0, fps: float = 10.0) -> None:
        self.restantes = frames
        self.fps = fps
        self.libertada = False

    def read(self):
        if self.restantes <= 0:
            return False, None
        self.restantes -= 1
        return True, np.zeros((4, 6, 3), dtype=np.uint8)

    def get(self, propriedade: int) -> float:
        return self.fps if propriedade == cv2.CAP_PROP_FPS else 0.0

    def release(self) -> None:
        self.libertada = True


class Relogio:
    def __init__(self) -> None:
        self.agora = 100.0

    def __call__(self) -> float:
        return self.agora


class Simulacao:
    """Relógio simulado: cada espera avança o tempo em vez de dormir, e fica registada."""

    def __init__(self, guiao: list[CapturaGuiao]) -> None:
        self.relogio = Relogio()
        self.guiao = guiao
        self.abertas: list[CapturaGuiao] = []
        self.esperas: list[float] = []

    def abrir(self, _: str) -> CapturaGuiao:
        captura = self.guiao.pop(0) if self.guiao else CapturaGuiao()
        self.abertas.append(captura)
        return captura

    def esperar(self, segundos: float) -> None:
        self.esperas.append(segundos)
        self.relogio.agora += segundos
        time.sleep(0)  # deixa a thread de teste correr

    def backoffs(self) -> list[float]:
        return [e for e in self.esperas if e >= 1]

    def argumentos(self) -> dict:
        return {"abrir": self.abrir, "relogio": self.relogio, "esperar": self.esperar}


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


def test_reabre_com_backoff_1_2_4_8_10_10():
    sim = Simulacao([])
    fonte = FonteRtsp("rtsp://falso", **sim.argumentos())
    fonte.iniciar()
    try:
        esperar(lambda: len(sim.backoffs()) >= 7)
    finally:
        fonte.parar()
    assert sim.backoffs()[:7] == [1, 2, 4, 8, 10, 10, 10]
    assert fonte.reconexoes >= 7
    assert all(c.libertada for c in sim.abertas)  # cada ligação falhada é libertada


def test_so_reabre_depois_de_3s_sem_frames():
    sim = Simulacao([])
    fonte = FonteRtsp("rtsp://falso", **sim.argumentos())
    fonte.iniciar()
    try:
        esperar(lambda: len(sim.backoffs()) >= 1)
    finally:
        fonte.parar()
    antes_do_primeiro_backoff = sim.esperas[: sim.esperas.index(1)]
    assert sum(antes_do_primeiro_backoff) == pytest.approx(3.0, abs=0.06)


def test_backoff_volta_a_1s_depois_de_um_frame_bom():
    sim = Simulacao([CapturaGuiao(), CapturaGuiao(), CapturaGuiao(frames=1)])
    fonte = FonteRtsp("rtsp://falso", **sim.argumentos())
    fonte.iniciar()
    try:
        esperar(lambda: len(sim.backoffs()) >= 4)
    finally:
        fonte.parar()
    assert sim.backoffs()[:4] == [1, 2, 1, 2]
    assert fonte.ultimo_frame().indice == 1


def test_parar_interrompe_o_backoff_sem_esperar():
    relogio = Relogio()

    def relogio_que_avanca() -> float:
        relogio.agora += 1.0
        return relogio.agora

    fonte = FonteRtsp(
        "rtsp://falso",
        abrir=lambda _: CapturaGuiao(),
        relogio=relogio_que_avanca,
        reconexao_s=(30,),
        pausa_falha_s=0,
    )
    fonte.iniciar()
    esperar(lambda: fonte.reconexoes >= 1)  # já está na espera real de 30 s
    inicio = time.monotonic()
    fonte.parar()
    assert time.monotonic() - inicio < 1.0
    assert all(t.name != "fonte-video" for t in threading.enumerate())


def test_clip_recomeca_no_fim_com_indice_sempre_a_crescer():
    sim = Simulacao([CapturaGuiao(frames=3), CapturaGuiao(frames=3), CapturaGuiao(frames=3)])
    fonte = FonteClip("clip.mp4", **sim.argumentos())
    fonte.iniciar()
    try:
        esperar(lambda: (f := fonte.ultimo_frame()) is not None and f.indice >= 7)
    finally:
        fonte.parar()
    assert fonte.ao_vivo is False
    primeiras = sim.esperas[:6]
    assert primeiras == pytest.approx([0.1] * 6)  # ritmo do ficheiro (10 fps), sem backoff


def test_clip_em_falta_nao_rebenta_e_tenta_de_novo():
    sim = Simulacao([])
    fonte = FonteClip("nao-existe.mp4", **sim.argumentos())
    fonte.iniciar()
    try:
        esperar(lambda: len(sim.backoffs()) >= 2)
        assert fonte.camara_ok is False
        assert fonte.ultimo_frame() is None
    finally:
        fonte.parar()
    assert sim.backoffs()[:2] == [1, 2]


def test_abrir_que_lanca_erro_e_tratado_como_falha():
    sim = Simulacao([])

    def abrir(_: str):
        sim.abertas.append(None)
        raise OSError("rtsp://utilizador:segredo@camara")

    fonte = FonteRtsp("rtsp://falso", abrir=abrir, relogio=sim.relogio, esperar=sim.esperar)
    fonte.iniciar()
    try:
        esperar(lambda: len(sim.backoffs()) >= 2)
    finally:
        fonte.parar()
    assert len(sim.abertas) >= 2


def test_criar_fonte_escolhe_camara_ou_clip():
    def settings(fonte: str):
        return SimpleNamespace(
            video_source=fonte,
            video_sem_frame_s=3.0,
            video_reconexao_s=(1, 2, 4, 8, 10),
            video_timeout_abrir_ms=5000,
        )

    assert isinstance(criar_fonte(settings("rtsp://camara/stream")), FonteRtsp)
    clip = criar_fonte(settings("clips/demo.mp4"))
    assert isinstance(clip, FonteClip) and clip.ao_vivo is False
