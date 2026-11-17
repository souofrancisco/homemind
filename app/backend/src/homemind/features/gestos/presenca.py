"""Presença binária com debounce (#6). Lógica pura: sem I/O, sem relógio de parede.

Só se guardam contadores e tempos; nunca pessoas, caixas, keypoints ou imagens.
"""

from homemind.contracts.eventos import Presenca
from homemind.contracts.visao import FrameDeteccoes
from homemind.features.gestos.parametros import ParametrosPresenca

_EPS = 1e-9  # tolerância para comparações de tempo em vírgula flutuante


class DetetorPresenca:
    """Com estado, síncrono. Frames por ordem crescente de `t`. Emite só transições."""

    def __init__(self, params: ParametrosPresenca | None = None) -> None:
        self._p = params or ParametrosPresenca()
        self._ha_alguem = False  # contrato: presença inicial False
        self._positivos = 0
        self._t_primeiro_vazio: float | None = None
        self._t_anterior: float | None = None

    @property
    def ha_alguem(self) -> bool:
        return self._ha_alguem

    def processar(self, frame: FrameDeteccoes) -> tuple[Presenca, ...]:
        p, t = self._p, frame.t
        if self._t_anterior is not None and t - self._t_anterior > p.intervalo_max_s:
            # Frames que não existiram não confirmam ausência nem regresso.
            self._positivos = 0
            self._t_primeiro_vazio = t
        self._t_anterior = t

        if frame.pessoas:
            self._positivos += 1
            self._t_primeiro_vazio = None
            if not self._ha_alguem and self._positivos >= p.frames_regresso:
                self._ha_alguem = True
                return (Presenca(ha_alguem=True, hora=frame.hora),)
            return ()

        self._positivos = 0
        if self._t_primeiro_vazio is None:
            self._t_primeiro_vazio = t
        if self._ha_alguem and t - self._t_primeiro_vazio >= p.ausencia_s - _EPS:
            self._ha_alguem = False
            return (Presenca(ha_alguem=False, hora=frame.hora),)
        return ()
