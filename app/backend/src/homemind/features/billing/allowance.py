"""Plafond solidário de aquecimento (BILL-03): o aquecimento básico de cada quarto é de todos.

Premissas (explícitas, documentadas em `docs/modules/billing.md`):
- O plafond é `room.included_wh` por MÊS e por quarto (configurado pelo senhorio na criação do
  quarto, visível antes da adesão). Uma fatura que não seja um mês de calendário recebe a
  proporção de cada mês que cobre (dias do período nesse mês ÷ dias do mês), arredondado
  para baixo ao Wh: novembro inteiro = X; outubro + novembro = 2X.
- Só conta o aquecimento PROVADO: consumo com aparelho identificado (assinatura com vencedor)
  da categoria `heating`, medido numa tomada do PRÓPRIO quarto e atribuído ao seu morador.
  Sem prova (aparelho não identificado ou ambíguo) o benefício não se aplica; a explicação do
  recibo (BILL-05) di-lo, nunca em silêncio.
- O plafond enche por ordem cronológica dos consumos (empates pelo id): os primeiros X Wh de
  aquecimento passam para a conta comum (divididos por igual por todos os moradores); o resto
  é do morador, como qualquer consumo do quarto.

Funções puras: sem base de dados.
"""

import calendar
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, timedelta
from fractions import Fraction
from math import floor
from uuid import UUID

from homemind.contracts.billing import BillPeriod
from homemind.contracts.energy import ConsumptionEvent, LocationKind
from homemind.features.billing.allocation import EnergyShare


def period_limit(monthly_wh: int, period: BillPeriod) -> int:
    """Plafond de um período: soma, por mês de calendário, da fração do mês coberta."""
    months = Fraction(0)
    d = period.start
    while d <= period.end:
        last = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
        end = min(last, period.end)
        months += Fraction((end - d).days + 1, last.day)
        d = end + timedelta(days=1)
    return floor(monthly_wh * months)


def is_proven_heating(
    c: ConsumptionEvent, resident_room: UUID | None, heating: frozenset[UUID]
) -> bool:
    return (
        c.match.appliance_id is not None
        and c.match.appliance_id in heating
        and c.location is LocationKind.room
        and resident_room is not None
        and c.room_id == resident_room
    )


def apply(
    shares: Sequence[EnergyShare],
    consumptions: Mapping[UUID, ConsumptionEvent],
    residents: Mapping[UUID, UUID | None],
    limits: Mapping[UUID, int],
    heating: frozenset[UUID],
) -> tuple[list[EnergyShare], dict[UUID, int]]:
    """Separa a parte coberta pelo plafond. Devolve (partes, Wh coberto por consumo).

    `limits`: quarto → plafond do período em Wh (já proporcional). Cada parte coberta passa a
    uma `EnergyShare` sem morador e com `solidarity=True`, com a mesma proveniência do consumo.
    """
    left = dict(limits)
    covered: dict[UUID, int] = {}
    eligible = sorted(
        (
            s
            for s in shares
            if s.resident_id is not None
            and s.consumption_id is not None
            and is_proven_heating(
                consumptions[s.consumption_id], residents.get(s.resident_id), heating
            )
        ),
        key=lambda s: (consumptions[s.consumption_id].started_at, str(s.consumption_id)),
    )
    for s in eligible:
        room = residents[s.resident_id]
        take = min(s.energy_wh, left.get(room, 0))
        if take:
            covered[s.consumption_id] = take
            left[room] -= take
    out: list[EnergyShare] = []
    for s in shares:
        take = covered.get(s.consumption_id, 0) if s.resident_id is not None else 0
        if not take:
            out.append(s)
            continue
        if s.energy_wh > take:
            out.append(replace(s, energy_wh=s.energy_wh - take))
        out.append(replace(s, resident_id=None, energy_wh=take, solidarity=True))
    return out, covered
