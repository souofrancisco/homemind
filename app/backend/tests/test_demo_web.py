"""Demo web: a cópia é separada da original, só o comando local liga `sub`s, guardas de marcador."""

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from homemind.contracts import fixtures as fx
from homemind.demo import web
from homemind.demo.cli import FILE_NAME, DemoStore


@pytest.fixture
def roots(tmp_path, monkeypatch):
    demo, copy = tmp_path / "demo", tmp_path / "web"
    DemoStore(demo).prepare()
    monkeypatch.setattr(web, "DEMO_ROOT", demo)
    monkeypatch.setattr(web, "WEB_ROOT", copy)
    return demo, copy


def _subs(path):
    with closing(sqlite3.connect(path)) as c:
        return dict(c.execute("SELECT display_name, auth_subject FROM resident"))


def test_prepare_copia_sem_tocar_na_original(roots):
    demo, copy = roots
    before = hashlib.sha256((demo / FILE_NAME).read_bytes()).hexdigest()
    assert web.prepare() == "criada" and web.prepare() == "existente"
    assert hashlib.sha256((demo / FILE_NAME).read_bytes()).hexdigest() == before
    web.link("ana", "sub-real-ana")
    assert _subs(copy / web.WEB_FILE)["Ana"] == "sub-real-ana"
    assert _subs(demo / FILE_NAME)["Ana"] == "sub-ana"  # original e `demo-reset` intactos
    DemoStore(demo)._guard(existing=True)


def test_copia_web_ancorada_no_relógio_e_com_catálogo_real(roots):
    web.prepare()
    with closing(sqlite3.connect(web.web_path())) as c:
        recent = c.execute(
            "SELECT max(ts) FROM domain_event WHERE type='energy.reading_recorded'"
        ).fetchone()[0]
        assert datetime.now(UTC) - datetime.fromisoformat(recent) < timedelta(minutes=30)
        device = c.execute(
            "SELECT role,room_id,name FROM device WHERE name LIKE '%SIMULADA%'"
            " AND role='room_meter'"
        ).fetchone()
        assert device[0] == "room_meter" and "SIMULADA" in device[2]
        assert c.execute("SELECT count(*) FROM appliance").fetchone()[0] >= 8
        assert (
            c.execute(
                "SELECT count(*) FROM appliance_signature WHERE origin='simulated'"
            ).fetchone()[0]
            >= 8
        )


