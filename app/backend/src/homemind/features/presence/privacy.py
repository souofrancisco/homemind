"""Porta de privacidade para pistas individuais de presença (PRIV-02).

Esta função NÃO é um coletor, nem publica eventos. PRES-03 deve chamá-la na
MESMA transação SQLite em que persistir uma pista, incluindo após revogação.
Nada é logado aqui: nem MAC/IP/SSID, nem padrões de presença ou identificadores.
"""

import sqlite3
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts.presence import PresenceEvent, PresenceSource, PresenceState


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
    corpo do pedido). Para Wi-Fi, além do opt-in é necessária ativação global
    deliberada e um coletor autenticado, ainda NÃO implementado.
    """
    if now.utcoffset() is None:
        raise ValueError("now exige timezone")
    if cue.source is PresenceSource.wifi:
        if not wifi_collection_enabled:
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


def automatic_state_when_sensor_unavailable(
    proposed: PresenceState, *, sensor_available: bool
) -> PresenceState:
    """A ausência de observação não prova uma saída; só para inferência automática.

    Declarações manuais mantêm a sua fonte própria; não utilizar esta função
    para converter o relato do morador em falta de sensor.
    """
    return proposed if sensor_available else PresenceState.uncertain
