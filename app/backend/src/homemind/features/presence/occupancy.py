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
- `likely_empty` (PRES-06, candidato a AWAY; nunca arma nada): contagem fiável a 0 (sem entrada
  perdida), câmara ativa e nenhum telemóvel com opt-in em casa. Moradores sem opt-in não bloqueiam:
  decide a porta. O zero fiável mantém-se para lá da janela de 24 h enquanto a câmara estiver
  ativa e não houver passagens depois (`empty_since`, o instante em que o estado passou a vazio).
  O cartão (GET) e o evento `presence.occupancy_changed` usam este mesmo cálculo.
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


def _empty(now: datetime, prov: Provenance) -> HouseOccupancy:
    return HouseOccupancy(
        ts=now,
        state=OccupancyState.likely_empty,
        people_inside=0,
        visitors=0,
        residents_home=0,
        provenance=prov,
    )


def compute_occupancy(
    doors: Sequence[DoorCrossed],
    residents: Residents,
    now: datetime,
    *,
    camera_ok: bool,
    camera_origin: Origin,
    empty_since: datetime | None = None,
) -> HouseOccupancy:
    """Ocupação em `now` a partir das passagens da janela (já filtradas, por ordem de registo).
    `empty_since`: desde quando o último estado registado é `likely_empty` (ou `None`)."""
    simulated = camera_origin is Origin.simulated or any(
        d.provenance.origin is Origin.simulated for d in doors
    )
    prov = Provenance(
        origin=Origin.simulated if simulated else Origin.real, kind=ValueKind.inferred
    )
    if not camera_ok:
        return _uncertain(now, residents, prov)  # sem câmara: nada se prova
    if (
        empty_since is not None
        and residents.home == 0
        and not any(d.ts >= empty_since for d in doors)
    ):
        return _empty(now, prov)  # zero fiável mantido: ninguém passou na porta desde então
    if not doors:
        return _uncertain(now, residents, prov)  # sem passagens: nada se prova
    saldo, desync = door_balance(doors)
    if saldo > MAX_PEOPLE or saldo < residents.home:
        return _uncertain(now, residents, prov)  # contagem a divergir dos telemóveis em casa
    if desync and saldo == 0:
        return _uncertain(now, residents, prov)  # reiniciada e ainda sem prova coerente
    if saldo == 0:
        return _empty(now, prov)  # zero fiável e nenhum telemóvel em casa (saldo >= home)
    visitors = saldo - residents.home if residents.unknown == 0 else None
    return HouseOccupancy(
        ts=now,
        state=OccupancyState.occupied,
        people_inside=saldo,
        visitors=visitors,
        residents_home=residents.home,
        provenance=prov,
    )
