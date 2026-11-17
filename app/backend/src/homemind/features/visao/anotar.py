"""Desenha as deteções sobre uma cópia do frame, para o MJPEG (#28).

Só caixas, classe, confiança e esqueleto. Sem texto identificativo nem `track_id`.
"""

import cv2
import numpy as np

from homemind.contracts.visao import FrameDeteccoes, Keypoint

CONFIANCA_MIN_KP = 0.5

# Ligações do esqueleto COCO (pares de índices de keypoints).
ESQUELETO: tuple[tuple[int, int], ...] = (
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),
)

COR_OBJETO = (0, 200, 0)  # BGR
COR_PESSOA = (200, 120, 0)
COR_OSSO = (0, 220, 255)


def _ponto(kp: Keypoint) -> tuple[int, int]:
    return (round(kp.x), round(kp.y))


def desenhar(imagem: np.ndarray, det: FrameDeteccoes) -> np.ndarray:
    """Devolve uma cópia de `imagem` anotada; o original não é alterado."""
    saida = imagem.copy()
    for pessoa in det.pessoas:
        c = pessoa.caixa
        cv2.rectangle(saida, (round(c.x1), round(c.y1)), (round(c.x2), round(c.y2)), COR_PESSOA, 1)
        for a, b in ESQUELETO:
            ka, kb = pessoa.keypoints[a], pessoa.keypoints[b]
            if ka.confianca > CONFIANCA_MIN_KP and kb.confianca > CONFIANCA_MIN_KP:
                cv2.line(saida, _ponto(ka), _ponto(kb), COR_OSSO, 2)
        for kp in pessoa.keypoints:
            if kp.confianca > CONFIANCA_MIN_KP:
                cv2.circle(saida, _ponto(kp), 3, COR_OSSO, -1)
    for obj in det.objetos:
        c = obj.caixa
        p1 = (round(c.x1), round(c.y1))
        cv2.rectangle(saida, p1, (round(c.x2), round(c.y2)), COR_OBJETO, 2)
        rotulo = f"{obj.classe} {obj.confianca:.2f}"
        cv2.putText(
            saida,
            rotulo,
            (p1[0], max(12, p1[1] - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            COR_OBJETO,
            1,
            cv2.LINE_AA,
        )
    return saida
