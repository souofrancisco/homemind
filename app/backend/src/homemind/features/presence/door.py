"""Contagem de entradas/saídas na soleira (PRES-02). Lógica pura: sem YOLO, sem rede, sem I/O.

Privacidade: a imagem só é vista aqui para pintar a preto tudo o que está fora da soleira
(`mascarar`), ANTES de qualquer inferência. Nada é guardado: o contador só recebe caixas e
confianças; `track_id` é efémero (vive em memória enquanto a pessoa é vista) e nunca é
persistido nem sai deste módulo. Ninguém é identificado: só sai «entrou»/«saiu».

Geometria (coordenadas normalizadas 0–1, origem no canto superior esquerdo, y para baixo): a
linha vai de (x1, y1) a (x2, y2); para um ponto P, `s = (x2-x1)*(Py-y1) - (y2-y1)*(Px-x1)`
normalizado pelo comprimento é a distância com sinal. `sinal_interior` diz de que lado (sinal de
`s`) fica o interior da casa: passar para esse lado é `in`, para o outro é `out`. Usa-se o ponto
dos pés (centro da base da caixa).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from homemind.contracts.presence import DoorDirection

Retangulo = tuple[float, float, float, float]  # x1, y1, x2, y2 normalizados


@dataclass(frozen=True, slots=True)
class PessoaCaixa:
    """Uma pessoa detetada: só caixa e confiança do detetor. Sem pose, sem cara, sem imagem."""

    track_id: int | None  # ID efémero do tracker; None = ainda não confirmado (não conta)
    x1: float
    y1: float
    x2: float
    y2: float
    confianca: float  # 0–1, pontuação do detetor (não é uma precisão medida)


class DetetorPessoas(Protocol):
    """Recebe a imagem JÁ mascarada; síncrono e com estado (tracker)."""

    def detetar(self, imagem: Any) -> Sequence[PessoaCaixa]: ...


def parse_retangulo(texto: str) -> Retangulo | None:
    """«x1,y1,x2,y2» -> tuplo; vazio -> None; inválido -> ValueError (sem repetir o valor)."""
    if not texto.strip():
        return None
    try:
        v = tuple(float(p) for p in texto.split(","))
    except ValueError:
        raise ValueError("coordenadas inválidas: esperado x1,y1,x2,y2") from None
    if len(v) != 4 or not all(math.isfinite(c) and 0.0 <= c <= 1.0 for c in v):
        raise ValueError("coordenadas inválidas: esperado 4 valores entre 0 e 1")
    return v  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Soleira:
    roi: Retangulo  # zona analisada; fora dela a imagem é preta
    linha: Retangulo  # início e fim da linha orientada (dentro da roi)
    sinal_interior: int = 1
    margem: float = 0.02  # histerese: só conta ao passar esta distância da linha

    def __post_init__(self) -> None:
        rx1, ry1, rx2, ry2 = self.roi
        if not (rx1 < rx2 and ry1 < ry2):
            raise ValueError("soleira: roi vazia ou invertida")
        lx1, ly1, lx2, ly2 = self.linha
        if (lx1, ly1) == (lx2, ly2):
            raise ValueError("soleira: linha sem comprimento")
        for x, y in ((lx1, ly1), (lx2, ly2)):
            if not (rx1 <= x <= rx2 and ry1 <= y <= ry2):
                raise ValueError("soleira: a linha tem de estar dentro da roi")
        if self.sinal_interior not in (1, -1):
            raise ValueError("soleira: sinal_interior é 1 ou -1")
        if not 0 <= self.margem < 0.5:
            raise ValueError("soleira: margem fora de 0–0,5")

    def dentro(self, x: float, y: float) -> bool:
        x1, y1, x2, y2 = self.roi
        return x1 <= x <= x2 and y1 <= y <= y2

    def distancia(self, x: float, y: float) -> float:
        """Distância com sinal à linha, em fração do frame."""
        x1, y1, x2, y2 = self.linha
        comprimento = math.hypot(x2 - x1, y2 - y1)
        return ((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) / comprimento


def mascarar(imagem: np.ndarray, roi: Retangulo) -> np.ndarray:
    """Cópia da imagem toda a preto exceto a roi. Não altera o frame partilhado com o MJPEG."""
    altura, largura = imagem.shape[:2]
    x1, y1, x2, y2 = roi
    c0, c1 = int(x1 * largura), math.ceil(x2 * largura)
    l0, l1 = int(y1 * altura), math.ceil(y2 * altura)
    saida = np.zeros_like(imagem)
    saida[l0:l1, c0:c1] = imagem[l0:l1, c0:c1]
    return saida


@dataclass(frozen=True, slots=True)
class Passagem:
    t: float  # relógio monotónico do cruzamento (não da confirmação)
    direcao: DoorDirection
    confianca: float  # média das confianças do detetor nessa pessoa; não é precisão medida


@dataclass(slots=True)
class _Pista:
    lado: int | None = None
    frames: int = 0
    soma_conf: float = 0.0
    visto_t: float = 0.0


@dataclass(slots=True)
class _Pendente:
    track_id: int
    passagem: Passagem


@dataclass
class ContadorPorta:
    """Cruzamento da linha por pessoa, com três proteções contra contagens a mais:

    - histerese (`margem`): oscilar sobre a linha não conta;
    - confirmação (`confirmar_s`): um cruzamento só é emitido depois deste tempo; se a mesma
      pessoa voltar para trás dentro dele, os dois anulam-se (não passou);
    - cooldown (`cooldown_s`): no mesmo sentido, uma 2.ª passagem logo a seguir é ignorada
      (a mesma pessoa partida em duas pistas). Duas pessoas coladas na mesma janela contam como
      uma: preferimos contar a menos a inventar entradas.
    """

    soleira: Soleira
    cooldown_s: float = 1.0
    confirmar_s: float = 1.0
    min_frames: int = 2
    perdida_s: float = 2.0
    _pistas: dict[int, _Pista] = field(default_factory=dict, init=False, repr=False)
    _pendentes: list[_Pendente] = field(default_factory=list, init=False, repr=False)
    _ultimo: dict[DoorDirection, float] = field(default_factory=dict, init=False, repr=False)

    def atualizar(
        self, t: float, pessoas: Sequence[PessoaCaixa], largura: int, altura: int
    ) -> list[Passagem]:
        """Processa um frame (`t` monotónico); devolve as passagens confirmadas."""
        s = self.soleira
        for p in pessoas:
            if p.track_id is None:
                continue
            px, py = (p.x1 + p.x2) / 2 / largura, p.y2 / altura
            if not s.dentro(px, py):
                continue
            pista = self._pistas.setdefault(p.track_id, _Pista())
            pista.frames += 1
            pista.soma_conf += p.confianca
            pista.visto_t = t
            d = s.distancia(px, py)
            if abs(d) <= s.margem:
                continue
            lado = 1 if d > 0 else -1
            antes, pista.lado = pista.lado, lado
            if antes is not None and antes != lado and pista.frames >= self.min_frames:
                self._cruzou(t, p.track_id, pista, lado)
        self._esquecer(t)
        return self._confirmar(t)

    def _cruzou(self, t: float, track_id: int, pista: _Pista, lado: int) -> None:
        direcao = (
            DoorDirection.entered if lado == self.soleira.sinal_interior else DoorDirection.left
        )
        for pend in self._pendentes:
            if pend.track_id == track_id and pend.passagem.direcao is not direcao:
                self._pendentes.remove(pend)  # voltou atrás: não passou
                return
        confianca = min(1.0, max(0.0, pista.soma_conf / pista.frames))
        self._pendentes.append(_Pendente(track_id, Passagem(t, direcao, confianca)))

    def _confirmar(self, t: float) -> list[Passagem]:
        prontas: list[Passagem] = []
        for pend in list(self._pendentes):
            if t - pend.passagem.t < self.confirmar_s:
                continue
            self._pendentes.remove(pend)
            p = pend.passagem
            ultimo = self._ultimo.get(p.direcao)
            if ultimo is not None and p.t - ultimo < self.cooldown_s:
                continue
            self._ultimo[p.direcao] = p.t
            prontas.append(p)
        return prontas

    def _esquecer(self, t: float) -> None:
        for tid in [i for i, p in self._pistas.items() if t - p.visto_t > self.perdida_s]:
            del self._pistas[tid]
