# Contratos ObjectOS (documento canónico)

> **IMPLEMENTADO — API que existe hoje no código (ObjectOS).** Não descreve a Conta Certa. Os contratos **propostos** da Conta Certa estão em [contracts.md](contracts.md). Os endpoints `/api/state`, `/api/rules`, `/api/off`, `/api/simulate` e o `HomeState` pertencem ao motor antigo e saem na fase M4 de [migration.md](migration.md); `/healthz`, `/api/me`, `/api/status`, `/api/mcp/tools` e o protocolo WebSocket são reutilizados. `/api/video` está desativado por PRIV-02. Por isso este documento **não foi arquivado**: o código ainda o cumpre e o OpenAPI é gerado dele.

Substitui as propostas v1–v3 do contrato frontend↔backend e as extensões do frontend (removidas; ficam no histórico Git). Qualquer mudança faz-se primeiro aqui e nos modelos Pydantic, com acordo da equipa.

**Fontes de verdade no código:** `app/backend/src/homemind/contracts/` (modelos internos) e o **OpenAPI** do backend (`/docs`, `/openapi.json`). `make contracts` gera `app/frontend/src/shared/api/schema.d.ts`; o frontend deriva daí os seus tipos (`src/types/home.ts`). As mensagens do WebSocket não constam do OpenAPI e estão descritas abaixo.

```text
FonteVideo ──FrameVideo──▶ visão ──FrameDeteccoes──▶ gestos/presença ──Evento──▶ motor ──Home──▶ FakeHome | McpHome
 (video.py)                (visao.py)                (eventos.py)              (home.py, regras.py)
                                                              motor ──REST + WS──▶ painel
```

## 1. Contratos internos (`contracts/`)

### Vídeo (`video.py`)

`FonteVideo`: `iniciar()`, `parar()`, `ultimo_frame() -> FrameVideo | None` (nunca bloqueia), `camara_ok`. `FrameVideo`: `imagem` (ndarray BGR), `indice` (igual ao anterior = sem frame novo), `t` (`time.monotonic()`). Frames só em memória.

### Deteções (`visao.py`)

| Modelo | Campos |
|---|---|
| `FrameDeteccoes` | `indice`, `t`, `hora`, `largura`, `altura`, `objetos`, `pessoas` |
| `ObjetoDetetado` | `classe` (`caneca` / `livro` / `comando`), `confianca`, `caixa`, `track_id` |
| `PessoaDetetada` | `confianca`, `caixa`, `track_id`, `keypoints` (17 COCO) |
| `Caixa` / `Keypoint` | `x1,y1,x2,y2` (+ `centro`) / `x,y,confianca` |

- Coordenadas em píxeis, origem em cima à esquerda, **y cresce para baixo** (pulso acima do cotovelo: `pulso.y < cotovelo.y`).
- Keypoints: ombros 5/6, cotovelos 7/8, pulsos 9/10 (enum `KP`). Ponto não detetado: `confianca=0`.
- `t` monotónico para janelas e cooldowns; `hora` (UTC) só para registo.
- `track_id` é efémero (ByteTrack), não identifica ninguém e não é persistido.
- Classes COCO: 41 caneca, 73 livro, 65 comando (`VISAO_LIVRO_COCO` permite trocar o livro).
- `Detetor.detetar(FrameVideo) -> FrameDeteccoes`. Modelos imutáveis, sem campos extra.

### Eventos (`eventos.py`)

```python
ObjetoLevantado(tipo="objeto_levantado", classe, hora)
Presenca(tipo="presenca", ha_alguem, hora)      # só transições
```

`Evento` é a união discriminada por `tipo`. `ProcessadorEventos.processar(frame) -> tuple[Evento, ...]` (síncrono, sem I/O) e `PublicadorEventos.publicar(evento)` (qualquer thread, nunca bloqueia). São internos: o painel só os vê como linhas do registo e pelo efeito no `HomeState`.

Semântica acordada:

- Um `ObjetoLevantado` por gesto confirmado, mesmo com o modo já ativo (o motor regista «já está ativo»).
- Presença começa `False` na visão; no motor começa desconhecida (`null`) e o primeiro `Presenca` conta sempre.
- Sem frames novos não há eventos: câmara em baixo nunca é interpretada como divisão vazia.
- Limiares em `core/config.py` (`GESTO_*`, `PRESENCA_*`); detalhe em `features/gestos/README.md`.

