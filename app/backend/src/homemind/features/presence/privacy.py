"""Porta transacional de privacidade para pistas individuais de presença (PRIV-02).

Não recolhe sensores nem escreve logs. `record_individual_cue` só grava pistas que passam o gate,
na transação SQLite do chamador; Wi-Fi permanece bloqueado até existir persistência de consentimento
por dispositivo. Nunca registar MAC/IP/SSID, padrões de presença ou identificadores.
"""

import sqlite3
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.domain_events import PresenceCueRecorded
from homemind.contracts.presence import PresenceEvent, PresenceSource, PresenceState
from homemind.core.events import append_event


def individual_cue_allowed(
    conn: sqlite3.Connection,
    cue: PresenceEvent,
    *,
    now: datetime,
    actor_resident_id: UUID | None = None,
    wifi_collection_enabled: bool = False,
) -> bool:
    """Falha fechada: fonte admitida, casa, proveniência e opt-in ATUAL por casa.

    Para uma declaração manual, a identidade vem da sessão Authentik (não do
    corpo do pedido). Wi-Fi é sempre recusado enquanto o consentimento de `PresenceDevice` não
    existir como dado persistido consultável; a flag global não lhe dá autorização.
    """
    if now.utcoffset() is None:
        raise ValueError("now exige timezone")
    if cue.source is PresenceSource.wifi:
        # PresenceDevice consent is a separate per-device choice and has no persisted
        # repository yet. A global flag or Membership.presence_opt_in cannot substitute for it.
        return False
    elif cue.source is PresenceSource.manual:
        if actor_resident_id != cue.resident_id:
            return False
    else:
        return False

    house = conn.execute(
        "SELECT timezone, source_kind FROM household WHERE id = ?",
        (str(cue.household_id),),
    ).fetchone()
    if house is None:
        return False
    if house["source_kind"] == "real" and cue.provenance.simulated:
        return False

    today = now.astimezone(ZoneInfo(house["timezone"])).date().isoformat()
    return (
        conn.execute(
            "SELECT 1 FROM membership WHERE household_id = ? AND resident_id = ?"
            " AND role = 'tenant' AND status = 'active' AND presence_opt_in = 1"
            " AND starts_on <= ? AND (ends_on IS NULL OR ends_on >= ?)",
            (str(cue.household_id), str(cue.resident_id), today, today),
        ).fetchone()
        is not None
    )


def record_individual_cue(
    conn: sqlite3.Connection,
    cue: PresenceEvent,
    *,
    now: datetime,
    actor_resident_id: UUID | None = None,
    wifi_collection_enabled: bool = False,
) -> bool:
    """Aplica o gate e persiste a pista na mesma transação SQLite.

    O produtor deve chamar esta função dentro de `Database.run`/`run_sync`. SQLite `BEGIN
    IMMEDIATE` serializa esta decisão com uma revogação concorrente da membership: ou a gravação
    ocorre antes da revogação, ou observa a revogação e não grava.
    """
    if not conn.in_transaction:
        raise RuntimeError("gravação de pista exige transação SQLite ativa")
    if not individual_cue_allowed(
        conn,
        cue,
        now=now,
        actor_resident_id=actor_resident_id,
        wifi_collection_enabled=wifi_collection_enabled,
    ):
        return False
    append_event(
        conn,
        PresenceCueRecorded(
            id=cue.id,
            ts=cue.ts,
            household_id=cue.household_id,
            provenance=cue.provenance,
            data=cue,
        ),
    )
    return True


def automatic_state_when_sensor_unavailable(
    proposed: PresenceState, *, sensor_available: bool
) -> PresenceState:
    """A ausência de observação não prova uma saída; só para inferência automática.

    Declarações manuais mantêm a sua fonte própria; não utilizar esta função
    para converter o relato do morador em falta de sensor.
    """
    return proposed if sensor_available else PresenceState.uncertain
