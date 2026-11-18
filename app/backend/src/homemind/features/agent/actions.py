"""Ações propostas (AGENT-03): propor, confirmar, rejeitar e registar o desfecho. Síncrono sobre
a conexão SQLite (`db.run`); sem I/O externo, por isso nunca toca num dispositivo.

Invariantes (todos testados):
- só uma pessoa confirma e só a destinatária (`proposed_for_resident_id`); nada se executa sem
  `confirm`; cada transição é um *compare-and-set* (duas confirmações nunca executam duas vezes);
- `confirm` faz COMMIT de `proposed → confirmed` ANTES de qualquer execução (que corre fora da
  transação, em `actions_router`); o desfecho entra depois, `confirmed → executed`;
- os limites espelham os de `connectors/write_policy.py` (MCP-04) e aplicam-se por dispositivo;
  um limite violado grava um resultado `blocked` sem chamar o executor;
- o estado `expired` é derivado na leitura (`expires_at`), sem escrita;
- `executed_at` (coluna usada pelos limites) é SEMPRE a hora do servidor; a hora que o executor
  declara fica só em `execution_json`, para que um relógio errado ou hostil não anule o cooldown;
- uma ação `confirmed` há mais de `stale_s` (prazo do executor + margem) ficou interrompida
  (cancelamento, crash): `sweep_stale` resolve-a como `executed/uncertain/interrupted`, de forma
  preguiçosa (na leitura e antes dos limites). Nunca se repete e bloqueia o dispositivo;
- `agent_action_log` tem uma linha por transição (só a acrescentar) e a proposta publica
  `agent.action_proposed` no outbox, na mesma transação.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field

from homemind.contracts.agent import (
    ActionConfirmation,
    ActionExecutionResult,
    ActionStatus,
    DeviceCapability,
    DeviceCommand,
    ExecutionStatus,
    ProposedAction,
)
from homemind.contracts.common import (
    ContractModel,
    Origin,
    Provenance,
    ValueKind,
    new_id,
    replace,
    stable_id,
)
from homemind.contracts.devices import DeviceKind
from homemind.contracts.domain_events import AgentActionProposed
from homemind.core.events import append_event
from homemind.features.agent.devices import ActuatorDevice

log = logging.getLogger(__name__)

NOT_FOUND = "action_not_found"
NOT_PENDING = "action_not_pending"
EXPIRED = "action_expired"

INTERRUPTED = "interrupted"
STALE_MARGIN_S = 30.0  # folga sobre o prazo do executor antes de dar uma confirmação por perdida
_COUNTED = (ExecutionStatus.confirmed, ExecutionStatus.failed, ExecutionStatus.uncertain)


@dataclass(frozen=True)
class ActionLimits:
    ttl_s: float
    max_open: int
    cooldown_s: float
    max_per_hour: int
    lockout_s: float
    timeout_s: float = 15.0

    @property
    def stale_s(self) -> float:
        """Uma ação `confirmed` há mais do que isto já não está em execução."""
        return self.timeout_s + STALE_MARGIN_S

    @classmethod
    def from_settings(cls, s) -> Self:
        return cls(
            ttl_s=s.agent_action_ttl_s,
            max_open=s.agent_action_max_open,
            cooldown_s=s.agent_action_cooldown_s,
            max_per_hour=s.agent_action_max_per_hour,
            lockout_s=s.agent_action_lockout_s,
            timeout_s=s.agent_action_timeout_s,
        )


class AgentActionView(ContractModel):
    """Vista de uma ação proposta para a app. PROPOSTA: mover para `contracts/agent.py`
    (revisão #73). Sem ids externos de dispositivos; `message` é honesta por estado."""

    action: ProposedAction
    execution: ActionExecutionResult | None = None
    origin: Origin
    device_name: Annotated[str, Field(max_length=120)]
    message: Annotated[str, Field(max_length=400)]


@dataclass(frozen=True)
class ConfirmOutcome:
    """`error` (código) ou a vista. `pending` só existe se o executor ainda tem de ser chamado."""

    view: AgentActionView | None = None
    error: str | None = None
    pending: tuple[ProposedAction, ActionConfirmation] | None = None


# --- texto -------------------------------------------------------------------------------------

_BLOCKED = {
    "executor_unavailable": "Não há forma de executar ações nesta casa; nada foi executado.",
    "cooldown": "Bloqueada por segurança: houve outra ação neste dispositivo há muito pouco "
    "tempo. Nada foi executado.",
    "hourly_limit": "Bloqueada por segurança: limite de ações por hora neste dispositivo. "
    "Nada foi executado.",
    "uncertain_lockout": "Bloqueada: a última ação neste dispositivo teve resultado incerto. "
    "Confirma o estado do dispositivo e tenta mais tarde. Nada foi executado.",
    "not_confirmed": "Bloqueada: sem confirmação. Nada foi executado.",
}


def describe(
    status: ActionStatus, execution: ActionExecutionResult | None, origin: Origin, name: str
) -> str:
    """Mensagem PT por estado. Sucesso só com releitura; incerteza nunca se repete; SIMULADO
    sempre etiquetado."""
    sim = origin is Origin.simulated
    tag = "SIMULADO: " if sim else ""
    if execution is not None:
        match execution.status:
            case ExecutionStatus.confirmed:  # o contrato garante `readback_confirmed`
                if sim:
                    return (
                        f"SIMULADO: o estado simulado de «{name}» foi relido e confirma a ação; "
                        "nenhum aparelho real foi tocado."
                    )
                return f"Confirmado por releitura do estado de «{name}»."
            case ExecutionStatus.failed:
                return f"{tag}Falhou; nada foi aplicado a «{name}». Podes propor de novo."
            case ExecutionStatus.uncertain:
                return (
                    f"{tag}Resultado incerto em «{name}»: pode ter sido aplicado ou não. "
                    "Não repito a ação; verifica o estado do dispositivo."
                )
            case ExecutionStatus.blocked:
                return tag + _BLOCKED.get(execution.code or "", "Bloqueada; nada foi executado.")
    match status:
        case ActionStatus.proposed:
            return f"{tag}Proposta por confirmar sobre «{name}»; nada foi executado."
        case ActionStatus.rejected:
            return f"{tag}Rejeitada; nada foi executado."
        case ActionStatus.expired:
            return f"{tag}A proposta expirou; nada foi executado."
        case _:  # confirmed (executed sem resultado não existe: CHECK na tabela)
            return f"{tag}Confirmada; a execução ainda não terminou, sem resultado por agora."


# --- leitura -----------------------------------------------------------------------------------


def _utc(now: datetime) -> datetime:
    return now.astimezone(UTC)


def _view(row: sqlite3.Row, now: datetime) -> AgentActionView:
    action = ProposedAction.model_validate_json(row["json"])
    status = ActionStatus(row["status"])
    if status is ActionStatus.proposed and _utc(now) >= action.expires_at:
        status = ActionStatus.expired  # derivado; não se escreve
    execution = (
        ActionExecutionResult.model_validate_json(row["execution_json"])
        if row["execution_json"]
        else None
    )
    origin = Origin(row["origin"])
    return AgentActionView(
        action=replace(action, status=status),
        execution=execution,
        origin=origin,
        device_name=row["device_name"],
        message=describe(status, execution, origin, row["device_name"]),
    )


def _own(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, action_id: UUID
) -> sqlite3.Row | None:
    """Só a ação desta casa e deste residente: a de outro é como se não existisse."""
    return conn.execute(
        "SELECT * FROM agent_action WHERE id = ? AND household_id = ?"
        " AND proposed_for_resident_id = ?",
        (str(action_id), str(household_id), str(resident_id)),
    ).fetchone()


def get_view(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    action_id: UUID,
    now: datetime,
) -> AgentActionView | None:
    row = _own(conn, household_id, resident_id, action_id)
    return _view(row, now) if row else None


def list_views(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    now: datetime,
    status: ActionStatus | None = None,
    limit: int = 50,
) -> list[AgentActionView]:
    """O filtro vê o estado derivado (`expired`) e vai para o SQL, tal como o LIMIT. As datas são
    sempre gravadas por `_utc(...).isoformat()`, por isso a comparação de texto é cronológica."""
    now_s = _utc(now).isoformat()
    where, args = "", []
    if status is ActionStatus.proposed:
        where, args = " AND status = 'proposed' AND expires_at > ?", [now_s]
    elif status is ActionStatus.expired:
        where, args = (
            " AND (status = 'expired' OR (status = 'proposed' AND expires_at <= ?))",
            [now_s],
        )
    elif status is not None:
        where, args = " AND status = ?", [status.value]
    rows = conn.execute(
        "SELECT * FROM agent_action WHERE household_id = ? AND proposed_for_resident_id = ?"
        + where
        + " ORDER BY proposed_at DESC, rowid DESC LIMIT ?",
        (str(household_id), str(resident_id), *args, limit),
    ).fetchall()
    return [_view(r, now) for r in rows]


# --- escrita -----------------------------------------------------------------------------------


def _log(
    conn: sqlite3.Connection,
    action_id: UUID,
    at: datetime,
    from_status: ActionStatus | None,
    to_status: ActionStatus,
    by: UUID | None,
    code: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO agent_action_log (action_id, at, from_status, to_status, by_resident_id, code)"
        " VALUES (?,?,?,?,?,?)",
        (
            str(action_id),
            _utc(at).isoformat(),
            from_status.value if from_status else None,
            to_status.value,
            str(by) if by else None,
            code,
        ),
    )


def propose(
    conn: sqlite3.Connection,
    *,
    household_id: UUID,
    resident_id: UUID,
    device: ActuatorDevice,
    command: DeviceCommand,
    rationale: str,
    origin: Origin,
    now: datetime,
    limits: ActionLimits,
    source: str = "chat",
    action_id: UUID | None = None,
) -> tuple[AgentActionView, AgentActionProposed] | None:
    """Grava a proposta, o log e `agent.action_proposed` numa transação; devolve a vista e o
    evento (para acordar o barramento depois do COMMIT). `None` se o residente já tem propostas
    abertas a mais. O agente nunca propõe ligar uma tomada. `action_id` (omissão: novo) deixa um
    produtor automático usar um id derivado, para que reprocessar o mesmo evento não duplique;
    quem o passa verifica antes se a ação já existe (`exists`)."""
    if device.kind is DeviceKind.plug and (
        command.capability is not DeviceCapability.power or command.power is not False
    ):
        raise ValueError("plug_turn_on_not_allowed")
    now = _utc(now)
    open_now = [
        r
        for r in conn.execute(
            "SELECT expires_at FROM agent_action WHERE household_id = ?"
            " AND proposed_for_resident_id = ? AND status = 'proposed'",
            (str(household_id), str(resident_id)),
        )
        if datetime.fromisoformat(r["expires_at"]) > now
    ]
    if len(open_now) >= limits.max_open:
        return None
    action = ProposedAction(
        id=action_id or new_id(),
        household_id=household_id,
        proposed_for_resident_id=resident_id,
        command=command,
        rationale=rationale,
        proposed_at=now,
        expires_at=now + timedelta(seconds=limits.ttl_s),
    )
    conn.execute(
        "INSERT INTO agent_action (id, household_id, proposed_for_resident_id, target_device_id,"
        " device_name, capability, status, origin, source, proposed_at, expires_at, json,"
        " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(action.id), str(household_id), str(resident_id), str(device.id), device.name,
            command.capability.value, ActionStatus.proposed.value, origin.value, source,
            now.isoformat(), action.expires_at.isoformat(), action.model_dump_json(),
            now.isoformat(),
        ),
    )  # fmt: skip
    _log(conn, action.id, now, None, ActionStatus.proposed, resident_id)
    event = AgentActionProposed(
        id=stable_id("agent.action_proposed", str(action.id)),
        ts=now,
        household_id=household_id,
        correlation_id=action.id,
        provenance=Provenance(origin=origin, kind=ValueKind.measured),
        data=action,
    )
    append_event(conn, event)
    view = get_view(conn, household_id, resident_id, action.id, now)
    assert view is not None
    return view, event


