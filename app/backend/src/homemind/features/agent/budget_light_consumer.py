"""ALERT-06: o orçamento a 80 % / 100 % vira uma PROPOSTA de pôr a lâmpada âmbar / vermelha.

Consumidor do barramento (`agent.budget_light`, nome PERMANENTE: é a chave de idempotência em
`processed_event`) de `alerts.threshold_crossed` (billing, ALERT-01). A cor vem do contrato
(`contracts.billing.budget_light`, a mesma da página Orçamento); abaixo de 80 % não se propõe nada.

Invariantes (o mesmo caminho seguro do AGENT-03b, `safety_consumer.py`):
- NUNCA executa: só propõe ao próprio morador. Quem executa é `POST …/confirm`, depois de uma
  confirmação humana; uma casa real só com o executor da P1 (flag + grant + releitura, MCP-04).
  Sem executor fica `blocked`, e sucesso físico só existe com releitura;
- privacidade: o orçamento é pessoal. Prefere-se uma lâmpada no quarto do morador; sem ela, uma
  lâmpada de zona comum, com o aviso de que a cor fica à vista de quem lá estiver (é o morador
  quem decide mostrá-la). Nunca a lâmpada do quarto de outra pessoa nem uma de divisão
  desconhecida. Senhorio e operador nunca recebem propostas;
- uma casa real nunca recebe propostas de um evento simulado nem comanda dispositivos simulados;
- idempotente: o id da proposta deriva do evento, por isso reprocessar não duplica. Um novo
  limiar retira a proposta anterior ainda por confirmar (âmbar → vermelho); um evento além da
  validade (`agent_action_ttl_s`) é ignorado.
"""

import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI

from homemind.contracts import domain_events as de
from homemind.contracts.agent import DeviceCapability, DeviceCommand, RgbColor
from homemind.contracts.billing import BudgetLight, budget_light
from homemind.contracts.common import Origin, stable_id
from homemind.contracts.devices import DeviceKind
from homemind.core.events import Handler
from homemind.features.agent import actions
from homemind.features.agent.actions import ActionLimits
from homemind.features.agent.config import get_agent_settings
from homemind.features.agent.devices import ActuatorDevice, select_directory
from homemind.features.agent.safety_consumer import _today

log = logging.getLogger(__name__)

BUDGET_LIGHT_CONSUMER = "agent.budget_light"
BUDGET_LIGHT_EVENT_TYPES = ("alerts.threshold_crossed",)
SOURCE = "budget"
SUPERSEDED = "superseded"
_COLOR_PT = {BudgetLight.amber: "âmbar", BudgetLight.red: "vermelho"}


def action_id_for(event_id: UUID, resident_id: UUID) -> UUID:
    return stable_id("agent.budget_light", str(event_id), str(resident_id))


def _own_room(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, now: datetime
) -> UUID | None | bool:
    """O quarto do inquilino ativo hoje (fuso da casa); `False` se não for inquilino ativo."""
    today = _today(conn, household_id, now)
    row = conn.execute(
        "SELECT room_id FROM membership WHERE household_id = ? AND resident_id = ?"
        " AND role = 'tenant' AND status = 'active' AND starts_on <= ?"
        " AND (ends_on IS NULL OR ends_on >= ?)",
        (str(household_id), str(resident_id), today, today),
    ).fetchone()
    if today is None or row is None:
        return False
    return UUID(row["room_id"]) if row["room_id"] else None


def _common_rooms(conn: sqlite3.Connection, household_id: UUID) -> set[UUID]:
    rows = conn.execute(
        "SELECT id FROM room WHERE household_id = ? AND kind = 'common'", (str(household_id),)
    ).fetchall()
    return {UUID(r["id"]) for r in rows}


def choose_bulb(
    bulbs: list[ActuatorDevice], own_room: UUID | None, common: set[UUID]
) -> tuple[ActuatorDevice, bool] | None:
    """Puro: (lâmpada, à vista de todos?) ou `None`. Quarto do próprio primeiro; depois uma zona
    comum; nunca outro quarto nem divisão desconhecida. Empates pelo nome (determinístico)."""
    bulbs = sorted((b for b in bulbs if b.kind is DeviceKind.bulb), key=lambda b: b.name)
    mine = [b for b in bulbs if own_room is not None and b.room_id == own_room]
    if mine:
        return mine[0], False
    shared = [b for b in bulbs if b.room_id in common]
    return (shared[0], True) if shared else None


def rationale(pct: int, color: str, device: str, shared: bool) -> str:
    text = f"Já gastaste {pct} % do teu orçamento. Queres pôr a «{device}» em {color}?"
    if shared:
        text += " Fica à vista de quem estiver nessa divisão."
    return text


def _withdraw_previous(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, keep: UUID, now: datetime
) -> None:
    rows = conn.execute(
        "SELECT id FROM agent_action WHERE household_id = ? AND proposed_for_resident_id = ?"
        " AND source = ? AND status = 'proposed' AND id != ?",
        (str(household_id), str(resident_id), SOURCE, str(keep)),
    ).fetchall()
    for r in rows:
        actions.system_reject(conn, household_id, UUID(r["id"]), now, SUPERSEDED)


def make_handler(app: FastAPI, clock: Callable[[], datetime]) -> Handler:
    """Lê `app.state` em tempo de evento (a ordem de arranque dos módulos não importa)."""

    def handler(conn: sqlite3.Connection, stored: de.StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.AlertsThresholdCrossed):
            return []
        cue, now = budget_light(ev.data.pct), clock()
        if cue is None or cue.light not in _COLOR_PT:
            return []  # verde: não há nada a mostrar
        limits = ActionLimits.from_settings(get_agent_settings())
        if (now - ev.ts).total_seconds() > limits.ttl_s:
            return []  # reprocessamento tardio: o gasto já pode ser outro
        row = conn.execute(
            "SELECT source_kind FROM household WHERE id = ?", (str(ev.household_id),)
        ).fetchone()
        if row is None:
            return []
        source_kind = row["source_kind"]
        if source_kind != "demo" and ev.provenance.simulated:
            return []
        resident_id = ev.data.resident_id
        own_room = _own_room(conn, ev.household_id, resident_id, now)
        if own_room is False:
            return []  # já não é inquilino ativo (ou nunca foi)
        devices = select_directory(app.state, ev.household_id, source_kind).actuators(
            ev.household_id
        )
        if source_kind != "demo":
            devices = [d for d in devices if not d.simulated]
        chosen = choose_bulb(devices, own_room, _common_rooms(conn, ev.household_id))
        if chosen is None:
            log.info("budget_light: sem lâmpada adequada no diretório; sem proposta")
            return []
        device, shared = chosen
        action_id = action_id_for(ev.id, resident_id)
        if actions.exists(conn, action_id):
            return []
        _withdraw_previous(conn, ev.household_id, resident_id, action_id, now)
        r, g, b = cue.rgb
        made = actions.propose(
            conn,
            household_id=ev.household_id,
            resident_id=resident_id,
            device=device,
            command=DeviceCommand(
                target_device_id=device.id,
                capability=DeviceCapability.color_rgb,
                color_rgb=RgbColor(r=r, g=g, b=b),
            ),
            rationale=rationale(ev.data.pct, _COLOR_PT[cue.light], device.name, shared),
            origin=Origin.simulated if source_kind == "demo" else Origin.real,
            now=now,
            limits=limits,
            source=SOURCE,
            action_id=action_id,
        )
        return [made[1]] if made is not None else []

    return handler
