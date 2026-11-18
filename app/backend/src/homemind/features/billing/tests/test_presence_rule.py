"""Regra C da sala, «por quem estava em casa» (BILL-07). Casa demo e presença SIMULADAS.

Aquecedor na sala das 19h00 às 20h30 de 17/11 (`fx.consumption`). A Ana é «o João» do v5.1:
sozinha em casa, o consumo é dela; com qualquer dúvida, é de todos."""

import time
from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.billing import AttributionMethod, AttributionTarget
from homemind.contracts.common import ValueKind, replace, stable_id
from homemind.contracts.presence import (
    HouseOccupancy,
    OccupancyState,
    PersonPresence,
    PresenceSource,
    PresenceState,
    UncertainReason,
)
from homemind.features.billing import attributor, presence_rule

IN, OUT, UNSURE = PresenceState.home, PresenceState.away, PresenceState.uncertain
TENANTS = (fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO)
BEFORE = fx.T0 - timedelta(hours=1)
H = f"/api/households/{fx.HOUSEHOLD}"
HEADERS = {r: {"x-test-sub": s} for r, s in fx.SUBJECTS.items()}


@pytest.fixture
def regra_c(app):
    def work(conn):
        conn.execute("UPDATE household SET common_area_rule = 'presence'")
        conn.execute("UPDATE membership SET presence_opt_in = 1 WHERE role = 'tenant'")

    app.state.db.run_sync(work)


def _feed(app, ev):
    app.state.db.run_sync(lambda c: presence_rule.handle(c, de.StoredEvent(seq=1, event=ev)))


def _presenca(app, resident, state, since=BEFORE, confidence=0.97):
    p = PersonPresence(
        resident_id=resident,
        state=state,
        since=since,
        confidence=confidence,
        provenance=fx.SIM_INFERRED,
        sources=[PresenceSource.fusion],
        reason=UncertainReason.no_recent_cues if state is UNSURE else None,
    )
    _feed(
        app,
        de.PresenceChanged(
            id=stable_id("presence", str(resident), since.isoformat()),
            ts=since,
            household_id=fx.HOUSEHOLD,
            provenance=fx.SIM_INFERRED,
            data=p,
        ),
    )


def _porta(app, inside, visitors=0, ts=BEFORE):
    if inside is None:
        state = OccupancyState.uncertain
    else:
        state = OccupancyState.occupied if inside else OccupancyState.likely_empty
    o = HouseOccupancy(
        ts=ts,
        state=state,
        people_inside=inside,
        visitors=None if inside is None else visitors,
        residents_home=1 if inside else 0,
        provenance=fx.SIM_INFERRED,
    )
    _feed(
        app,
        de.PresenceOccupancyChanged(
            id=stable_id("occupancy", ts.isoformat()),
            ts=ts,
            household_id=fx.HOUSEHOLD,
            provenance=fx.SIM_INFERRED,
            data=o,
        ),
    )


def _ana_sozinha(app, **over):
    for r in TENANTS:
        _presenca(app, r, IN if r == fx.ANA else OUT, **over)
    _porta(app, 1)


def _consumo(app, nome="aquecedor", wh=3000, **over):
    c = replace(
        fx.consumption(closed=True),
        id=stable_id("consumption", nome),
        energy_wh=wh,
        cost_estimate=None,
        **over,
    )
    ev = de.EnergyConsumptionClosed(
        ts=c.ended_at or fx.T0,
        household_id=fx.HOUSEHOLD,
        provenance=c.provenance,
        data=c,
    )
    out = app.state.db.run_sync(
        lambda conn: attributor.handle(conn, de.StoredEvent(seq=1, event=ev))
    )
    a = app.state.db.run_sync(lambda conn: attributor.active_attribution(conn, c.id))
    return out, a


