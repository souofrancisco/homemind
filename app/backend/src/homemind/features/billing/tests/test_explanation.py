"""Explicação do recibo (BILL-05): casa demo e fatura de 120 €, tudo SIMULADO."""

from datetime import UTC, datetime, timedelta

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import Attribution, AttributionMethod, AttributionTarget
from homemind.contracts.common import Audit, Provenance, stable_id
from homemind.contracts.energy import ApplianceMatch
from homemind.features.billing import attributor
from homemind.features.billing.tests.test_closing import (
    ANA,
    BRUNO,
    LANDLORD,
    OPERATOR,
    URL,
    _consumo,
    _fechar,
    _no_quarto,
    _rascunho,
    _recibo,
    dezembro,  # noqa: F401  (fixture autouse: fatura de novembro fechada em dezembro)
)


def _explicacao(client, bill, who=ANA):
    r = client.get(f"{URL}/{bill}/receipt/explanation", headers=who)
    assert r.status_code == 200, r.text
    return r.json()


def _nomes(app):
    """Aparelho e tomada com nome, como os registaria a casa (HOUSE-03)."""

    def seed(conn):
        conn.execute(
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
        conn.execute(
            "INSERT INTO device (id, household_id, room_id, name, kind, source) VALUES"
            " (?,?,?,?,?,?)",
            (str(fx.METER), str(fx.HOUSEHOLD), str(fx.ROOM_ANA), "Tomada Ana", "plug", "fake"),
        )

    app.state.db.run_sync(seed)


def _reconcilia(e):
    total = (
        e["fixed_cents"]
        + e["residual"]["amount_cents"]
        + sum(i["amount_cents"] for i in e["own"])
        + sum(g["amount_cents"] for g in e["common"])
        + (e["allowance"]["amount_cents"] if e["allowance"] else 0)
    )
    assert total == e["amount_cents"]


def test_quarto_e_sala_explicados_ao_centimo(app, client):
    _nomes(app)
    _consumo(app, "ana-quarto", 100_000, **_no_quarto(fx.ROOM_ANA))
    _consumo(app, "chaleira", 2_000)  # sala, abaixo do limiar → conta comum
    bill = _rascunho(client)
    _fechar(client, bill)
    recibo = _recibo(client, bill, ANA)
    e = _explicacao(client, bill)

    assert e["evidence_available"] and e["amount_cents"] == recibo["amount_cents"]
    _reconcilia(e)
    assert e["residents"] == 4 and e["equal_split_cents"] == 3000
    [mine] = e["own"]
    # aquecedor provado no quarto da Ana: 30 kWh do plafond solidário (BILL-03) são de todos
    assert mine["energy_wh"] == 100_000 and mine["covered_wh"] == 30_000
    assert mine["heating"] and mine["amount_cents"] == 1120
    assert mine["appliance_name"] == "Aquecedor" and mine["device_name"] == "Tomada Ana"
    assert mine["match_outcome"] == "identified" and mine["match_confidence"] == 0.9
    assert mine["method"] == "room_rule" and mine["decided_by"] == "system"
    stages = [s["stage"] for s in mine["steps"]]
    assert stages == ["measurement", "identification", "location", "decision", "allowance", "share"]
    assert "SIMULADO" in mine["steps"][0]["text"] and "teu quarto" in mine["steps"][2]["text"]
    assert "11,20 €" in mine["steps"][-1]["text"] and "70,00 kWh" in mine["steps"][-1]["text"]
    plafond = e["allowance"]
    assert plafond["limit_wh"] == 30_000 and plafond["covered_wh"] == 30_000
    assert plafond["house_covered_wh"] == 30_000 and plafond["my_share_wh"] == 7_500

    [sala] = e["common"]
    assert sala["consumptions"] == 1 and sala["energy_wh"] == 2_000
    assert sala["my_energy_wh"] == 500 and sala["method"] == "equal_fallback"
    assert "started_at" not in sala  # a conta comum não mostra horas
    assert e["residual"]["attributed_wh"] == 102_000
    assert e["residual"]["residual_wh"] == 600_000 - 102_000


def test_outro_morador_nao_ve_os_meus_consumos(app, client):
    _consumo(app, "ana-quarto", 100_000, **_no_quarto(fx.ROOM_ANA))
    bill = _rascunho(client)
    _fechar(client, bill)
    e = _explicacao(client, bill, BRUNO)
    assert e["own"] == [] and e["common"] == []
    _reconcilia(e)
    assert str(fx.ANA) not in str(e) and e["amount_cents"] < e["equal_split_cents"]


def test_aparelho_desconhecido_corrigido_por_votacao_sem_revelar_quem(app, client):
    c = _consumo(
        app,
        "desconhecido",
        20_000,
        match=ApplianceMatch(),
        appliance_owner_resident_id=None,
        **_no_quarto(fx.ROOM_BRUNO),
    )  # no quarto do Bruno → do Bruno; depois a votação dá-o à Ana
    voto = Attribution(
        id=stable_id("attribution", "voto"),
        household_id=fx.HOUSEHOLD,
        consumption_event_id=c.id,
        target_type=AttributionTarget.resident,
        target_resident_id=fx.ANA,
        method=AttributionMethod.confirmation,
        provenance=Provenance(origin="simulated", kind="measured"),
        decided_by=Audit(at=fx.T0 + timedelta(hours=3), by_resident_id=fx.CARLA),
    )
    app.state.db.run_sync(lambda conn: attributor._record(conn, voto, stable_id("corr")))
    bill = _rascunho(client)
    _fechar(client, bill)
    e = _explicacao(client, bill)
    [mine] = e["own"]
    assert mine["match_outcome"] == "unknown" and mine["appliance_name"] is None
    assert mine["decided_by"] == "housemates" and mine["corrections"] == 1
    stages = [s["stage"] for s in mine["steps"]]
    assert "correction" in stages and "votação" in mine["steps"][3]["text"]
    assert "não identificado" in mine["steps"][1]["text"]
    assert str(fx.CARLA) not in str(e) and str(fx.BRUNO) not in str(e)
    _reconcilia(e)


def test_pergunta_sem_decisao_no_fecho_fica_no_residuo(app, client, now):
    tarde = datetime(2026, 11, 30, 20, tzinfo=UTC)
    _consumo(app, "aquecedor-tarde", 10_000, started=tarde)  # 1,60 € → pergunta até 1/12 21h
    now["value"] = datetime(2026, 12, 1, 10, tzinfo=UTC)
    bill = _rascunho(client)
    _fechar(client, bill)
    e = _explicacao(client, bill)
    assert e["own"] == [] and e["common"] == []
    assert e["residual"]["undecided_consumptions"] == 1
    assert e["residual"]["undecided_wh"] == 10_000 and e["residual"]["attributed_wh"] == 0
    _reconcilia(e)


def test_fatura_sem_evidencia_guardada_nao_inventa(app, client):
    _consumo(app, "ana-quarto", 100_000, **_no_quarto(fx.ROOM_ANA))
    bill = _rascunho(client)
    _fechar(client, bill)
    app.state.db.run_sync(lambda c: c.execute("DELETE FROM billing_allocation_item"))
    e = _explicacao(client, bill)  # como uma fatura fechada antes da BILL-05
    assert not e["evidence_available"] and e["own"] == []
    assert e["amount_cents"] == _recibo(client, bill, ANA)["amount_cents"]


def test_correcao_da_fatura_tem_a_sua_evidencia(app, client):
    _consumo(app, "ana-quarto", 100_000, **_no_quarto(fx.ROOM_ANA))
    bill = _rascunho(client)
    _fechar(client, bill)
    body = {
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "total_cents": 13_000,
        "fixed_cents": 2_400,
        "total_wh": 600_000,
        "origin": "simulated",
    }
    nova = client.post(f"{URL}/{bill}/revisions", json=body, headers=LANDLORD).json()["id"]
    antiga, e = _explicacao(client, bill), _explicacao(client, nova)
    assert e["revision"] == 2 and e["evidence_available"] and len(e["own"]) == 1
    assert antiga["evidence_available"] and antiga["amount_cents"] != e["amount_cents"]
    _reconcilia(e)


def test_permissoes_da_explicacao(client):
    bill = _rascunho(client)
    assert client.get(f"{URL}/{bill}/receipt/explanation", headers=ANA).status_code == 404
    _fechar(client, bill)
    for who in (LANDLORD, OPERATOR):
        r = client.get(f"{URL}/{bill}/receipt/explanation", headers=who)
        assert r.status_code == 403
    r = client.get(f"{URL}/{stable_id('x')}/receipt/explanation", headers=ANA)
    assert r.status_code == 404


def test_reconciliacao_com_varios_consumos_e_proveniencias(app, client):
    real = Provenance(origin="real", kind="estimated")
    for n in range(5):
        _consumo(app, f"q{n}", 1_001 + n, **_no_quarto(fx.ROOM_ANA))
        _consumo(app, f"s{n}", 333 + n)  # sala, abaixo do limiar
    _consumo(app, "lampada", 777, provenance=real, **_no_quarto(fx.ROOM_ANA))
    bill = _rascunho(client)
    _fechar(client, bill)
    e = _explicacao(client, bill)
    assert e["evidence_available"] and len(e["own"]) == 6
    _reconcilia(e)
