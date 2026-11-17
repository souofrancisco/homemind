"""Thread de visão + motor real (processador e ponte da P2 reais; fonte e detetor SIMULADOS)."""

import asyncio
import threading
import time

import pytest

from homemind.connectors.fake_home import FakeHome
from homemind.contracts.video import FrameVideo
from homemind.features.engine.engine import Engine, Estado, Tempos
from homemind.features.engine.eventlog import EventLog
from homemind.features.engine.rules import RulesStore
from homemind.features.gestos.ponte import PublicadorFila
from homemind.features.gestos.processador import ProcessadorObjectOS
from homemind.features.gestos.tests._fakes import DetetorDeClip
from homemind.features.visao.thread import DetetorIndisponivel, ThreadVisao, carregar_detetor


class FonteSimulada:
    """`total` frames a 10 fps (sem imagem); depois repete o último (como uma câmara parada)."""

    def __init__(self, total: int) -> None:
        self.total = total
        self._i = 0
        self._lock = threading.Lock()

    def iniciar(self) -> None: ...

    def parar(self) -> None: ...

    @property
    def camara_ok(self) -> bool:
        return True

    def ultimo_frame(self) -> FrameVideo | None:
        with self._lock:
            i = min(self._i, self.total - 1)
            self._i += 1
        return FrameVideo(imagem=None, indice=i, t=i / 10)


def test_gesto_simulado_chega_ao_motor_e_ativa_modo(tmp_path):
    async def cenario():
        regras = RulesStore(tmp_path / "rules.json")
        regras.carregar()
        engine = Engine(FakeHome(), regras, EventLog(tmp_path / "e.jsonl"), Tempos())
        await engine.iniciar()
        consumidor = asyncio.create_task(engine.consumir())
        thread = ThreadVisao(
            FonteSimulada(60),
            DetetorDeClip(),
            ProcessadorObjectOS(),
            PublicadorFila(engine.loop, engine.fila),
        )
        thread.iniciar()
        for _ in range(100):  # até 5 s
            await asyncio.sleep(0.05)
            if engine.modo:
                break
        thread.parar()
        consumidor.cancel()
        assert engine.presenca is True
        assert engine.estado == Estado.ATIVO and engine.modo.id == "pausa"  # caneca
        assert thread.frames == 60  # cada frame uma só vez

    asyncio.run(cenario())


def test_frame_com_erro_nao_para_a_visao():
    class DetetorQueFalha(DetetorDeClip):
        def detetar(self, frame):
            if frame.indice == 3:
                raise RuntimeError("frame corrompido")
            return super().detetar(frame)

    publicados = []

    class Lista:
        def publicar(self, evento):
            publicados.append(evento)

    thread = ThreadVisao(FonteSimulada(30), DetetorQueFalha(), ProcessadorObjectOS(), Lista())
    thread.iniciar()
    for _ in range(100):
        if thread.frames >= 29:
            break
        threading.Event().wait(0.02)
    thread.parar()
    assert thread.frames == 29 and publicados  # 30 frames, 1 falhou; presença publicada


@pytest.mark.parametrize(
    "especificacao",
    ["sem_dois_pontos", "modulo.inexistente:Classe", "homemind.features.visao.thread:Nada"],
)
def test_detetor_invalido(especificacao):
    with pytest.raises(DetetorIndisponivel):
        carregar_detetor(especificacao)


def test_detetor_por_especificacao():
    d = carregar_detetor("homemind.features.gestos.tests._fakes:DetetorDeClip")
    assert callable(d.detetar)


def test_ultima_deteccao_expira():
    class DetetorFixo(DetetorDeClip):
        pass

    thread = ThreadVisao(
        FonteSimulada(5),
        DetetorFixo(),
        ProcessadorObjectOS(),
        type("L", (), {"publicar": lambda s, e: None})(),
    )
    assert thread.ultima_deteccao() is None
    thread.iniciar()
    for _ in range(100):
        if thread.frames >= 5:
            break
        time.sleep(0.02)
    thread.parar()
    assert thread.ultima_deteccao(idade_max_s=5.0) is not None
    time.sleep(0.05)
    assert thread.ultima_deteccao(idade_max_s=0.01) is None


def test_detetor_que_nao_carrega_desliga_so_a_visao():
    class SemPesos:
        def preparar(self):
            raise FileNotFoundError("pesos YOLO em falta")

        def detetar(self, frame):
            raise AssertionError("não devia ser chamado")

    t = ThreadVisao(None, SemPesos(), None, None)  # type: ignore[arg-type]
    t._ciclo()  # regressa sem usar a fonte nem rebentar
    assert t.frames == 0
