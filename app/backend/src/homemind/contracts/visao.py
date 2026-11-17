"""Contrato de detecção por frame: o que a visão (Pessoa 1) entrega aos gestos/presença (Pessoa 2).

Só dados. Nenhuma regra de gesto ou presença vive aqui.

Convenções:
- Coordenadas em píxeis do frame original, origem no canto superior esquerdo; **y cresce para
  baixo** (pulso acima do cotovelo significa `pulso.y < cotovelo.y`).
- Esquerda/direita são as da pessoa (convenção COCO), não as da imagem.
- `track_id` é o ID efémero do ByteTrack: muda entre execuções, não identifica ninguém e nunca
  é persistido.
"""

from datetime import datetime
from enum import IntEnum
from typing import Literal

from pydantic import Field, model_validator

from homemind.contracts.base import Contrato as _Contrato

ClasseObjeto = Literal["caneca", "livro", "comando"]

# Categorias COCO do yolo11s.pt -> classe ObjectOS.
COCO_PARA_CLASSE: dict[int, ClasseObjeto] = {41: "caneca", 73: "livro", 65: "comando"}

NUM_KEYPOINTS = 17


class KP(IntEnum):
    """Índices dos 17 keypoints COCO, na ordem do yolo11s-pose.pt."""

    NARIZ = 0
    OLHO_ESQ = 1
    OLHO_DIR = 2
    ORELHA_ESQ = 3
    ORELHA_DIR = 4
    OMBRO_ESQ = 5
    OMBRO_DIR = 6
    COTOVELO_ESQ = 7
    COTOVELO_DIR = 8
    PULSO_ESQ = 9
    PULSO_DIR = 10
    ANCA_ESQ = 11
    ANCA_DIR = 12
    JOELHO_ESQ = 13
    JOELHO_DIR = 14
    TORNOZELO_ESQ = 15
    TORNOZELO_DIR = 16


class Caixa(_Contrato):
    """Caixa xyxy em píxeis."""

    x1: float
    y1: float
    x2: float
    y2: float

    @model_validator(mode="after")
    def _ordenada(self) -> "Caixa":
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError("caixa xyxy invertida")
        return self

    @property
    def centro(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)


class Keypoint(_Contrato):
    """Ponto da pose. Não detetado: `confianca=0` (x/y sem significado)."""

    x: float
    y: float
    confianca: float = Field(ge=0, le=1)


class ObjetoDetetado(_Contrato):
    classe: ClasseObjeto
    confianca: float = Field(ge=0, le=1)
    caixa: Caixa
    track_id: int | None = None  # None enquanto o tracker não confirmar a track


class PessoaDetetada(_Contrato):
    confianca: float = Field(ge=0, le=1)
    caixa: Caixa
    track_id: int | None = None
    keypoints: tuple[Keypoint, ...] = Field(min_length=NUM_KEYPOINTS, max_length=NUM_KEYPOINTS)

    def kp(self, indice: KP) -> Keypoint:
        return self.keypoints[indice]


class FrameDeteccoes(_Contrato):
    """Resultado de um frame processado. Não contém imagem."""

    indice: int = Field(ge=0)  # contador crescente de frames processados
    t: float  # segundos de relógio monotónico: usar para janelas, cooldowns e ausências
    hora: datetime  # relógio de parede (UTC), só para registo
    largura: int = Field(gt=0)
    altura: int = Field(gt=0)
    objetos: tuple[ObjetoDetetado, ...] = ()
    pessoas: tuple[PessoaDetetada, ...] = ()