def test_joao_sozinho_em_casa_paga_o_aquecedor_da_sala(app, regra_c):
    _ana_sozinha(app)
    [ev], a = _consumo(app)
    assert isinstance(ev, de.BillingAttributionChanged) and ev.data == a
    assert (a.target_type, a.target_resident_id) == (AttributionTarget.resident, fx.ANA)
    assert a.method is AttributionMethod.presence_rule
    assert a.provenance.kind is ValueKind.inferred and a.provenance.simulated
    assert a.confidence == 0.97


@pytest.mark.parametrize(
    "duvida",
    [
        "visita",
        "contagem_perdida",
        "incerto",
        "dois_em_casa",
        "ninguem_em_casa",
        "confianca_baixa",
        "sem_consentimento",
        "sem_dados",
        "sai_a_meio",
        "visita_a_meio",
    ],
)
def test_qualquer_duvida_divide_por_todos(app, regra_c, duvida):
    if duvida == "sem_dados":
        _porta(app, 1)
        _presenca(app, fx.ANA, IN)  # os outros sem estado nenhum
    else:
        _ana_sozinha(app)
    match duvida:
        case "visita":
            _porta(app, 2, visitors=1)
        case "contagem_perdida":
            _porta(app, None)
        case "incerto":
            _presenca(app, fx.BRUNO, UNSURE)
        case "dois_em_casa":
            _presenca(app, fx.BRUNO, IN)
        case "ninguem_em_casa":
            _presenca(app, fx.ANA, OUT)
        case "confianca_baixa":
            _presenca(app, fx.CARLA, OUT, confidence=0.7)
        case "sem_consentimento":
            app.state.db.run_sync(
                lambda c: c.execute(
                    "UPDATE membership SET presence_opt_in = 0 WHERE resident_id = ?",
                    (str(fx.DIOGO),),
                )
            )
        case "sai_a_meio":
            _presenca(app, fx.ANA, OUT, since=fx.T0 + timedelta(minutes=40))
        case "visita_a_meio":
            _porta(app, 2, visitors=1, ts=fx.T0 + timedelta(minutes=40))
    _, a = _consumo(app)
    assert a.target_type is AttributionTarget.common
    assert a.method is AttributionMethod.equal_fallback
    assert a.provenance.kind is ValueKind.measured and a.confidence is None


def test_quarto_continua_do_morador_e_a_decorrer_espera(app, regra_c):
    _ana_sozinha(app)
    _, a = _consumo(app, "no-quarto-do-bruno", room_id=fx.ROOM_BRUNO, location="room")
    assert (a.method, a.target_resident_id) == (AttributionMethod.room_rule, fx.BRUNO)
    ongoing = replace(fx.consumption(), id=stable_id("consumption", "a-decorrer"))
    out = app.state.db.run_sync(
        lambda conn: attributor.handle(
            conn,
            de.StoredEvent(
                seq=1,
                event=de.EnergyConsumptionDetected(
                    ts=fx.T0, household_id=fx.HOUSEHOLD, provenance=fx.SIM_INFERRED, data=ongoing
                ),
            ),
        )
    )
    assert out == []


def test_regra_c_nunca_pergunta(app, regra_c):
    out, a = _consumo(app, "grande", wh=50_000)  # 8 €: com a regra B perguntava
    assert [type(e) for e in out] == [de.BillingAttributionChanged]
    assert a.target_type is AttributionTarget.common


def test_outras_regras_ignoram_a_presenca(app, regra_c):
    app.state.db.run_sync(lambda c: c.execute("UPDATE household SET common_area_rule = 'equal'"))
    _ana_sozinha(app)
    _, a = _consumo(app)
    assert a.method is AttributionMethod.equal_fallback