def exists(conn: sqlite3.Connection, action_id: UUID) -> bool:
    return (
        conn.execute("SELECT 1 FROM agent_action WHERE id = ?", (str(action_id),)).fetchone()
        is not None
    )


def system_reject(
    conn: sqlite3.Connection, household_id: UUID, action_id: UUID, now: datetime, code: str
) -> bool:
    """O sistema retira uma proposta que perdeu o sentido (ex.: o alerta que a originou foi
    resolvido): `proposed → rejected` (CAS), com linha em `agent_action_log` sem residente e o
    `code`. Só uma proposta ainda por confirmar e dentro do prazo; uma já confirmada, decidida ou
    expirada fica como está. `False` se nada mudou. Nunca executa nada."""
    now = _utc(now)
    cur = conn.execute(
        "UPDATE agent_action SET status = 'rejected', updated_at = ?"
        " WHERE id = ? AND household_id = ? AND status = 'proposed' AND expires_at > ?",
        (now.isoformat(), str(action_id), str(household_id), now.isoformat()),
    )
    if cur.rowcount != 1:
        return False
    _log(conn, action_id, now, ActionStatus.proposed, ActionStatus.rejected, None, code)
    return True


def _limit_code(
    conn: sqlite3.Connection,
    household_id: UUID,
    device_id: str,
    exclude: UUID,
    now: datetime,
    limits: ActionLimits,
) -> str | None:
    """Mesma lógica de `RuleWritePolicy.check`: bloqueio após incerto, cooldown, limite horário.
    Contam as tentativas (confirmadas, falhadas, incertas) e as ações já confirmadas ainda sem
    desfecho (em curso); as bloqueadas não contam."""
    sweep_stale(conn, household_id, now, limits.stale_s)  # interrompidas → incertas
    attempts: list[tuple[datetime, bool]] = []  # (instante, incerta?)
    rows = conn.execute(
        "SELECT status, execution_status, executed_at, updated_at FROM agent_action"
        " WHERE household_id = ? AND target_device_id = ? AND id != ?"
        " AND (status = 'confirmed' OR (status = 'executed' AND execution_status IN (?,?,?)))",
        (str(household_id), device_id, str(exclude), *(s.value for s in _COUNTED)),
    )
    for r in rows:
        at = datetime.fromisoformat(r["executed_at"] or r["updated_at"])
        attempts.append((at, r["execution_status"] == ExecutionStatus.uncertain.value))
    attempts = sorted(a for a in attempts if now - a[0] <= timedelta(hours=1))
    if attempts:
        last_at, last_uncertain = attempts[-1]
        if last_uncertain and (now - last_at).total_seconds() < limits.lockout_s:
            return "uncertain_lockout"
        if (now - last_at).total_seconds() < limits.cooldown_s:
            return "cooldown"
    if len(attempts) >= limits.max_per_hour:
        return "hourly_limit"
    return None


