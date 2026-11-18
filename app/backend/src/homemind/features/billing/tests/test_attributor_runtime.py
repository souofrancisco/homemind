"""BILL-02 com consumos como energy os publica hoje: localização `unknown` e sem custo estimado.

Billing completa a sua cópia com a divisão configurada da tomada e estima o custo pelo preço
de referência (0,16 €/kWh na casa demo). Quatro moradores, tudo SIMULADO."""

from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.billing import AttributionMethod, AttributionTarget
from homemind.contracts.common import replace, stable_id
from homemind.contracts.energy import LocationKind
from homemind.features.billing import attributor

PLUG_ANA = stable_id("device", "tomada-quarto-ana")
PLUG_BRUNO = stable_id("device", "tomada-quarto-bruno")
PLUG_SALA = stable_id("device", "tomada-sala")
METER = stable_id("device", "contador-geral-sala")
LOOSE = stable_id("device", "tomada-sem-divisao")
UNKNOWN = stable_id("device", "tomada-nao-registada")

LANDLORD = {"x-test-sub": "sub-senhorio"}
WHO = {r: {"x-test-sub": f"sub-{n}"} for r, n in ((fx.ANA, "ana"), (fx.BRUNO, "bruno"))}
WHO |= {fx.CARLA: {"x-test-sub": "sub-carla"}, fx.DIOGO: {"x-test-sub": "sub-diogo"}}
URL = f"/api/households/{fx.HOUSEHOLD}/bills"


@pytest.fixture(autouse=True)
def tomadas(app):
    def work(conn):
        for did, room, role in (
            (PLUG_ANA, fx.ROOM_ANA, "room_meter"),
            (PLUG_BRUNO, fx.ROOM_BRUNO, "none"),
            (PLUG_SALA, fx.ROOM_SALA, "none"),
            (METER, fx.ROOM_SALA, "main_meter"),
            (LOOSE, None, "none"),
        ):
            conn.execute(
                "INSERT INTO device (id, household_id, room_id, name, kind, role, source)"
                " VALUES (?,?,?,?,'plug',?,'fake')",
                (str(did), str(fx.HOUSEHOLD), room and str(room), f"tomada {did}", role),
            )

    app.state.db.run_sync(work)


def _como_energy(nome, device, wh, **over):
    """Consumo fechado tal como energy o publica: sem localização nem custo."""
    base = fx.consumption(closed=True)
    return replace(
        base,
        id=stable_id("consumption", nome),
        device_id=device,
        energy_wh=wh,
        location=LocationKind.unknown,
        room_id=None,
        cost_estimate=None,
        **over,
    )


def _handle(app, c, ts=fx.T0 + timedelta(hours=2)):
    ev = de.EnergyConsumptionClosed(
        ts=ts, household_id=fx.HOUSEHOLD, provenance=c.provenance, data=c
    )
    return app.state.db.run_sync(
        lambda conn: attributor.handle(conn, de.StoredEvent(seq=1, event=ev))
    )


def _ativa(app, c):
    return app.state.db.run_sync(lambda conn: attributor.active_attribution(conn, c.id))


def _guardado(app, c):
    return app.state.db.run_sync(lambda conn: attributor.load_consumption(conn, c.id))


def test_tomada_do_quarto_e_do_morador_mesmo_com_aparelho_de_outro(app):
    # aquecedor da Carla ligado no quarto do Bruno: paga o Bruno (o sítio, não o dono)
    c = _como_energy("aquecedor-no-bruno", PLUG_BRUNO, 3000, appliance_owner_resident_id=fx.CARLA)
    [ev] = _handle(app, c)
    a = _ativa(app, c)
    assert ev.data == a and a.method is AttributionMethod.room_rule
    assert a.target_resident_id == fx.BRUNO
    guardado = _guardado(app, c)
    assert (guardado.location, guardado.room_id) == (LocationKind.room, fx.ROOM_BRUNO)
    assert guardado.cost_estimate is None  # o custo estimado só serve para decidir


def test_sala_com_custo_estimado_pergunta_e_abaixo_do_limiar_divide(app):
    grande = _como_energy("aquecedor-sala", PLUG_SALA, 5000)  # 0,80 € ≥ 0,50 €
    [ev] = _handle(app, grande)
    assert isinstance(ev, de.BillingConfirmationNeeded)
    assert ev.data.estimated_cost_cents == 80 and _ativa(app, grande) is None
    assert _guardado(app, grande).location is LocationKind.common

    pequeno = _como_energy("chaleira-sala", PLUG_SALA, 1000)  # 0,16 €
    _handle(app, pequeno)
    a = _ativa(app, pequeno)
    assert a.target_type is AttributionTarget.common
    assert a.method is AttributionMethod.equal_fallback


