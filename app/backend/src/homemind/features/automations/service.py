"""Regras da casa votadas e regras individuais (SAFE-04): propor, votar, suspender e reativar.
Síncrono sobre SQLite (`db.run`); nunca executa nada nem toca num dispositivo.

Invariantes (todos testados):
- só inquilinos ativos propõem e votam (o senhorio e o operador nunca); a regra da casa exige
  UNANIMIDADE (D-39), a do contrato (`rule_approval_outcome`: todos os elegíveis a favor, um
  voto contra rejeita) sobre o grupo de elegíveis gravado à abertura da ronda, por isso não
  muda se alguém entra ou sai a meio;
- regra INDIVIDUAL (`scope=personal`, D-39): só o dono (inquilino ativo) a cria, `active` na
  hora (a criação é a confirmação humana), sem votação, sem aviso nem evento para os outros, e
  só em tomadas do quarto do próprio. É PRIVADA: só o dono a vê (os outros, o senhorio e o
  operador recebem «não encontrada»); só o dono a suspende e reativa (reativar é imediato);
- prazo fixo de 24 h; um voto fora de prazo nunca conta (filtra-se antes da função pura) e uma
  ronda sem todos os votos no prazo é rejeitada, de forma preguiçosa (na leitura e antes de votar),
  idempotente e sem relógio em segundo plano;
- cada transição é um *compare-and-set*; um voto decisivo perdido (outro decidiu primeiro)
  levanta `ConflictError` e a transação inteira volta atrás;
- aprovada: `proposed|disabled → active` com `approved_by_resident_id` = quem deu o último voto
  decisivo (`vote_decided` + `status_changed`); rejeitada: `proposed → draft` (uma reativação
  rejeitada deixa a regra `disabled`), só `vote_decided`;
- qualquer inquilino suspende (`active → disabled`, `status_changed`); reativar abre uma nova
  ronda de votos limpa (`active` só por unanimidade) e reemite `automation.proposed` (regra
  `disabled`) para avisar os moradores;
- os eventos entram no outbox na mesma transação (`append_event`, ids estáveis: repetir não
  duplica); o chamador acorda o barramento depois do COMMIT;
- `automation_log` tem uma linha por acontecimento (só a acrescentar);
- só se desliga uma tomada conhecida da casa (o contrato já recusa qualquer outra ação; a
  lâmpada não é alvo).
"""

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from homemind.contracts.agent import (
    AutomationRule,
    AutomationScope,
    AutomationSource,
    AutomationStatus,
    AutomationTrigger,
    AutomationVote,
    DeviceCapability,
    DeviceCommand,
    RuleApprovalOutcome,
    RuleVerdict,
    TriggerKind,
    rule_approval_outcome,
)
from homemind.contracts.common import (
    ContractModel,
    Origin,
    PowerW,
    Provenance,
    ShortText,
    UtcDatetime,
    ValueKind,
    new_id,
    replace,
    stable_id,
)
from homemind.contracts.domain_events import (
    AutomationProposed,
    AutomationStatusChanged,
    AutomationStatusChangedData,
    AutomationVoteDecided,
    AutomationVoteDecidedData,
    DomainEvent,
)
from homemind.core.events import append_event
from homemind.features.automations import repo

VOTE_WINDOW = timedelta(hours=24)
MAX_OPEN_PER_PROPOSER = 3  # propostas abertas por morador-proponente (como `agent_action`)

NOT_FOUND = "automation_not_found"
NOT_ELIGIBLE = "not_eligible"
INVALID_TARGET = "invalid_target"
VOTE_NOT_OPEN = "vote_not_open"
VOTE_EXPIRED = "vote_expired"
ALREADY_VOTED = "already_voted"
NOT_ACTIVE = "automation_not_active"
NOT_DISABLED = "automation_not_disabled"
VOTE_ALREADY_OPEN = "vote_already_open"
TOO_MANY_OPEN = "too_many_open"
CONFLICT = "vote_conflict"


class ConflictError(RuntimeError):
    """Outra transação decidiu primeiro: a atual volta atrás (o cliente relê e tenta de novo)."""


class AutomationTriggerIn(ContractModel):
    """Gatilho do pedido. Tipo próprio (e não `AutomationTrigger`) para o OpenAPI não duplicar o
    do contrato em pares `-Input`/`-Output`; a coerência por tipo é validada pelo contrato."""

    kind: TriggerKind
    device_id: UUID | None = None
    threshold_w: Annotated[PowerW, Field(gt=0)] | None = None
    duration_s: Annotated[int, Field(strict=True, ge=0, le=86_400)] | None = None


