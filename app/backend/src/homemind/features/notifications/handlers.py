"""Consumidores do barramento da feature: eventos de outros módulos -> notificações.

Síncronos, sem I/O externo, na transação do efeito (`processed_event`): correm sobre a ligação
que o barramento passa. Idempotentes por evento de origem (ids derivados) e devolvem os eventos
de seguimento (`notification.created`) para o *outbox*.

Os nomes dos consumidores são PERMANENTES: são a chave de idempotência em `processed_event`.
Renomear um faz-lhe reprocessar todo o histórico dos seus tipos.
"""

import sqlite3
from collections.abc import Callable
from datetime import datetime

from homemind.contracts import domain_events as de
from homemind.contracts.domain_events import StoredEvent
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.service import NotificationService
from homemind.features.notifications.sqlite import SqliteNotificationRepository

CONFIRMATION_CONSUMER = "notifications.confirmation_needed"
CONFIRMATION_EVENT_TYPES = ("billing.confirmation_needed",)

PRESENCE_CHECK_CONSUMER = "notifications.presence_check"
PRESENCE_CHECK_EVENT_TYPES = ("presence.confirmation_needed",)

SAFETY_ALERT_CONSUMER = "notifications.safety_alert"
SAFETY_ALERT_EVENT_TYPES = ("safety.alert_raised",)

ATTRIBUTION_CONSUMER = "notifications.attribution_changed"
ATTRIBUTION_EVENT_TYPES = ("billing.attribution_changed",)

ALLOCATION_CONSUMER = "notifications.allocation_published"
ALLOCATION_EVENT_TYPES = ("billing.allocation_published",)

BUDGET_CONSUMER = "notifications.budget_threshold"
BUDGET_EVENT_TYPES = ("alerts.threshold_crossed",)

PEAK_CONSUMER = "notifications.peak_alert"
PEAK_EVENT_TYPES = ("alerts.alert_raised",)

COLD_ROOM_CONSUMER = "notifications.cold_room"
COLD_ROOM_EVENT_TYPES = ("alerts.cold_room",)

CONTESTATION_CONSUMER = "notifications.contestation"
CONTESTATION_EVENT_TYPES = ("billing.contestation_changed",)
RULES_PROPOSAL_CONSUMER = "notifications.rules_proposal"
RULES_PROPOSAL_EVENT_TYPES = ("billing.rules_proposal_changed",)

AGENT_ACTION_CONSUMER = "notifications.agent_action"
AGENT_ACTION_EVENT_TYPES = ("agent.action_proposed",)

AUTOMATION_PROPOSAL_CONSUMER = "notifications.automation_proposal"
AUTOMATION_PROPOSAL_EVENT_TYPES = ("automation.proposed",)

AUTOMATION_DECIDED_CONSUMER = "notifications.automation_decided"
AUTOMATION_DECIDED_EVENT_TYPES = ("automation.vote_decided",)

IDENTIFICATION_CONSUMER = "notifications.appliance_identification"
IDENTIFICATION_EVENT_TYPES = ("energy.identification_needed",)

Handler = Callable[[sqlite3.Connection, StoredEvent], list[de.DomainEvent]]


def _service(conn: sqlite3.Connection, clock: Callable[[], datetime]) -> NotificationService:
    return NotificationService(
        SqliteNotificationRepository(conn), SqliteResidentDirectory(conn), clock
    )


def make_confirmation_handler(clock: Callable[[], datetime]) -> Handler:
    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.BillingConfirmationNeeded):  # nunca acontece (filtro de tipos)
            return []
        out = _service(conn, clock).on_confirmation_needed(
            ev.data,
            source_event_id=ev.id,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_presence_check_handler(clock: Callable[[], datetime]) -> Handler:
    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.PresenceConfirmationNeeded):
            return []
        out = _service(conn, clock).on_presence_check(
            ev.data,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_safety_alert_handler(clock: Callable[[], datetime]) -> Handler:
    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.SafetyAlertRaised):
            return []
        out = _service(conn, clock).on_safety_alert(
            ev.data,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_attribution_handler(clock: Callable[[], datetime]) -> Handler:
    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.BillingAttributionChanged):
            return []
        out = _service(conn, clock).on_attribution_changed(
            ev.data,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_allocation_handler(clock: Callable[[], datetime]) -> Handler:
    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.BillingAllocationPublished):
            return []
        out = _service(conn, clock).on_allocation_published(
            ev.data,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_budget_handler(clock: Callable[[], datetime]) -> Handler:
    """`alerts.threshold_crossed` (ALERT-01) -> aviso pessoal ao dono do orçamento."""

    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.AlertsThresholdCrossed):
            return []
        d = ev.data
        out = _service(conn, clock).on_budget_threshold(
            source_event_id=ev.id,
            household_id=ev.household_id,
            resident_id=d.resident_id,
            budget_id=d.budget_id,
            pct=d.pct,
            spent_cents=d.spent_cents,
            limit_cents=d.limit_cents,
            forecast_cents=d.forecast_cents,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_peak_handler(clock: Callable[[], datetime]) -> Handler:
    """`alerts.alert_raised` (ALERT-03) -> aviso da casa: `kind=peak` (pico) ou `anomaly` (gasto
    do dia fora do habitual). Os outros `kind` (aparelho esquecido, «não bate certo») ainda não
    têm produtor nem texto: ignorados."""

    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.AlertsAlertRaised):
            return []
        if ev.data.kind is de.AlertKind.anomaly:
            out = _service(conn, clock).on_anomaly_alert(
                ev.data,
                source_event_id=ev.id,
                household_id=ev.household_id,
                correlation_id=ev.correlation_id,
                provenance=ev.provenance,
            )
            return list(out.events)
        out = _service(conn, clock).on_peak_alert(
            ev.data,
            source_event_id=ev.id,
            ts=ev.ts,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_cold_room_handler(clock: Callable[[], datetime]) -> Handler:
    """`alerts.cold_room` (ALERT-06) -> aviso privado ao morador do quarto frio."""

    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.AlertsColdRoom):
            return []
        out = _service(conn, clock).on_cold_room(
            ev.data,
            source_event_id=ev.id,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_contestation_handler(clock: Callable[[], datetime]) -> Handler:
    """`billing.contestation_changed` (BILL-06) -> senhorio (aberta) ou autor (decidida)."""

    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.BillingContestationChanged):
            return []
        out = _service(conn, clock).on_contestation(
            ev.data,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_rules_proposal_handler(clock: Callable[[], datetime]) -> Handler:
    """`billing.rules_proposal_changed` (HOUSE-04) -> votar / aprovada / não aprovada."""

    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.BillingRulesProposalChanged):
            return []
        out = _service(conn, clock).on_rules_proposal(
            ev.data, correlation_id=ev.correlation_id, provenance=ev.provenance
        )
        return list(out.events)

    return handler


