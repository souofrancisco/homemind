# Contratos

> **HOUSE-03 #86 (IMPLEMENTADO, PR #142):** catálogo temporal de aparelhos e medidores, API filtrada por papel e port tipado de leitura histórica para P1/P4 em `contracts/appliance_catalog.py`. Ver [house-03-appliance-catalog.md](house-03-appliance-catalog.md).

**IMPLEMENTADO (fundação F0)**: modelos Pydantic, eventos de domínio, SQLite, barramento persistente, guardas por casa/papel e OpenAPI→TS. **PLANEADO**: os motores e a maior parte das rotas de P1–P5; **HOUSE-02** (IMPLEMENTADO) acrescenta as rotas de convites e memberships. **DECISÃO PENDENTE**: marcadas por «(proposta)» e listadas em §9 e em [decisions.md](../decisions.md).

A API que já existia (ObjectOS) está em [api-implementada.md](api-implementada.md) e **não mudou**. Entidades e estados: [data-model.md](data-model.md); eventos: [event-flow.md](event-flow.md).

## 1. Como mudar um contrato

1. Mudança de um modelo em `app/backend/src/homemind/contracts/`, `make contracts` e **este documento no mesmo PR**.
2. Só com acordo das pessoas que o produzem ou consomem (matriz em §3). O frontend usa **só** os tipos gerados por `make contracts`; nunca redefine tipos da API.
3. Compatível: campo opcional novo, valor novo de enum que ninguém interpreta por exclusão. Incompatível: remover/renomear campo, mudar unidade ou significado. Eventos incompatíveis = nova classe com `schema_version` 2 e *upcast* no armazenamento (a 1 não se apaga).

## 2. Decisões da revisão crítica

| | Problema na proposta | Decisão (IMPLEMENTADA) | Compromisso |
|---|---|---|---|
| **A** Proveniência | Um só enum `measured\|estimated\|inferred\|simulated` mistura **origem** (real/simulada) e **natureza** (medida/estimada/inferida); uma assinatura inferida sobre dados simulados perdia a origem | `Provenance{origin: real\|simulated, kind: measured\|estimated\|inferred}`. Agregação: simulada se alguma for, natureza menos fiável (`Provenance.combine`). Aceita as strings antigas (`"simulated"` ⇒ `simulated/measured`) | O JSON deixa de ser uma string simples. «Medida simulada» (FakeHome) é `simulated/measured`: a origem manda na UI |
| **B** Identificadores | Mistura de ids | UUID interno em todo o domínio (`uuid5` em fixtures). O `sub` do Authentik e o id MCP (`Device.external_ref`) são **externos**: ficam na entidade persistida (`repr=False`), nunca em DTOs, eventos nem logs | `DeviceView` e `MemberView` são DTOs próprios; `Device`/`Resident`/`Membership` não saem no OpenAPI |
| **C** Unidades | `float` para tudo; `cost_estimate_cents` obrigatório | Tempo UTC com fuso (naïve é erro). Dinheiro `int` cêntimos, `strict`, sem negativos (só `adjustment` pode ser negativo). Potência `float` W em [0, 100 kW], sem NaN/inf. **Ausência = `None`, nunca 0** (0 W é leitura válida). Confiança em [0,1] | `unit_unknown` ⇒ `power_w=None` e nunca `measured` |
| **D** Precisão financeira | `energy_kwh: float` acumula erro (0,16 €/kWh não é exato) | Energia em **Wh inteiros** (`energy_wh`), preço em **milicêntimos/kWh** (`16000` = 0,16 €), custo por `cost_cents()` em `Decimal` com um só arredondamento (par). Float só em potência instantânea e `confidence` | Arredondado uma vez no fecho do consumo (<1 Wh de erro); sem `Decimal` nos DTOs (geraria schemas `-Input/-Output`) |
| **E** Estados | Strings livres; `ConsumptionEvent.status` misturava ciclo de vida de P1 com estado de atribuição de P4 | Enums + tabelas de transição (`check_transition`, `InvalidTransitionError`). `ConsumptionStatus = ongoing→closed\|discarded` (P1); o estado de atribuição vive em `Attribution` (P4, `active→superseded`) | `pending_confirmation`/`attributed`/`contested` deixam de ser estados do consumo (ver §2.1) |
| **F** Fonte de verdade | «Quem altera» difuso | Um dono por entidade (§3); outro módulo só altera por **evento** | Sem repositório genérico: cada módulo escreve as suas tabelas |
| **G** Maturidade | O mesmo modelo para HTTP, base de dados e resposta | Entidade persistida ≠ DTO ≠ evento ≠ comando. `*View` para respostas; `*In`/`Patch` com `extra=forbid` para entradas | `MeContext`, `NotificationView`, `LandlordBillView`… |