class AutomationProposeIn(ContractModel):
    """Corpo de `POST …/automations`. A regra nasce `manual` e `proposed` e a única ação é
    desligar a tomada `target_device_id`; o autor vem do token."""

    name: ShortText
    trigger: AutomationTriggerIn
    target_device_id: UUID
    # `personal` = regra individual: só em tomadas do quarto do próprio, ativa na hora, privada.
    scope: AutomationScope = AutomationScope.house


class AutomationStatusIn(ContractModel):
    """Corpo de `PATCH …/automations/{id}`: só se suspende (`disabled`); ativar é pela votação."""

    status: Literal[AutomationStatus.disabled]


class AutomationVoteIn(ContractModel):
    approve: bool


class AutomationPlugView(ContractModel):
    """Tomada que o servidor aceita como gatilho ou alvo de uma regra. Só id interno e nome.
    `room_id` = divisão da tomada (`None` = desconhecida); `personal_allowed` = serve numa regra
    individual DE QUEM PEDE (a tomada está no quarto dele)."""

    id: UUID
    name: Annotated[str, Field(max_length=500)]
    simulated: bool
    room_id: UUID | None = None
    personal_allowed: bool = False


class AutomationView(ContractModel):
    """Vista de uma regra para a app. Só contagens: nunca quem votou o quê."""

    id: UUID
    name: ShortText
    scope: AutomationScope
    status: AutomationStatus
    source: AutomationSource
    trigger: AutomationTrigger
    actions: list[DeviceCommand]
    device_name: Annotated[str, Field(max_length=500)]
    origin: Origin
    proposed_by_me: bool
    vote_open: bool
    vote_round: Annotated[int, Field(strict=True, ge=1)]
    vote_deadline: UtcDatetime
    votes_for: Annotated[int, Field(strict=True, ge=0)]
    votes_against: Annotated[int, Field(strict=True, ge=0)]
    eligible: Annotated[int, Field(strict=True, ge=1)]
    # votos a favor necessários: nas regras da casa, todos os elegíveis (unanimidade, D-39);
    # o nome vem da maioria absoluta (D-35) e mantém-se por compatibilidade com a app.
    majority: Annotated[int, Field(strict=True, ge=1)]
    my_vote: bool | None  # `True` = a favor; `None` = ainda não votou nesta ronda
    last_verdict: RuleVerdict | None
    message: Annotated[str, Field(max_length=400)]


@dataclass(frozen=True)
class Result:
    """`error` (código) ou a vista. `events` já estão no outbox: acordar o barramento depois do
    COMMIT (mesmo com erro: um prazo resolvido na leitura deixa eventos)."""

    view: AutomationView | None = None
    error: str | None = None
    events: tuple[DomainEvent, ...] = ()


# --- leitura -------------------------------------------------------------------------------


def _counted(votes: list[AutomationVote], deadline: datetime) -> list[AutomationVote]:
    """Votos fora de prazo nunca contam: filtra-se aqui, antes da função pura."""
    return [v for v in votes if v.at < deadline]


def _outcome(
    conn: sqlite3.Connection, row: sqlite3.Row, *, expired: bool
) -> tuple[RuleApprovalOutcome, int]:
    eligible = repo.eligible_of(row)
    deadline = datetime.fromisoformat(row["vote_deadline"])
    votes = [v for v in repo.votes_of(conn, row["id"]) if v.resident_id in eligible]
    return rule_approval_outcome(_counted(votes, deadline), eligible, expired=expired), len(
        eligible
    )


def _message(row: sqlite3.Row, out: RuleApprovalOutcome, eligible: int, status: AutomationStatus):
    tag = "SIMULADO: " if row["origin"] == Origin.simulated.value else ""
    if row["scope"] == AutomationScope.personal.value:
        if status is AutomationStatus.active:
            return f"{tag}Ativa no teu quarto. Só tu a vês e a podes suspender."
        return f"{tag}Suspensa: não executa. Só tu a podes reativar, na hora."
    if row["vote_open"]:
        return (
            f"{tag}Em votação: precisa de {out.votes_needed} de {eligible} votos a favor "
            "(todos os moradores têm de concordar) em 24 h. "
            "Nada é executado enquanto a regra não estiver ativa."
        )
    if status is AutomationStatus.active:
        return f"{tag}Ativa: aprovada por todos os moradores. Qualquer morador a pode suspender."
    if status is AutomationStatus.disabled:
        return f"{tag}Suspensa: não executa. Reativar abre uma nova votação."
    if row["last_verdict"] == RuleVerdict.rejected.value:
        return f"{tag}Rejeitada: nem todos os moradores concordaram. Nada foi executado."
    return f"{tag}Rascunho; nada foi executado."


