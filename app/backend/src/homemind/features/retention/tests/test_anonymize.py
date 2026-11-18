"""PRIV-04: anonimização de ex-moradores. Desligada por omissão; nunca toca em quem ainda mora
numa casa nem nos valores financeiros."""

from datetime import UTC, datetime

import pytest

from homemind.contracts import fixtures as fx
from homemind.core.config import Settings
from homemind.features.retention.anonymize import ANONYMOUS_EMAIL, anonymize

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
BRUNO, ANA = str(fx.BRUNO), str(fx.ANA)


def test_desligada_por_omissao_e_minimo_30_dias():
    assert Settings().retention_anonymize_after_days == 0
    assert Settings(retention_anonymize_after_days=30).retention_anonymize_after_days == 30
    with pytest.raises(ValueError, match="30"):
        Settings(retention_anonymize_after_days=7)


def _saiu(app, ends_on="2026-09-30"):
    """O Bruno saiu de todas as casas em `ends_on` e deixou dados pessoais e financeiros."""

    def work(conn):
        conn.execute(
            "UPDATE membership SET status = 'ended', ends_on = ? WHERE resident_id = ?",
            (ends_on, BRUNO),
        )
        conn.execute("UPDATE resident SET auth_subject = 'sub-bruno' WHERE id = ?", (BRUNO,))
        m = conn.execute(
            "SELECT id FROM membership WHERE resident_id = ? LIMIT 1", (BRUNO,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO membership_invitation (id, membership_id, token_sha256, target_email,"
            " created_by_membership_id, created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
            ("inv-b", m, "a" * 64, "bruno@example.pt", m, "2026-01-01", "2026-01-08"),
        )
        for rid in (BRUNO, ANA):
            conn.execute(
                "INSERT INTO agent_message VALUES (?,?,?,'user','quanto gastei?',?)",
                (f"msg-{rid}", str(fx.HOUSEHOLD), rid, NOW.isoformat()),
            )
            conn.execute(
                "INSERT INTO notification (id, household_id, scope, recipient_resident_id, kind,"
                " status, created_at, origin, json, updated_at)"
                " VALUES (?,?,'personal',?,'info','unread',?,'simulated','{}',?)",
                (f"n-{rid}", str(fx.HOUSEHOLD), rid, NOW.isoformat(), NOW.isoformat()),
            )
            conn.execute(
                "INSERT INTO notification_read VALUES (?,?,?)", (f"n-{rid}", rid, NOW.isoformat())
            )
        conn.execute(
            "INSERT INTO billing_budget (id, household_id, kind, resident_id, period,"
            " limit_cents, thresholds, updated_at)"
            " VALUES ('orc-b',?,'personal',?,'2026-09',3000,'[50,80,100]',?)",
            (str(fx.HOUSEHOLD), BRUNO, NOW.isoformat()),
        )

    app.state.db.run_sync(work)


def _q(app, sql, *args):
    return app.state.db.run_sync(lambda c: c.execute(sql, args).fetchall())


def test_ex_morador_anonimizado_e_financeiro_intacto(app):
    _saiu(app)
    assert anonymize(app.state.db.run_sync, NOW, 0) == 0  # desligada: nada
    # o Bruno (saiu a 30/09) e o Fred da casa B (saiu a 01/10, nas fixtures)
    assert anonymize(app.state.db.run_sync, NOW, 30) == 2
    [r] = _q(app, "SELECT * FROM resident WHERE id = ?", BRUNO)
    assert r["display_name"] == f"Ex-morador {BRUNO[:4]}" and r["auth_subject"] is None
    [inv] = _q(app, "SELECT target_email FROM membership_invitation WHERE id = 'inv-b'")
    assert inv["target_email"] == ANONYMOUS_EMAIL
    for table, col in (
        ("agent_message", "resident_id"),
        ("notification", "recipient_resident_id"),
        ("notification_read", "resident_id"),
    ):
        assert _q(app, f"SELECT 1 FROM {table} WHERE {col} = ?", BRUNO) == []
        assert len(_q(app, f"SELECT 1 FROM {table} WHERE {col} = ?", ANA)) == 1  # a Ana fica
    # valores e contratos ficam ligados ao mesmo id (evidência financeira)
    assert len(_q(app, "SELECT 1 FROM billing_budget WHERE resident_id = ?", BRUNO)) == 1
    assert len(_q(app, "SELECT 1 FROM membership WHERE resident_id = ?", BRUNO)) == 2
    [ana] = _q(app, "SELECT display_name FROM resident WHERE id = ?", ANA)
    assert not ana["display_name"].startswith("Ex-morador")
    assert anonymize(app.state.db.run_sync, NOW, 30) == 0  # uma vez só


def test_saida_recente_ou_contrato_aberto_nao_anonimiza(app):
    _saiu(app, ends_on="2026-11-01")  # há 17 dias
    anonymize(app.state.db.run_sync, NOW, 30)  # só o Fred (saiu a 01/10)
    assert _q(app, "SELECT 1 FROM retention_anonymized_resident WHERE resident_id = ?", BRUNO) == []
    app.state.db.run_sync(
        lambda c: c.execute(
            "UPDATE membership SET status = 'active', ends_on = NULL"
            " WHERE resident_id = ? AND household_id = ?",
            (BRUNO, str(fx.HOUSEHOLD)),
        )
    )
    anonymize(app.state.db.run_sync, datetime(2027, 6, 1, tzinfo=UTC), 30)
    # ainda mora na casa demo: nunca é anonimizado, por mais antigo que seja o outro contrato
    assert _q(app, "SELECT 1 FROM retention_anonymized_resident WHERE resident_id = ?", BRUNO) == []
