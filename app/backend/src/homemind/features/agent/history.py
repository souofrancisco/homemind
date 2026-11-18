"""Histórico da conversa com o assistente (#111): gravar a troca e lê-la de volta ao próprio.

Síncrono sobre a conexão SQLite (`db.run`). Dados pessoais: uma linha é sempre de UM residente
numa casa e só esse residente a lê. A retenção é curta e aplica-se ao gravar: ficam no máximo
`keep` mensagens e nenhuma com mais de `days` dias (P-25). O histórico serve só para a app o
mostrar; NUNCA é passado ao assistente nem a um LLM (P-06).
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import UUID

from homemind.contracts.agent import AgentMessage, MessageRole
from homemind.contracts.common import new_id


def _utc(now: datetime) -> datetime:
    return now.astimezone(UTC)


def record_exchange(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    user_text: str,
    reply_text: str,
    now: datetime,
    keep: int,
    days: int,
) -> None:
    """Grava a pergunta e a resposta numa transação e corta o que excede a retenção."""
    now = _utc(now)
    house, resident = str(household_id), str(resident_id)
    # A resposta fica 1 µs depois da pergunta: a ordem cronológica é estável mesmo com o mesmo
    # relógio nas duas.
    rows = (
        (MessageRole.user, user_text, now),
        (MessageRole.assistant, reply_text, now + timedelta(microseconds=1)),
    )
    conn.executemany(
        "INSERT INTO agent_message (id, household_id, resident_id, role, text, created_at)"
        " VALUES (?,?,?,?,?,?)",
        [(str(new_id()), house, resident, r.value, t, at.isoformat()) for r, t, at in rows],
    )
    conn.execute(
        "DELETE FROM agent_message WHERE household_id = ? AND resident_id = ? AND created_at < ?",
        (house, resident, (now - timedelta(days=days)).isoformat()),
    )
    conn.execute(
        "DELETE FROM agent_message WHERE household_id = ? AND resident_id = ? AND rowid NOT IN ("
        " SELECT rowid FROM agent_message WHERE household_id = ? AND resident_id = ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?)",
        (house, resident, house, resident, keep),
    )


def list_messages(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, limit: int
) -> list[AgentMessage]:
    """As últimas `limit` mensagens do residente, da mais antiga para a mais recente."""
    rows = conn.execute(
        "SELECT id, household_id, role, text, created_at FROM agent_message"
        " WHERE household_id = ? AND resident_id = ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (str(household_id), str(resident_id), limit),
    ).fetchall()
    return [
        AgentMessage(
            id=UUID(r["id"]),
            household_id=UUID(r["household_id"]),
            role=MessageRole(r["role"]),
            text=r["text"],
            ts=datetime.fromisoformat(r["created_at"]),
        )
        for r in reversed(rows)
    ]
