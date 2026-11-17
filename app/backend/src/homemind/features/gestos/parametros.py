"""Parâmetros dos detetores de gesto e presença (P2), como dataclasses imutáveis.

A lógica pura não lê `get_settings()`: recebe estes objetos. Testes e afinador passam valores
explícitos; a aplicação usa `.de_settings(get_settings())`.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homemind.core.config import Settings


@dataclass(frozen=True, slots=True)
class ParametrosGesto:
    distancia_max_ombros: float = 0.6  # × largura dos ombros
    confianca_min: float = 0.5  # estritamente maior
    janela_s: float = 1.0
    fracao_min: float = 0.8
    min_frames: int = 3
    cooldown_s: float = 3.0  # por classe
    intervalo_max_s: float = 1.0  # buraco entre frames que reinicia a janela

    @classmethod
    def de_settings(cls, settings: "Settings") -> "ParametrosGesto":
        return cls(
            distancia_max_ombros=settings.gesto_distancia_max_ombros,
            confianca_min=settings.gesto_confianca_min,
            janela_s=settings.gesto_janela_s,
            fracao_min=settings.gesto_fracao_min,
            min_frames=settings.gesto_min_frames,
            cooldown_s=settings.gesto_cooldown_s,
            intervalo_max_s=settings.visao_intervalo_max_s,
        )


@dataclass(frozen=True, slots=True)
class ParametrosPresenca:
    """Definido já aqui para #6 (partilha o bloco de config)."""

    ausencia_s: float = 3.0
    frames_regresso: int = 2
    intervalo_max_s: float = 1.0

    @classmethod
    def de_settings(cls, settings: "Settings") -> "ParametrosPresenca":
        return cls(
            ausencia_s=settings.presenca_ausencia_s,
            frames_regresso=settings.presenca_frames_regresso,
            intervalo_max_s=settings.visao_intervalo_max_s,
        )
