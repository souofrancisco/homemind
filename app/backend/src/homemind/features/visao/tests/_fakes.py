"""Fakes de resultados Ultralytics (arrays numpy) e de modelos; sem torch nem pesos."""

from types import SimpleNamespace

import numpy as np


def boxes(xyxy, conf, cls, ids=None):
    return SimpleNamespace(
        xyxy=np.array(xyxy, dtype=float).reshape(-1, 4),
        conf=np.array(conf, dtype=float),
        cls=np.array(cls, dtype=float),
        id=None if ids is None else np.array(ids, dtype=float),
    )


def resultado_objetos(xyxy, conf, cls, ids=None):
    return SimpleNamespace(boxes=boxes(xyxy, conf, cls, ids), keypoints=None)


def resultado_pose(xyxy, conf, kp_xy, kp_conf=None, ids=None):
    kps = SimpleNamespace(xy=np.array(kp_xy, dtype=float), conf=kp_conf)
    return SimpleNamespace(boxes=boxes(xyxy, conf, [0] * len(conf), ids), keypoints=kps)


class ModeloFalso:
    def __init__(self, resultado):
        self.resultado = resultado
        self.chamadas: list[dict] = []

    def track(self, imagem, **kw):
        self.chamadas.append({"imagem": imagem, **kw})
        return [self.resultado]
