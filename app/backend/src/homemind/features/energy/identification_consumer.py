"""Consumidor da aprendizagem por confirmação (ENERGY-04). Transacional, sem rede nem hardware.

- `energy.consumption_closed` sem aparelho (nem candidatos) e que o catálogo também não explica
  (`assign_appliance` da ENERGY-01) entra num grupo (`identification.py`); à 3.ª ocorrência em
  7 dias sai **um** `energy.identification_needed` por grupo.
- `notification.responded` com `ref.type=appliance_identification`: a primeira resposta válida
  fecha o pedido. «É meu» cria um aparelho pessoal de quem respondeu, «É da casa» um comum; a
  assinatura nasce das sessões do grupo (amostras `confirmation`). «Ignorar» pausa o grupo 7 dias.

Estado em tabelas da `0401` na transação do barramento (sobrevive a reinícios); ids derivados do
evento de origem (`stable_id`), por isso repetir um evento não repete efeitos. Os tempos vêm dos
eventos (nunca do relógio do processo). Não lê nem altera leituras, consumos ou eventos.
"""

import sqlite3
from datetime import datetime
from statistics import fmean
from uuid import UUID

from homemind.contracts.appliance_catalog import ApplianceCatalog
from homemind.contracts.common import stable_id
from homemind.contracts.devices import ApplianceOwnership, ApplianceScope, SignaturePattern
from homemind.contracts.domain_events import (
    DomainEvent,
    EnergyConsumptionClosed,
    EnergyIdentificationNeeded,
    NotificationResponded,
    StoredEvent,
)
from homemind.contracts.energy import (
    ApplianceIdentificationRequest,
    ConsumptionStatus,
    IdentificationChoice,
    approx_power_w,
)
from homemind.contracts.notification import RefType
from homemind.core.events import Handler
from homemind.features.energy import identification as rules
from homemind.features.energy.learning import SignatureSample, assign_appliance
from homemind.features.energy.learning_consumer import (
    NewSample,
    household_zone,
    sample_of,
    session_observation,
    stamp,
    store_signature,
)

INPUT_TYPES = ["energy.consumption_closed", "notification.responded"]


def _at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _groups(conn: sqlite3.Connection, household_id: UUID) -> list[rules.GroupSummary]:
    rows = conn.execute(
        "SELECT g.id,avg(s.power_w) AS power_w,avg(s.duration_s) AS duration_s"
        " FROM energy_identification_group g JOIN energy_identification_session s"
        " ON s.group_id=g.id WHERE g.household_id=? GROUP BY g.id ORDER BY g.id",
        (str(household_id),),
    ).fetchall()
    return [rules.GroupSummary(UUID(r["id"]), r["power_w"], r["duration_s"]) for r in rows]


def group_sessions(conn: sqlite3.Connection, group_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM energy_identification_session WHERE group_id=?"
        " ORDER BY started_at,consumption_id",
        (group_id,),
    ).fetchall()


def _on_closed(
    conn: sqlite3.Connection, catalog: ApplianceCatalog, event: EnergyConsumptionClosed
) -> list[DomainEvent]:
    session = event.data
    if (
        session.status is not ConsumptionStatus.closed
        or session.match.appliance_id is not None
        or session.match.candidates  # ambíguo entre aparelhos conhecidos: não é desconhecido
        or session.peak_w <= 50
    ):
        return []
    house = event.household_id
    if conn.execute(
        "SELECT 1 FROM energy_identification_session WHERE consumption_id=?", (str(session.id),)
    ).fetchone():
        return []
    zone = household_zone(conn, house)
    obs = session_observation(conn, house, session)
    if zone is None or obs is None:
        return []
    # A ENERGY-01 já o atribui (tomada associada ou potência registada única): não perguntar.
    if assign_appliance(obs, catalog.appliances_for_household(conn, house, session.started_at)):
        return []
    sample = sample_of(obs, session.started_at.astimezone(zone).hour)
    group_id = rules.choose_group(sample.power_w, sample.duration_s, _groups(conn, house))
    if group_id is None:
        group_id = stable_id("energy.identification_group", str(event.id))
        conn.execute(
            "INSERT INTO energy_identification_group(id,household_id,status,created_at)"
            " VALUES (?,?,'open',?)",
            (str(group_id), str(house), stamp(event.ts)),
        )
    conn.execute(
        "INSERT INTO energy_identification_session(consumption_id,source_event_id,group_id,"
        "household_id,device_id,started_at,power_w,duration_s,pattern,hour_local)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(session.id),
            str(event.id),
            str(group_id),
            str(house),
            str(session.device_id),
            stamp(session.started_at),
            sample.power_w,
            sample.duration_s,
            sample.pattern.value,
            sample.hour_local,
        ),
    )
    group = conn.execute(
        "SELECT * FROM energy_identification_group WHERE id=?", (str(group_id),)
    ).fetchone()
    status, snoozed_until = group["status"], _at(group["snoozed_until"])
    if status == "asked":
        pending = conn.execute(
            "SELECT id,expires_at FROM energy_identification_request"
            " WHERE group_id=? AND status='pending'",
            (str(group_id),),
        ).fetchone()
        expires_at = _at(pending["expires_at"]) if pending else None
        if expires_at is not None and expires_at > session.ended_at:
            return []  # já perguntado e ainda à espera: sem nova pergunta (sem spam)
        # Caducou sem resposta: conta como «Ignorar» desde que caducou.
        if pending is not None:
            conn.execute(
                "UPDATE energy_identification_request SET status='expired' WHERE id=?",
                (pending["id"],),
            )
        snoozed_until = expires_at + rules.SNOOZE if expires_at else None
        status = "open"
        conn.execute(
            "UPDATE energy_identification_group SET status='open',snoozed_until=? WHERE id=?",
            (stamp(snoozed_until) if snoozed_until else None, str(group_id)),
        )
    rows = group_sessions(conn, str(group_id))
    at = session.started_at
    count = rules.occurrences((_at(r["started_at"]) for r in rows), at)
    if not rules.should_ask(status=status, snoozed_until=snoozed_until, count=count, at=at):
        return []
    recent = [r for r in rows if at - rules.WINDOW < _at(r["started_at"]) <= at]
    request = ApplianceIdentificationRequest(
        id=stable_id("energy.identification", str(event.id)),
        device_id=session.device_id,
        power_w=fmean(r["power_w"] for r in rows),
        duration_s=max(1, round(fmean(r["duration_s"] for r in rows))),
        hour_local=rules.usual_hour(r["hour_local"] for r in recent),
        occurrences=count,
        expires_at=session.ended_at + rules.REQUEST_TTL,
        provenance=event.provenance,
    )
    conn.execute(
        "INSERT INTO energy_identification_request(id,group_id,household_id,status,power_w,"
        "hour_local,occurrences,created_at,expires_at) VALUES (?,?,?,'pending',?,?,?,?,?)",
        (
            str(request.id),
            str(group_id),
            str(house),
            request.power_w,
            request.hour_local,
            request.occurrences,
            stamp(event.ts),
            stamp(request.expires_at),
        ),
    )
    conn.execute(
        "UPDATE energy_identification_group SET status='asked' WHERE id=?", (str(group_id),)
    )
    return [
        EnergyIdentificationNeeded(
            id=stable_id("energy.identification_needed", str(request.id)),
            ts=event.ts,
            household_id=house,
            correlation_id=event.correlation_id,
            provenance=event.provenance,
            data=request,
        )
    ]