def _store_result(
    conn: sqlite3.Connection, action_id: UUID, result: ActionExecutionResult, now: datetime
) -> bool:
    """CAS `confirmed → executed`. `False` se já não estava `confirmed` (nada se grava). A coluna
    `executed_at` leva a hora do SERVIDOR (`now`); a do executor fica só em `execution_json`."""
    cur = conn.execute(
        "UPDATE agent_action SET status = 'executed', execution_json = ?, execution_status = ?,"
        " executed_at = ?, updated_at = ? WHERE id = ? AND status = 'confirmed'",
        (
            result.model_dump_json(),
            result.status.value,
            _utc(now).isoformat(),
            _utc(now).isoformat(),
            str(action_id),
        ),
    )
    if cur.rowcount != 1:
        return False
    _log(
        conn, action_id, now, ActionStatus.confirmed, ActionStatus.executed, None,
        result.code or result.status.value,
    )  # fmt: skip
    return True


def sweep_stale(conn: sqlite3.Connection, household_id: UUID, now: datetime, stale_s: float) -> int:
    """Resolve as ações `confirmed` há mais de `stale_s` (execução interrompida: cancelamento ou
    crash entre a confirmação e o desfecho) como `executed/uncertain/interrupted`. Pode ter sido
    aplicado, por isso nunca se repete e o dispositivo fica bloqueado (`uncertain_lockout`)."""
    now = _utc(now)
    cutoff = (now - timedelta(seconds=stale_s)).isoformat()
    rows = conn.execute(
        "SELECT id FROM agent_action WHERE household_id = ? AND status = 'confirmed'"
        " AND updated_at < ?",
        (str(household_id), cutoff),
    ).fetchall()
    done = 0
    for r in rows:
        action_id = UUID(r["id"])
        result = ActionExecutionResult(
            action_id=action_id, status=ExecutionStatus.uncertain, executed_at=now,
            code=INTERRUPTED,
        )  # fmt: skip
        if _store_result(conn, action_id, result, now):
            log.warning("Ação %s ficou confirmada sem desfecho; resolvida como incerta", action_id)
            done += 1
    return done


