"""Plafond solidário editado depois de criado o quarto (BILL-03): só vale no mês seguinte.

Casa demo (plafond inicial 30 kWh/mês por quarto), relógio 17/11/2026, tudo SIMULADO."""

from datetime import date

from homemind.contracts import fixtures as fx
from homemind.contracts.billing import BillPeriod
from homemind.contracts.common import stable_id
from homemind.features.billing.allowance import period_limit
from homemind.features.billing.closing import room_limits

H = f"/api/households/{fx.HOUSEHOLD}"
URL = f"{H}/room-allowances"
WHO = {s: {"x-test-sub": f"sub-{s}"} for s in ("senhorio", "ana", "operador")}


def _mudar(client, room=fx.ROOM_ANA, wh=50_000, who="senhorio"):
    return client.put(f"{URL}/{room}", json={"included_wh": wh}, headers=WHO[who])


def _do_quarto(client, room=fx.ROOM_ANA, who="ana"):
    return next(v for v in client.get(URL, headers=WHO[who]).json() if v["room_id"] == str(room))


def test_limite_com_plafond_por_mes():
    por_mes = {date(2026, 10, 1): 30_000, date(2026, 11, 1): 60_000}
    bimestral = BillPeriod(start=date(2026, 10, 1), end=date(2026, 11, 30))
    assert period_limit(por_mes.__getitem__, bimestral) == 90_000


def test_mudanca_so_vale_no_mes_seguinte(client):
    r = _mudar(client)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["current_wh"] == 30_000  # novembro não muda
    assert (v["upcoming_wh"], v["upcoming_from"]) == (50_000, "2026-12-01")
    assert _do_quarto(client)["upcoming_wh"] == 50_000  # o morador vê-a antes de começar
    assert _mudar(client, wh=0).json()["upcoming_wh"] == 0  # substituir; 0 = sem plafond


def test_limites_por_periodo(app, client, now):
    _mudar(client)

    def limite(start, end):
        p = BillPeriod(start=start, end=end)
        return app.state.db.run_sync(lambda c: room_limits(c, fx.HOUSEHOLD, p)).get(fx.ROOM_ANA)

    assert limite(date(2026, 11, 1), date(2026, 11, 30)) == 30_000
    assert limite(date(2026, 12, 1), date(2026, 12, 31)) == 50_000
    assert limite(date(2026, 11, 16), date(2026, 12, 15)) == 15_000 + 750_000 // 31
    now["value"] = now["value"].replace(month=12, day=2)
    assert _do_quarto(client)["current_wh"] == 50_000 and _do_quarto(client)["upcoming_wh"] is None


def test_fatura_fechada_de_novembro_nao_muda(app, client, now):
    _mudar(client)
    now["value"] = now["value"].replace(month=12, day=5)
    body = {
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "total_cents": 12_000,
        "fixed_cents": 2_400,
        "total_wh": 600_000,
        "origin": "simulated",
    }
    bill = client.post(f"{H}/bills", json=body, headers=WHO["senhorio"]).json()["id"]
    assert client.post(f"{H}/bills/{bill}/finalize", headers=WHO["senhorio"]).status_code == 200
    limite = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT limit_wh FROM billing_allowance WHERE bill_id = ? AND room_id = ?",
            (bill, str(fx.ROOM_ANA)),
        ).fetchone()["limit_wh"]
    )
    assert limite == 30_000


def test_permissoes_e_validacao(client):
    assert _mudar(client, who="ana").status_code == 403
    assert _mudar(client, who="operador").status_code == 403
    assert _mudar(client, room=fx.ROOM_SALA).status_code == 400  # a sala não tem plafond
    assert _mudar(client, room=stable_id("room", "b1")).status_code == 404  # quarto de outra casa
    assert _mudar(client, wh=-1).status_code == 400  # validação do corpo
    assert client.get(URL).status_code == 401
