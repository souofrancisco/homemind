"""Desenha as deteções sobre uma cópia do frame, para o MJPEG (#28).

Só caixas, classe, confiança e esqueleto. Sem texto identificativo nem `track_id` (o `track_id`
só escolhe a cor, para o mesmo alvo manter a cor entre frames).
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
# Cores por track (BGR), distintas e legíveis sobre vídeo.
CORES_TRACK = ((255, 160, 40), (60, 200, 60), (50, 120, 255), (210, 90, 220), (40, 210, 230))


def _ponto(kp: Keypoint) -> tuple[int, int]:
    return (round(kp.x), round(kp.y))


def _cor(track_id: int | None, base: tuple[int, int, int]) -> tuple[int, int, int]:
    return base if track_id is None else CORES_TRACK[track_id % len(CORES_TRACK)]


def _rotulo(saida: np.ndarray, texto: str, p: tuple[int, int], cor: tuple[int, int, int]) -> None:
    """Texto branco sobre fundo da cor do alvo (contraste); fica dentro da imagem."""
    (w, h), base = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    x = max(0, min(p[0], saida.shape[1] - w - 6))
    y = p[1] if p[1] - h - base - 4 >= 0 else p[1] + h + base + 4  # sem espaço acima: por baixo
    cv2.rectangle(saida, (x, y - h - base - 4), (x + w + 6, y), cor, -1)
    cv2.putText(
        saida,
        texto,
        (x + 3, y - base - 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )


def desenhar(imagem: np.ndarray, det: FrameDeteccoes, *, esqueleto: bool = True) -> np.ndarray:
    """Devolve uma cópia de `imagem` anotada; o original não é alterado."""
    saida = imagem.copy()
    for pessoa in det.pessoas:
        c = pessoa.caixa
        cor = _cor(pessoa.track_id, COR_PESSOA)
        p1 = (round(c.x1), round(c.y1))
        cv2.rectangle(saida, p1, (round(c.x2), round(c.y2)), cor, 2)
        _rotulo(saida, f"pessoa {pessoa.confianca:.2f}", p1, cor)
        if not esqueleto:
            continue
        for a, b in ESQUELETO:
            ka, kb = pessoa.keypoints[a], pessoa.keypoints[b]
            if ka.confianca > CONFIANCA_MIN_KP and kb.confianca > CONFIANCA_MIN_KP:
                cv2.line(saida, _ponto(ka), _ponto(kb), COR_OSSO, 2)
        for kp in pessoa.keypoints:
            if kp.confianca > CONFIANCA_MIN_KP:
                cv2.circle(saida, _ponto(kp), 3, COR_OSSO, -1)
    for obj in det.objetos:
        c = obj.caixa
        cor = _cor(obj.track_id, COR_OBJETO)
        p1 = (round(c.x1), round(c.y1))
        cv2.rectangle(saida, p1, (round(c.x2), round(c.y2)), cor, 2)
        _rotulo(saida, f"{obj.classe} {obj.confianca:.2f}", p1, cor)
    return saida
