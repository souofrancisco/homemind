"""Helpers de teste (dados SIMULADOS) para gestos/presença. Sem hardware nem rede."""

import threading
import time
from collections.abc import Iterable, Iterator
from typing import Literal

from homemind.contracts.eventos import ProcessadorEventos, PublicadorEventos
from homemind.contracts.simulacao import objeto_simulado, pessoa_simulada, sequencia_simulada
from homemind.contracts.video import FrameVideo
from homemind.contracts.visao import KP, ClasseObjeto, FrameDeteccoes, Keypoint, PessoaDetetada

Lado = Literal["esq", "dir"]
Estado = Literal["levantado", "repouso", "beber", "longe"]


def pessoa_levantada(lado: Lado = "dir", *, confianca_pulso: float | None = None) -> PessoaDetetada:
    """Pessoa com o pulso do `lado` acima do cotovelo (o simulador só levanta o direito)."""
    pessoa = pessoa_simulada(pulso_dir_levantado=lado == "dir")
    if lado == "dir" and confianca_pulso is None:
        return pessoa
    i_pulso, i_ombro = (
        (KP.PULSO_ESQ, KP.OMBRO_ESQ) if lado == "esq" else (KP.PULSO_DIR, KP.OMBRO_DIR)
    )
    pontos = list(pessoa.keypoints)
    if lado == "esq":
        y = pessoa.kp(i_ombro).y + 10
        pontos[i_pulso] = pontos[i_pulso].model_copy(update={"y": y})
    if confianca_pulso is not None:
        pontos[i_pulso] = pontos[i_pulso].model_copy(update={"confianca": confianca_pulso})
    return pessoa.model_copy(update={"keypoints": tuple[Keypoint, ...](pontos)})


def segmento(
    duracao_s: float,
    estado: Estado,
    classe: ClasseObjeto = "caneca",
    *,
    fps: float = 10.0,
    t0: float = 0.0,
    indice0: int = 0,
    lado: Lado = "dir",
    confianca_pulso: float | None = None,
) -> list[FrameDeteccoes]:
    """Frames de `duracao_s` a `fps` no `estado`:
    levantado = objeto no pulso levantado; repouso = braços em baixo, objeto pousado longe;
    beber = objeto no pulso mas abaixo do cotovelo; longe = pulso levantado, objeto longe."""
    n = round(duracao_s * fps)
    base = sequencia_simulada(
        n,
        fps=fps,
        classe=classe,
        levantado=estado in ("levantado", "longe"),
        objeto_no_pulso=estado in ("levantado", "beber"),
        t0=t0,
        indice0=indice0,
    )
    if lado == "dir" and confianca_pulso is None:
        return list(base)
    saida = []
    for f in base:
        pessoa = (
            pessoa_levantada(lado, confianca_pulso=confianca_pulso)
            if estado
            in (
                "levantado",
                "longe",
            )
            else pessoa_simulada()
        )
        objetos = f.objetos
        if estado in ("levantado", "beber") and lado == "esq":
            pulso = pessoa.kp(KP.PULSO_ESQ)
            objetos = (objeto_simulado(classe, (pulso.x, pulso.y)),)
        saida.append(f.model_copy(update={"pessoas": (pessoa,), "objetos": objetos}))
    return saida


def encadear(*partes: Iterable[FrameDeteccoes]) -> Iterator[FrameDeteccoes]:
    for p in partes:
        yield from p


def segmento_presenca(
    duracao_s: float,
    com_pessoa: bool,
    *,
    fps: float = 10.0,
    t0: float = 0.0,
    indice0: int = 0,
) -> list[FrameDeteccoes]:
    """Frames de `duracao_s` a `fps` só com (ou sem) pessoa; sem objetos."""
    n = round(duracao_s * fps)
    return list(sequencia_simulada(n, fps=fps, com_pessoa=com_pessoa, t0=t0, indice0=indice0))


def plano_presenca(
    passos: Iterable[tuple[float, bool | None]], *, fps: float = 10.0
) -> list[FrameDeteccoes]:
    """Encadeia (duração_s, pessoa) continuando t e índice; `None` = buraco sem frames."""
    frames: list[FrameDeteccoes] = []
    t, i = 0.0, 0
    for dur, com_pessoa in passos:
        if com_pessoa is None:
            t += dur
            continue
        seg = segmento_presenca(dur, com_pessoa, fps=fps, t0=t, indice0=i)
        frames += seg
        t += len(seg) / fps
        i += len(seg)
    return frames


# --- Mocks de P1 (thread de visão, #7). Substituir por Detetor/FonteVideo/thread reais. ---


class DetetorFalso:
    """Mock de `Detetor` (P1): devolve os `FrameDeteccoes` da sequência pelo `indice` do frame;
    `atraso_s` simula inferência lenta."""

    def __init__(self, frames: Iterable[FrameDeteccoes], atraso_s: float = 0.0) -> None:
        self._frames = list(frames)
        self.atraso_s = atraso_s

    def detetar(self, frame: FrameVideo) -> FrameDeteccoes:
        if self.atraso_s:
            time.sleep(self.atraso_s)
        return self._frames[frame.indice]


class FonteVideoFalsa:
    """Mock de `FonteVideo` (P1): cada `ultimo_frame()` devolve um frame novo (sem imagem)
    até `total`; depois `None` e `esgotada=True`."""

    def __init__(self, total: int, *, camara_ok: bool = True) -> None:
        self.total = total
        self._camara_ok = camara_ok
        self._proximo = 0

    def iniciar(self) -> None: ...

    def parar(self) -> None: ...

    @property
    def camara_ok(self) -> bool:
        return self._camara_ok

    @property
    def esgotada(self) -> bool:
        return self._proximo >= self.total

    def ultimo_frame(self) -> FrameVideo | None:
        if self.esgotada:
            return None
        i = self._proximo
        self._proximo += 1
        return FrameVideo(imagem=None, indice=i, t=float(i))


class ThreadVisaoFalsa:
    """Mock da thread de visão de P1: lê da fonte, `detetar` -> `processar` -> `publicar` até a
    fonte esgotar ou `parar` ser pedido. Exceções da thread ficam em `erro`."""

    def __init__(
        self,
        fonte: FonteVideoFalsa,
        detetor: DetetorFalso,
        processador: ProcessadorEventos,
        publicador: PublicadorEventos,
    ) -> None:
        self.parar = threading.Event()
        self.erro: BaseException | None = None
        self._args = (fonte, detetor, processador, publicador)
        self._thread = threading.Thread(target=self._correr, daemon=True, name="visao-falsa")

    def iniciar(self) -> None:
        self._thread.start()

    def esperar(self, timeout: float = 5.0) -> bool:
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _correr(self) -> None:
        fonte, detetor, processador, publicador = self._args
        try:
            while not self.parar.is_set() and not fonte.esgotada:
                fv = fonte.ultimo_frame()
                if fv is None:
                    continue
                for evento in processador.processar(detetor.detetar(fv)):
                    publicador.publicar(evento)
        except BaseException as e:  # noqa: BLE001
            self.erro = e
