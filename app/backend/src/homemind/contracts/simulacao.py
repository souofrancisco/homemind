"""Dados SIMULADOS conformes ao contrato de visão, para testes e pipelines sem câmara.

Geometria sintética e determinística; não representa nenhuma pessoa real.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from homemind.contracts.visao import (
    KP,
    NUM_KEYPOINTS,
    Caixa,
    ClasseObjeto,
    FrameDeteccoes,
    Keypoint,
    ObjetoDetetado,
    PessoaDetetada,
)

_INICIO = datetime(2026, 1, 1, tzinfo=UTC)


def pessoa_simulada(
    *,
    x: float = 320.0,
    y_ombros: float = 200.0,
    largura_ombros: float = 100.0,
    pulso_dir_levantado: bool = False,
    confianca: float = 0.9,
    track_id: int | None = 1,
) -> PessoaDetetada:
    """Pessoa de frente, centrada em `x`. Com o pulso levantado, fica acima do cotovelo."""
    meio = largura_ombros / 2
    pontos = {
        KP.NARIZ: (x, y_ombros - 50),
        KP.OLHO_ESQ: (x + 10, y_ombros - 60),
        KP.OLHO_DIR: (x - 10, y_ombros - 60),
        KP.ORELHA_ESQ: (x + 20, y_ombros - 55),
        KP.ORELHA_DIR: (x - 20, y_ombros - 55),
        KP.OMBRO_ESQ: (x + meio, y_ombros),
        KP.OMBRO_DIR: (x - meio, y_ombros),
        KP.COTOVELO_ESQ: (x + meio + 10, y_ombros + 60),
        KP.COTOVELO_DIR: (x - meio - 10, y_ombros + 60),
        KP.PULSO_ESQ: (x + meio + 10, y_ombros + 120),
        KP.PULSO_DIR: (x - meio - 10, y_ombros + (10 if pulso_dir_levantado else 120)),
        KP.ANCA_ESQ: (x + meio * 0.6, y_ombros + 140),
        KP.ANCA_DIR: (x - meio * 0.6, y_ombros + 140),
        KP.JOELHO_ESQ: (x + meio * 0.6, y_ombros + 210),
        KP.JOELHO_DIR: (x - meio * 0.6, y_ombros + 210),
        KP.TORNOZELO_ESQ: (x + meio * 0.6, y_ombros + 270),
        KP.TORNOZELO_DIR: (x - meio * 0.6, y_ombros + 270),
    }
    keypoints = tuple(
        Keypoint(x=pontos[KP(i)][0], y=pontos[KP(i)][1], confianca=confianca)
        for i in range(NUM_KEYPOINTS)
    )
    return PessoaDetetada(
        confianca=confianca,
        caixa=Caixa(x1=x - meio - 30, y1=y_ombros - 80, x2=x + meio + 30, y2=y_ombros + 280),
        track_id=track_id,
        keypoints=keypoints,
    )


def objeto_simulado(
    classe: ClasseObjeto,
    centro: tuple[float, float],
    *,
    tamanho: float = 40.0,
    confianca: float = 0.8,
    track_id: int | None = 1,
) -> ObjetoDetetado:
    cx, cy = centro
    meio = tamanho / 2
    return ObjetoDetetado(
        classe=classe,
        confianca=confianca,
        caixa=Caixa(x1=cx - meio, y1=cy - meio, x2=cx + meio, y2=cy + meio),
        track_id=track_id,
    )


def sequencia_simulada(
    n: int,
    *,
    fps: float = 10.0,
    com_pessoa: bool = True,
    classe: ClasseObjeto | None = None,
    levantado: bool = False,
    largura: int = 640,
    altura: int = 480,
) -> Iterator[FrameDeteccoes]:
    """`n` frames a `fps`. Com `classe`, o objeto está no pulso direito se `levantado`,
    senão pousado longe da pessoa."""
    for i in range(n):
        pessoas = (pessoa_simulada(pulso_dir_levantado=levantado),) if com_pessoa else ()
        objetos: tuple[ObjetoDetetado, ...] = ()
        if classe is not None:
            if levantado and pessoas:
                pulso = pessoas[0].kp(KP.PULSO_DIR)
                centro = (pulso.x, pulso.y)
            else:
                centro = (largura - 60.0, altura - 60.0)
            objetos = (objeto_simulado(classe, centro),)
        yield FrameDeteccoes(
            indice=i,
            t=i / fps,
            hora=_INICIO + timedelta(seconds=i / fps),
            largura=largura,
            altura=altura,
            objetos=objetos,
            pessoas=pessoas,
        )