def make_identification_handler(clock: Callable[[], datetime]) -> Handler:
    """`energy.identification_needed` (ENERGY-04) -> «O que é este aparelho?» da casa."""

    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.EnergyIdentificationNeeded):
            return []
        out = _service(conn, clock).on_identification_needed(
            ev.data,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_agent_action_handler(clock: Callable[[], datetime]) -> Handler:
    """`agent.action_proposed` (AGENT-03) -> «Ação por confirmar» ao morador a quem se propõe."""

    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.AgentActionProposed):
            return []
        out = _service(conn, clock).on_action_proposed(
            ev.data,
            source_event_id=ev.id,
            household_id=ev.household_id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_automation_proposal_handler(clock: Callable[[], datetime]) -> Handler:
    """`automation.proposed` (SAFE-04) -> «Nova regra da casa para votar» aos inquilinos."""

    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.AutomationProposed):
            return []
        out = _service(conn, clock).on_automation_proposed(
            ev.data,
            source_event_id=ev.id,
            correlation_id=ev.correlation_id,
            provenance=ev.provenance,
        )
        return list(out.events)

    return handler


def make_automation_decided_handler(clock: Callable[[], datetime]) -> Handler:
    """`automation.vote_decided` (SAFE-04) -> fecha os avisos de votação da regra."""

    def handler(conn: sqlite3.Connection, stored: StoredEvent) -> list[de.DomainEvent]:
        ev = stored.event
        if not isinstance(ev, de.AutomationVoteDecided):
            return []
        _service(conn, clock).on_automation_decided(ev.household_id, ev.data.rule_id)
        return []

    return handler


# Todos os consumidores da feature: (nome, fábrica, tipos).
CONSUMERS: tuple[tuple[str, Callable[[Callable[[], datetime]], Handler], tuple[str, ...]], ...] = (
    (CONFIRMATION_CONSUMER, make_confirmation_handler, CONFIRMATION_EVENT_TYPES),
    (PRESENCE_CHECK_CONSUMER, make_presence_check_handler, PRESENCE_CHECK_EVENT_TYPES),
    (SAFETY_ALERT_CONSUMER, make_safety_alert_handler, SAFETY_ALERT_EVENT_TYPES),
    (ATTRIBUTION_CONSUMER, make_attribution_handler, ATTRIBUTION_EVENT_TYPES),
    (ALLOCATION_CONSUMER, make_allocation_handler, ALLOCATION_EVENT_TYPES),
    (BUDGET_CONSUMER, make_budget_handler, BUDGET_EVENT_TYPES),
    (PEAK_CONSUMER, make_peak_handler, PEAK_EVENT_TYPES),
    (COLD_ROOM_CONSUMER, make_cold_room_handler, COLD_ROOM_EVENT_TYPES),
    (CONTESTATION_CONSUMER, make_contestation_handler, CONTESTATION_EVENT_TYPES),
    (RULES_PROPOSAL_CONSUMER, make_rules_proposal_handler, RULES_PROPOSAL_EVENT_TYPES),
    (IDENTIFICATION_CONSUMER, make_identification_handler, IDENTIFICATION_EVENT_TYPES),
    (AGENT_ACTION_CONSUMER, make_agent_action_handler, AGENT_ACTION_EVENT_TYPES),
    (
        AUTOMATION_PROPOSAL_CONSUMER,
        make_automation_proposal_handler,
        AUTOMATION_PROPOSAL_EVENT_TYPES,
    ),
    (
        AUTOMATION_DECIDED_CONSUMER,
        make_automation_decided_handler,
        AUTOMATION_DECIDED_EVENT_TYPES,
    ),
)
