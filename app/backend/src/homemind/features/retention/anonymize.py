"""Anonimização de ex-moradores (PRIV-04). DESLIGADA por omissão
(`RETENTION_ANONYMIZE_AFTER_DAYS=0`) até a equipa/DPO fixar o prazo (P-08).

Quem: um residente sem nenhum contrato aberto (`invited`/`active`) e cujo último contrato acabou
há mais de `days` dias. Uma pessoa ainda ligada a alguma casa nunca é anonimizada.

O que muda (tudo na mesma transação, uma vez por pessoa):
- `resident.display_name` → «Ex-morador XXXX» (4 caracteres do id, só para distinguir na casa);
- `resident.auth_subject` → `NULL`: a conta deixa de estar ligada; se a pessoa voltar com um
  convite novo, é um residente novo (o convite cria sempre um residente reservado);
- email dos convites dessa pessoa → `anonimizado`;
- conversa com o assistente, notificações pessoais, leituras de notificações e preferências:
  apagadas (dados pessoais sem valor contabilístico).

O que fica (evidência financeira): o id do residente em faturas, parcelas, atribuições, votos,
contestações (incluindo o motivo escrito), propostas de regra e no registo de eventos. O
registo de eventos é imutável: o texto de notificações antigas lá guardado não se reescreve
(limitação conhecida, ver `docs/modules/billing.md`). Presença: PRIV-03 (#51).
"""

import sqlite3
from datetime import datetime, timedelta

ANONYMOUS_EMAIL = "anonimizado"


def candidates(conn: sqlite3.Connection, now: datetime, days: int) -> list[str]:
    cutoff = (now - timedelta(days=days)).date().isoformat()
    rows = conn.execute(
        "SELECT r.id FROM resident r"
        " WHERE EXISTS (SELECT 1 FROM membership m WHERE m.resident_id = r.id)"
        " AND NOT EXISTS (SELECT 1 FROM membership m WHERE m.resident_id = r.id"
        "   AND (m.status IN ('invited', 'active') OR m.ends_on IS NULL OR m.ends_on >= ?))"
        " AND NOT EXISTS (SELECT 1 FROM retention_anonymized_resident a"
        "   WHERE a.resident_id = r.id)"
        " ORDER BY r.id",
        (cutoff,),
    ).fetchall()
    return [r["id"] for r in rows]


def anonymize_resident(conn: sqlite3.Connection, resident_id: str, now: datetime) -> None:
    conn.execute(
        "UPDATE resident SET display_name = ?, auth_subject = NULL WHERE id = ?",
        (f"Ex-morador {resident_id[:4]}", resident_id),
    )
    conn.execute(
        "UPDATE membership_invitation SET target_email = ? WHERE membership_id IN"
        " (SELECT id FROM membership WHERE resident_id = ?)",
        (ANONYMOUS_EMAIL, resident_id),
    )
    conn.execute("DELETE FROM agent_message WHERE resident_id = ?", (resident_id,))
    conn.execute(
        "DELETE FROM notification_read WHERE resident_id = ? OR notification_id IN"
        " (SELECT id FROM notification WHERE recipient_resident_id = ?)",
        (resident_id, resident_id),
    )
    conn.execute("DELETE FROM notification WHERE recipient_resident_id = ?", (resident_id,))
    conn.execute("DELETE FROM notification_preferences WHERE resident_id = ?", (resident_id,))
    conn.execute(
        "INSERT INTO retention_anonymized_resident (resident_id, anonymized_at) VALUES (?, ?)",
        (resident_id, now.isoformat()),
    )


def anonymize(run, now: datetime, days: int) -> int:
    """Anonimiza todos os elegíveis, um por transação. `days == 0`: desligado."""
    if days <= 0:
        return 0
    done = 0
    for rid in run(lambda conn: candidates(conn, now, days)):

        def one(conn, rid=rid) -> bool:
            # Reconfirma na mesma transação: entretanto pode ter recebido um convite novo.
            if rid not in candidates(conn, now, days):
                return False
            anonymize_resident(conn, rid, now)
            return True

        done += run(one)
    return done