def confirm(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    action_id: UUID,
    now: datetime,
    limits: ActionLimits,
) -> ConfirmOutcome:
    """`proposed → confirmed` (CAS, com a confirmação humana gravada). Se um limite impede, grava
    `blocked` na mesma transação e não há nada a executar. Não levanta: um erro de negócio
    voltaria atrás da transação."""
    now = _utc(now)
    row = _own(conn, household_id, resident_id, action_id)
    if row is None:
        return ConfirmOutcome(error=NOT_FOUND)
    action = ProposedAction.model_validate_json(row["json"])
    if row["status"] == ActionStatus.expired.value or (
        row["status"] == ActionStatus.proposed.value and now >= action.expires_at
    ):
        return ConfirmOutcome(error=EXPIRED)
    confirmation = ActionConfirmation(
        action_id=action_id, resident_id=resident_id, accepted=True, at=now
    )
    cur = conn.execute(
        "UPDATE agent_action SET status = 'confirmed', confirmation_json = ?, updated_at = ?"
        " WHERE id = ? AND status = 'proposed'",
        (confirmation.model_dump_json(), now.isoformat(), str(action_id)),
    )
    if cur.rowcount != 1:  # já confirmada, rejeitada ou executada
        return ConfirmOutcome(error=NOT_PENDING)
    _log(conn, action_id, now, ActionStatus.proposed, ActionStatus.confirmed, resident_id)
    code = _limit_code(conn, household_id, row["target_device_id"], action_id, now, limits)
    if code is not None:
        blocked = ActionExecutionResult(
            action_id=action_id, status=ExecutionStatus.blocked, executed_at=now, code=code
        )
        _store_result(conn, action_id, blocked, now)
        return ConfirmOutcome(view=get_view(conn, household_id, resident_id, action_id, now))
    confirmed = replace(action, status=ActionStatus.confirmed)
    return ConfirmOutcome(
        view=get_view(conn, household_id, resident_id, action_id, now),
        pending=(confirmed, confirmation),
    )


def record_execution(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    action_id: UUID,
    result: ActionExecutionResult,
    now: datetime,
) -> AgentActionView | None:
    """Grava o desfecho (`confirmed → executed`). `None` se a ação já não estava `confirmed`."""
    if not _store_result(conn, action_id, result, now):
        return None
    return get_view(conn, household_id, resident_id, action_id, now)


def reject(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    action_id: UUID,
    now: datetime,
) -> tuple[AgentActionView | None, str | None]:
    now = _utc(now)
    row = _own(conn, household_id, resident_id, action_id)
    if row is None:
        return None, NOT_FOUND
    action = ProposedAction.model_validate_json(row["json"])
    if row["status"] == ActionStatus.expired.value or (
        row["status"] == ActionStatus.proposed.value and now >= action.expires_at
    ):
        return None, EXPIRED
    cur = conn.execute(
        "UPDATE agent_action SET status = 'rejected', updated_at = ?"
        " WHERE id = ? AND status = 'proposed'",
        (now.isoformat(), str(action_id)),
    )
    if cur.rowcount != 1:
        return None, NOT_PENDING
    _log(conn, action_id, now, ActionStatus.proposed, ActionStatus.rejected, resident_id)
    return get_view(conn, household_id, resident_id, action_id, now), None
