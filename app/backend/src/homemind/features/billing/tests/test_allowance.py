"""Plafond solidário de aquecimento (BILL-03): regras puras e o exemplo do PDF, tudo SIMULADO."""

from datetime import date, timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import BillPeriod
from homemind.contracts.common import replace, stable_id
from homemind.contracts.energy import ApplianceMatch, LocationKind
from homemind.features.billing.allocation import EnergyShare
from homemind.features.billing.allowance import apply, period_limit
from homemind.features.billing.tests.test_closing import (
    ANA,
    LANDLORD,
    URL,
    _consumo,
    _fechar,
    _no_quarto,
    _rascunho,
    _recibo,
    dezembro,  # noqa: F401  (fixture autouse: fatura de novembro fechada em dezembro)
)
from homemind.features.billing.tests.test_closing import BRUNO as BRUNO_H

X = 30_000  # 30 kWh/mês, o exemplo do v5.1 §8
RESIDENTS = {fx.ANA: fx.ROOM_ANA, fx.BRUNO: fx.ROOM_BRUNO, fx.CARLA: None}
HEATING = frozenset({fx.HEATER})


def _c(nome, wh, *, minutes=0, room=fx.ROOM_ANA, appliance=fx.HEATER):
    base = fx.consumption(closed=True)
    match = (
        ApplianceMatch(appliance_id=appliance, confidence=0.9) if appliance else ApplianceMatch()
    )
    location = {"location": LocationKind.room, "room_id": room} if room else {}
    return replace(
        base,
        id=stable_id("consumption", nome),
        energy_wh=wh,
        cost_estimate=None,
        match=match,
        appliance_owner_resident_id=None,
        started_at=fx.T0 + timedelta(minutes=minutes),
        ended_at=fx.T0 + timedelta(minutes=minutes + 30),
        **location,
    )


def _apply(consumptions, owner=fx.ANA, limits=None):
    by_id = {c.id: c for c in consumptions}
    shares = [EnergyShare(owner, c.energy_wh, c.provenance, c.id) for c in consumptions]
    return apply(shares, by_id, RESIDENTS, limits or {fx.ROOM_ANA: X}, HEATING)


# --- limite do período --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 11, 1), date(2026, 11, 30), X),  # mês inteiro
        (date(2026, 2, 1), date(2026, 2, 28), X),  # fevereiro também é um mês
        (date(2026, 10, 1), date(2026, 11, 30), 2 * X),  # fatura bimestral
        (date(2026, 11, 1), date(2026, 11, 15), X // 2),  # meio mês
        (date(2026, 10, 17), date(2026, 11, 16), 30_516),  # (15/31 + 16/30) × X, por baixo
    ],
)
def test_limite_proporcional_aos_meses(start, end, expected):
    assert period_limit(X, BillPeriod(start=start, end=end)) == expected


# --- limites X-1, X e X+1 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("wh", "covered", "own"),
    [(X - 1, X - 1, 0), (X, X, 0), (X + 1, X, 1)],
)
def test_fronteiras_do_plafond(wh, covered, own):
    c = _c("aq", wh)
    shares, cov = _apply([c])
    assert cov == {c.id: covered}
    pooled = [s for s in shares if s.solidarity]
    mine = [s for s in shares if s.resident_id == fx.ANA]
    assert [s.energy_wh for s in pooled] == [covered] and pooled[0].resident_id is None
    assert sum(s.energy_wh for s in mine) == own
    assert sum(s.energy_wh for s in shares) == wh  # nada se cria nem perde


def test_enche_por_ordem_cronologica():
    tarde, cedo = _c("tarde", 20_000, minutes=120), _c("cedo", 20_000)
    _, cov = _apply([tarde, cedo])
    assert cov == {cedo.id: 20_000, tarde.id: 10_000}


@pytest.mark.parametrize(
    "consumo",
    [
        _c("sem-prova", 10_000, appliance=None),  # aparelho não identificado
        _c("outro-aparelho", 10_000, appliance=fx.KETTLE),  # identificado, mas não aquece
        _c("na-sala", 10_000, room=None),  # aquecedor na zona comum
        _c("no-quarto-do-bruno", 10_000, room=fx.ROOM_BRUNO),  # não é o quarto da Ana
    ],
    ids=lambda c: c.id.hex[:6],
)
def test_sem_prova_de_aquecimento_no_proprio_quarto_nao_se_aplica(consumo):
    shares, cov = _apply([consumo])
    assert cov == {} and not any(s.solidarity for s in shares)


