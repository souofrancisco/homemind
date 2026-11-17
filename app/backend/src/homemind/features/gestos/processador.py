"""Processador único de gestos + presença (#8). Implementa `ProcessadorEventos`.

É o objeto que P1 chama na thread de visão (e o afinador offline): presença primeiro, depois gesto.
Frames com `indice` repetido ou anterior ao último processado são ignorados.
"""

from typing import TYPE_CHECKING

from homemind.contracts.eventos import Evento
from homemind.contracts.visao import FrameDeteccoes
from homemind.features.gestos.gesto import DetetorGesto
from homemind.features.gestos.parametros import ParametrosGesto, ParametrosPresenca
from homemind.features.gestos.presenca import DetetorPresenca

if TYPE_CHECKING:
    from homemind.core.config import Settings


class ProcessadorObjectOS:
    def __init__(
        self,
        params_gesto: ParametrosGesto | None = None,
        params_presenca: ParametrosPresenca | None = None,
    ) -> None:
        self._presenca = DetetorPresenca(params_presenca)
        self._gesto = DetetorGesto(params_gesto)
        self._ultimo_indice: int | None = None

    @classmethod
    def de_settings(cls, settings: "Settings") -> "ProcessadorObjectOS":
        return cls(ParametrosGesto.de_settings(settings), ParametrosPresenca.de_settings(settings))

    @property
    def ha_alguem(self) -> bool:
        return self._presenca.ha_alguem

    def processar(self, frame: FrameDeteccoes) -> tuple[Evento, ...]:
        if self._ultimo_indice is not None and frame.indice <= self._ultimo_indice:
            return ()
        self._ultimo_indice = frame.indice
        return (*self._presenca.processar(frame), *self._gesto.processar(frame))