### 2.1 Outros problemas encontrados e resolvidos

- `ApplianceMatch.candidates: list[tuple]` → `ApplianceCandidate` tipado; vencedor só se houver um claro (`outcome`: `identified|ambiguous|unknown`).
- `PresenceEvent` e `DoorCrossed` sobrepunham-se → `DoorCrossed` (anónimo), `PresenceEvent` (pista por pessoa: só Wi-Fi/manual; Wi-Fi nunca diz «fora») e `PersonPresence` (estado fundido, `uncertain` exige `reason`).
- `Device` ≠ `Appliance`; `ApplianceOwnership` (dono ≠ quem usa). Uma tomada mede vários aparelhos; a assinatura sugere, não decide quem paga.
- Fatura: `total_wh` é da fatura real, **não** a soma da tomada; correções = nova revisão (`supersedes_id`), a finalizada nunca se edita; resíduo comum explícito em `residual_share_cents`.
- Notificação: `responder_ids` (snapshot de quem pode responder; o senhorio nunca), `Notification.respond` é a regra pura e a persistência tem de fazer *compare-and-set*. **REGRA B = VOTAÇÃO (D-32, prevalece):** em `confirmation_request` cada inquilino vota uma vez; um «É minha» fecha; atribuir a outro exige ≥ metade dos elegíveis com o mesmo alvo (fecha antes se o próprio assumir); todos votaram sem decisão ou 24 h → por todos. Fonte única: `confirmation_outcome` em `contracts/notification.py`. **Quem fizer merge (pessoa ou agente) adapta o código de P3/P5/billing a esta regra; não reintroduzir «primeira resposta vence» nas confirmações.** Outros tipos: primeira resposta vence (`409 already_responded`); expirada: `409 notification_expired`.
- Execução física: `isError=false` **não** confirma; `ActionExecutionResult(confirmed)` exige `readback_confirmed`; `uncertain` nunca se repete (`may_retry=False`).
- Um não-membro recebe **404** (não revela que a casa existe); um membro sem papel recebe **403 `forbidden_role`**.

## 3. Matriz de contratos

Módulo `contracts/`: `common.py` (tipos, `Provenance`, `Audit`, `cost_cents`), `household.py`, `devices.py`, `energy.py`, `presence.py`, `sensors.py`, `safety.py`, `billing.py`, `notification.py`, `agent.py`, `domain_events.py`, `api.py` (erros e `OPENAPI_MODELS`), `fixtures.py` (determinísticas). Os contratos ObjectOS (`base.py`, `eventos.py`, `home.py`, `regras.py`, `simulacao.py`, `video.py`, `visao.py`) **não foram tocados**.

