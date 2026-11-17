"""Repartição da fatura (BILL-02) e arredondamento com fecho a 100 % (BILL-04).

    preço            = (total − fixa) ÷ total_kWh            (da fatura real, não da tomada)
    individual_i     = kWh próprios_i + parte igual da conta comum
    resíduo          = total_kWh − Σ individual               (≥ 0; senão bill_inconsistent)
    valor_i          = fixa ÷ N + resíduo × preço ÷ N + individual_i × preço

Arredondamento: cada componente (fixa, individual, resíduo) é repartida em cêntimos inteiros
pelo método do maior resto. Empates (ex.: 100 € por 3) resolvem-se por SORTEIO reproduzível
(D-34): ordem pseudo-aleatória com semente na casa e no mês da fatura. Cada mês calha a alguém
diferente, mas recalcular (ou rever) a mesma fatura dá sempre o mesmo recibo. Cada linha do
recibo é um inteiro, as linhas somam o valor de cada morador e `Σ valor_i = total` exatamente.

Consumos sem atribuição ativa (pergunta pendente, ambíguos, a decorrer) não criam dívida:
ficam no resíduo, dividido por igual. Os moradores são os ativos no período da fatura (entradas
e saídas fazem-se no fim do mês; não há repartição por dias).
"""

import hashlib
from collections import defaultdict
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import floor
from uuid import UUID

from homemind.contracts.billing import (
    Attribution,
    AttributionStatus,
    AttributionTarget,
    BillAllocation,
    BillBreakdownLine,
    BillInconsistentError,
    BreakdownKind,
    ElectricityBill,
    assert_single_active,
    validate_allocations,
)
from homemind.contracts.common import Origin, Provenance, ValueKind, stable_id
from homemind.contracts.energy import ConsumptionEvent, ConsumptionStatus, EnergyTotal


@dataclass(frozen=True)
class EnergyShare:
    """Energia atribuída: a um morador (`resident_id`) ou à conta comum (`None`)."""

    resident_id: UUID | None
    energy_wh: int
    provenance: Provenance


def shares_from_attributions(
    attributions: Sequence[Attribution], consumptions: Mapping[UUID, ConsumptionEvent]
) -> list[EnergyShare]:
    """Só atribuições ativas de consumos fechados entram na fatura."""
    assert_single_active(list(attributions))
    out = []
    for a in attributions:
        if a.status is not AttributionStatus.active:
            continue
        event = consumptions.get(a.consumption_event_id)
        if event is None or event.household_id != a.household_id:
            raise BillInconsistentError("atribuição sem o consumo correspondente")
        if event.status is not ConsumptionStatus.closed or not event.energy_wh:
            continue
        resident = a.target_resident_id if a.target_type is AttributionTarget.resident else None
        out.append(EnergyShare(resident, event.energy_wh, event.provenance))
    return out


def largest_remainder[K: Hashable](
    total: int,
    weights: Mapping[K, Fraction | int],
    tiebreak: Callable[[K], object] | None = None,
) -> dict[K, int]:
    """Reparte `total` em proporção aos pesos; soma exata. Empates: menor `tiebreak(chave)`
    (omissão: a própria chave)."""
    if total < 0 or any(w < 0 for w in weights.values()):
        raise ValueError("total e pesos não negativos")
    soma = sum(weights.values())
    if soma == 0:
        if total:
            raise ValueError("pesos nulos com total positivo")
        return dict.fromkeys(weights, 0)
    quotas = {k: Fraction(total) * w / soma for k, w in weights.items()}
    out = {k: floor(q) for k, q in quotas.items()}
    falta = total - sum(out.values())
    order = tiebreak or (lambda k: k)
    for k in sorted(weights, key=lambda k: (-(quotas[k] - out[k]), order(k)))[:falta]:
        out[k] += 1
    return out


def draw_order(bill: ElectricityBill) -> Callable[[UUID], str]:
    """Sorteio reproduzível dos empates (D-34): hash(casa, mês da fatura, morador)."""
    seed = f"{bill.household_id}/{bill.period.start.isoformat()}"
    return lambda r: hashlib.sha256(f"{seed}/{r}".encode()).hexdigest()


