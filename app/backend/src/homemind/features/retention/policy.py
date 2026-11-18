"""Retenção por categoria (PRIV-04). Fonte única dos prazos; `docs/modules/billing.md` explica-os.

Categorias do registo de eventos (`domain_event`) e das tabelas derivadas:

- `financial`: tudo o que explica uma cobrança (fatura, consumos, votos D-32, atribuições,
  parcelas, contestações, avisos de orçamento). **Nunca se apaga automaticamente**: a base de
  dados recusa-o (trigger `domain_event_no_delete`, migração 0004). O prazo legal de
  conservação contabilística está por fixar com o DPO (P-08) e não se inventa aqui.
- `telemetry`: leituras em bruto de energia e sensores. Apagadas ao fim de
  `RETENTION_TELEMETRY_DAYS` (omissão 90). Nada do que explica um recibo depende delas: o
  consumo (`energy.consumption_*`) e a atribuição guardam o necessário.
- `daily_aggregates`: agregados diários dos alertas (gasto por tomada comum, noites frias).
  Mesmo prazo da telemetria; os detetores só olham para os últimos 7 dias.
- `presence`: pistas e passagens. Política própria na PRIV-03 (#51); aqui não se toca.
- `operational`: tudo o resto (notificações, automações, agente). Sem expurgo por agora
  (PLANEADO); o histórico da conversa já tem retenção curta própria (P-25).

Anonimização: PLANEADA. Exige base legal por categoria (P-08); até lá não se reescreve
nenhum registo financeiro (seria alterar evidência).
"""

from enum import StrEnum


class Category(StrEnum):
    financial = "financial"
    telemetry = "telemetry"
    daily_aggregates = "daily_aggregates"
    presence = "presence"
    operational = "operational"


# Tipos de evento por categoria. Um tipo novo sem categoria falha no teste (ver testes).
EVENT_CATEGORY: dict[str, Category] = {
    # telemetria em bruto (a migração 0004 só deixa apagar estes)
    "energy.reading_recorded": Category.telemetry,
    "sensor.reading_recorded": Category.telemetry,
    # cadeia financeira: medição -> hipótese -> confirmação -> atribuição -> parcela
    "energy.step_detected": Category.financial,
    "energy.consumption_detected": Category.financial,
    "energy.consumption_closed": Category.financial,
    "energy.identification_needed": Category.financial,
    "billing.confirmation_needed": Category.financial,
    "notification.responded": Category.financial,
    "billing.attribution_changed": Category.financial,
    "billing.bill_created": Category.financial,
    "billing.bill_finalized": Category.financial,
    "billing.allocation_published": Category.financial,
    "billing.contestation_changed": Category.financial,
    "alerts.threshold_crossed": Category.financial,
    # presença (PRIV-03 #51)
    "presence.cue_recorded": Category.presence,
    "presence.door_crossed": Category.presence,
    "presence.changed": Category.presence,
    "presence.occupancy_changed": Category.presence,
    "presence.confirmation_needed": Category.presence,
    # operacional
    "notification.created": Category.operational,
    "alerts.alert_raised": Category.operational,
    "alerts.cold_room": Category.operational,
    "safety.alert_raised": Category.operational,
    "agent.action_proposed": Category.operational,
    "automation.proposed": Category.operational,
    "automation.executed": Category.operational,
}

PURGEABLE_EVENT_TYPES = tuple(
    sorted(t for t, c in EVENT_CATEGORY.items() if c is Category.telemetry)
)

# Tabelas de agregados diários: (tabela, coluna com a data local ISO).
DAILY_AGGREGATE_TABLES = (("alerts_device_day", "day"), ("alerts_room_night", "night"))
