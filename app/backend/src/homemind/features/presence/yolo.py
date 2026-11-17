"""`DetetorYoloPessoas`: YOLO11 só com a classe «pessoa» + ByteTrack, local (PRES-02).

Extra opcional `visao` (torch/ultralytics fora do CI e do Docker). Os pesos são os mesmos do resto
da visão (`yolo11{s,n}.pt`, ver `features/visao/pesos.py`); nunca descarrega nada. Só devolve caixas
e confianças: não guarda a imagem, não usa pose nem caras.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from homemind.core.config import Settings, get_settings
from homemind.features.presence.door import PessoaCaixa
from homemind.features.visao.dispositivo import escolher_device

COCO_PESSOA = 0
RAIZ_BACKEND = Path(__file__).resolve().parents[4]  # app/backend


def pasta_modelos(cfg: Settings) -> Path:
    """`VISAO_PASTA_MODELOS` relativa conta a partir de app/backend, não do diretório atual."""
    pasta = Path(cfg.visao_pasta_modelos).expanduser()
    return pasta if pasta.is_absolute() else RAIZ_BACKEND / pasta


def pessoas_de_resultado(res: Any) -> tuple[PessoaCaixa, ...]:
    """Resultado do Ultralytics (ou fake com `.boxes`) -> caixas; só a classe pessoa."""
    boxes = getattr(res, "boxes", None)
    if boxes is None:
        return ()

    def arr(x: Any) -> np.ndarray:
        if hasattr(x, "cpu"):
            x = x.cpu()
        if hasattr(x, "numpy"):
            x = x.numpy()
        return np.asarray(x, dtype=float)

    xyxy = arr(boxes.xyxy).reshape(-1, 4)
    if len(xyxy) == 0:
        return ()
    conf = arr(boxes.conf).reshape(-1)
    cls = arr(boxes.cls).reshape(-1)
    ids = getattr(boxes, "id", None)
    ids_l: list[int | None] = (
        [None] * len(xyxy) if ids is None else [int(i) for i in arr(ids).reshape(-1)]
    )
    saida = []
    for (x1, y1, x2, y2), c, k, i in zip(xyxy, conf, cls, ids_l, strict=True):
        if int(k) != COCO_PESSOA:
            continue
        saida.append(
            PessoaCaixa(
                track_id=i,
                x1=min(x1, x2),
                y1=min(y1, y2),
                x2=max(x1, x2),
                y2=max(y1, y2),
                confianca=min(1.0, max(0.0, float(c))),
            )
        )
    return tuple(saida)


class DetetorYoloPessoas:
    def __init__(self, settings: Settings | None = None, *, modelo: Any = None) -> None:
        self._cfg = settings or get_settings()
        self._modelo = modelo
        self._device = escolher_device(self._cfg.visao_device) if modelo is not None else "cpu"

    def preparar(self) -> None:
        """Carrega o modelo e aquece com um frame preto. Idempotente; sem rede."""
        if self._modelo is not None:
            return
        cfg = self._cfg
        peso = pasta_modelos(cfg) / (cfg.visao_modelo_objetos or f"yolo11{cfg.visao_variante}.pt")
        if not peso.is_file():
            raise FileNotFoundError(
                f"pesos YOLO em falta ({peso.name});"
                " correr python -m homemind.features.visao.pesos"
            )
        import ultralytics  # extra opcional `visao`
        from ultralytics import YOLO

        ultralytics.settings.update({"sync": False})  # sem telemetria
        self._device = escolher_device(cfg.visao_device)
        self._modelo = YOLO(str(peso))
        self.detetar(np.zeros((cfg.visao_imgsz, cfg.visao_imgsz, 3), dtype=np.uint8))

    def detetar(self, imagem: Any) -> Sequence[PessoaCaixa]:
        if self._modelo is None:
            self.preparar()
        cfg = self._cfg
        res = self._modelo.track(
            imagem,
            persist=True,
            tracker=cfg.visao_tracker,
            classes=[COCO_PESSOA],
            conf=cfg.visao_conf_pessoa,
            imgsz=cfg.visao_imgsz,
            device=self._device,
            verbose=False,
        )[0]
        return pessoas_de_resultado(res)
