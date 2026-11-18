"""Ocupação agregada da casa e visitas como número (PRES-05). Lógica pura: sem I/O nem relógio.

Privacidade: só entram sentidos de passagem na soleira (`DoorCrossed`, anónimos) e contagens de
moradores; só sai `HouseOccupancy` (números). Nenhum nome, horário por pessoa ou imagem. Uma
visita nunca gera conta individual nem pista individual: é só um número na vista agregada.

Contagem = saldo da porta (entradas − saídas) na janela. Conservadora:
- nunca negativa: uma saída sem entrada anterior (entrada perdida) reinicia o contador e marca-o
  «dessincronizado» (`people_inside=None`, `uncertain`) até voltar a haver prova coerente;
- reconcilia-se com os moradores em casa (telemóvel com opt-in): menos pessoas na porta do que
  moradores em casa = evento perdido ou contagem anterior à janela → incerto;
- sem eventos, câmara em falha ou contagem absurda → incerto (nunca «0 pessoas» inventado);
- `likely_empty` nunca é produzido aqui (é a PRES-06, fase 2; nunca arma nada).
- visitas = pessoas dentro − moradores em casa, só quando TODOS os moradores são conhecidos
  (opt-in e estado `in`/`out`); com algum morador desconhecido, `visitors=None`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from homemind.contracts.common import Origin, Provenance, ValueKind
from homemind.contracts.presence import (
    DoorCrossed,
    DoorDirection,
    HouseOccupancy,
    OccupancyState,
)

WINDOW = timedelta(hours=24)  # entradas mais antigas já não se confiam
MAX_PEOPLE = 20  # uma casa de 4 quartos com mais é contagem a divergir, não festa


@dataclass(frozen=True, slots=True)
class Residents:
    """O que se sabe dos moradores ativos, só como números."""

    home: int  # com opt-in e estado «em casa»
    unknown: int  # sem opt-in ou com estado incerto: não se sabe se estão em casa


def door_balance(doors: Sequence[DoorCrossed]) -> tuple[int, bool]:
    """(saldo, dessincronizado) por ordem de registo. Uma saída com saldo 0 não o torna negativo:
    reinicia-o a 0 e marca a contagem como dessincronizada até o saldo voltar a ser provado."""
    saldo, desync = 0, False
    for d in doors:
        if d.direction is DoorDirection.entered:
            saldo += 1
            continue
        if saldo == 0:
            desync = True  # saída sem entrada: houve uma entrada perdida (ou antes da janela)
        else:
            saldo -= 1
    return saldo, desync


def _uncertain(
    now: datetime,
    residents: Residents,
    prov: Provenance,
    *,
    people: int | None = None,
    visitors: int | None = None,
) -> HouseOccupancy:
    return HouseOccupancy(
        ts=now,
        state=OccupancyState.uncertain,
        people_inside=people,
        visitors=visitors,
        residents_home=residents.home,
        provenance=prov,
    )


def compute_occupancy(
    doors: Sequence[DoorCrossed],
    residents: Residents,
    now: datetime,
    *,
    camera_ok: bool,
    camera_origin: Origin,
) -> HouseOccupancy:
    """Ocupação em `now` a partir das passagens da janela (já filtradas, por ordem de registo)."""
    simulated = camera_origin is Origin.simulated or any(
        d.provenance.origin is Origin.simulated for d in doors
    )
    prov = Provenance(
        origin=Origin.simulated if simulated else Origin.real, kind=ValueKind.inferred
    )
    if not camera_ok or not doors:
        return _uncertain(now, residents, prov)  # sem câmara ou sem passagens: nada se prova
    saldo, desync = door_balance(doors)
    if saldo > MAX_PEOPLE or saldo < residents.home:
        return _uncertain(now, residents, prov)  # contagem a divergir dos telemóveis em casa
    if desync and saldo == 0:
        return _uncertain(now, residents, prov)  # reiniciada e ainda sem prova coerente
    if saldo == 0:
        # Zero na porta com ninguém conhecido em casa: não é «casa vazia» (PRES-06).
        return _uncertain(now, residents, prov, people=0, visitors=0)
    visitors = saldo - residents.home if residents.unknown == 0 else None
    return HouseOccupancy(
        ts=now,
        state=OccupancyState.occupied,
        people_inside=saldo,
        visitors=visitors,
        residents_home=residents.home,
        provenance=prov,
    )