def test_contador_geral_sem_divisao_ou_desconhecida_ficam_por_localizar(app):
    for nome, device in (("geral", METER), ("solta", LOOSE), ("estranha", UNKNOWN)):
        c = _como_energy(nome, device, 1000)
        _handle(app, c)
        assert (
            _guardado(app, c).location is LocationKind.unknown and _guardado(app, c).room_id is None
        )
        assert _ativa(app, c).target_type is AttributionTarget.common  # nunca um morador


def test_localizacao_dada_por_energy_nunca_e_substituida(app):
    c = replace(
        _como_energy("ja-localizado", PLUG_ANA, 1000),
        location=LocationKind.common,
        room_id=fx.ROOM_SALA,
    )
    _handle(app, c)
    assert _guardado(app, c).location is LocationKind.common
    assert _ativa(app, c).target_type is AttributionTarget.common


def test_sem_preco_nao_pergunta_e_usa_o_preco_da_ultima_fatura_fechada(app, client, now):
    app.state.db.run_sync(
        lambda conn: conn.execute("UPDATE household SET energy_price_millicents_per_kwh = NULL")
    )
    c = _como_energy("sem-preco", PLUG_SALA, 50_000)
    assert [type(e) for e in _handle(app, c)] == [de.BillingAttributionChanged]
    assert _ativa(app, c).target_type is AttributionTarget.common

    # com uma fatura fechada (outubro: 120 € / 600 kWh, 24 € fixos → 0,16 €/kWh) já pergunta
    now["value"] = now["value"].replace(month=12, day=5)
    body = {
        "period": {"start": "2026-10-01", "end": "2026-10-31"},
        "total_cents": 12_000,
        "fixed_cents": 2_400,
        "total_wh": 600_000,
        "origin": "simulated",
    }
    bill = client.post(URL, json=body, headers=LANDLORD).json()["id"]
    assert client.post(f"{URL}/{bill}/finalize", headers=LANDLORD).status_code == 200
    depois = _como_energy("com-preco-da-fatura", PLUG_SALA, 5000)
    [ev] = _handle(app, depois)
    assert isinstance(ev, de.BillingConfirmationNeeded) and ev.data.estimated_cost_cents == 80


def test_quatro_moradores_do_consumo_ao_recibo(app, client, now):
    """Medido no quarto, pergunta sem resposta, conta comum e consumo por localizar: a fatura
    fecha ao cêntimo, a base comum fica em todos e nada ambíguo vira dívida de alguém."""
    _handle(app, _como_energy("ana", PLUG_ANA, 100_000))
    _handle(app, _como_energy("bruno", PLUG_BRUNO, 50_000))
    _handle(app, _como_energy("sala-grande", PLUG_SALA, 20_000))  # pergunta; ninguém responde
    _handle(app, _como_energy("sala-pequena", PLUG_SALA, 2_000))
    _handle(app, _como_energy("por-localizar", LOOSE, 8_000))  # pergunta; ninguém responde

    now["value"] = now["value"].replace(month=12, day=5)
    body = {
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "total_cents": 12_000,
        "fixed_cents": 2_400,
        "total_wh": 600_000,
        "origin": "simulated",
    }
    bill = client.post(URL, json=body, headers=LANDLORD).json()["id"]
    assert client.post(f"{URL}/{bill}/finalize", headers=LANDLORD).status_code == 200

    recibos = {r: client.get(f"{URL}/{bill}/receipt", headers=h).json() for r, h in WHO.items()}
    assert sum(x["amount_cents"] for x in recibos.values()) == 12_000
    assert all(x["fixed_share_cents"] == 600 for x in recibos.values())
    # partes comuns iguais (± o cêntimo sorteado): Carla e Diogo só pagam o que é de todos
    comum = {r: x["amount_cents"] for r, x in recibos.items() if r in (fx.CARLA, fx.DIOGO)}
    assert abs(comum[fx.CARLA] - comum[fx.DIOGO]) <= 1
    assert recibos[fx.CARLA]["individual_cents"] == recibos[fx.DIOGO]["individual_cents"]
    # Ana e Bruno pagam o seu quarto (100 kWh = 16,00 €; 50 kWh = 8,00 €) acima disso
    assert recibos[fx.ANA]["individual_cents"] - recibos[fx.CARLA]["individual_cents"] == 1600
    assert recibos[fx.BRUNO]["individual_cents"] - recibos[fx.CARLA]["individual_cents"] == 800