def allocate(
    bill: ElectricityBill,
    residents: Mapping[UUID, UUID | None],
    shares: Sequence[EnergyShare],
) -> list[BillAllocation]:
    """`residents`: morador ativo no período → o seu quarto (ou None). Ordem irrelevante."""
    if not residents:
        raise BillInconsistentError("fatura sem moradores ativos")
    ids = sorted(residents)
    equal = dict.fromkeys(ids, 1)
    draw = draw_order(bill)

    # kWh por morador e proveniência: próprios e parte (igual) de cada consumo comum.
    own: dict[UUID, dict[Provenance, int]] = {r: defaultdict(int) for r in ids}
    common: dict[UUID, dict[Provenance, int]] = {r: defaultdict(int) for r in ids}
    for s in shares:
        if s.energy_wh < 0:
            raise BillInconsistentError("energia negativa")
        if s.resident_id is None:
            for r, wh in largest_remainder(s.energy_wh, equal, draw).items():
                common[r][s.provenance] += wh
        elif s.resident_id in residents:
            own[s.resident_id][s.provenance] += s.energy_wh
        else:
            raise BillInconsistentError("atribuição a quem não é morador ativo no período")
    wh = {r: sum(own[r].values()) + sum(common[r].values()) for r in ids}
    attributed = sum(wh.values())
    if attributed > bill.total_wh:
        raise BillInconsistentError("kWh atribuídos acima do total da fatura")
    residual_wh = bill.total_wh - attributed

    # Componentes em cêntimos (cada uma soma exatamente o seu total).
    energy = bill.energy_cents
    exact = {r: Fraction(energy * wh[r], bill.total_wh) for r in ids}
    pool = _round(sum(exact.values(), Fraction(0)))  # ≤ energy, porque Σ wh ≤ total_wh
    individual = largest_remainder(pool, exact, draw)
    residual = largest_remainder(energy - pool, equal, draw)
    fixed = largest_remainder(bill.fixed_cents, equal, draw)
    residual_wh_share = largest_remainder(residual_wh, equal, draw)
    residual_prov = _residual_provenance(bill, shares)

    out = []
    for r in ids:
        lines = [
            BillBreakdownLine(
                kind=BreakdownKind.fixed_share,
                label="Termo fixo (parte igual)",
                amount_cents=fixed[r],
            ),
            BillBreakdownLine(
                kind=BreakdownKind.residual_share,
                label="Consumo não atribuído (parte igual)",
                energy_wh=residual_wh_share[r],
                amount_cents=residual[r],
                provenance=residual_prov,
            ),
            *_energy_lines(own[r], common[r], individual[r]),
        ]
        totals: dict[Provenance, int] = defaultdict(int)
        for group in (own[r], common[r]):
            for prov, e in group.items():
                totals[prov] += e
        out.append(
            BillAllocation(
                id=stable_id("allocation", str(bill.id), str(r)),
                bill_id=bill.id,
                resident_id=r,
                room_id=residents[r],
                fixed_share_cents=fixed[r],
                residual_share_cents=residual[r],
                individual_cents=individual[r],
                amount_cents=fixed[r] + residual[r] + individual[r],
                attributed_wh=[
                    EnergyTotal(provenance=p, energy_wh=e)
                    for p, e in sorted(totals.items(), key=lambda i: (i[0].origin, i[0].kind))
                    if e
                ],
                breakdown=lines,
            )
        )
    validate_allocations(bill, out)
    return out


_LABELS = {
    BreakdownKind.room: "Consumo atribuído a ti",
    BreakdownKind.common: "Zonas comuns (parte igual)",
}


def _energy_lines(
    own: Mapping[Provenance, int], common: Mapping[Provenance, int], cents: int
) -> list[BillBreakdownLine]:
    """Uma linha por (tipo, proveniência); os cêntimos individuais repartem-se pelos Wh."""
    keys = [
        (i, kind, prov, e)
        for i, (kind, group) in enumerate(
            ((BreakdownKind.room, own), (BreakdownKind.common, common))
        )
        for prov, e in sorted(group.items(), key=lambda g: (g[0].origin, g[0].kind))
        if e
    ]
    split = largest_remainder(cents, {n: k[3] for n, k in enumerate(keys)}) if keys else {}
    return [
        BillBreakdownLine(
            kind=kind,
            label=_LABELS[kind],
            energy_wh=e,
            amount_cents=split[n],
            provenance=prov,
        )
        for n, (_, kind, prov, e) in enumerate(keys)
    ]


def _residual_provenance(bill: ElectricityBill, shares: Sequence[EnergyShare]) -> Provenance:
    """O resíduo é calculado (fatura − atribuído): estimado; simulado se alguma entrada o for."""
    simulated = bill.provenance.simulated or any(s.provenance.simulated for s in shares)
    return Provenance(
        origin=Origin.simulated if simulated else Origin.real, kind=ValueKind.estimated
    )


def _round(x: Fraction) -> int:
    return round(x)  # exato; empate ao par (como `cost_cents`)