def test_recibo_explica_contestavel_e_senhorio_nao_ve_presenca(app, client, now, regra_c):
    _ana_sozinha(app)
    _, a = _consumo(app, "aquecedor-grande", wh=50_000)  # 8,00 € a 0,16 €/kWh
    assert a.target_resident_id == fx.ANA
    now["value"] = now["value"].replace(month=12, day=5)
    body = {
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "total_cents": 12_000,
        "fixed_cents": 2_400,
        "total_wh": 600_000,
        "origin": "simulated",
    }
    landlord = HEADERS[fx.LANDLORD]
    bill = client.post(f"{H}/bills", json=body, headers=landlord).json()["id"]
    assert client.post(f"{H}/bills/{bill}/finalize", headers=landlord).status_code == 200

    ana = HEADERS[fx.ANA]
    recibos = {
        r: client.get(f"{H}/bills/{bill}/receipt", headers=HEADERS[r]).json() for r in TENANTS
    }
    assert sum(x["amount_cents"] for x in recibos.values()) == 12_000
    assert recibos[fx.ANA]["individual_cents"] - recibos[fx.BRUNO]["individual_cents"] == 800
    explicacao = client.get(f"{H}/bills/{bill}/receipt/explanation", headers=ana)
    assert explicacao.status_code == 200 and "eras a única pessoa em casa" in explicacao.text

    r = client.post(
        f"{H}/bills/{bill}/contestations",
        json={"reason": "Não fui eu", "consumption_event_id": str(a.consumption_event_id)},
        headers=ana,
    )
    assert r.status_code == 201

    for url in (f"{H}/bills/{bill}/summary", f"{H}/contestations"):
        texto = client.get(url, headers=landlord).text.lower()
        assert "presen" not in texto and "inferred" not in texto and "casa" not in texto


def test_consumidor_guarda_so_o_necessario_e_apaga_o_antigo(app, regra_c):
    velho = fx.T0 - timedelta(days=60)
    _presenca(app, fx.ANA, OUT, since=velho)
    _presenca(app, fx.ANA, IN, since=velho + timedelta(days=1))
    _porta(app, 0, ts=velho)
    _porta(app, 1, ts=velho + timedelta(days=1))
    _presenca(app, fx.ANA, OUT, since=fx.T0)  # chega agora: o antigo sai
    _porta(app, 0, ts=fx.T0)

    def rows(conn):
        p = conn.execute("SELECT since, state FROM billing_presence_state").fetchall()
        o = conn.execute("SELECT ts FROM billing_occupancy").fetchall()
        return [tuple(r) for r in p], [r[0] for r in o]

    estados, porta = app.state.db.run_sync(rows)
    # fica o último estado antes do corte (ainda em vigor nessa altura) e o novo
    assert estados == [
        ((velho + timedelta(days=1)).isoformat(), "in"),
        (fx.T0.isoformat(), "out"),
    ]
    assert porta == [(velho + timedelta(days=1)).isoformat(), fx.T0.isoformat()]


def test_revogar_o_opt_in_apaga_a_copia_do_morador_e_so_a_dele(app, regra_c):
    _presenca(app, fx.ANA, IN)
    _presenca(app, fx.BRUNO, OUT)
    app.state.db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET presence_opt_in = 0 WHERE resident_id = ?", (str(fx.ANA),)
        )
    )
    _porta(app, 0, ts=fx.T0)  # qualquer mensagem de presença da casa dispara a limpeza

    def residentes(conn):
        return {r[0] for r in conn.execute("SELECT resident_id FROM billing_presence_state")}

    assert app.state.db.run_sync(residentes) == {str(fx.BRUNO)}


def test_subscrito_no_barramento(app, regra_c):
    p = PersonPresence(
        resident_id=fx.ANA,
        state=IN,
        since=BEFORE,
        confidence=0.97,
        provenance=fx.SIM_INFERRED,
        sources=[PresenceSource.fusion],
    )
    app.state.bus.publish_threadsafe(
        de.PresenceChanged(
            id=stable_id("presence", "bus"),
            ts=BEFORE,
            household_id=fx.HOUSEHOLD,
            provenance=fx.SIM_INFERRED,
            data=p,
        )
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        n = app.state.db.run_sync(
            lambda c: c.execute("SELECT count(*) FROM billing_presence_state").fetchone()[0]
        )
        if n:
            return
        time.sleep(0.05)
    raise AssertionError("o consumidor billing.presence não gravou o estado")
