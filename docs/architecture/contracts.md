# Contratos propostos

**PLANEADO — propostas sujeitas a implementação e a acordo da equipa.** Não existem ainda nos modelos Pydantic nem no OpenAPI. A API que existe hoje está em [api-implementada.md](api-implementada.md). Entidades e estados: [data-model.md](data-model.md).

## Como se acordam e mudam

1. Estes contratos têm de ser **aceites pelas cinco pessoas antes de cada uma implementar** o seu módulo (ver «Definição de pronto dos contratos» em [development/roadmap.md](../development/roadmap.md)).
2. Ao implementar: modelos em `app/backend/src/homemind/contracts/` (um ficheiro por domínio: `provenance.py`, `household.py`, `energy.py`, `presence.py`, `billing.py`, `notification.py`, `domain_events.py`), OpenAPI gerado, `make contracts`, e **este documento atualizado no mesmo PR**.
3. O frontend usa só os tipos gerados; nunca redefine tipos da API.
4. Contratos mudam por acordo; mudança de campo sem acordo é bloqueada em revisão.

## 1. Contratos internos (Python)

Esboços; os nomes e as validações finais são decididos na implementação.

```python
# contracts/provenance.py
class Provenance(StrEnum): measured; estimated; inferred; simulated

# contracts/energy.py
class EnergyReading(BaseModel):          # P1 → energy, billing, notifications
    device_id: str; ts: datetime; power_w: float | None
    provenance: Provenance; raw_value: float | None = None; raw_unit: str | None = None

class PowerStep(BaseModel):              # P1 → energy (interno), billing
    device_id: str; ts: datetime; delta_w: float; direction: Literal["up", "down"]
    provenance: Provenance

class ApplianceMatch(BaseModel):         # P1 → billing, notifications
    appliance_id: str | None; confidence: float          # None = desconhecido
    candidates: list[tuple[str, float]]

class ConsumptionEvent(BaseModel):       # P1 cria, P4 consome
    id: str; household_id: str; appliance_id: str | None; match: ApplianceMatch
    started_at: datetime; ended_at: datetime | None
    peak_w: float; energy_kwh: float | None; location: Literal["room", "common", "unknown"]
    room_id: str | None; cost_estimate_cents: int; provenance: Provenance; status: str

# contracts/presence.py
class DoorCrossed(BaseModel):            # P2 → presence (sem identidade)
    ts: datetime; direction: Literal["in", "out"]; confidence: float; provenance: Provenance
class PersonPresence(BaseModel):         # P2 → billing (regra C), alerts, UI
    resident_id: str; state: Literal["in", "out", "uncertain"]; since: datetime; confidence: float

# contracts/billing.py
class Attribution(BaseModel):            # P4
    consumption_event_id: str; target_type: Literal["resident", "common"]
    target_resident_id: str | None; method: str; provenance: Provenance; confidence: float | None
class BillAllocation(BaseModel):         # P4 → UI, agente
    bill_id: str; resident_id: str; amount_cents: int; fixed_share_cents: int
    residual_share_cents: int; individual_cents: int
    attributed_kwh_by_provenance: dict[Provenance, float]; breakdown: list["BreakdownLine"]

# contracts/notification.py
class NotificationAction(BaseModel):  id: str; label: str; style: Literal["primary", "neutral", "danger"] = "neutral"
class Notification(BaseModel):           # P3
    id: str; household_id: str; scope: Literal["personal", "household"]; recipient_resident_id: str | None
    kind: str; severity: Literal["info", "warning", "critical"]; title: str; body: str
    actions: list[NotificationAction]; status: str; expires_at: datetime | None
    ref_type: str | None; ref_id: str | None; correlation_id: str
```

`Home` (`contracts/home.py`) mantém-se. Mudança **proposta** (por acordo P1+P5): acrescentar `ler_leituras() -> list[EnergyReading]` e o papel do dispositivo; o `ler_consumo() -> float | None` atual mantém-se até a migração terminar.

## 2. Eventos de domínio

Envelope comum (**PLANEADO**, `contracts/domain_events.py`):