### Casa (`home.py`)

```python
class Home(Protocol):
    async def definir_lampada(self, ligada: bool, cor: Cor | None = None, brilho: int | None = None) -> bool
    async def definir_tomada(self, ligada: bool) -> bool
    async def ler_consumo(self) -> float | None      # W em cache; None = indisponível
    async def estado(self) -> EstadoCasa
```

- As escritas devolvem `True` **só com o estado confirmado** (no `McpHome`, por releitura).
- `cor`/`brilho` a `None` = manter; com `ligada=False` são ignorados. `brilho` 1–100.
- `Cor`: `branco`, `branco_quente`, `branco_frio`, `azul`, `vermelho`, `verde`, `amarelo`, `laranja`, `roxo`, `rosa` (RGB de referência em `CORES`).
- `EstadoCasa`: `backend` (`fake` | `mcp`), `mcp_ok`, `lampada {ligada, cor, rgb, brilho}`, `tomada {ligada, consumo_w, consumo_lido_em}`, `atualizado_em`, `aviso`. **`null` = desconhecido**, nunca «desligado» nem «0 W».

### Regras (`regras.py`)

```json
{ "id": "leitura", "objeto": "livro", "nome": "Modo leitura", "enabled": true,
  "acoes": [ { "dispositivo": "lampada", "ligada": true, "cor": "branco_quente", "brilho": 40 },
             { "dispositivo": "tomada", "ligada": true } ] }
```

- `id`: `^[a-z0-9_-]{1,40}$`; `nome`: 1–60 caracteres; 1–2 ações, no máximo uma por dispositivo.
- Campos desconhecidos são rejeitados (400).
- No máximo uma regra `enabled` por objeto: gravar ou ativar uma desativa as outras do mesmo objeto.
- Predefinidas (criadas no 1.º arranque): `pausa` (caneca: luz branco quente 30 %), `leitura` (livro: luz branco quente 40 % + tomada), `cinema` (comando: luz azul 10 % + tomada).

## 2. API HTTP

Prefixo `/api`. JSON UTF-8, `snake_case`, horas ISO 8601 UTC. Todas as rotas `/api/*` exigem `Authorization: Bearer <access_token>` (Authentik). Só `/healthz` é público.

