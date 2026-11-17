"""Interface da fonte de vídeo: câmara RTSP e clip de reserva implementam o mesmo contrato.

Os frames vivem só em memória; nenhuma implementação os grava, envia ou regista.
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class FrameVideo:
    imagem: Any  # numpy.ndarray BGR (altura, largura, 3), como devolvido pelo OpenCV
    indice: int  # contador crescente da fonte; igual ao anterior = ainda não há frame novo
    t: float  # time.monotonic() no momento da captura


class FonteVideo(Protocol):
    """Só o frame mais recente é mantido; não há fila de imagens."""

    def iniciar(self) -> None: ...

    def parar(self) -> None: ...

    def ultimo_frame(self) -> FrameVideo | None:
        """Frame mais recente, ou None se ainda não chegou nenhum. Nunca bloqueia."""
        ...

    @property
    def camara_ok(self) -> bool:
        """False quando não chega frame há mais tempo do que o limite configurado."""
        ...
