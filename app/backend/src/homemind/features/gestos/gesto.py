"""Deteção do gesto «objeto levantado» (#5). Lógica pura: sem I/O, sem relógio de parede.

Só se guarda, por classe, `(t, válido)`; nunca pessoas, caixas ou keypoints.
"""

from collections import deque
from dataclasses import dataclass, field
from math import dist

from homemind.contracts.eventos import ObjetoLevantado
from homemind.contracts.visao import KP, ClasseObjeto, FrameDeteccoes, PessoaDetetada
from homemind.features.gestos.parametros import ParametrosGesto

CLASSES: tuple[ClasseObjeto, ...] = ("caneca", "livro", "comando")
_EPS = 1e-9  # tolerância para comparações de tempo em vírgula flutuante
_LADOS = (
    (KP.PULSO_ESQ, KP.COTOVELO_ESQ),
    (KP.PULSO_DIR, KP.COTOVELO_DIR),
)


@dataclass
class _EstadoClasse:
    janela: deque[tuple[float, bool]] = field(default_factory=deque)
    armado: bool = True
    t_ultimo_evento: float | None = None
    t_inicio_valido: float | None = None


def _pessoa_levanta(
    pessoa: PessoaDetetada, centro: tuple[float, float], p: ParametrosGesto
) -> bool:
    ombro_e, ombro_d = pessoa.kp(KP.OMBRO_ESQ), pessoa.kp(KP.OMBRO_DIR)
    if ombro_e.confianca <= p.confianca_min or ombro_d.confianca <= p.confianca_min:
        return False
    largura = dist((ombro_e.x, ombro_e.y), (ombro_d.x, ombro_d.y))
    if largura <= 0:
        return False
    for i_pulso, i_cotovelo in _LADOS:
        pulso, cotovelo = pessoa.kp(i_pulso), pessoa.kp(i_cotovelo)
        if pulso.confianca <= p.confianca_min or cotovelo.confianca <= p.confianca_min:
            continue
        if pulso.y >= cotovelo.y:  # y cresce para baixo
            continue
        if dist(centro, (pulso.x, pulso.y)) < p.distancia_max_ombros * largura:
            return True
    return False


class DetetorGesto:
    """Com estado, síncrono. Frames por ordem crescente de `t`."""

    def __init__(self, params: ParametrosGesto | None = None) -> None:
        self._p = params or ParametrosGesto()
        self._estado: dict[ClasseObjeto, _EstadoClasse] = {c: _EstadoClasse() for c in CLASSES}
        self._t_anterior: float | None = None

    def processar(self, frame: FrameDeteccoes) -> tuple[ObjetoLevantado, ...]:
        p, t = self._p, frame.t
        buraco = self._t_anterior is not None and t - self._t_anterior > p.intervalo_max_s
        self._t_anterior = t
        eventos: list[ObjetoLevantado] = []
        for classe in CLASSES:
            e = self._estado[classe]
            if buraco:  # frames que não existiram não confirmam gestos
                e.janela.clear()
                e.t_inicio_valido = None
                e.armado = True
            valido = any(
                _pessoa_levanta(pessoa, obj.caixa.centro, p)
                for obj in frame.objetos
                if obj.classe == classe
                for pessoa in frame.pessoas
            )
            if self._avancar(e, t, valido):
                eventos.append(ObjetoLevantado(classe=classe, hora=frame.hora))
        return tuple(eventos)

    def _avancar(self, e: _EstadoClasse, t: float, valido: bool) -> bool:
        p = self._p
        e.janela.append((t, valido))
        while e.janela[0][0] <= t - p.janela_s + _EPS:
            e.janela.popleft()
        n_validos = sum(1 for _, v in e.janela if v)
        fracao = n_validos / len(e.janela)
        if valido and e.t_inicio_valido is None:
            e.t_inicio_valido = t
        if n_validos == 0:
            e.t_inicio_valido = None
        if fracao < p.fracao_min - _EPS:
            if not e.armado:  # o gesto acabou: rearmar
                e.armado = True
                e.t_inicio_valido = None
            return False
        if not e.armado or e.t_inicio_valido is None:
            return False
        if t - e.t_inicio_valido < p.janela_s - _EPS or n_validos < p.min_frames:
            return False
        # Gesto completo: consome-se sempre; só emite fora do cooldown.
        e.armado = False
        if e.t_ultimo_evento is not None and t - e.t_ultimo_evento < p.cooldown_s - _EPS:
            return False
        e.t_ultimo_evento = t
        return True