def view_of(
    conn: sqlite3.Connection, row: sqlite3.Row, resident_id: UUID, now: datetime
) -> AutomationView:
    rule = repo.rule_of(row)
    out, eligible = _outcome(conn, row, expired=False)
    mine = {v.resident_id: v.approve for v in repo.votes_of(conn, row["id"])}.get(resident_id)
    return AutomationView(
        id=rule.id,
        name=rule.name,
        scope=rule.scope,
        status=rule.status,
        source=rule.source,
        trigger=rule.trigger,
        actions=rule.actions,
        device_name=row["device_name"],
        origin=Origin(row["origin"]),
        proposed_by_me=rule.created_by_resident_id == resident_id,
        vote_open=bool(row["vote_open"]),
        vote_round=row["vote_round"],
        vote_deadline=datetime.fromisoformat(row["vote_deadline"]),
        votes_for=out.votes_for,
        votes_against=out.votes_against,
        eligible=eligible,
        majority=out.votes_needed,
        my_vote=mine,
        last_verdict=RuleVerdict(row["last_verdict"]) if row["last_verdict"] else None,
        message=_message(row, out, eligible, rule.status),
    )


def _prov(row: sqlite3.Row) -> Provenance:
    return Provenance(origin=Origin(row["origin"]), kind=ValueKind.measured)


# --- fecho da ronda --------------------------------------------------------------------------


def _close(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    out: RuleApprovalOutcome,
    eligible: int,
    now: datetime,
    *,
    by: UUID | None,
    expired: bool,
) -> tuple[DomainEvent, ...]:
    """Aplica um veredicto decidido: CAS sobre a ronda lida, log e eventos (outbox). `by` é quem
    deu o voto decisivo (`None` = prazo)."""
    rule = repo.rule_of(row)
    old = rule.status
    approved = out.verdict is RuleVerdict.approved
    if approved:
        assert by is not None  # a unanimidade só se atinge com um voto
        updated = replace(rule, status=AutomationStatus.active, approved_by_resident_id=by)
    elif old is AutomationStatus.proposed:  # rejeitada: `proposed → draft`
        updated = replace(rule, status=AutomationStatus.draft, approved_by_resident_id=None)
    else:  # uma reativação rejeitada deixa a regra suspensa como estava
        updated = rule
    new = updated.status
    if not repo.close_vote(conn, row, rule=updated, verdict=out.verdict.value, now=now):
        raise ConflictError(CONFLICT)
    code = "expired" if expired else ("approved" if approved else "rejected_by_vote")
    repo.log(conn, row["id"], now, "decided", from_status=old, to_status=new, by=by, code=code)
    decided = AutomationVoteDecided(
        id=stable_id("automation.vote_decided", row["id"], str(row["vote_round"])),
        ts=now,
        household_id=rule.household_id,
        correlation_id=rule.id,
        provenance=_prov(row),
        data=AutomationVoteDecidedData(
            rule_id=rule.id,
            verdict=out.verdict,  # type: ignore[arg-type]  # só approved|rejected aqui
            votes_for=out.votes_for,
            votes_against=out.votes_against,
            eligible=eligible,
            expired=expired,
        ),
    )
    events: list[DomainEvent] = [decided]
    if approved:  # a rejeição `proposed → draft` fica só no `vote_decided`
        events.append(_status_event(row, rule.household_id, old, new, by, row["rev"] + 1, now))
    for e in events:
        append_event(conn, e)
    return tuple(events)


def _status_event(
    row: sqlite3.Row,
    household_id: UUID,
    old: AutomationStatus,
    new: AutomationStatus,
    by: UUID | None,
    rev: int,
    now: datetime,
) -> AutomationStatusChanged:
    return AutomationStatusChanged(
        id=stable_id("automation.status_changed", row["id"], str(rev)),
        ts=now,
        household_id=household_id,
        correlation_id=UUID(row["id"]),
        provenance=_prov(row),
        data=AutomationStatusChangedData(
            rule_id=UUID(row["id"]), from_status=old, to_status=new, resident_id=by
        ),
    )


