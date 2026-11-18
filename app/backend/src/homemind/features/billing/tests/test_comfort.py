"""Lâmpada do orçamento e quartos frios (ALERT-06). Casa demo e sensores de clima SIMULADOS.

Fuso da casa: Europe/Lisbon (= UTC em novembro). Noites 22:00–08:00."""

import time
from datetime import UTC, datetime

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.billing import BudgetLight, budget_light
from homemind.contracts.common import stable_id
from homemind.contracts.sensors import SensorKind, SensorReading, SensorStatus
from homemind.features.billing import comfort

H = f"/api/households/{fx.HOUSEHOLD}"
ANA, BRUNO, LANDLORD = ({"x-test-sub": s} for s in ("sub-ana", "sub-bruno", "sub-senhorio"))
SENSOR = stable_id("device", "clima-quarto-ana")


def _leitura(at: datetime, temp: float | None, room=fx.ROOM_ANA, status=SensorStatus.ok):
    r = SensorReading(
        id=stable_id("leitura", str(room), at.isoformat()),
        device_id=SENSOR,
        room_id=room,
        ts=at,
        kind=SensorKind.temperature,
        status=status,
        temperature_c=temp if status is SensorStatus.ok else None,
        provenance=fx.SIM_MEASURED,
    )
    return de.SensorReadingRecorded(
        id=stable_id("evento", r.id.hex), ts=at, household_id=fx.HOUSEHOLD,
        provenance=fx.SIM_MEASURED, data=r,
    )  # fmt: skip


def _noite(dia: int, temps=(16.0, 15.0), room=fx.ROOM_ANA):
    """Leituras às 23:00 do dia `dia` e às 03:00 do dia seguinte (novembro de 2026)."""
    return [
        _leitura(datetime(2026, 11, dia, 23, tzinfo=UTC), temps[0], room),
        _leitura(datetime(2026, 11, dia + 1, 3, tzinfo=UTC), temps[1], room),
    ]


def _manha(dia: int, room=fx.ROOM_ANA):
    return _leitura(datetime(2026, 11, dia, 9, tzinfo=UTC), 19.0, room)


def _aplicar(app, eventos):
    out = []
    for i, ev in enumerate(eventos, 1):
        out += app.state.db.run_sync(
            lambda c, ev=ev, i=i: comfort.handle(c, de.StoredEvent(seq=i, event=ev))
        )
    return out


def test_tres_noites_frias_avisam_o_morador_uma_vez(app):
    out = _aplicar(app, [*_noite(10), *_noite(12), *_noite(14), _manha(15)])
    [ev] = out
    assert isinstance(ev, de.AlertsColdRoom) and ev.provenance.simulated
    d = ev.data
    assert (d.resident_id, d.room_id, d.cold_nights, d.window_nights) == (fx.ANA, fx.ROOM_ANA, 3, 7)
    assert d.coldest_night_c == 15.5 and d.threshold_c == 18.0
    assert str(d.last_night) == "2026-11-14"
    assert d.allowance_left_wh == 30_000  # plafond do quarto da Ana por usar em novembro
    assert _aplicar(app, [*_noite(15), _manha(16)]) == []  # mesma janela: não repete


def test_duas_noites_frias_nao_chegam(app):
    assert _aplicar(app, [*_noite(10), *_noite(12), _manha(14)]) == []


def test_a_noite_conta_pela_media_e_a_noite_em_curso_nao_conta(app):
    morna = _noite(12, temps=(16.0, 21.0))  # média 18,5 °C: não é fria
    assert _aplicar(app, [*_noite(10), *morna, *_noite(13), _manha(14)]) == []
    # a 3.ª noite fria ainda está a decorrer às 23:00: só conta depois das 08:00
    assert _aplicar(app, [_leitura(datetime(2026, 11, 14, 23, tzinfo=UTC), 15.0)]) == []
    assert len(_aplicar(app, [_manha(15)])) == 1


def test_noites_fora_da_janela_nao_contam(app):
    assert _aplicar(app, [*_noite(1), *_noite(2), *_noite(12), _manha(15)]) == []


