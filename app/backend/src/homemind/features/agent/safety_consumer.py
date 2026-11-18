"""AGENT-03b: um alerta de janela aberta com aquecimento vira uma PROPOSTA a confirmar.

Consumidor do barramento (`agent.safety_suggestion`, nome PERMANENTE: é a chave de idempotência em
`processed_event`) de `safety.alert_raised`. Para um alerta ativo `window_open_heating` com
`suggested_command` («desligar a tomada») e quarto, grava uma proposta (`source="safety"`) a cada
inquilino ativo que a pode confirmar. Quando o alerta é resolvido, retira as propostas ainda por
confirmar (rejeitadas pelo sistema).

Invariantes:
- NUNCA executa nada nem chama o executor: só propõe; quem executa é `POST …/confirm`, depois de
  uma confirmação humana. O handler é síncrono sobre a ligação da transação do barramento;
- só propõe num dispositivo que o diretório da casa expõe como atuador e que seja uma tomada. A
  casa demo usa os dispositivos SIMULADOS; uma casa real só o diretório registado pela P1 em
  `app.state` (sem ele não há propostas) e nunca um alerta ou dispositivo simulado;
- idempotente: o id da proposta deriva de (alerta, residente), por isso reprocessar o evento não
  duplica; o alerta além da validade (`agent_action_ttl_s`) é ignorado;
- destinatários: os inquilinos ativos do quarto (quarto) ou todos os inquilinos ativos (zona
  comum). O senhorio e o operador nunca recebem propostas.
"""

import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from homemind.contracts import domain_events as de
from homemind.contracts.common import Origin, stable_id
from homemind.contracts.devices import DeviceKind
from homemind.contracts.household import RoomKind
from homemind.contracts.safety import SafetyAlert, SafetyAlertKind, SafetyAlertStatus
from homemind.core.events import Handler
from homemind.features.agent import actions
from homemind.features.agent.actions import ActionLimits
from homemind.features.agent.config import get_agent_settings
from homemind.features.agent.devices import select_directory

log = logging.getLogger(__name__)

SAFETY_CONSUMER = "agent.safety_suggestion"
SAFETY_EVENT_TYPES = ("safety.alert_raised",)
SOURCE = "safety"
ALERT_RESOLVED = "alert_resolved"
RATIONALE = "Janela aberta com o aquecimento ligado. Queres desligar a tomada do aquecedor?"


def action_id_for(alert_id: UUID, resident_id: UUID) -> UUID:
    """Id estável da proposta de um alerta a um residente (idempotência e resolução)."""
    return stable_id("agent.safety", str(alert_id), str(resident_id))


def _today(conn: sqlite3.Connection, household_id: UUID, at: datetime) -> str | None:
    row = conn.execute(
        "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
    ).fetchone()
    return at.astimezone(ZoneInfo(row["timezone"])).date().isoformat() if row else None


def _recipients(
    conn: sqlite3.Connection, household_id: UUID, room_id: UUID, now: datetime
) -> list[UUID]:
    """Inquilinos ativos hoje (no fuso da casa): os do quarto, ou todos se for zona comum.
    DUPLICAÇÃO CONSCIENTE de `notifications/directory.py` (uma feature não importa outra)."""
    today = _today(conn, household_id, now)
    room = conn.execute(
        "SELECT kind FROM room WHERE household_id = ? AND id = ?",
        (str(household_id), str(room_id)),
    ).fetchone()
    if today is None or room is None:
        return []
    sql = (
        "SELECT resident_id FROM membership WHERE household_id = ? AND role = 'tenant'"
        " AND status = 'active' AND starts_on <= ? AND (ends_on IS NULL OR ends_on >= ?)"
    )
    args: list[str] = [str(household_id), today, today]
    if RoomKind(room["kind"]) is RoomKind.bedroom:
        sql += " AND room_id = ?"
        args.append(str(room_id))
    rows = conn.execute(sql + " ORDER BY resident_id", args).fetchall()
    return list(dict.fromkeys(UUID(r["resident_id"]) for r in rows))


def _propose(
    conn: sqlite3.Connection,
    app: FastAPI,
    alert: SafetyAlert,
    origin: Origin,
    source_kind: str,
    now: datetime,
) -> list[de.DomainEvent]:
    command = alert.suggested_command
    if (
        command is None
        or alert.room_id is None
        or alert.kind is not SafetyAlertKind.window_open_heating
    ):
        return []  # fumo nunca sugere cortes; sem comando ou quarto não há a quem propor
    limits = ActionLimits.from_settings(get_agent_settings())
    if (now - alert.started_at).total_seconds() > limits.ttl_s:
        return []  # alerta antigo (reprocessamento tardio): a janela já pode estar fechada
    if source_kind != "demo" and alert.provenance.simulated:
        return []  # uma casa real nunca recebe propostas de um alerta simulado
    devices = select_directory(app.state, alert.household_id, source_kind).actuators(
        alert.household_id
    )
    if source_kind != "demo":  # uma casa real nunca comanda dispositivos simulados
        devices = [d for d in devices if not d.simulated]
    device = next((d for d in devices if d.id == command.target_device_id), None)
    if device is None or device.kind is not DeviceKind.plug:
        log.info("safety: sem tomada comandável no diretório; sem proposta")
        return []
    events: list[de.DomainEvent] = []
    for resident_id in _recipients(conn, alert.household_id, alert.room_id, now):
        action_id = action_id_for(alert.id, resident_id)
        if actions.exists(conn, action_id):
            continue
        made = actions.propose(
            conn,
            household_id=alert.household_id,
            resident_id=resident_id,
            device=device,
            command=command,
            rationale=RATIONALE,
            origin=origin,
            now=now,
            limits=limits,
            source=SOURCE,
            action_id=action_id,
        )
        if made is not None:  # `None`: o residente já tem propostas por confirmar a mais
            events.append(made[1])
    return events


def _withdraw(conn: sqlite3.Connection, alert: SafetyAlert, now: datetime) -> None:
    """Alerta resolvido: as propostas ainda por confirmar deixam de fazer sentido. Os ids são
    derivados, por isso cobre qualquer residente que tenha tido membership na casa."""
    rows = conn.execute(
        "SELECT DISTINCT resident_id FROM membership WHERE household_id = ?",
        (str(alert.household_id),),
    ).fetchall()
    for r in rows:
        actions.system_reject(
            conn,
            alert.household_id,
            action_id_for(alert.id, UUID(r["resident_id"])),
            now,
            ALERT_RESOLVED,
        )


def make_handler(app: FastAPI, clock: Callable[[], datetime]) -> Handler:
    """Lê `app.state` em tempo de evento (a ordem de arranque dos módulos não importa)."""

    def handler(conn: sqlite3.Connection, stored: de.StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.SafetyAlertRaised):
            return []
        alert, now = ev.data, clock()
        if alert.status is SafetyAlertStatus.resolved:
            _withdraw(conn, alert, now)
            return []
        if alert.kind is not SafetyAlertKind.window_open_heating:
            return []
        row = conn.execute(
            "SELECT source_kind FROM household WHERE id = ?", (str(alert.household_id),)
        ).fetchone()
        if row is None:
            return []
        source_kind = row["source_kind"]
        origin = Origin.simulated if source_kind == "demo" else Origin.real
        return _propose(conn, app, alert, origin, source_kind, now)

    return handler
