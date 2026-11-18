"""Aprendizagem por confirmação (ENERGY-04): agrupamento e regras. Puro, sem BD nem relógio.

Regras decididas pelo utilizador (18/11/2026):

- só entram sessões fechadas **sem aparelho identificado** (nem candidatos);
- uma sessão junta-se a um grupo se a potência estiver dentro de `max(50 W, 10 %)` da média do
  grupo **e** a duração for semelhante (`min/max >= 0,5` face à duração média do grupo); havendo
  vários, fica o de potência mais próxima (desempate pelo id);
- pergunta-se à **3.ª ocorrência em 7 dias**, uma só vez por grupo (com um pedido pendente não se
  volta a perguntar); depois de «Ignorar» ou de a pergunta caducar sem resposta, o grupo fica
  **7 dias** sem perguntar;
- a pergunta mostra a potência arredondada e a hora local habitual, nunca nomes de pessoas.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

POWER_TOLERANCE_W = 50.0
POWER_TOLERANCE_RATIO = 0.1
DURATION_RATIO = 0.5
OCCURRENCES_TO_ASK = 3
WINDOW = timedelta(days=7)
SNOOZE = timedelta(days=7)
REQUEST_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class GroupSummary:
    id: UUID
    power_w: float  # média das sessões do grupo
    duration_s: float  # média das sessões do grupo


def power_matches(power_w: float, reference_w: float) -> bool:
    return abs(power_w - reference_w) <= max(POWER_TOLERANCE_W, reference_w * POWER_TOLERANCE_RATIO)


def duration_matches(duration_s: float, reference_s: float) -> bool:
    if duration_s <= 0 or reference_s <= 0:
        return False
    return min(duration_s, reference_s) / max(duration_s, reference_s) >= DURATION_RATIO


def choose_group(power_w: float, duration_s: float, groups: Iterable[GroupSummary]) -> UUID | None:
    """Grupo mais próximo em potência entre os compatíveis; `None` cria um grupo novo."""
    compatible = [
        g
        for g in groups
        if power_matches(power_w, g.power_w) and duration_matches(duration_s, g.duration_s)
    ]
    if not compatible:
        return None
    return min(compatible, key=lambda g: (abs(power_w - g.power_w), str(g.id))).id


def occurrences(started: Iterable[datetime], at: datetime) -> int:
    """Ocorrências com início em `(at - 7 dias, at]`."""
    return sum(1 for t in started if at - WINDOW < t <= at)


def should_ask(*, status: str, snoozed_until: datetime | None, count: int, at: datetime) -> bool:
    """Só grupos abertos (sem pedido pendente nem resolvidos), fora da pausa, à 3.ª ocorrência."""
    if status != "open" or count < OCCURRENCES_TO_ASK:
        return False
    return snoozed_until is None or at >= snoozed_until


def usual_hour(hours: Iterable[int]) -> int:
    """Hora mais frequente (desempate: a mais cedo)."""
    counts = Counter(hours)
    if not counts:
        raise ValueError("sem horas")
    return min(counts, key=lambda h: (-counts[h], h))


def appliance_name(approx_power_w: int) -> str:
    """Nome genérico do aparelho criado pela resposta; o morador renomeia-o depois."""
    return f"Aparelho ~{approx_power_w} W"