def test_sem_quarto_ou_sem_plafond_nao_se_aplica():
    c = _c("aq", 10_000)
    assert _apply([c], owner=fx.CARLA)[1] == {}  # morador sem quarto
    assert _apply([c], limits={fx.ROOM_BRUNO: X})[1] == {}  # o quarto da Ana não tem plafond


# --- exemplo do PDF (v5.1 §20: 360 kWh de aquecedor, plafond de 30 kWh) -------------------------


def _aquecedor_registado(app):
    app.state.db.run_sync(
        lambda conn: conn.execute(
            "INSERT INTO appliance (id, household_id, name, category, registered_by_resident_id,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (
                str(fx.HEATER),
                str(fx.HOUSEHOLD),
                "Aquecedor",
                "heating",
                str(fx.ANA),
                "2026-11-01T00:00:00.000000+00:00",
            ),
        )
    )


def test_exemplo_do_pdf_excesso_de_330_kwh(app, client):
    """Fatura de 120 € (24 € fixos + 600 kWh × 0,16 €); 4 moradores; Ana com aquecedor 360 kWh
    no quarto e plafond de 30 kWh: paga 330 kWh × 0,16 € = 52,80 € do quarto (v5.1 §20)."""
    _aquecedor_registado(app)
    _consumo(app, "aquecedor-ana", 360_000, **_no_quarto(fx.ROOM_ANA))
    bill = _rascunho(client)
    assert _fechar(client, bill).status_code == 200
    ana = _recibo(client, bill, ANA)
    linhas = {line["kind"]: line for line in ana["breakdown"]}
    assert linhas["room"]["energy_wh"] == 330_000 and linhas["room"]["amount_cents"] == 5280
    assert linhas["heating_allowance"]["energy_wh"] == 7_500
    assert linhas["heating_allowance"]["amount_cents"] == 120
    assert ana["amount_cents"] == 600 + 960 + 5280 + 120
    bruno = _recibo(client, bill, BRUNO_H)
    assert bruno["amount_cents"] == 600 + 960 + 120  # paga a sua parte do aquecimento básico
    e = client.get(f"{URL}/{bill}/receipt/explanation", headers=BRUNO_H).json()
    assert e["own"] == [] and e["allowance"]["amount_cents"] == 120
    assert e["allowance"]["house_covered_wh"] == 30_000 and e["allowance"]["covered_wh"] == 0
    assert str(fx.ANA) not in str(e)  # sabe quanto foi coberto na casa, não de quem
    partes = e["fixed_cents"] + e["residual"]["amount_cents"] + e["allowance"]["amount_cents"]
    assert partes == e["amount_cents"]
    resumo = client.get(f"{URL}/{bill}/summary", headers=LANDLORD)
    assert sum(q["amount_cents"] for q in resumo.json()["rooms"]) == 12_000


def test_sem_aparelho_registado_como_aquecimento_nao_ha_beneficio(app, client):
    _consumo(app, "aquecedor-ana", 360_000, **_no_quarto(fx.ROOM_ANA))  # catálogo vazio
    bill = _rascunho(client)
    _fechar(client, bill)
    ana = _recibo(client, bill, ANA)
    assert "heating_allowance" not in {line["kind"] for line in ana["breakdown"]}
    e = client.get(f"{URL}/{bill}/receipt/explanation", headers=ANA).json()
    assert e["allowance"]["covered_wh"] == 0 and e["allowance"]["limit_wh"] == X


def test_explicacao_diz_quando_nao_ha_prova(app, client):
    _consumo(
        app,
        "desconhecido",
        50_000,
        match=ApplianceMatch(),
        appliance_owner_resident_id=None,
        **_no_quarto(fx.ROOM_ANA),
    )
    bill = _rascunho(client)
    _fechar(client, bill)
    e = client.get(f"{URL}/{bill}/receipt/explanation", headers=ANA).json()
    assert e["allowance"]["unproven_consumptions"] == 1
    assert e["allowance"]["unproven_wh"] == 50_000
    [mine] = e["own"]
    texto = next(s["text"] for s in mine["steps"] if s["stage"] == "allowance")
    assert "Sem prova" in texto and mine["covered_wh"] == 0