def _resolve(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime):
    """Prazo acabado: a ronda fecha sem todos os votos (`expired=True`). Idempotente: depois de
    fechada deixa de ser devolvida por `due_rows`."""
    out, eligible = _outcome(conn, row, expired=True)
    return _close(conn, row, out, eligible, now, by=None, expired=True)


def resolve_expired(
    conn: sqlite3.Connection, household_id: UUID, now: datetime
) -> tuple[DomainEvent, ...]:
    """Resolve de forma preguiçosa todas as votações da casa fora de prazo (na leitura)."""
    events: tuple[DomainEvent, ...] = ()
    for row in repo.due_rows(conn, household_id, now):
        events += _resolve(conn, row, now)
    return events


# --- escrita ---------------------------------------------------------------------------------


def propose(
    conn: sqlite3.Connection,
    *,
    household_id: UUID,
    resident_id: UUID,
    body: AutomationProposeIn,
    plugs: Mapping[UUID, str],
    origin: Origin,
    now: datetime,
    plug_rooms: Mapping[UUID, UUID | None] | None = None,
) -> Result:
    """Grava a regra `proposed`, o log e `automation.proposed` numa transação. `plugs` são as
    tomadas conhecidas da casa (id → nome): qualquer outro alvo (lâmpada incluída) é recusado.
    Levanta `pydantic.ValidationError` se o gatilho não cumpre o contrato (ex.: sem limiar).

    O proponente vota a favor ao propor (1 voto): com a unanimidade já atingida (ex.: 1 morador)
    a regra fecha aprovada no próprio pedido, com os eventos normais. No máximo
    `MAX_OPEN_PER_PROPOSER` propostas abertas por proponente.

    `scope=personal`: regra individual (ver `_propose_personal`); `plug_rooms` (tomada → divisão)
    decide se a tomada está no quarto do dono.

    Alvo e `trigger.device_id` têm de ser tomadas conhecidas da casa (nunca de outra casa nem a
    lâmpada). Atenção: pode ser a tomada AGREGADA (a extensão, que alimenta vários aparelhos):
    desligá-la corta tudo o que lá está. A UI (onda 4) tem de o avisar a quem vota."""
    events = resolve_expired(conn, household_id, now)
    eligible = repo.active_tenants(conn, household_id, now)
    if resident_id not in eligible:
        return Result(error=NOT_ELIGIBLE, events=events)
    rule = AutomationRule(
        id=new_id(),
        household_id=household_id,
        name=body.name,
        source=AutomationSource.manual,
        trigger=AutomationTrigger(**body.trigger.model_dump()),
        actions=[
            DeviceCommand(
                target_device_id=body.target_device_id,
                capability=DeviceCapability.power,
                power=False,
            )
        ],
        status=AutomationStatus.proposed,
        created_by_resident_id=resident_id,
    )
    if body.scope is AutomationScope.personal:
        return _propose_personal(
            conn, rule, plugs=plugs, plug_rooms=plug_rooms or {}, origin=origin, now=now,
            events=events,
        )  # fmt: skip
    if any(a.target_device_id not in plugs for a in rule.actions) or (
        rule.trigger.device_id is not None and rule.trigger.device_id not in plugs
    ):
        return Result(error=INVALID_TARGET, events=events)
    if repo.count_open_by(conn, household_id, resident_id) >= MAX_OPEN_PER_PROPOSER:
        return Result(error=TOO_MANY_OPEN, events=events)
    names = ", ".join(dict.fromkeys(plugs[a.target_device_id] for a in rule.actions))
    repo.insert_rule(
        conn, rule, origin=origin.value, device_name=names, now=now,
        deadline=now + VOTE_WINDOW, eligible=eligible,
    )  # fmt: skip
    repo.log(conn, rule.id, now, "proposed", to_status=AutomationStatus.proposed, by=resident_id)
    row = repo.get_row(conn, household_id, rule.id)
    assert row is not None
    event = AutomationProposed(
        id=stable_id("automation.proposed", str(rule.id)),
        ts=now,
        household_id=household_id,
        correlation_id=rule.id,
        provenance=_prov(row),
        data=rule,
    )
    append_event(conn, event)
    ballot = AutomationVote(resident_id=resident_id, approve=True, at=now)
    repo.insert_vote(conn, rule.id, ballot)  # o proponente vota a favor
    repo.log(conn, rule.id, now, "voted", by=resident_id, approve=True)
    out, n = _outcome(conn, row, expired=False)
    events += (event,)
    if out.decided:  # todos já votaram a favor (ex.: 1 morador)
        events += _close(conn, row, out, n, now, by=resident_id, expired=False)
    fresh = repo.get_row(conn, household_id, rule.id)
    assert fresh is not None
    return Result(view_of(conn, fresh, resident_id, now), events=events)


