from datetime import UTC, datetime

import numpy as np

from homemind.contracts.visao import (
    Caixa,
    FrameDeteccoes,
    Keypoint,
    ObjetoDetetado,
    PessoaDetetada,
)
from homemind.features.visao.anotar import desenhar


def _det(confianca_kp: float) -> FrameDeteccoes:
    kps = tuple(Keypoint(x=10 + 4 * i, y=10 + 4 * i, confianca=confianca_kp) for i in range(17))
    return FrameDeteccoes(
        indice=0,
        t=0.0,
        hora=datetime.now(UTC),
        largura=100,
        altura=100,
        objetos=(
            ObjetoDetetado(
                classe="caneca", confianca=0.9, caixa=Caixa(x1=60, y1=60, x2=90, y2=90), track_id=7
            ),
        ),
        pessoas=(
            PessoaDetetada(
                confianca=0.9, caixa=Caixa(x1=5, y1=5, x2=80, y2=80), track_id=3, keypoints=kps
            ),
        ),
    )


def test_desenha_sobre_copia_e_deixa_original_intacto():
    original = np.zeros((100, 100, 3), dtype=np.uint8)
    saida = desenhar(original, _det(0.9))
    assert saida is not original
    assert not original.any()
    assert saida.any()


def test_keypoints_com_confianca_baixa_nao_sao_desenhados():
    original = np.zeros((100, 100, 3), dtype=np.uint8)
    com = desenhar(original, _det(0.9))
    sem = desenhar(original, _det(0.3))
    assert (com != sem).any()
    assert com[10, 10].any()  # keypoint 0 desenhado
    assert not sem[10, 10].any()
