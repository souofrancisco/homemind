"""Consentimento por fonte de presença (PRIV-03 #51, decisão D-37). Funções síncronas sobre uma
`conn` já dentro de uma transação (a decisão e a gravação são atómicas).

Três fontes individuais com opt-in SEPARADO, desligado por omissão: Wi-Fi, aparelho a ligar e
resposta manual. A porta/câmara só conta pessoas e não entra aqui. Uma pista só se grava com o
opt-in global (`Membership.presence_opt_in`) E o da sua fonte. Desligar UMA fonte apaga só os
dados dessa fonte; o estado recalcula-se com o resto (ver `PresenceService.revoke_source`).
O registo (`presence_consent_log`) é só de acrescentar. Nada aqui toca em dados financeiros.
"""

import sqlite3
from datetime import datetime
from uuid import UUID

from homemind.contracts.presence import (
    ConsentAction,
    ConsentReason,
    ConsentSource,
    PresenceConsentLogView,
    PresenceConsentsView,
    PresenceSourceConsentView,
)
from homemind.features.presence import repo
from homemind.features.presence.consent_texts import TEXT_VERSION, TEXTS
from homemind.features.presence.retention import _delete_events

_DAILY_COLUMN = {
    ConsentSource.wifi: "cues_wifi",
    ConsentSource.appliance: "cues_appliance",
    ConsentSource.manual: "cues_manual",
}


def has_source_consent(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, source: ConsentSource
) -> bool:
    """Opt-in da fonte em vigor. Não verifica o opt-in global (ver `repo.has_presence_opt_in`)."""
    return (
        conn.execute(
            "SELECT 1 FROM presence_source_consent WHERE household_id = ? AND resident_id = ?"
            " AND source = ? AND enabled = 1",
            (str(household_id), str(resident_id), source.value),
        ).fetchone()
        is not None
    )


def list_states(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT source, enabled, updated_at FROM presence_source_consent"
        " WHERE household_id = ? AND resident_id = ?",
        (str(household_id), str(resident_id)),
    ).fetchall()


def list_log(conn: sqlite3.Connection, household_id: UUID, resident_id: UUID) -> list[sqlite3.Row]:
    """Registo do próprio, do mais antigo para o mais recente (por `id`, só de acrescentar)."""
    return conn.execute(
        "SELECT at, subject, action, text_version, reason FROM presence_consent_log"
        " WHERE household_id = ? AND resident_id = ? ORDER BY id",
        (str(household_id), str(resident_id)),
    ).fetchall()


def collection_allowed(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    source: ConsentSource,
    now: datetime,
) -> bool:
    """Gate de recolha: inquilino ativo com opt-in global E opt-in da fonte."""
    return repo.has_presence_opt_in(conn, household_id, resident_id, now) and has_source_consent(
        conn, household_id, resident_id, source
    )


def _append_log(
    conn: sqlite3.Connection,
    hid: str,
    rid: str,
    subject: str,
    action: ConsentAction,
    now: datetime,
    reason: ConsentReason,
    version: str = TEXT_VERSION,
) -> None:
    conn.execute(
        "INSERT INTO presence_consent_log (at, household_id, resident_id, subject, action,"
        " text_version, reason) VALUES (?,?,?,?,?,?,?)",
        (now.isoformat(), hid, rid, subject, action.value, version, reason.value),
    )


def grant(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    source: ConsentSource,
    now: datetime,
) -> bool:
    """Liga a fonte. `False` se já estava ligada (idempotente: nada se regista). O chamador
    verifica antes o opt-in global e a versão do texto."""
    hid, rid = str(household_id), str(resident_id)
    if has_source_consent(conn, household_id, resident_id, source):
        return False
    conn.execute(
        "INSERT INTO presence_source_consent (household_id, resident_id, source, enabled,"
        " text_version, updated_at) VALUES (?,?,?,1,?,?) ON CONFLICT (household_id, resident_id,"
        " source) DO UPDATE SET enabled = 1, text_version = excluded.text_version,"
        " updated_at = excluded.updated_at",
        (hid, rid, source.value, TEXT_VERSION, now.isoformat()),
    )
    _append_log(conn, hid, rid, source.value, ConsentAction.granted, now, ConsentReason.resident)
    return True