def _propose_personal(
    conn: sqlite3.Connection,
    draft: AutomationRule,
    *,
    plugs: Mapping[UUID, str],
    plug_rooms: Mapping[UUID, UUID | None],
    origin: Origin,
    now: datetime,
    events: tuple[DomainEvent, ...],
) -> Result:
    """Regra individual: o dono (já validado como inquilino ativo) cria-a `active` na hora, sem
    votação, sem `automation.proposed` e sem qualquer aviso aos outros. Alvo e gatilho têm de ser
    tomadas conhecidas DO QUARTO do dono (a divisão vem da `membership`); com divisão
    desconhecida ou outra, `INVALID_TARGET`. Só fica registo no `automation_log`."""
    owner = draft.created_by_resident_id
    room = repo.tenant_room(conn, draft.household_id, owner, now)
    devices = [a.target_device_id for a in draft.actions]
    if draft.trigger.device_id is not None:
        devices.append(draft.trigger.device_id)
    if room is None or any(d not in plugs or plug_rooms.get(d) != room for d in devices):
        return Result(error=INVALID_TARGET, events=events)
    rule = replace(
        draft,
        status=AutomationStatus.active,
        approved_by_resident_id=owner,
        scope=AutomationScope.personal,
        owner_resident_id=owner,
        room_id=room,
    )
    names = ", ".join(dict.fromkeys(plugs[a.target_device_id] for a in rule.actions))
    repo.insert_personal(conn, rule, origin=origin.value, device_name=names, now=now)
    repo.log(
        conn, rule.id, now, "proposed", to_status=AutomationStatus.active, by=owner,
        code="personal",
    )  # fmt: skip
    row = repo.get_row(conn, rule.household_id, rule.id)
    assert row is not None
    return Result(view_of(conn, row, owner, now), events=events)


def vote(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    rule_id: UUID,
    approve: bool,
    now: datetime,
) -> Result:
    row = repo.visible_row(conn, household_id, rule_id, resident_id)
    if row is None:
        return Result(error=NOT_FOUND)
    if row["vote_open"] and datetime.fromisoformat(row["vote_deadline"]) <= now:
        return Result(error=VOTE_EXPIRED, events=_resolve(conn, row, now))  # o prazo fecha-a
    if not row["vote_open"]:
        return Result(error=VOTE_NOT_OPEN)
    if resident_id not in repo.eligible_of(row):
        return Result(error=NOT_ELIGIBLE)
    ballot = AutomationVote(resident_id=resident_id, approve=approve, at=now)
    if not repo.insert_vote(conn, rule_id, ballot):
        return Result(error=ALREADY_VOTED)
    repo.log(conn, rule_id, now, "voted", by=resident_id, approve=approve)
    out, eligible = _outcome(conn, row, expired=False)
    events: tuple[DomainEvent, ...] = ()
    if out.decided:
        events = _close(conn, row, out, eligible, now, by=resident_id, expired=False)
    fresh = repo.get_row(conn, household_id, rule_id)
    assert fresh is not None
    return Result(view_of(conn, fresh, resident_id, now), events=events)


def suspend(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, rule_id: UUID, now: datetime
) -> Result:
    """Qualquer inquilino suspende uma regra da casa `active`, na hora (sem votação: é o veto);
    uma individual só o dono a suspende (para os outros nem existe) e sem eventos."""
    events = resolve_expired(conn, household_id, now)  # não deixa prazos por fechar
    row = repo.visible_row(conn, household_id, rule_id, resident_id)
    if row is None:
        return Result(error=NOT_FOUND, events=events)
    rule = repo.rule_of(row)
    if rule.status is not AutomationStatus.active:
        return Result(error=NOT_ACTIVE, events=events)
    if not repo.suspend(conn, row, rule=replace(rule, status=AutomationStatus.disabled), now=now):
        raise ConflictError(CONFLICT)
    repo.log(
        conn, rule_id, now, "suspended", from_status=AutomationStatus.active,
        to_status=AutomationStatus.disabled, by=resident_id,
    )  # fmt: skip
    fresh = repo.get_row(conn, household_id, rule_id)
    assert fresh is not None
    if rule.scope is AutomationScope.personal:  # privada: nada sai para o barramento
        return Result(view_of(conn, fresh, resident_id, now), events=events)
    event = _status_event(
        row, household_id, AutomationStatus.active, AutomationStatus.disabled, resident_id,
        row["rev"] + 1, now,
    )  # fmt: skip
    append_event(conn, event)
    return Result(view_of(conn, fresh, resident_id, now), events=(*events, event))


