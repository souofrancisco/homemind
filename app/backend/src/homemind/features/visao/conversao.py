"""Resultados do Ultralytics -> contratos (`ObjetoDetetado`, `PessoaDetetada`). Lógica pura.

Não importa `ultralytics` nem `torch`: aceita qualquer objeto com a mesma forma (tensores ou
arrays), o que permite testar sem modelos. Não guarda nem devolve imagens.
"""

from collections.abc import Mapping
from typing import Any

import numpy as np

from homemind.contracts.visao import (
    NUM_KEYPOINTS,
    Caixa,
    ClasseObjeto,
    Keypoint,
    ObjetoDetetado,
    PessoaDetetada,
)


def _np(x: Any) -> np.ndarray:
    """Tensor (torch, possivelmente em GPU/MPS) ou array -> numpy."""
    if hasattr(x, "cpu"):
        x = x.cpu()
    if hasattr(x, "numpy"):
        x = x.numpy()
    return np.asarray(x)


def _unit(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def _caixa(xyxy: Any) -> Caixa:
    x1, y1, x2, y2 = (float(v) for v in xyxy)
    return Caixa(x1=min(x1, x2), y1=min(y1, y2), x2=max(x1, x2), y2=max(y1, y2))


def _ids(boxes: Any, n: int) -> list[int | None]:
    ids = getattr(boxes, "id", None)
    if ids is None:
        return [None] * n
    return [int(i) for i in _np(ids).reshape(-1)]


def objetos_de_resultado(
    res: Any, mapa_coco: Mapping[int, ClasseObjeto]
) -> tuple[ObjetoDetetado, ...]:
    """Caixas do modelo de objetos; descarta categorias COCO fora de `mapa_coco`."""
    boxes = getattr(res, "boxes", None)
    if boxes is None:
        return ()
    xyxy = _np(boxes.xyxy).reshape(-1, 4)
    n = len(xyxy)
    if n == 0:
        return ()
    conf = _np(boxes.conf).reshape(-1)
    cls = _np(boxes.cls).reshape(-1)
    ids = _ids(boxes, n)
    objetos = []
    for i in range(n):
        classe = mapa_coco.get(int(cls[i]))
        if classe is None:
            continue
        objetos.append(
            ObjetoDetetado(
                classe=classe,
                confianca=_unit(conf[i]),
                caixa=_caixa(xyxy[i]),
                track_id=ids[i] if i < len(ids) else None,
            )
        )
    return tuple(objetos)


def pessoas_de_resultado(res: Any) -> tuple[PessoaDetetada, ...]:
    """Pessoas do modelo de pose; descarta as que não tenham exatamente 17 keypoints."""
    boxes = getattr(res, "boxes", None)
    kps = getattr(res, "keypoints", None)
    if boxes is None or kps is None:
        return ()
    xyxy = _np(boxes.xyxy).reshape(-1, 4)
    n = len(xyxy)
    if n == 0:
        return ()
    conf = _np(boxes.conf).reshape(-1)
    ids = _ids(boxes, n)
    xy = _np(kps.xy)
    if xy.ndim != 3 or xy.shape[0] != n or xy.shape[1:] != (NUM_KEYPOINTS, 2):
        return ()  # forma inesperada: não adivinhar (também descarta N != 17)
    kconf = getattr(kps, "conf", None)
    kconf = _np(kconf) if kconf is not None else np.zeros((n, NUM_KEYPOINTS))
    pessoas = []
    for i in range(n):
        pessoas.append(
            PessoaDetetada(
                confianca=_unit(conf[i]),
                caixa=_caixa(xyxy[i]),
                track_id=ids[i] if i < len(ids) else None,
                keypoints=tuple(
                    Keypoint(
                        x=float(xy[i, k, 0]), y=float(xy[i, k, 1]), confianca=_unit(kconf[i, k])
                    )
                    for k in range(NUM_KEYPOINTS)
                ),
            )
        )
    return tuple(pessoas)