def test_sensor_sem_valor_sala_e_sem_quarto_nao_geram_inferencias(app):
    sem_valor = [
        _leitura(datetime(2026, 11, d, 23, tzinfo=UTC), None, status=s)
        for d, s in (
            (10, SensorStatus.unknown),
            (11, SensorStatus.stale),
            (12, SensorStatus.unknown),
        )
    ]
    sala = [*_noite(10, room=fx.ROOM_SALA), *_noite(11, room=fx.ROOM_SALA)]
    sala += [*_noite(12, room=fx.ROOM_SALA), _manha(13, room=fx.ROOM_SALA)]
    sem_quarto = [
        _leitura(datetime(2026, 11, d, 23, tzinfo=UTC), 10.0, room=None) for d in (10, 11, 12)
    ]  # noqa: E501
    assert _aplicar(app, [*sem_valor, *sala, *sem_quarto, _manha(13)]) == []
    noites = app.state.db.run_sync(
        lambda c: c.execute("SELECT count(*) FROM alerts_room_night").fetchone()[0]
    )
    assert noites == 0


def test_aviso_privado_chega_so_a_ana(app, client):
    for ev in [*_noite(10), *_noite(12), *_noite(14), _manha(15)]:
        app.state.bus.publish_threadsafe(ev)
    fim = time.monotonic() + 5
    while time.monotonic() < fim:
        avisos = [
            n
            for n in client.get(f"{H}/notifications", headers=ANA).json()
            if n["kind"] == "comfort_alert"
        ]
        if avisos:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("o aviso de quarto frio não chegou")
    [aviso] = avisos
    assert aviso["title"] == "O teu quarto tem estado frio"
    assert "18 °C em 3 das últimas 7 noites" in aviso["body"] and "SIMULADO" in aviso["body"]
    assert "ainda tem 30,0 kWh do plafond solidário" in aviso["body"] and "€" not in aviso["body"]
    for quem in (BRUNO, LANDLORD):
        outros = client.get(f"{H}/notifications", headers=quem).json()
        assert not [n for n in outros if n["kind"] == "comfort_alert"]


def test_aviso_diz_o_plafond_que_ainda_resta(app, client):
    """BILL-03 + ALERT-06: o aquecimento provado já coberto desconta-se do plafond do mês."""
    from homemind.features.billing.tests.test_budgets import _aquecedor, _consumo

    _aquecedor(app)
    _consumo(app, "aquecedor", 12_000)  # 12 kWh de aquecedor no quarto da Ana
    [ev] = _aplicar(app, [*_noite(10), *_noite(12), *_noite(14), _manha(15)])
    assert ev.data.allowance_left_wh == 18_000


def test_aviso_com_plafond_gasto_e_sem_plafond(app):
    from homemind.features.billing.tests.test_budgets import _aquecedor, _consumo

    _aquecedor(app)
    _consumo(app, "aquecedor", 45_000)  # passa os 30 kWh
    [ev] = _aplicar(app, [*_noite(10), *_noite(12), *_noite(14), _manha(15)])
    assert ev.data.allowance_left_wh == 0
    app.state.db.run_sync(lambda c: c.execute("UPDATE room SET included_wh = NULL"))
    b = fx.ROOM_BRUNO
    frio = [*_noite(10, room=b), *_noite(12, room=b), *_noite(14, room=b), _manha(15, room=b)]
    [ev] = _aplicar(app, frio)
    assert ev.data.allowance_left_wh is None  # sem plafond não se promete nada


# --- lâmpada do orçamento ---------------------------------------------------------------------


def test_cor_do_orcamento():
    assert budget_light(None) is None  # sem gasto conhecido não há cor
    cores = [budget_light(p) for p in (0, 50, 79, 80, 99, 100, 140)]
    assert [c.light for c in cores] == [BudgetLight.green] * 3 + [BudgetLight.amber] * 2 + [
        BudgetLight.red
    ] * 2
    ambar = budget_light(85)
    assert (ambar.color, ambar.rgb) == ("amarelo", (255, 200, 0))
    assert ambar.label == "Atenção: perto do limite do orçamento (85 %)"  # não depende da cor


def test_o_estado_do_orcamento_traz_a_cor(client):
    assert client.get(f"{H}/budgets/me", headers=ANA).json()["light"] is None  # sem orçamento
    r = client.put(f"{H}/budgets/me", json={"limit_cents": 2500}, headers=ANA)
    assert r.status_code == 200
    assert r.json()["light"]["light"] == "green" and r.json()["light"]["color"] == "verde"