```json
{ "id": "uuid", "type": "energy.consumption_detected", "ts": "2026-11-18T18:05:10Z",
  "household_id": "uuid", "provenance": "inferred", "correlation_id": "uuid", "seq": 1042, "data": { } }
```

| Evento | Produtor | Consumidores | `data` essencial |
|---|---|---|---|
| `energy.reading_recorded` | P1 | P1, P4 | `device_id`, `power_w` |
| `energy.step_detected` | P1 | P1 | `delta_w`, `direction` |
| `energy.consumption_detected` | P1 | P4, P3 | `consumption_event_id`, `appliance_id?`, `confidence`, `location` |
| `energy.consumption_closed` | P1 | P4 | `consumption_event_id`, `energy_kwh` |
| `presence.door_crossed` | P2 | P2 | `direction`, `confidence` |
| `presence.changed` | P2 | P4, P3 | `resident_id`, `state`, `confidence` |
| `billing.confirmation_needed` | P4 | P3 | `consumption_event_id`, `estimated_cost_cents`, `options` |
| `notification.created` | P3 | UI (WS) | `notification_id`, `scope` |
| `notification.responded` | P3 | P4 | `notification_id`, `action_id`, `resident_id`, `ref_id` |
| `billing.attribution_changed` | P4 | P3, P4 | `consumption_event_id`, `target`, `method` |
| `alerts.threshold_crossed` | P4 | P3 | `budget_id`, `pct`, `forecast_cents?` |
| `alerts.alert_raised` | P4 | P3 | `kind` (`peak`, `forgotten_appliance`, `mismatch`), `ref_id` |
| `billing.bill_created` / `bill_finalized` | P4 | P3, UI | `bill_id` |
| `billing.allocation_published` | P4 | P3 | `bill_id`, `resident_id` |
| `automation.proposed` / `executed` | P3 / P1 | P3 | `rule_id`, `result` |
| `agent.action_proposed` | P3 | P3 | `action_id`, `requires_confirmation` |

`seq` é atribuído pelo barramento ao gravar (o produtor não o define); `correlation_id` só agrupa um fluxo e **não garante ordem**. Regras: eventos são imutáveis; consumidores são **idempotentes** por `event.id` (registo de ids processados na mesma transação do efeito; ver [event-flow.md](event-flow.md) §4); um consumidor nunca bloqueia o produtor; sem imagens nem identificadores de dispositivos externos no `data`.

## 3. Endpoints REST propostos

Prefixo `/api`, JSON `snake_case`, `Authorization: Bearer`, formato de erro `{ "error": {"code", "message"} }` (como hoje). Papéis: **L** senhorio, **T** inquilino, **O** operador. As permissões são aplicadas no servidor; respostas de **L** usam DTOs próprios sem presença nem aparelhos.

### Casas e moradores (P5)

| Método | Rota | Papéis | Notas |
|---|---|---|---|
| `GET` | `/api/me` | todos | **Existe hoje**; passa a incluir `memberships` |
| `GET` `POST` | `/api/households` | L, O | |
| `GET` | `/api/households/{id}` | L, T, O | |
| `GET` `POST` | `/api/households/{id}/rooms` | L, T (leitura), O | |
| `GET` `POST` | `/api/households/{id}/memberships` | L (escrita), T (leitura limitada) | Convite → `invited` |
| `PATCH` | `/api/memberships/{id}` | L; T só `presence_opt_in` | |

### Dispositivos, aparelhos e energia (P1)

| Método | Rota | Papéis | Notas |
|---|---|---|---|
| `GET` | `/api/households/{id}/devices` | O | Sem `external_ref` |
| `PATCH` | `/api/devices/{id}` | O | `role`, `power_unit` |
| `GET` `POST` | `/api/households/{id}/appliances` | T, O | T só os seus e os partilhados |
| `PATCH` `DELETE` | `/api/appliances/{id}` | T (dono), O | |
| `GET` | `/api/households/{id}/energy/readings?from&to&device_id` | T, O | Cada ponto com `provenance` |
| `GET` | `/api/households/{id}/energy/summary?period` | T (a sua parte), L (totais por quarto) | |
| `GET` | `/api/households/{id}/consumption-events?status` | T | |
| `POST` | `/api/consumption-events/{id}/contest` | T | |
| `POST` | `/api/simulation/readings` · `/api/simulation/reset` | O | Só `source=fake/replay`; senão `403 simulation_disabled` (padrão existente) |