| Contrato | Produtor (dono) | Consumidores | Persistência | Testes | Pendente |
|---|---|---|---|---|---|
| `Household`, `Room`, `Resident`, `Membership` | P5 | todos (via guardas) | **IMPLEMENTADA** (`0001_core_households.sql`); HOUSE-02 acrescenta `0003_core_membership_invitations.sql` | `tests/test_contracts_foundation`, `households/tests` | HOUSE-02: convites e revogação REST IMPLEMENTADOS (activação real bloqueada: Authentik sem `email_verified`); onboarding visual HOUSE-05 |
| `HouseholdView`, `MemberView`, `MeContext` | P5 | frontend | — (DTO) | `test_authorization`, `test_openapi_contract` | P-04 (o que um inquilino vê dos outros) |
| `Device`, `DeviceView`, `Appliance`, `ApplianceSignature` | P1 | P1, P4, P3 | PLANEADA (P1: `0030_energy_*.sql`) | modelos | Capacidades por dispositivo |
| `ApplianceCatalog` port, `MeterContextSegment`, `ApplianceContextSegment` | HOUSE-03 (implementação SQLite) | P1, P4 via injeção tipada | **IMPLEMENTADO** (`contracts/appliance_catalog.py`) | adapter estrutural + catálogo | Composição/injeção no runtime P1/P4 |
| `EnergyReading`, `PowerStep` | P1 | P1 (P4 só o resumo) | PLANEADA (retenção P-08) | modelos + evento | Limiar de `stale` |
| `ApplianceMatch`, `ConsumptionEvent` | P1 | P4, P3 | PLANEADA (P1) | modelos + cenário | Limiar de «bate certo» (0,9?) |
| `DoorCrossed`, `PresenceEvent`, `PersonPresence` | P2 | P4 (regra C), P3 | PLANEADA (P2) | modelos | Tolerância 20–30 min na fusão |
| `PresenceEvent(source=appliance)`, `PresenceMeIn`, `PresenceConfirmationRequest`, `HouseOccupancy`, `PresenceDevice`/`PresenceDeviceView`, `CameraStatus` (**PROPOSTA**, D-31) | P2 | P3 (pedido), app (DTOs), P2 | PLANEADA (P2) | modelos + fixtures | Tolerância; retenção (P-20) |
| `SensorReading` (contacto, fumo, temperatura, humidade; `unknown` sem valor) (**PROPOSTA**, D-31) | P1 (MCP-03) | P2 (SAFE) | PLANEADA (P1) | modelos | Capacidades reais do kit (MCP-03) |
| `SafetyAlert` (janela aberta + aquecimento, fumo) (**PROPOSTA**, D-31) | P2 | P3 (→ `Notification` e, AGENT-03b, `ProposedAction`: consumidores **IMPLEMENTADOS**) | PLANEADA (P2) | modelos | Autorização do senhorio para fumo |
| `Attribution` (+`supersede`) | P4 | P3, agente | PLANEADA: índice único parcial `(consumption_event_id) WHERE status='active'` | modelos + cenário | — |
| `ElectricityBill`, `BillAllocation` (+`validate_allocations`) | P4 | UI, agente, P3 | PLANEADA (P4) | fixtures A/B/C exatas | Entrada da fatura (manual vs LLM) |
| `Budget`, `BudgetThreshold`, `Contestation` | P4 | P3 | PLANEADA (P4) | modelos | P-10 (individual vs fixa) |
| `Notification`, `NotificationView`, `NotificationAction/Response/Preferences`, `ConfirmationRequest` | P3 (pedido: P4) | UI, P4 | **IMPLEMENTADA** (`0300_notifications_core.sql`: `notification`, `notification_read`, `notification_preferences`; *compare-and-set* sobre o estado e a versão/n.º de votos) | modelos + cenário + `notifications/tests` | D-32 (votação nas confirmações) |
| `ProposedAction`, `ActionConfirmation`, `ActionExecutionResult` | P3 (execução: P1) | P3, `notifications` | **IMPLEMENTADA** (`0310_agent_actions.sql`: `agent_action`, com a confirmação e o resultado em JSON, e `agent_action_log` *append-only* como auditoria; AGENT-03 #112). Executor real **PLANEADO** (P1); na casa demo só SIMULADO | modelos + `agent/tests` | P-06 (LLM e dados) |
| `AgentMessage` | P3 | app (DTO) | **IMPLEMENTADA** (`0311_agent_messages.sql`: `agent_message`, por residente; retenção 50 mensagens / 30 dias, P-25; nunca enviada ao LLM, P-06; #111) | `agent/tests/test_history.py` | `AgentMessage` sem `resident_id` (desejado: só o próprio lê) |
| `AgentToolRequest/Result`, `AutomationRule` | P3 (execução: P1) | P3 | PLANEADA (P3); as ferramentas não persistem resultados; `AutomationRule` é AGENT-04 | modelos | P-06 (LLM e dados) |
| `DomainEvent` (23 tipos), `StoredEvent` | cada módulo | cada módulo | **IMPLEMENTADA** (`domain_event`) | `test_events`, cenário | — |

## 4. Eventos de domínio

Envelope (`EventBase`): `id` (UUID, estável), `schema_version` (=1), `type`, `ts` (UTC), `household_id`, `correlation_id`, `provenance`, `data` (payload **tipado por tipo**, discriminador `type`). `seq` **não** está no envelope do produtor: `StoredEvent{seq, event}` é atribuído pela base de dados ao gravar. O envelope valida que `provenance` e `household_id` coincidem com os do payload.

| Evento | Produtor | `data` | Consumidores | Idempotência (por `event.id`, por consumidor) |
|---|---|---|---|---|
| `energy.reading_recorded` | P1 | `EnergyReading` | P1, P4 | `processed_event` |
| `energy.step_detected` | P1 | `PowerStep` | P1 | idem |
| `energy.consumption_detected` | P1 | `ConsumptionEvent` (`ongoing`; `appliance_owner_resident_id` PROPOSTA) | P4, P3, P2 (pista `appliance`) | idem |
| `energy.consumption_closed` | P1 | `ConsumptionEvent` (`closed`/`discarded`) | P4 | idem |
| `energy.identification_needed` | P1 | `ApplianceIdentificationRequest` (ENERGY-04: «O que é este aparelho?»; sem nomes) | P3 (`notifications.appliance_identification`); a resposta volta em `notification.responded` (`ref.type=appliance_identification`) para P1 | idem |
| `presence.door_crossed` | P2 | `DoorCrossed` (anónimo) | P2 | idem |
| `presence.changed` | P2 | `PersonPresence` | P4, P3 | idem |
| `presence.cue_recorded` (PROPOSTA) | P2 | `PresenceEvent` (Wi-Fi, manual, aparelho) | P2 | idem |
| `presence.confirmation_needed` (PROPOSTA) | P2 | `PresenceConfirmationRequest` | P3 (`notifications.presence_check`, **IMPLEMENTADO**) | idem |
| `presence.occupancy_changed` (PROPOSTA) | P2 | `HouseOccupancy` (anónimo) | P2, P3 | idem |
| `sensor.reading_recorded` (PROPOSTA) | P1 | `SensorReading` | P2 | idem |
| `safety.alert_raised` (PROPOSTA) | P2 | `SafetyAlert` (o mesmo `id` volta com `status=resolved`) | P3 (`notifications.safety_alert`, **IMPLEMENTADO**); P3 (`agent.safety_suggestion`, **IMPLEMENTADO**, AGENT-03b: só propõe, uma `ProposedAction` por inquilino ativo; alerta resolvido → propostas pendentes `rejected`; em runtime real só dispara quando a `safety` tiver o resolvedor de aquecedores, ENERGY-03 #81; hoje só na demo SIMULADA e nos testes) | idem |
| `billing.confirmation_needed` | P4 | `ConfirmationRequest` | P3 (consumidor `notifications.confirmation_needed`, **IMPLEMENTADO**) | idem |
| `billing.attribution_changed` | P4 | `Attribution` | P3 (`notifications.attribution_changed`, **IMPLEMENTADO**), P4 | idem |
| `billing.bill_created` / `bill_finalized` | P4 | `BillRef` | P3, UI | idem |
| `billing.allocation_published` | P4 | `AllocationPublished` | P3 (`notifications.allocation_published`, **IMPLEMENTADO**) | idem |
| `billing.contestation_changed` | P4 | `Contestation` (BILL-06: aberta → aviso ao senhorio; decidida → aviso a quem contestou) | P3 (`notifications.contestation`, **IMPLEMENTADO**) | idem |
| `notification.created` | P3 | `NotificationCreatedData` | UI (DTO) | idem |
| `notification.responded` | P3 | `NotificationRespondedData` (resposta + `ref` + `outcome` nas confirmações: um evento por voto; P4 só atribui com `outcome.decided`) | P4 | idem |
| `alerts.threshold_crossed` | P4 | `BudgetThreshold` | P3 (`notifications.budget_threshold`, **IMPLEMENTADO**); P3 (`agent.budget_light`, ALERT-06: proposta de cor na lâmpada, **IMPLEMENTADO**) | idem |
| `alerts.alert_raised` | P4 | `AlertRaisedData` | P3 (`notifications.peak_alert`, `kind=peak` e `kind=anomaly`, **IMPLEMENTADO**) | idem |
| `alerts.cold_room` | P4 | `ColdRoomData` (ALERT-06: quarto do morador várias noites < 18 °C; privado) | P3 (`notifications.cold_room`, **IMPLEMENTADO**) | idem |
| `agent.action_proposed` | P3 | `ProposedAction` | P3 (`notifications.agent_action`, **IMPLEMENTADO**: aviso pessoal sem botões; emitido pelo chat e pelo `agent.safety_suggestion`; o contrato não tem `source`, #157) | idem |
| `automation.proposed` | P3 | `AutomationRule` | P3 | idem |
| `automation.executed` | P1 | `AutomationExecutedData` | P3 | idem |

Garantias e limites: [event-flow.md](event-flow.md) §4. Eventos **não** se expõem à app em bruto (`StoredEvent` não está no OpenAPI: inclui presença de pessoas); chegam como DTOs filtrados por papel.

## 5. Autorização: recurso × papel (IMPLEMENTADA em `core/access.py`)

Única fonte: `PERMISSIONS`. Âmbito: `own` só os seus; `household` dados partilhados da casa; `aggregate` só totais; `diagnostic` estado técnico sem dados pessoais; `—` sem acesso (`403 forbidden_role`). Cada rota nova ⇒ teste papel × rota (`test_matrix_is_enforced…` percorre todas as combinações).

| Recurso | Landlord | Tenant | Operator |
|---|---|---|---|
| `household`, `room` (leitura) | household | household | diagnostic |
| `household`, `room` (escrita) | household | — | — |
| `member` (leitura) | household (todos os estados) | household (só ativos) | — |
| `member` (escrita) | household | **own** (só `presence_opt_in`) | — |
| `device` | — | — | diagnostic (r/w) |
| `appliance` | — | own (r/w) | diagnostic (r/w) |
| `energy` (leituras, resumos) | **aggregate** | own | diagnostic |
| `consumption` | — | household (r), own (contestar) | diagnostic (r) |
| `presence` | **—** | **own** (r/w) | **—** |
| `camera_status` | — | — | diagnostic |
| `attribution` | — | own | — |
| `bill` | aggregate (r), household (w) | own (r) | — |
| `receipt` (alocações) | aggregate | own (r, contestar) | — |
| `house_rules` (regra da sala versionada) | household (r) | household (r/w) | — |
| `budget`, `agent` | — | own | — |
| `notification` | own | own | — |
| `automation` | — | household | diagnostic |
| `simulation` (w) | — | — | diagnostic |

Regras transversais: a identidade é o `sub` do token → `resident` → membership **ativa e dentro de datas no fuso da casa**; nunca um `resident_id` do cliente; sem membership ⇒ `404 household_not_found`; recurso de outra casa ⇒ 404; erros sem detalhes privados.

## 6. Endpoints REST (PLANEADOS, salvo os marcados)

**IMPLEMENTADOS hoje** (HOUSE-01, parcial): `GET /api/me/context`, `GET /api/households/{id}`, `…/rooms`, `…/members`, `PATCH …/memberships/{id}` (só `presence_opt_in` próprio). Tudo o resto desta secção é **PLANEADO**. Prefixo `/api`, JSON `snake_case`, `Authorization: Bearer`, formato de erro `{ "error": {"code", "message"} }` (como hoje). Papéis: **L** senhorio, **T** inquilino, **O** operador. As permissões são aplicadas no servidor; respostas de **L** usam DTOs próprios sem presença nem aparelhos.

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
| `GET` | `/api/households/{id}/presence` | T | **Só o próprio** (opt-in); **L/O: 403**; ainda PLANEADO |
| `PUT` | `/api/presence/me` | T | `PresenceMeIn` `{ "state": "in" \| "out" }` (substitui «cheguei/saí») |
| `GET` | `/api/presence/camera/status` | O | `CameraStatus`: só diagnóstico (FPS, `camera_ok`, fonte e origem); sem imagens nem URL |
| `GET` | `/api/households/{id}/occupancy` | T | `HouseOccupancy` (PROPOSTA): número de pessoas e visitas, sem nomes; **L: 403** |
| `GET`·`POST`·`DELETE` | `/api/presence/devices` | T (own) | `PresenceDeviceView` (PROPOSTA): telemóvel para o Wi-Fi, consentimento e revogação; nunca o MAC |

### Atribuição, fatura e recibos (P4)

| Método | Rota | Papéis | Notas |
|---|---|---|---|
| `GET` | `/api/households/{id}/attributions?event_id` | T | |
| `GET` `POST` | `/api/households/{id}/bills` (+ `POST …/bills/preview`, `GET …/bills/{bill_id}`) | L (criar, ver todas), T (só finalizadas) | **IMPLEMENTADO (BILL-01):** `BillIn` → `BillPreview` / `BillView`; ver [api-implementada.md](api-implementada.md) |
| `POST` | `/api/households/{id}/bills/{bill_id}/finalize` (+ `…/revisions`) | L | **IMPLEMENTADO (BILL-04):** calcula e fixa; `409 bill_finalized` se repetido; correção = nova revisão (`409 bill_not_finalized` num rascunho) |
| `GET` | `/api/households/{id}/bills/{bill_id}/summary` | L (totais por quarto) | **IMPLEMENTADO** (`LandlordBillView`) |
| `GET` | `/api/households/{id}/bills/{bill_id}/receipt` | T | **IMPLEMENTADO**: `BillAllocation` própria (recibo por linhas) |
| `GET` | `/api/households/{id}/bills/{bill_id}/receipt/explanation` | T | **IMPLEMENTADO (BILL-05):** `ReceiptExplanation` (evidência guardada no fecho, `billing_allocation_item`) |
| `POST` | `/api/allocations/{id}/contest` | T | |
| `GET` · `PUT` `DELETE` | `/api/households/{id}/rules` · `…/rules/next` | L, T (ler) · T (agendar/cancelar) | **IMPLEMENTADO (HOUSE-04):** `HouseRulesView`; `HouseRulesIn` agenda para o dia 1 do mês seguinte |
| `GET` `PUT` | `/api/households/{id}/budgets/me?period` | T | **IMPLEMENTADO (ALERT-01):** `BudgetIn` → `BudgetStatus` (com `forecast: BudgetForecast \| null`, ALERT-02) |
| `GET` `PUT` | `/api/households/{id}/tariff` | L (definir), L e T (ver) | **IMPLEMENTADO (ALERT-02):** `TariffIn` → `TariffStatus` (simples ou bi-horário; só estimativas) |
| `GET` · `PUT` | `/api/households/{id}/room-allowances` · `…/{room_id}` | L, T (ler) · L (agendar) | **IMPLEMENTADO (BILL-03):** `RoomAllowanceView`; `RoomAllowanceIn` vale no mês seguinte |

### Notificações (P3)

| Método | Rota | Papéis | Notas |
|---|---|---|---|
| `GET` | `/api/households/{household_id}/notifications?status&scope&limit` | T, L (as suas) | **IMPLEMENTADO.** Pessoais + da casa, como `NotificationView` (com `voting`); o senhorio só recebe os tipos da allow-list (hoje `info`). Caminho por casa; revisão P5 |
| `POST` | `/api/households/{household_id}/notifications/{id}/read` | dono | **IMPLEMENTADO.** Caminho por casa; revisão P5 |
| `POST` | `/api/households/{household_id}/notifications/{id}/respond` | T autorizado | **IMPLEMENTADO.** `NotificationRespondIn` `{ "action_id": "mine" \| "everyone" \| "unknown" \| "other", "target_resident_id"? }` (alvo só com `other`, outro inquilino elegível); `409 already_responded` (já votou / já fechada), `409 notification_expired`, `400 invalid_request` (alvo inválido). Caminho por casa; revisão P5 |
| `GET` `PUT` | `/api/households/{household_id}/notification-preferences` | T, L | **IMPLEMENTADO.** Silêncio noturno e tipos desligados, por casa (`security_alert` não se desliga: `400`). Caminho por casa; revisão P5 |
| `WS` | `/api/ws` | todos | **PLANEADO.** Novas mensagens: `notification`, `notification_update` (ver abaixo) |

### Assistente e automações (P3)

| Método | Rota | Papéis | Notas |
|---|---|---|---|
| `POST` | `/api/households/{household_id}/agent/messages` | T | **IMPLEMENTADO** (parcial). `{ "text": "…" }` → `AgentResponse`. Dados **SIMULADOS** da casa demo (as outras casas não têm dados); LLM desligado por omissão (`AGENT_LLM_ENABLED`). Um pedido de ação («desliga a luz») devolve `proposed_actions` com uma `ProposedAction` por confirmar (AGENT-03); nunca executa nada. A troca fica no histórico do próprio residente. Caminho por casa; revisão P5 |
| `GET` | `/api/households/{household_id}/agent/messages?limit` | T | **IMPLEMENTADO** (#111). `[AgentMessage]` (`limit` 1..100, omissão 50), do mais antigo para o mais recente; só o histórico do **próprio** residente (nunca o de outro nem de outra casa). Dados pessoais com retenção curta (50 mensagens, 30 dias, P-25); **nunca** enviado ao LLM (P-06). Revisão P5 |
| `GET` | `/api/households/{id}/agent/actions[/{aid}]` · `POST …/agent/actions/{aid}/confirm` · `…/reject` | T | **IMPLEMENTADO** (AGENT-03; ver `api-implementada.md`). Só no `confirm` uma ação é executada, no máximo uma vez; na casa demo o executor é SIMULADO. O executor real (hardware) é **PLANEADO** (P1). Caminho por casa (substitui o `/api/agent/actions/{id}/…` proposto); revisão P5 |
| `GET` `POST` | `/api/households/{id}/automations` | T, O | |
| `PATCH` | `/api/automations/{id}` | T, O | `{ "status" }`; ativação é passo explícito |
| `POST` | `/api/automations/parse` | T, O | Reaproveita `POST /api/rules/parse` (NVIDIA); não grava |

### Operação (P1/P5, existentes)

`GET /healthz`, `GET /api/status` e `GET /api/mcp/tools` continuam. `GET /api/video` responde sempre `404` por PRIV-02; nenhuma role recebe frames. Ver [migration.md](migration.md).

## 7. WebSocket (PLANEADO)

O protocolo atual (`auth` na primeira mensagem, snapshot, `event`, `home_state`, `error`; ver [api-implementada.md](api-implementada.md) §3) mantém-se. Mensagens novas:

```json
{ "type": "notification",        "data": Notification }
{ "type": "notification_update", "data": { "id": "…", "status": "actioned", "response": { "action_id": "mine" } } }
```

O servidor só envia notificações do utilizador autenticado (pessoais) e da sua casa. O cliente que reconecta recupera por `GET /api/households/{household_id}/notifications`.

## 8. Códigos de erro

| HTTP | `code` | Quando |
|---|---|---|
| 403 | `forbidden_role` | Papel sem acesso ao recurso (ex.: senhorio a pedir presença) |
| 404 | `household_not_found`, `bill_not_found`, `notification_not_found` | |
| 409 | `already_responded`, `notification_expired`, `bill_finalized`, `bill_not_finalized` | |
| 422 | `bill_inconsistent` | Soma de kWh atribuídos acima do total da fatura |
| 403 | `simulation_disabled` | Já existe |

## 9. Pontos para revisão da equipa (DECISÃO PENDENTE)

Prioridade para aprovar antes de implementar os módulos: ver [decisions.md](../decisions.md) D-23…D-30 e P-16…P-21. Resumo: (1) `Provenance` em duas dimensões; (2) Wh inteiros + milicêntimos; (3) semântica do barramento; (4) 404 vs 403 e membership por datas; (5) `None` em energia/custo; (6) regras de resposta das notificações; (7) OpenAPI por `OPENAPI_MODELS`; (8) nenhuma alteração ao código ObjectOS de domínio; (9) **sem dependências novas**; (10) quem aprova cada pendência.

> **PRIV-02 #119 (revisão de acesso):** o âmbito de leitura do recurso `presence` foi restringido de `household` a `own` para o inquilino; a regra de escrita `own` não mudou. A API de presença permanece planeada. Ver [módulo presença](../modules/presence.md#priv-02-119--investigação-e-arquitetura-de-privacidade-17112026).

## HOUSE-02 — extensão de comandos REST sem alterar DTOs F0

`RoomView`, `MemberView`, `MembershipSelfView`, `MeContext` e a matriz `PERMISSIONS` mantêm a forma e os campos. Os pedidos `CreateRoom`, `CreateInvitation` e `RedeemInvitation` e a resposta pontual `InvitationIssued` são comandos/DTOs HTTP da feature, não entidades de domínio nem eventos. Só um senhorio efetivo pode criar convites para `tenant`; `landlord` e `operator` são provisionados fora das rotas públicas. O contexto é derivado de um access token Authentik e da tabela membership, revalidado na transação de escrita. Documentação de endpoints, estados, ADR e limitações: [house-02-memberships.md](house-02-memberships.md).