| Método | Rota | Resposta |
|---|---|---|
| `GET` | `/healthz` | `{ "status": "ok", "backend": "fake"\|"mcp", "physical_writes": bool }` |
| `GET` | `/api/me` | `User` do token |
| `GET` | `/api/status` | `Status`: `camera_ok`, `mcp_ok`, `backend`, `updated_at` |
| `GET` | `/api/state` | `HomeState` (igual ao do WebSocket) |
| `GET` | `/api/events?limit=1..50` | `{ "events": [EventLogItem] }`, do mais antigo para o mais recente |
| `POST` | `/api/off` | sempre `200 OffResult` |
| `POST` | `/api/simulate` | `HomeState`; só com `HOME_BACKEND=fake` (senão `403 simulation_disabled`) |
| `GET` | `/api/rules` | `{ "rules": [Rule] }` |
| `POST` | `/api/rules` | `201 Rule` (cria ou substitui pelo `id`) |
| `PATCH` | `/api/rules/{id}` | corpo `{ "enabled": bool }` → `Rule` · `404 rule_not_found` |
| `DELETE` | `/api/rules/{id}` | `204` · `404 rule_not_found` |
| `POST` | `/api/rules/parse` | corpo `{ "text": "…" }` (3–300) → `ParseResponse` |
| `GET` | `/api/presence/camera/status` | `CameraStatus` (PRES-01): só papel `operator` (`403` aos restantes); sem imagem nem URL; fonte em falha ⇒ `camera_ok=false` |
| `GET` | `/api/video` | **Só papel `operator`** (`403` aos restantes; sem `household_id`, decisão de demo P-28). MJPEG (`multipart/x-mixed-replace`) **desligado por omissão**: `404` salvo clip sintético allowlisted com `PROFILE=demo`, `HOME_BACKEND=fake` e `ENABLE_DEV_VIDEO_PREVIEW=true` (PRIV-02). Query opcional `anotacoes` e `esqueleto` (omissão `true`) |
| `GET` | `/api/mcp/tools` | `tools/list` do MCP (diagnóstico); `502` se indisponível |
| `GET` | `/api/me/context` | `MeContext`: o residente ligado ao `sub` e as suas memberships ativas (**Conta Certa, F0**) |
| `GET` | `/api/households/{id}` | `HouseholdView` · `404 household_not_found` (não-membro ou casa inexistente) · `403 forbidden_role` |
| `GET` | `/api/households/{id}/rooms` | `[RoomView]` (inclui `included_wh`: plafond solidário mensal do quarto, BILL-03) |
| `GET` | `/api/households/{id}/members` | `[MemberView]`: senhorio vê todos os estados, inquilino só ativos; operador `403`; nunca `presence_opt_in` nem `sub` |
| `PATCH` | `/api/households/{id}/memberships/{mid}` | corpo `{ "presence_opt_in": bool }` (`extra=forbid`) → `MembershipSelfView`; só a própria membership de um inquilino (`403` a de outro, `404` se não é desta casa) |
| `GET` | `/api/presence?household_id=` | `PersonPresence` **só do próprio** (**PRES-04**); sem pistas: `uncertain/no_recent_cues`; senhorio/operador `403`, não-membro `404` |
| `GET` | `/api/presence/devices?household_id=` | `[PresenceDeviceView]` dos telemóveis do próprio (nunca o hash nem o MAC) |
| `POST` | `/api/presence/devices?household_id=` | corpo `{label, wifi_address, consent: true}` → `201 PresenceDeviceView` · `400 invalid_request` · `409 device_already_registered \| device_limit` · `503 wifi_unconfigured` |
| `DELETE` | `/api/presence/devices/{id}?household_id=` | opt-out imediato → `204` · `404 device_not_found` (inexistente ou de outro) |
| `POST` | `/api/presence/wifi/observations` | **fora do OpenAPI**; só `PRESENCE_WIFI_COLLECTION_ENABLED=true` e `PRESENCE_WIFI_MODE=ingest`; `X-Presence-Token` (token de máquina, não JWT); `204`/`401`/`404` |
| `POST` | `/api/households/{id}/agent/messages` | corpo `{ "text": "…" }` → `AgentResponse`; só inquilino (`403 forbidden_role` ao senhorio e ao operador) · `404 household_not_found` (não-membro). Dados **SIMULADOS** (casa demo); LLM desligado por omissão (`AGENT_LLM_ENABLED`). A troca (pergunta e resposta) fica gravada no histórico do próprio residente (ver `GET …/agent/messages`). Um **pedido de ação** («desliga a luz», «põe a luz azul», «desliga a tomada») nunca chega ao LLM nem executa nada: devolve `proposed_actions` com **uma** `ProposedAction` por confirmar (ou um texto de recusa e `proposed_actions` vazio: `forbidden_kind`, `plug_turn_on_not_allowed`, `ambiguous_device`, `no_device`, `unsupported`) (**Conta Certa, P3, AGENT-03**) |
| `GET` | `/api/households/{id}/agent/messages?limit` | `[AgentMessage]` (`limit` 1..100, omissão 50; `400 invalid_request` fora disto): o histórico do **próprio** residente, do mais antigo para o mais recente (nunca o de outro residente nem de outra casa). Só inquilino (`403 forbidden_role` ao senhorio e ao operador) · `404 household_not_found` (não-membro). Dados pessoais com retenção curta (50 mensagens, 30 dias, P-25); **nunca** é passado ao LLM (P-06) (**Conta Certa, P3, #111**) |
| `GET` | `/api/households/{id}/agent/actions?status&limit` | `[AgentActionView]` (`status` = `ActionStatus`; `limit` 1..100): só as ações propostas **ao próprio** (pelo chat ou, AGENT-03b, pelo consumidor `agent.safety_suggestion` a partir de um alerta de janela aberta com aquecimento: só na demo/SIMULADO ou com diretório registado; uma proposta cujo alerta foi resolvido passa a `rejected`), da mais recente à mais antiga; `expired` é derivado de `expires_at`. Só inquilino (**P3, AGENT-03; `AgentActionView` é vista local, PROPOSTA mover para `contracts/agent.py`**) |
| `GET` | `/api/households/{id}/agent/actions/{aid}` | `AgentActionView` (`action`, `execution` ou `null`, `origin`, `device_name`, `message` PT honesta por estado; **SIMULADO** etiquetado) · `404 action_not_found` (inexistente, de outra casa **ou de outro residente**) |
| `POST` | `/api/households/{id}/agent/actions/{aid}/confirm` | **único ponto onde uma ação é executada.** Faz COMMIT de `proposed → confirmed` e só depois chama o executor, no máximo **uma vez**; devolve `AgentActionView` com `execution`: `confirmed` só com **releitura**; `uncertain` (prazo, exceção, resultado inválido: **nunca se repete**) ou `blocked` (`executor_unavailable`, `cooldown`, `hourly_limit`, `uncertain_lockout`: o executor não é chamado). Casa demo: executor SIMULADO, nunca hardware · `404 action_not_found` · `409 action_not_pending` (já confirmada/rejeitada/executada) · `409 action_expired` |
| `POST` | `/api/households/{id}/agent/actions/{aid}/reject` | `AgentActionView` (`rejected`); nada é executado · `404 action_not_found` · `409 action_not_pending` · `409 action_expired` |
| `GET` | `/api/households/{id}/notifications?status&scope&limit` | `[NotificationView]` (`limit` 1..100); só pessoais do próprio e da casa; o senhorio só recebe os tipos da allow-list (hoje `info`); operador `403 forbidden_role` · `404 household_not_found` (não-membro) (**Conta Certa, P3**) |
| `POST` | `/api/households/{id}/notifications/{nid}/read` | `NotificationView`; recibo por residente · `404 notification_not_found` · `403 forbidden_role` |
| `POST` | `/api/households/{id}/notifications/{nid}/respond` | corpo `NotificationRespondIn` `{ "action_id": "mine"\|"other"\|"everyone"\|"unknown", "target_resident_id"?: uuid }` → `NotificationView` (com `voting`, votos anónimos); só inquilino elegível; **votação D-32**: um voto por pessoa, fecha quando a regra decide · `404 notification_not_found` · `403 forbidden_role` · `409 already_responded` (já votou ou votação fechada) · `409 notification_expired` · `400 invalid_request` (ação ou alvo inválido) |
| `GET` | `/api/households/{id}/notification-preferences` | `NotificationPreferences` do próprio (por pessoa) · `403 forbidden_role` · `404 household_not_found` |
| `PUT` | `/api/households/{id}/notification-preferences` | por casa; corpo `{ quiet_hours, disabled_kinds }` → `NotificationPreferences` · `400 invalid_request` (ex.: desligar `security_alert`) · `403` · `404` |
| `POST` | `/api/households/{id}/bills/preview` | corpo `BillIn` → `BillPreview` (preço médio derivado, dias, parcela de energia); **não grava**: é a validação humana antes de confirmar. Só senhorio (`403` inquilino/operador) · `422 bill_inconsistent` com a razão (Conta Certa, P4, BILL-01) |
| `POST` | `/api/households/{id}/bills` | corpo `BillIn` → `201 BillView` em `draft`; grava e emite `billing.bill_created` na mesma transação. Recusa (`422 bill_inconsistent`): período por terminar ou > 62 dias, fixa ≥ total, preço médio fora de 0,01–1,00 €/kWh, tarifa declarada que não fecha (folga 1 %, mín. 5 cêntimos), período sobreposto, fatura simulada numa casa real. Campos extra/em falta: `400` |
| `GET` | `/api/households/{id}/bills` · `/api/households/{id}/bills/{bill_id}` | `[BillView]` / `BillView`; senhorio vê todas, inquilino só `finalized` e `superseded` (revisões antigas, para auditoria) (rascunho → `404 bill_not_found`); operador `403`; sem autor nem ids de terceiros |
| `POST` | `/api/households/{id}/bills/{bill_id}/finalize` | Senhorio. Fecha o rascunho: expira pedidos de confirmação vencidos, reparte (consumos fechados iniciados no período com atribuição ativa; o resto no resíduo), grava as parcelas (imutáveis) e emite `billing.bill_finalized` + `billing.allocation_published` na mesma transação → `BillView`. `409 bill_finalized` se repetido (nada duplica) · `422 bill_inconsistent` (kWh atribuídos acima da fatura) · `404 bill_not_found` (BILL-04) |
| `POST` | `/api/households/{id}/bills/{bill_id}/revisions` | Senhorio, corpo `BillIn` → `201 BillView`: nova revisão já fechada; a anterior fica `superseded` com as suas parcelas · `409 bill_not_finalized` (rascunho) · `422` |
| `GET` | `/api/households/{id}/bills/{bill_id}/summary` | Só senhorio → `LandlordBillView` (totais por quarto; nunca aparelhos, horários, presença nem ids de moradores) · `403` a inquilino/operador · `404` se não fechada |
| `GET` | `/api/households/{id}/bills/{bill_id}/receipt` | Só inquilino → `BillAllocation` própria (linhas, kWh por proveniência) · `403` senhorio/operador · `404` se não fechada ou sem parcela |
| `GET` | `/api/households/{id}/bills/{bill_id}/receipt/explanation` | Só inquilino → `ReceiptExplanation` (BILL-05): os meus consumos da medição à parcela (`steps`), conta comum agregada sem horas nem pessoas, resíduo e consumos sem decisão no fecho, `equal_split_cents`. Reconcilia ao cêntimo com o recibo; `evidence_available=false` em faturas fechadas sem evidência guardada. Quem decidiu: `me`/`housemates`/`system`, nunca ids de terceiros · `403` senhorio/operador · `404` se não fechada ou sem parcela |
| `POST` | `/api/households/{id}/bills/{bill_id}/contestations` | Só inquilino, corpo `ContestationIn` `{ reason, consumption_event_id? }` → `201 Contestation` (BILL-06). Só o próprio recibo de uma fatura em vigor; o consumo tem de lhe estar atribuído nessa fatura · `400 invalid_request` · `409 contestation_open` (já tem uma aberta) · `409 bill_not_finalized` (fatura substituída) · `404` rascunho/sem parcela · `403` senhorio/operador |
| `GET` | `/api/households/{id}/contestations/mine` | Só inquilino → `Contestation[]` próprias (estado, justificação, `before_cents`/`after_cents`, `revision_bill_id`) |
| `GET` | `/api/households/{id}/contestations` | Só senhorio → `LandlordContestationView[]`: quarto, motivo, decisão e antes/depois; nunca o consumo, aparelho, horas nem ids de moradores |
| `POST` | `/api/households/{id}/contestations/{contestation_id}/decision` | Só senhorio, corpo `ContestationDecisionIn` `{ status: accepted\|rejected, resolution, bill? }` → `LandlordContestationView` (a mesma vista da lista: quarto, nunca o consumo nem o morador). Aceitar reemite a fatura como nova revisão (consumo contestado → conta comum; `bill` corrige dados) · `409 contestation_resolved` · `404 contestation_not_found` · `422 bill_inconsistent` · `400` `bill` ao rejeitar |
| `GET` | `/api/households/{id}/rules` | Senhorio e inquilinos → `HouseRulesView` (HOUSE-04): `current` (versão em vigor hoje; `effective_from=null` = política inicial da casa), `proposal` (`RuleProposalView`: a proposta aberta com contagens `approvals`/`rejections`/`eligible`/`needed`, o meu voto `my_vote` e `proposed_by_me`; nunca quem votou o quê), `upcoming` (mudança agendada ou `null`), `history` (versões que já valeram, mais recente primeiro) e `next_change_from` (dia 1 do mês seguinte) · `403` operador |
| `PUT` | `/api/households/{id}/rules/next` | Só inquilino ativo, corpo `HouseRulesIn` `{ common_area_rule, ask_threshold_cents, ask_timeout_hours }` → `HouseRulesView`. **Propõe** a regra para o dia 1 do mês seguinte (substitui a proposta aberta, sem herdar votos); quem propõe conta como «sim». Só fica agendada (`upcoming`) quando pelo menos metade dos moradores com contrato ativo aprova (`proposal.needed`); com 1 morador é imediata. Evento `billing.rules_proposal_changed` · `400 invalid_request` (`presence` ainda não existe; regra igual à que já vai valer) · `403` senhorio/operador |
| `POST` | `/api/households/{id}/rules/next/vote` | Só inquilino ativo, corpo `RuleVoteIn` `{ approve }` → `HouseRulesView`. Vota na proposta aberta (pode mudar o voto até à decisão). Maioria → agendada; maioria impossível → `rejected`; mês começado sem maioria → `expired` (também pela tarefa periódica) · `400 invalid_request` sem proposta aberta · `403` |
| `DELETE` | `/api/households/{id}/rules/next` | Só quem propôs → `HouseRulesView`. **Retira** a proposta aberta. Uma mudança já aprovada só se desfaz com outra proposta aprovada · `400 invalid_request` sem proposta aberta · `403` outro morador, senhorio ou operador |
| `GET` | `/api/households/{id}/budgets/me?period=YYYY-MM` | Só inquilino → `BudgetStatus`: objetivo do mês e gasto com **todos os custos** (D-31): consumo próprio (`confirmed_cents`), parte igual da conta comum (`shared_cents`) e parte do termo fixo + resíduo estimada pelo último recibo (`base_cents`, `null` sem recibo anterior). Sem preço nem fatura: `spent_cents=null` (desconhecido, nunca 0 €). Com a fatura do mês fechada: `final=true` e valores reais. `light` (ALERT-06): cor da lâmpada do quarto `{light: green|amber|red, color, rgb, label}` ou `null` sem orçamento/gasto. `forecast` (ALERT-02): `{cents, low_cents, high_cents, observed_days}` ou `null` (mês sem dados, < 3 dias observados ou fatura fechada) · `403` senhorio/operador (ALERT-01) |
| `PUT` | `/api/households/{id}/budgets/me` | Só inquilino, corpo `BudgetIn` `{ limit_cents, period?, thresholds? }` → `BudgetStatus`. Redefinir = reset explícito dos avisos; avalia logo e pode emitir `alerts.threshold_crossed` · `400 invalid_request` (mês passado, limiares fora de ordem, limite 0) |
| `GET` | `/api/households/{id}/tariff` | Senhorio e inquilinos → `TariffStatus` `{tariff: {kind: simple\|bi_hourly, price_millicents_per_kwh, offpeak_price_millicents_per_kwh}\|null, source: configured\|reference\|last_bill\|null}`: a tarifa usada nas estimativas (ALERT-02) · `403` operador |
| `PUT` | `/api/households/{id}/tariff` | Só senhorio, corpo `TariffIn` → `TariffStatus`. Bi-horário: vazio 22h–08h e fim de semana. Só muda estimativas (orçamento, previsão), nunca faturas; reavalia logo os orçamentos do mês · `400` (preço de vazio só e sempre no bi-horário; > 1,00 €/kWh) |

### `HomeState`

```json
{ "mode": "leitura", "mode_name": "Modo leitura", "state": "em_espera", "presence": null,
  "camera_ok": true, "mcp_ok": false, "backend": "fake",
  "waiting_remaining_seconds": 7.5, "energy_saved_wh": 12.5, "energy_saved_eur": 0.002,
  "updated_at": "2026-11-17T15:20:00Z", "casa": { "…": "EstadoCasa" } }
```

| Campo | Significado |
|---|---|
| `mode`, `mode_name` | `id` e `nome` da regra ativa; `null` sem modo |
| `state` | `inativo` · `ativo` · `em_espera` · `suspenso` |
| `presence` | `null` = ainda sem dados da visão |
| `mcp_ok`, `backend` | cópias de `casa`; com `fake`, `mcp_ok` é sempre `false` e a UI mostra **SIMULADO** |
| `waiting_remaining_seconds` | só em `em_espera`, no instante `updated_at`; a UI conta localmente |
| `energy_saved_wh` / `_eur` | **estimativa** desde o arranque do servidor (W da tomada ao suspender × horas suspensas × `TARIFA_EUR_KWH`); não conta com consumo desconhecido |
| `casa` | `EstadoCasa`; `null` só se a leitura falhar |

### `EventLogItem`

`{ id, timestamp, level, message, source }` — `level`: `info` | `warning` | `error`; `source`: backend da casa no momento. Só texto. Eventos injetados por `/api/simulate` levam `[SIMULADO]` na mensagem. Em memória ficam os últimos 50; `events.jsonl` guarda o histórico.

### `OffResult`

```json
{ "success": true, "state": "inativo", "backend": "fake",
  "devices": { "lampada": "off", "tomada": "off" }, "code": null, "message": null }
```

`devices.*` é `off` (confirmado) ou `unknown`. `code`: `partial_failure` (um falhou) ou `mcp_unavailable` (nenhum confirmado; `message` diz porquê). A UI só mostra sucesso com `success: true`.

### `ParseResponse` (NVIDIA)

`{ proposal: Rule, summary, replaces }`. **Não grava nem executa.** O `summary` é gerado pelo backend a partir da regra validada. Se o `id` já existir acrescenta-se `-2`, `-3`… `replaces` = nome da regra ativa do mesmo objeto que será desativada ao gravar. O modelo só recebe o texto e o schema; nunca imagens, histórico ou tokens. O frontend grava a proposta aceite com `enabled: false`; a ativação é um passo explícito.

### Erros

```json
{ "error": { "code": "rule_not_found", "message": "Regra não encontrada" } }
```

| HTTP | `code` | Quando |
|---|---|---|
| 400 | `invalid_request` | validação; a mensagem indica os campos (nunca os valores) |
| 400 | `rule_not_supported` | pedido de regra fora do suportado (a mensagem explica) |
| 401 | `http_401` | sem token ou token inválido/expirado |
| 403 | `simulation_disabled` | `/api/simulate` com `HOME_BACKEND=mcp` |
| 404 | `rule_not_found` | |
| 500 | `internal_error` | erro não previsto (sem detalhes) |
| 502 | `invalid_proposal` · `http_502` | o modelo falhou duas vezes · MCP indisponível em `/api/mcp/tools` |
| 503 | `nvidia_unavailable` · `http_503` | sem chave/rede NVIDIA · sem fonte de vídeo |

## 3. WebSocket `WS /api/ws`

```json
{ "type": "home_state", "data": HomeState }
{ "type": "event",      "data": EventLogItem }
{ "type": "error",      "data": { "code": "unauthorized", "message": "Não autenticado" } }
```

1. O cliente abre a ligação e envia, em 5 s, `{"type":"auth","token":"<access_token>"}`. **Nunca token no URL.**
2. Token inválido: `error` e fecho com código **1008**. O cliente renova a sessão uma vez; se falhar volta ao login (sem ciclo de reconexões).
3. Token válido: `home_state` imediato; depois um `event` por linha nova do registo e um `home_state` completo a cada mudança.
4. Outras mensagens do cliente são ignoradas. Sem heartbeat. Em queda, o cliente reconecta com backoff (1 s → 15 s) e recebe um snapshot novo; o histórico recupera-se por `GET /api/events`.
5. Cliente lento: fila de 200 mensagens por ligação; as mais antigas são descartadas (o `home_state` seguinte repõe o estado).

## 3b. Modelos partilhados no OpenAPI (Conta Certa, F0)

Além dos modelos das rotas, `app.openapi()` inclui os de `contracts/api.py::OPENAPI_MODELS` (`install_shared_schemas`, `core/openapi_models.py`), sem rotas falsas: `HouseholdView`, `MemberView`, `MeContext`, `DeviceView`, `Appliance`, `EnergyReading`, `ConsumptionEvent`, `EnergySummary`, `PersonPresence`, `Attribution`, `ElectricityBill`, `BillAllocation`, `LandlordBillView`, `Budget`, `Contestation`, `NotificationView`, `NotificationPreferences`, agente e automações, `Provenance`, `ApiErrorBody` e os enums. **Não** entram `Device`, `Resident`, `Membership`, `ApplianceSignature`, `PresenceEvent`, `ConfirmationRequest` nem os eventos de domínio (dados privados). Os schemas e rotas existentes não mudaram (verificado por diferença com o OpenAPI anterior). Respostas: campos com valor por omissão são obrigatórios (`null` ≠ ausente), por isso o TypeScript gerado não os marca opcionais. Erros novos: [contracts.md](contracts.md) §8.

## 4. Extensões propostas e não implementadas

Existem só no mock do frontend, nunca no backend; não as apresentar como reais.

- `EventLogItem` com `category`, `correlation_id`, `details`, `result` (opcionais nos tipos do frontend).
- Memória e sugestões de rotinas (`MemorySnapshot`, `RoutineSuggestion`): issues #30/#31, fora do MVP.
- Diagnóstico da câmara (FPS, latência) na API.