def test_copia_web_tem_historico_votos_orcamentos_e_recibos(roots):
    web.prepare()
    with closing(sqlite3.connect(web.web_path())) as c:
        c.row_factory = sqlite3.Row
        assert (
            c.execute(
                "SELECT count(*) FROM billing_budget WHERE kind='personal' "
                "AND period=strftime('%Y-%m','now')"
            ).fetchone()[0]
            == 4
        )
        assert (
            c.execute(
                "SELECT count(*) FROM billing_consumption "
                "WHERE started_at >= strftime('%Y-%m-01','now')"
            ).fetchone()[0]
            >= 30
        )
        assert (
            c.execute(
                "SELECT count(*) FROM billing_consumption "
                "WHERE started_at >= strftime('%Y-%m-01','now')"
            ).fetchone()[0]
            <= 45
        )
        from homemind.features.billing.budgets import month_spend

        now = datetime.now(UTC)
        period = now.strftime("%Y-%m")
        limits = {fx.ANA: 2500, fx.BRUNO: 3000, fx.CARLA: 2500, fx.DIOGO: 2000}
        percentages = {}
        for resident, limit in limits.items():
            spend = month_spend(c, fx.HOUSEHOLD, resident, period, now)
            assert spend is not None
            percentages[resident] = spend.total_cents * 100 // limit
            assert 40 <= percentages[resident] <= 90
        assert 45 <= percentages[fx.ANA] <= 60
        assert 75 <= percentages[fx.BRUNO] <= 90

        pending = [
            row[0]
            for row in c.execute(
                "SELECT json FROM notification WHERE kind='confirmation_request' "
                "AND status IN ('unread','read')"
            )
        ]
        assert len(pending) >= 4
        from homemind.contracts.notification import Notification

        models = [Notification.model_validate_json(value) for value in pending]
        for resident in fx.TENANTS:
            assert any(
                resident in item.responder_ids
                and all(vote.resident_id != resident for vote in item.responses)
                for item in models
            )
        assert any(item.responses for item in models)

        confirmation_rows = c.execute(
            "SELECT json FROM notification WHERE kind='confirmation_request'"
        ).fetchall()
        all_votes = [Notification.model_validate_json(row[0]) for row in confirmation_rows]
        assert sum(item.status.value == "unread" for item in all_votes) >= 4
        assert (
            sum(
                item.status.value == "actioned"
                and item.responses
                and item.responses[-1].action_id == "mine"
                for item in all_votes
            )
            == 2
        )
        assert (
            sum(
                item.status.value == "actioned"
                and item.outcome(item.expires_at).verdict.value == "everyone"
                for item in all_votes
            )
            == 1
        )
        assert sum(item.status.value == "expired" for item in all_votes) == 1

        bill = c.execute(
            "SELECT * FROM billing_bill WHERE status='finalized' "
            "ORDER BY period_start DESC LIMIT 1"
        ).fetchone()
        amounts = [
            row[0]
            for row in c.execute(
                "SELECT amount_cents FROM billing_allocation WHERE bill_id=?", (bill["id"],)
            )
        ]
        assert amounts and sum(amounts) == bill["total_cents"]

        from homemind.features.billing import closing as closing_service
        from homemind.features.billing import explanation

        allocations = closing_service.allocations_of(c, UUID(bill["id"]))
        assert len(allocations) == 4
        receipts = [explanation.explain(c, bill, allocation) for allocation in allocations]
        assert all(receipt.evidence_available for receipt in receipts)
        assert any(receipt.own for receipt in receipts)
        assert any(receipt.common for receipt in receipts)
        common_kinds = {
            group.provenance.kind.value for receipt in receipts for group in receipt.common
        }
        assert {"measured", "estimated"} <= common_kinds
        assert all(
            group.provenance.origin.value == "simulated"
            for receipt in receipts
            for group in receipt.common
        )
        before = c.execute("SELECT count(*) FROM billing_consumption").fetchone()[0]
        web._seed_history(c, datetime.now(UTC))
        assert c.execute("SELECT count(*) FROM billing_consumption").fetchone()[0] == before


def test_copia_web_sem_plafond_cada_um_paga_o_seu_quarto(roots):
    web.prepare()
    with closing(sqlite3.connect(web.web_path())) as c:
        quartos = c.execute("SELECT included_wh FROM room WHERE kind = 'bedroom'").fetchall()
        assert quartos and all(wh == 0 for (wh,) in quartos)  # 0 = sem plafond solidário
    # A original (cenário oficial offline, exemplo do PDF) mantém o plafond de 30 kWh.
    with closing(sqlite3.connect(roots[0] / FILE_NAME)) as c:
        assert {
            wh for (wh,) in c.execute("SELECT included_wh FROM room WHERE kind = 'bedroom'")
        } == {30000}


def test_link_recusa_desconhecido_vazio_e_duplicado(roots):
    web.prepare()
    for user, sub in (("eva", "x"), ("ana", ""), ("ana", "a" * 300)):
        with pytest.raises(web.WebDemoError):
            web.link(user, sub)
    web.link("ana", "S1")
    with pytest.raises(web.WebDemoError):
        web.link("bruno", "S1")


def test_recusa_ficheiro_sem_marcador(roots):
    _, copy = roots
    copy.mkdir()
    with closing(sqlite3.connect(copy / web.WEB_FILE)) as c:
        c.execute("CREATE TABLE x (a)")
    for fn in (web.prepare, web.clean, lambda: web.link("ana", "S")):
        with pytest.raises(web.WebDemoError):
            fn()
    assert (copy / web.WEB_FILE).exists()


def test_clean_apaga_so_a_copia(roots):
    demo, copy = roots
    web.prepare()
    web.clean()
    assert not (copy / web.WEB_FILE).exists() and (demo / FILE_NAME).exists()
    assert fx.ANA in web.ACCOUNTS["ana"]