def _on_answer(
    conn: sqlite3.Connection, catalog: ApplianceCatalog, event: NotificationResponded
) -> list[DomainEvent]:
    ref, response = event.data.ref, event.data.response
    if ref is None or ref.type is not RefType.appliance_identification:
        return []
    try:
        choice = IdentificationChoice(response.action_id)
    except ValueError:
        return []
    request = conn.execute(
        "SELECT * FROM energy_identification_request WHERE id=? AND household_id=?",
        (str(ref.id), str(event.household_id)),
    ).fetchone()
    if (
        request is None
        or request["status"] != "pending"
        or response.responded_at >= _at(request["expires_at"])
    ):
        return []  # outra resposta já fechou, caducou, ou não é um pedido nosso
    answered_at = stamp(response.responded_at)
    if choice is IdentificationChoice.ignore:
        conn.execute(
            "UPDATE energy_identification_request SET status='answered',choice='ignore',"
            "answered_at=? WHERE id=? AND status='pending'",
            (answered_at, request["id"]),
        )
        conn.execute(
            "UPDATE energy_identification_group SET status='open',snoozed_until=? WHERE id=?",
            (stamp(response.responded_at + rules.SNOOZE), request["group_id"]),
        )
        return []
    sessions = group_sessions(conn, request["group_id"])
    mine = choice is IdentificationChoice.mine
    try:
        appliance_id = catalog.create_learned_appliance(
            conn,
            event.household_id,
            name=rules.appliance_name(approx_power_w(request["power_w"])),
            typical_watts=fmean(s["power_w"] for s in sessions),
            ownership=ApplianceOwnership(
                scope=ApplianceScope.personal if mine else ApplianceScope.common,
                owner_resident_id=response.resident_id if mine else None,
            ),
            registered_by_resident_id=response.resident_id,
            at=response.responded_at,
        )
    except Exception as exc:
        # CatalogError (HOUSE-03) sem importar a feature: quem respondeu já não é inquilino.
        if getattr(exc, "status", None) in (403, 422):
            return []
        raise
    conn.execute(
        "UPDATE energy_identification_request SET status='answered',choice=?,appliance_id=?,"
        "answered_at=? WHERE id=? AND status='pending'",
        (choice.value, str(appliance_id), answered_at, request["id"]),
    )
    samples = [
        NewSample(
            source_event_id=UUID(s["source_event_id"]),
            sample=SignatureSample(
                s["power_w"], s["duration_s"], SignaturePattern(s["pattern"]), s["hour_local"]
            ),
            origin_kind="confirmation",
            created_at=response.responded_at,
            identification_id=UUID(request["id"]),
        )
        for s in sessions
    ]
    store_signature(
        conn, catalog, event.household_id, appliance_id, samples, updated_at=response.responded_at
    )
    conn.execute(
        "UPDATE energy_identification_group SET status='resolved',appliance_id=?,"
        "snoozed_until=NULL WHERE id=?",
        (str(appliance_id), request["group_id"]),
    )
    return []


def make_identification_consumer(catalog: ApplianceCatalog) -> Handler:
    def handle(conn: sqlite3.Connection, stored: StoredEvent) -> list[DomainEvent]:
        event = stored.event
        if isinstance(event, EnergyConsumptionClosed):
            return _on_closed(conn, catalog, event)
        if isinstance(event, NotificationResponded):
            return _on_answer(conn, catalog, event)
        return []

    return handle