def reactivate(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, rule_id: UUID, now: datetime
) -> Result:
    """Abre uma nova ronda de votos numa regra da casa `disabled`; a regra só volta a `active`
    por unanimidade. Não emite evento (o estado só muda quando a votação decide). Conta para o
    limite de `MAX_OPEN_PER_PROPOSER` votações abertas de quem reativa (como `propose`).
    Uma individual `disabled` só o dono a reativa, na hora (sem votação nem eventos)."""
    events = resolve_expired(conn, household_id, now)
    row = repo.visible_row(conn, household_id, rule_id, resident_id)
    if row is None:
        return Result(error=NOT_FOUND, events=events)
    if repo.rule_of(row).status is not AutomationStatus.disabled:
        return Result(error=NOT_DISABLED, events=events)
    if row["scope"] == AutomationScope.personal.value:
        return _reactivate_personal(conn, row, resident_id, now, events)
    if row["vote_open"]:
        return Result(error=VOTE_ALREADY_OPEN, events=events)
    eligible = repo.active_tenants(conn, household_id, now)
    if resident_id not in eligible:
        return Result(error=NOT_ELIGIBLE, events=events)
    if repo.count_open_by(conn, household_id, resident_id) >= MAX_OPEN_PER_PROPOSER:
        return Result(error=TOO_MANY_OPEN, events=events)  # reativar conta como propor
    if not repo.open_round(conn, row, now=now, deadline=now + VOTE_WINDOW, eligible=eligible):
        raise ConflictError(CONFLICT)
    repo.log(conn, rule_id, now, "reactivation_opened", by=resident_id)
    fresh = repo.get_row(conn, household_id, rule_id)
    assert fresh is not None
    # Reutiliza `automation.proposed` (regra `disabled`) para avisar os moradores; id estável por
    # regra+ronda (a proposta inicial, ronda 1, mantém o seu id).
    notice = AutomationProposed(
        id=stable_id("automation.proposed", str(rule_id), str(fresh["vote_round"])),
        ts=now,
        household_id=household_id,
        correlation_id=rule_id,
        provenance=_prov(fresh),
        data=repo.rule_of(fresh),
    )
    append_event(conn, notice)
    return Result(view_of(conn, fresh, resident_id, now), events=(*events, notice))


def _reactivate_personal(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    resident_id: UUID,
    now: datetime,
    events: tuple[DomainEvent, ...],
) -> Result:
    """O dono volta a ativar a sua regra: imediato. Só se ainda for inquilino ativo da casa."""
    rule = repo.rule_of(row)
    household_id = rule.household_id
    if resident_id not in repo.active_tenants(conn, household_id, now):
        return Result(error=NOT_ELIGIBLE, events=events)
    if not repo.reactivate_personal(
        conn, row, rule=replace(rule, status=AutomationStatus.active), now=now
    ):
        raise ConflictError(CONFLICT)
    repo.log(
        conn, rule.id, now, "decided", from_status=AutomationStatus.disabled,
        to_status=AutomationStatus.active, by=resident_id, code="personal_reactivated",
    )  # fmt: skip
    fresh = repo.get_row(conn, household_id, rule.id)
    assert fresh is not None
    return Result(view_of(conn, fresh, resident_id, now), events=events)


def get_view(
    conn: sqlite3.Connection, household_id: UUID, resident_id: UUID, rule_id: UUID, now: datetime
) -> tuple[AutomationView | None, tuple[DomainEvent, ...]]:
    events = resolve_expired(conn, household_id, now)
    row = repo.visible_row(conn, household_id, rule_id, resident_id)
    return (view_of(conn, row, resident_id, now) if row else None), events


def list_views(
    conn: sqlite3.Connection,
    household_id: UUID,
    resident_id: UUID,
    now: datetime,
    limit: int = 50,
) -> tuple[list[AutomationView], tuple[DomainEvent, ...]]:
    events = resolve_expired(conn, household_id, now)
    rows = repo.list_rows(conn, household_id, resident_id, limit)
    return [view_of(conn, r, resident_id, now) for r in rows], events
