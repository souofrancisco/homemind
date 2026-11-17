"""`DetetorYolo`: YOLO11 (objetos) + YOLO11-pose + ByteTrack, local. Implementa `Detetor` (#4).

Uso com a thread de visão: `VISAO_DETETOR=homemind.features.visao.detetor:DetetorYolo`.
Os modelos só são carregados em `preparar()` (ou no 1.º `detetar`), nunca ao importar nem ao
construir. Nunca descarrega pesos (ver `pesos.py`). Não guarda nem devolve a imagem.
"""

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from homemind.contracts.video import FrameVideo
from homemind.contracts.visao import COCO_PARA_CLASSE, ClasseObjeto, FrameDeteccoes
from homemind.core.config import Settings, get_settings
from homemind.features.visao.conversao import objetos_de_resultado, pessoas_de_resultado
from homemind.features.visao.dispositivo import escolher_device

COCO_PESSOA = 0


class DetetorYolo:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        modelo_objetos: Any = None,
        modelo_pose: Any = None,
    ) -> None:
        self._cfg = settings or get_settings()
        self._objetos = modelo_objetos
        self._pose = modelo_pose
        self._device = "cpu"
        self._pronto = modelo_objetos is not None and modelo_pose is not None
        # COCO -> classe ObjectOS; o livro pode apontar a outra categoria (VISAO_LIVRO_COCO).
        self._mapa: dict[int, ClasseObjeto] = {
            cod: classe for cod, classe in COCO_PARA_CLASSE.items() if classe != "livro"
        }
        self._mapa[self._cfg.visao_livro_coco] = "livro"
        if self._pronto:
            self._device = escolher_device(self._cfg.visao_device)

    @property
    def device(self) -> str:
        return self._device

    def _caminhos(self) -> tuple[Path, Path]:
        cfg = self._cfg
        pasta = Path(cfg.visao_pasta_modelos)
        v = cfg.visao_variante
        obj = pasta / (cfg.visao_modelo_objetos or f"yolo11{v}.pt")
        pose = pasta / (cfg.visao_modelo_pose or f"yolo11{v}-pose.pt")
        return obj, pose

    def preparar(self) -> None:
        """Carrega modelos e aquece com um frame preto. Idempotente; sem rede."""
        if self._pronto:
            return
        obj, pose = self._caminhos()
        em_falta = [p for p in (obj, pose) if not p.is_file()]
        if em_falta:
            raise FileNotFoundError(
                "pesos YOLO em falta (" + ", ".join(p.name for p in em_falta) + ") em "
                f"{obj.parent}; correr: python -m homemind.features.visao.pesos"
            )
        import ultralytics  # extra opcional `visao`; import preguiçoso (torch é pesado)
        from ultralytics import YOLO

        ultralytics.settings.update({"sync": False})  # sem telemetria/analytics
        self._device = escolher_device(self._cfg.visao_device)
        self._objetos = YOLO(str(obj))
        self._pose = YOLO(str(pose))
        self._pronto = True
        preto = np.zeros((self._cfg.visao_imgsz, self._cfg.visao_imgsz, 3), dtype=np.uint8)
        self._inferir(preto)

    def _inferir(self, imagem: Any) -> tuple[Any, Any]:
        cfg = self._cfg
        comum = {
            "persist": True,
            "tracker": cfg.visao_tracker,
            "imgsz": cfg.visao_imgsz,
            "device": self._device,
            "verbose": False,
        }
        res_obj = self._objetos.track(
            imagem, conf=cfg.visao_conf_objetos, classes=list(self._mapa), **comum
        )[0]
        res_pose = self._pose.track(
            imagem, conf=cfg.visao_conf_pessoa, classes=[COCO_PESSOA], **comum
        )[0]
        return res_obj, res_pose

    def detetar(self, frame: FrameVideo) -> FrameDeteccoes:
        if not self._pronto:
            self.preparar()
        res_obj, res_pose = self._inferir(frame.imagem)
        altura, largura = frame.imagem.shape[:2]
        # `hora` = instante de captura (UTC): agora menos a idade do frame.
        hora = datetime.now(UTC) - timedelta(seconds=max(0.0, time.monotonic() - frame.t))
        return FrameDeteccoes(
            indice=frame.indice,
            t=frame.t,
            hora=hora,
            largura=int(largura),
            altura=int(altura),
            objetos=objetos_de_resultado(res_obj, self._mapa),
            pessoas=pessoas_de_resultado(res_pose),
        )
