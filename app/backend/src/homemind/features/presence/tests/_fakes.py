"""Detetor falso e cenário da porta: sem YOLO, sem câmara, sem rede."""

import numpy as np

from homemind.features.presence.door import PessoaCaixa, Soleira

LARGURA = ALTURA = 100
FPS = 10
# Soleira: faixa central; a linha é horizontal a y=0.5 (início -> fim = +x), o interior fica
# abaixo (s > 0 com y para baixo): descer = entrar, subir = sair.
SOLEIRA = Soleira(roi=(0.2, 0.0, 0.8, 1.0), linha=(0.2, 0.5, 0.8, 0.5), sinal_interior=1)


def pessoa(tid, y, x=0.5, conf=0.9):
    """Pessoa com os pés em (x, y) normalizados."""
    return PessoaCaixa(tid, (x - 0.05) * LARGURA, (y - 0.3) * ALTURA, (x + 0.05) * LARGURA,
                       y * ALTURA, conf)  # fmt: skip


class DetetorRoteirizado:
    """Devolve, a cada chamada, a lista do roteiro; regista a imagem que recebeu (já mascarada)."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.imagens_vistas: list[np.ndarray] = []

    def detetar(self, imagem):
        self.imagens_vistas.append(imagem)
        return self.roteiro.pop(0) if self.roteiro else ()


def trajeto(tid, y0, y1, frames, x=0.5):
    """Pessoa que anda de y0 a y1 em `frames` frames."""
    return [[pessoa(tid, y0 + (y1 - y0) * i / (frames - 1), x)] for i in range(frames)]


def juntar(*trajetos, pausa=0):
    """Concatena trajetos, com `pausa` frames sem ninguém entre eles."""
    saida: list = []
    for t in trajetos:
        saida += t + [[]] * pausa
    return saida


def sobrepor(a, b):
    """Dois trajetos em simultâneo (mesmo frame)."""
    n = max(len(a), len(b))
    a, b = a + [[]] * (n - len(a)), b + [[]] * (n - len(b))
    return [x + y for x, y in zip(a, b, strict=True)]
