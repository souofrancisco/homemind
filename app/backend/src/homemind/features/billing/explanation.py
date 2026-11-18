"""Explicação do recibo (BILL-05): «porque é que pago isto?», da medição à parcela.

Lê a evidência fotografada no fecho (`billing_allocation_item`) e reparte os cêntimos de cada
linha do recibo pelos consumos que a compõem (maior resto, pelos Wh), logo reconcilia ao
cêntimo com a `BillAllocation` publicada. Privacidade (RBAC, CLAUDE.md):
- consumos atribuídos A MIM: detalhe completo (hora, tomada, aparelho, decisão);
- conta comum: agregada por aparelho/decisão, sem horas nem quem respondeu;
- resíduo: só totais da casa; quem decidiu é `me`/`housemates`/`system`, nunca um id.
Os textos são gerados aqui a partir dos dados (nunca inventados): o assistente e a app usam-nos.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.billing import (
    AllowanceExplanation,
    Attribution,
    AttributionMethod,
    BillAllocation,
    BreakdownKind,
    DecisionActor,
    ExplainedCommonGroup,
    ExplainedConsumption,
    ExplanationStage,
    ExplanationStep,
    ReceiptExplanation,
    ResidualExplanation,
)
from homemind.contracts.common import Origin, Provenance, ValueKind
from homemind.contracts.energy import ConsumptionEvent, LocationKind, MatchOutcome
from homemind.features.billing import bills, closing
from homemind.features.billing.allocation import draw_order, largest_remainder


@dataclass(frozen=True)
class _Item:
    consumption: ConsumptionEvent
    attribution: Attribution | None  # None: sem decisão no fecho (resíduo)
    target: UUID | None
    corrections: int
    heating: bool = False  # aquecimento provado (BILL-03)
    covered_wh: int = 0  # parte paga por todos pelo plafond solidário


class _Mismatch(Exception):
    """A evidência não reconcilia com o recibo (fatura fechada antes da BILL-05)."""


def explain(conn: sqlite3.Connection, row: sqlite3.Row, mine: BillAllocation) -> ReceiptExplanation:
    bill = closing._model(row)
    view = bills.to_view(row)
    everyone = closing.allocations_of(conn, bill.id)
    ids = sorted(a.resident_id for a in everyone)
    me = mine.resident_id
    equal = dict.fromkeys(ids, 1)
    draw = draw_order(bill)
    items = _items(conn, bill.id)
    house = conn.execute(
        "SELECT timezone, common_area_rule FROM household WHERE id = ?", (str(bill.household_id),)
    ).fetchone()
    names = _Names(conn, bill.household_id, ZoneInfo(house["timezone"]), mine.room_id)
    limit_row = conn.execute(
        "SELECT limit_wh FROM billing_allowance WHERE bill_id = ? AND room_id = ?",
        (str(bill.id), str(mine.room_id)),
    ).fetchone()
    limit = limit_row["limit_wh"] if limit_row else None

    try:
        own, common, pool = _reconcile(mine, items, ids, equal, draw)
        evidence = True
    except _Mismatch:
        own, common, pool, evidence = {}, {}, {}, False

    attributed_wh = sum(a.attributed_total_wh for a in everyone)
    residual_line = next(b for b in mine.breakdown if b.kind is BreakdownKind.residual_share)
    undecided = [i for i in items if i.attribution is None] if evidence else []
    return ReceiptExplanation(
        bill_id=bill.id,
        revision=bill.revision,
        period=bill.period,
        allocation_id=mine.id,
        amount_cents=mine.amount_cents,
        residents=len(ids),
        equal_split_cents=largest_remainder(bill.total_cents, equal, draw)[me],
        fixed_cents=mine.fixed_share_cents,
        price_millicents_per_kwh=view.price_millicents_per_kwh,
        common_area_rule=house["common_area_rule"],
        evidence_available=evidence,
        own=[
            _explain_own(item, cents, me, names, view.price_millicents_per_kwh, limit)
            for item, cents in sorted(own.values(), key=lambda v: v[0].consumption.started_at)
        ],
        common=_groups(common, names),
        residual=ResidualExplanation(
            bill_wh=bill.total_wh,
            attributed_wh=attributed_wh,
            residual_wh=bill.total_wh - attributed_wh,
            undecided_consumptions=len(undecided),
            undecided_wh=sum(i.consumption.energy_wh or 0 for i in undecided),
            my_energy_wh=residual_line.energy_wh or 0,
            amount_cents=mine.residual_share_cents,
            provenance=residual_line.provenance
            or Provenance(origin=Origin.real, kind=ValueKind.estimated),
        ),
        allowance=_allowance(conn, bill.id, mine, items, pool) if evidence else None,
    )


def _items(conn: sqlite3.Connection, bill_id: UUID) -> list[_Item]:
    rows = conn.execute(
        "SELECT target_resident_id, superseded_count, consumption_json, attribution_json,"
        " heating, covered_wh FROM billing_allocation_item WHERE bill_id = ?"
        " ORDER BY consumption_event_id",
        (str(bill_id),),
    ).fetchall()
    return [
        _Item(
            consumption=ConsumptionEvent.model_validate_json(r["consumption_json"]),
            attribution=Attribution.model_validate_json(r["attribution_json"])
            if r["attribution_json"]
            else None,
            target=UUID(r["target_resident_id"]) if r["target_resident_id"] else None,
            corrections=r["superseded_count"],
            heating=bool(r["heating"]),
            covered_wh=r["covered_wh"],
        )
        for r in rows
    ]


def _reconcile(mine, items, ids, equal, draw):
    """Reparte os cêntimos de cada linha `room`/`common`/`heating_allowance` (por proveniência)
    pelos seus consumos.

    Devolve `own[id] = (item, cents)`, `common[id] = (item, my_wh, cents)` e
    `pool[id] = (item, my_wh, cents)` (a minha parte do plafond solidário). Se os Wh da
    evidência não batem certo com os do recibo, `_Mismatch` (nunca se inventa uma repartição).
    """
    me = mine.resident_id
    weights: dict[tuple[BreakdownKind, Provenance], dict[UUID, int]] = defaultdict(dict)
    share_of: dict[UUID, int] = {}
    pool_of: dict[UUID, int] = {}
    mine_ids: list[UUID] = []
    for i in items:
        if i.attribution is None:
            continue
        c = i.consumption
        if i.covered_wh:
            pool_of[c.id] = largest_remainder(i.covered_wh, equal, draw)[me]
            if pool_of[c.id]:
                weights[(BreakdownKind.heating_allowance, c.provenance)][c.id] = pool_of[c.id]
        if i.target == me:
            mine_ids.append(c.id)
            if c.energy_wh - i.covered_wh:
                weights[(BreakdownKind.room, c.provenance)][c.id] = c.energy_wh - i.covered_wh
        elif i.target is None:
            share_of[c.id] = largest_remainder(c.energy_wh, equal, draw)[me]
            if share_of[c.id]:
                weights[(BreakdownKind.common, c.provenance)][c.id] = share_of[c.id]
    kinds = (BreakdownKind.room, BreakdownKind.common, BreakdownKind.heating_allowance)
    lines = {(b.kind, b.provenance): b for b in mine.breakdown if b.kind in kinds}
    if set(lines) != set(weights):
        raise _Mismatch
    cents: dict[tuple[BreakdownKind, UUID], int] = {}
    for key, line in lines.items():
        if sum(weights[key].values()) != line.energy_wh:
            raise _Mismatch
        for cid, v in largest_remainder(line.amount_cents, weights[key]).items():
            cents[(key[0], cid)] = v
    by_id = {i.consumption.id: i for i in items}
    own = {cid: (by_id[cid], cents.get((BreakdownKind.room, cid), 0)) for cid in mine_ids}
    common = {
        cid: (by_id[cid], wh, cents.get((BreakdownKind.common, cid), 0))
        for cid, wh in share_of.items()
    }
    pool = {
        cid: (by_id[cid], wh, cents.get((BreakdownKind.heating_allowance, cid), 0))
        for cid, wh in pool_of.items()
    }
    return own, common, pool


def _allowance(
    conn, bill_id: UUID, mine: BillAllocation, items, pool
) -> AllowanceExplanation | None:
    """O plafond do meu quarto (como estava no fecho) e a minha parte do da casa."""
    row = conn.execute(
        "SELECT limit_wh FROM billing_allowance WHERE bill_id = ? AND room_id = ?",
        (str(bill_id), str(mine.room_id)),
    ).fetchone()
    if row is None and not pool:
        return None
    me = mine.resident_id
    in_my_room = [
        i
        for i in items
        if i.attribution is not None
        and i.target == me
        and i.consumption.location is LocationKind.room
        and i.consumption.room_id == mine.room_id
    ]
    proven = [i for i in in_my_room if i.heating]
    unproven = [i for i in in_my_room if i.consumption.match.appliance_id is None]
    return AllowanceExplanation(
        limit_wh=row["limit_wh"] if row else 0,
        heating_wh=sum(i.consumption.energy_wh for i in proven),
        covered_wh=sum(i.covered_wh for i in proven),
        unproven_consumptions=len(unproven),
        unproven_wh=sum(i.consumption.energy_wh for i in unproven),
        house_covered_wh=sum(i.covered_wh for i in items),
        my_share_wh=sum(wh for _, wh, _ in pool.values()),
        amount_cents=sum(c for _, _, c in pool.values()),
    )


# --- textos --------------------------------------------------------------------------------------


class _Names:
    """Nomes da casa (aparelhos, tomadas, quartos) para os textos; nunca ids externos."""

    def __init__(self, conn, household_id: UUID, tz: ZoneInfo, my_room: UUID | None) -> None:
        hid = (str(household_id),)
        self.appliances = dict(
            conn.execute("SELECT id, name FROM appliance WHERE household_id = ?", hid).fetchall()
        )
        self.devices = dict(
            conn.execute("SELECT id, name FROM device WHERE household_id = ?", hid).fetchall()
        )
        self.rooms = dict(
            conn.execute("SELECT id, name FROM room WHERE household_id = ?", hid).fetchall()
        )
        self.tz, self.my_room = tz, my_room

    def appliance(self, c: ConsumptionEvent) -> str | None:
        aid = c.match.appliance_id
        return self.appliances.get(str(aid)) if aid else None

    def local(self, t: datetime) -> datetime:
        return t.astimezone(self.tz)


def money(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d} €"


def kwh(wh: int) -> str:
    return f"{wh / 1000:.2f}".replace(".", ",") + " kWh"


def price_per_kwh(millicents: int) -> str:
    return f"{millicents / 100_000:.4f}".replace(".", ",") + " €/kWh"


_KIND = {
    ValueKind.measured: "medido",
    ValueKind.estimated: "estimado",
    ValueKind.inferred: "inferido",
}


def _label(p: Provenance) -> str:
    return _KIND[p.kind] + (", SIMULADO" if p.origin is Origin.simulated else "")


def _actor(a: Attribution, me: UUID) -> DecisionActor:
    if a.decided_by.by_resident_id is None:
        return DecisionActor.system
    return DecisionActor.me if a.decided_by.by_resident_id == me else DecisionActor.housemates


_DECISION = {
    AttributionMethod.room_rule: "Regra 1, «o teu quarto é teu»: o que passa pelas tomadas do "
    "quarto é de quem lá mora (do contrato).",
    AttributionMethod.presence_rule: "Dividido por quem estava em casa.",
    AttributionMethod.equal_fallback: "Sem resposta no prazo à pergunta «De quem é esta conta?»: "
    "dividido por todos.",
    AttributionMethod.manual: "Decisão corrigida à mão.",
}


def _decision_text(a: Attribution, actor: DecisionActor) -> str:
    if a.method is AttributionMethod.confirmation:
        if actor is DecisionActor.me:
            return "Respondeste à pergunta «De quem é esta conta?» e a conta ficou contigo."
        return (
            "Decidido pela votação «De quem é esta conta?»: pelo menos metade dos moradores "
            "indicou que era teu."
        )
    return _DECISION[a.method]


def _explain_own(
    item: _Item, cents: int, me: UUID, names: _Names, price: int, limit: int | None
) -> ExplainedConsumption:
    c, a = item.consumption, item.attribution
    assert a is not None and c.energy_wh is not None
    actor = _actor(a, me)
    device = names.devices.get(str(c.device_id))
    appliance = names.appliance(c)
    start = names.local(c.started_at)
    end = names.local(c.ended_at) if c.ended_at else None
    when = start.strftime("%d/%m %H:%M") + (f"–{end:%H:%M}" if end else "")
    where = f"na tomada «{device}»" if device else "numa tomada"
    steps = [
        ExplanationStep(
            stage=ExplanationStage.measurement,
            text=f"{kwh(c.energy_wh)} {where}, {when} ({_label(c.provenance)}).",
        ),
        ExplanationStep(stage=ExplanationStage.identification, text=_identification(c, appliance)),
        ExplanationStep(stage=ExplanationStage.location, text=_location(c, names)),
        ExplanationStep(stage=ExplanationStage.decision, text=_decision_text(a, actor)),
    ]
    if item.corrections:
        steps.append(
            ExplanationStep(
                stage=ExplanationStage.correction,
                text=f"Esta decisão substituiu {item.corrections} anterior(es); "
                "conta só a mais recente.",
            )
        )
    note = _allowance_text(item, names, limit)
    if note:
        steps.append(ExplanationStep(stage=ExplanationStage.allowance, text=note))
    steps.append(
        ExplanationStep(
            stage=ExplanationStage.share,
            text=f"{money(cents)} no teu recibo: {kwh(c.energy_wh - item.covered_wh)} ao preço "
            f"médio da fatura ({price_per_kwh(price)}, sem termo fixo).",
        )
    )
    return ExplainedConsumption(
        consumption_event_id=c.id,
        started_at=c.started_at,
        ended_at=c.ended_at,
        energy_wh=c.energy_wh,
        provenance=c.provenance,
        device_name=device,
        appliance_name=appliance,
        match_outcome=c.match.outcome,
        match_confidence=c.match.confidence,
        location=c.location,
        room_name=names.rooms.get(str(c.room_id)) if c.room_id else None,
        method=a.method,
        decided_by=actor,
        decided_at=a.decided_by.at,
        corrections=item.corrections,
        heating=item.heating,
        covered_wh=item.covered_wh,
        amount_cents=cents,
        steps=steps,
    )


def _allowance_text(item: _Item, names: _Names, limit: int | None) -> str | None:
    """Plafond solidário (BILL-03): dito sempre que pode contar, nunca aplicado em silêncio."""
    c = item.consumption
    if not limit or c.location is not LocationKind.room or c.room_id != names.my_room:
        return None
    if item.covered_wh:
        return (
            f"Plafond solidário: {kwh(item.covered_wh)} deste aquecimento são pagos por todos "
            f"(o teu quarto tem {kwh(limit)} de aquecimento básico nesta fatura)."
        )
    if item.heating:
        return "Aquecimento acima do plafond solidário do teu quarto (já usado): é teu."
    if c.match.appliance_id is None:
        return (
            "Sem prova de que é aquecimento (aparelho não identificado): não conta para o "
            "plafond solidário."
        )
    return None


def _identification(c: ConsumptionEvent, appliance: str | None) -> str:
    outcome = c.match.outcome
    if outcome is MatchOutcome.identified:
        pct = round((c.match.confidence or 0) * 100)
        name = f"«{appliance}»" if appliance else "um aparelho registado"
        return f"Reconhecido como {name} pela assinatura de consumo (confiança {pct} %)."
    if outcome is MatchOutcome.ambiguous:
        return (
            f"Não deu para distinguir entre {len(c.match.candidates)} aparelhos parecidos; "
            "conta o sítio da tomada, não o aparelho."
        )
    return "Aparelho não identificado; conta o sítio da tomada, não o aparelho."


def _location(c: ConsumptionEvent, names: _Names) -> str:
    room = names.rooms.get(str(c.room_id)) if c.room_id else None
    if c.location is LocationKind.room:
        mine = c.room_id == names.my_room
        return f"No {'teu ' if mine else ''}quarto «{room or 'Quarto'}»."
    if c.location is LocationKind.common:
        return f"Numa zona comum «{room}»." if room else "Numa zona comum."
    return "Localização desconhecida (nunca se assume um quarto)."


def _groups(common, names: _Names) -> list[ExplainedCommonGroup]:
    acc: dict[tuple, list] = {}
    for item, my_wh, cents in common.values():
        c, a = item.consumption, item.attribution
        key = (str(c.match.appliance_id or ""), c.location, a.method, c.provenance)
        g = acc.setdefault(key, [names.appliance(c), 0, 0, 0, 0])
        g[1] += 1
        g[2] += c.energy_wh
        g[3] += my_wh
        g[4] += cents
    return [
        ExplainedCommonGroup(
            appliance_name=name,
            location=location,
            method=method,
            provenance=prov,
            consumptions=n,
            energy_wh=wh,
            my_energy_wh=my_wh,
            amount_cents=cents,
        )
        for (_, location, method, prov), (name, n, wh, my_wh, cents) in sorted(
            acc.items(), key=lambda kv: (-kv[1][4], -kv[1][2], kv[0][0])
        )
    ]