### Presença (P2)

| Método | Rota | Papéis | Notas |
|---|---|---|---|
| `GET` | `/api/households/{id}/presence` | T | Estado dos moradores com `presence_opt_in`; **L: 403** |
| `PUT` | `/api/presence/me` | T | `{ "state": "in" \| "out" }` (substitui «cheguei/saí») |
| `GET` | `/api/presence/camera/status` | O | Só diagnóstico (FPS, `camera_ok`); sem imagens ao senhorio |

### Atribuição, fatura e recibos (P4)

| Método | Rota | Papéis | Notas |
|---|---|---|---|
| `GET` | `/api/households/{id}/attributions?event_id` | T | |
| `GET` `POST` | `/api/households/{id}/bills` | L (criar), T (ler própria parte) | Entrada manual no MVP |
| `POST` | `/api/bills/{id}/finalize` | L | Calcula e fixa; `409 bill_finalized` se repetido |
| `GET` | `/api/bills/{id}/allocations` | L (totais por quarto), T (a sua) | |
| `GET` | `/api/bills/{id}/receipt/me` | T | Recibo explicado |
| `POST` | `/api/allocations/{id}/contest` | T | |
| `GET` `PUT` | `/api/me/budget?period` | T | Orçamento pessoal |
| `GET` `PUT` | `/api/households/{id}/room-allowances` | L | Plafond por quarto |

### Notificações (P3)

| Método | Rota | Papéis | Notas |
|---|---|---|---|
| `GET` | `/api/notifications?status&scope&limit` | T, L (as suas) | Pessoais + da casa |
| `POST` | `/api/notifications/{id}/read` | dono | |
| `POST` | `/api/notifications/{id}/respond` | T autorizado | `{ "action_id": "mine" \| "everyone" \| "unknown" }`; `409 already_responded`, `409 notification_expired` |
| `GET` `PUT` | `/api/me/notification-preferences` | T, L | limiares, silêncio noturno |
| `WS` | `/api/ws` | todos | Novas mensagens: `notification`, `notification_update` (ver abaixo) |

### Assistente e automações (P3)

| Método | Rota | Papéis | Notas |
|---|---|---|---|
| `POST` | `/api/agent/messages` | T | `{ "text": "…" }` → resposta + `proposed_actions[]` |
| `POST` | `/api/agent/actions/{id}/confirm` · `/reject` | T | Só aqui uma ação sugerida é executada |
| `GET` `POST` | `/api/households/{id}/automations` | T, O | |
| `PATCH` | `/api/automations/{id}` | T, O | `{ "status" }`; ativação é passo explícito |
| `POST` | `/api/automations/parse` | T, O | Reaproveita `POST /api/rules/parse` (NVIDIA); não grava |

### Operação (P1/P5, existentes)

`GET /healthz`, `GET /api/status`, `GET /api/mcp/tools`, `GET /api/video` continuam (os dois últimos restringem-se a **O**; ver [migration.md](migration.md)).

## 4. WebSocket (extensão proposta)

O protocolo atual (`auth` na primeira mensagem, snapshot, `event`, `home_state`, `error`; ver [api-implementada.md](api-implementada.md) §3) mantém-se. Mensagens novas:

```json
{ "type": "notification",        "data": Notification }
{ "type": "notification_update", "data": { "id": "…", "status": "actioned", "response": { "action_id": "mine" } } }
```

O servidor só envia notificações do utilizador autenticado (pessoais) e da sua casa. O cliente que reconecta recupera por `GET /api/notifications`.

## 5. Códigos de erro novos

| HTTP | `code` | Quando |
|---|---|---|
| 403 | `forbidden_role` | Papel sem acesso ao recurso (ex.: senhorio a pedir presença) |
| 404 | `household_not_found`, `bill_not_found`, `notification_not_found` | |
| 409 | `already_responded`, `notification_expired`, `bill_finalized` | |
| 422 | `bill_inconsistent` | Soma de kWh atribuídos acima do total da fatura |
| 403 | `simulation_disabled` | Já existe |