def revoke_flag(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    source: ConsentSource,
    now: datetime,
    reason: ConsentReason,
) -> bool:
    """Desliga a fonte e regista. `False` se já estava desligada (idempotente)."""
    hid, rid = str(household_id), str(resident_id)
    row = conn.execute(
        "SELECT text_version FROM presence_source_consent WHERE household_id = ?"
        " AND resident_id = ? AND source = ? AND enabled = 1",
        (hid, rid, source.value),
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE presence_source_consent SET enabled = 0, updated_at = ? WHERE household_id = ?"
        " AND resident_id = ? AND source = ?",
        (now.isoformat(), hid, rid, source.value),
    )
    _append_log(
        conn, hid, rid, source.value, ConsentAction.revoked, now, reason, row["text_version"]
    )
    return True


def revoke_all_flags(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    now: datetime,
    reason: ConsentReason,
) -> None:
    """Desliga todas as fontes (opt-in global revogado ou saída da casa)."""
    for source in ConsentSource:
        revoke_flag(conn, household_id, resident_id, source, now, reason)


def erase_source_data(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    source: ConsentSource,
    now: datetime,
) -> tuple[int, int]:
    """Apaga SÓ os dados desta fonte do próprio morador nesta casa: as pistas da fonte e as
    mudanças de estado que a citam (derivadas); em `wifi` também os telemóveis registados; em
    `manual` os pedidos «estás em casa?»; e zera a contagem da fonte nos agregados diários
    (as durações agregadas não se decompõem por fonte; não têm horários). Não toca em dados
    financeiros, de colegas, de outras casas nem nas outras fontes. Devolve (pistas, outros)."""
    hid, rid = str(household_id), str(resident_id)
    cues = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM domain_event WHERE household_id = ? AND type = 'presence.cue_recorded'"
            " AND json_extract(payload_json, '$.resident_id') = ?"
            " AND json_extract(payload_json, '$.source') = ?",
            (hid, rid, source.value),
        )
    ]
    derived = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM domain_event WHERE household_id = ? AND type = 'presence.changed'"
            " AND json_extract(payload_json, '$.resident_id') = ?"
            " AND EXISTS (SELECT 1 FROM json_each(payload_json, '$.sources') WHERE value = ?)",
            (hid, rid, source.value),
        )
    ]
    other = len(derived)
    if source is ConsentSource.manual:
        asks = [
            r[0]
            for r in conn.execute(
                "SELECT id FROM domain_event WHERE household_id = ?"
                " AND type = 'presence.confirmation_needed'"
                " AND json_extract(payload_json, '$.resident_id') = ?",
                (hid, rid),
            )
        ]
        derived += asks
        other += (
            len(asks)
            + conn.execute(
                "DELETE FROM presence_confirmation WHERE household_id = ? AND resident_id = ?",
                (hid, rid),
            ).rowcount
        )
    if source is ConsentSource.wifi:
        for dev in repo.list_devices(conn, household_id, resident_id):
            if dev.wifi_opt_in:
                repo.revoke_device(conn, household_id, resident_id, dev.id, now)
                other += 1
    _delete_events(conn, cues + derived)
    col = _DAILY_COLUMN[source]
    conn.execute(  # noqa: S608 - coluna de uma lista fixa
        f"UPDATE presence_daily SET {col} = 0 WHERE household_id = ? AND resident_id = ?",
        (hid, rid),
    )
    return len(cues), other


def build_view(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, now: datetime
) -> PresenceConsentsView:
    """O que o morador vê: o opt-in global, cada fonte com o seu texto e o registo do próprio."""
    states = {r["source"]: r for r in list_states(conn, household_id, resident_id)}
    sources = []
    for source in ConsentSource:
        row = states.get(source.value)
        sources.append(
            PresenceSourceConsentView(
                source=source,
                enabled=bool(row and row["enabled"]),
                updated_at=row["updated_at"] if row else None,
                **TEXTS[source],
            )
        )
    return PresenceConsentsView(
        presence_opt_in=repo.has_presence_opt_in(conn, household_id, resident_id, now),
        text_version=TEXT_VERSION,
        sources=sources,
        history=[
            PresenceConsentLogView(**dict(r)) for r in list_log(conn, household_id, resident_id)
        ],
    )
