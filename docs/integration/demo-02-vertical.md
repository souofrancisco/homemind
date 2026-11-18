# DEMO-02 #28 — revisão de integração vertical Conta Certa

**Auditoria:** 17/11/2026. **Base efetivamente lida:** `origin/main` em `76c16ce` (após #168–#170 e #172). **Branch:** `feat/demo-02-vertical-integration`. **Estado:** PARTIAL. Este relatório distingue código em `main`, código em PR e contratos/planos; issue fechada não foi usada como prova de integração.

> **Atualização 18/11/2026 (revisão dos PRs abertos, P4):** desde a auditoria entraram na `main` o **#174 ALERT-01** (orçamento e avisos, com o consumidor P3 `notifications.budget_threshold`), o **#141 APP-01** (shell e vistas por papel) e o **#144 DEMO-01** (dataset/reset/replay offline). O **#145 HOUSE-04 foi fechado sem merge**: duplicava o atribuidor P4 já integrado (#169: decisão quarto/sala, D-32, prazo e fallback); a política temporal versionada, se a equipa a quiser, entra como extensão do `features/billing/attributor.py`. As linhas abaixo marcadas com «(atualizado)» refletem isto; o resto é a auditoria original.

## 1. Estado real dos cinco módulos

### P1 — Bruno: MCP e energia

- **Na `main`:** MCP-02 (#139), MCP-03 (#155) e MCP-04 (#160). `EnergyCollector` converte leituras através de `reading_from_device`, conserva `None` quando os watts/unidade faltam ou estão inválidos e pode publicar `EnergyReadingRecorded`. `McpHome._aplicar_leitura` só o chama se alguém lhe atribuir `home.coletor`; a composição atual da app não o instancia nem o liga ao barramento F0. Os testes ligam-no explicitamente. MCP-03 lê sensores suportados. MCP-04 protege escritas; esta revisão não executou escrita física.
- **Fake:** PR #164 já está na `main` como `connectors/fake_mcp.py` (`FakeKit`), um simulador de sessão MCP. O `FakeHome` antigo continua a simular lâmpada/tomada, mas não alimenta o pipeline de energia Conta Certa. Nenhum dos dois substitui uma integração P1.
- **Na `main`:** PR #168 (#80) contém `features/energy/steps.py` e `consumer.py`: detetor de degraus e sessões ON/OFF, que podem emitir eventos de consumo. O tracker conserva sessões em memória; não há router/lifespan de produto a subscrevê-lo. A identificação fica `ApplianceMatch()` vazio/unknown.
- **Ainda sem motor entregue na `main`:** ENERGY-01 (#79), ENERGY-03 (#81), ENERGY-04 e ENERGY-05 (#83): assinaturas, classificação probabilística, aprendizagem e localização/resíduo. O catálogo temporal HOUSE-03 (#142) existe, mas P1 não o consulta. #168 cobre apenas ENERGY-02; a integração runtime continua por fazer.

### P2 — 1Mii: presença

- **Na `main`:** PRES-01/02/03/04 (#149/#151/#153/#159): estado da câmara e fontes, contagem anónima pela soleira, pistas Wi-Fi opt-in e fusão com tolerância. A presença individual é filtrada por `presence_opt_in`; o senhorio não lê estados individuais. O MAC é convertido em HMAC e não é persistido. A câmara não produz identidade. Câmara/clip de reserva são SIMULADOS; Wi-Fi pode ser `FakeWifiScanner` SIMULADO ou `ArpScanner` REAL no host. A ausência de Wi-Fi não produz `out`.
- “Presença manual” não significa check-in livre: o check-in foi removido. Uma resposta manual só surge quando o sistema pergunta “estás em casa?”, é guardada como pista e exige opt-in. `HouseOccupancy`/cruzamentos da porta são anónimos; não há reconhecimento facial nem gravação de frames.
- A fusão P2 pode consumir `energy.consumption_detected` para uma pista positiva do dono, mas a integração depende de um produtor P1 que ainda não existe na `main`.

### P3 — Rafael: notificações e assistente

- **Na `main`:** APP-02/03 (#156): tabelas SQLite, handler persistente `billing.confirmation_needed` → `notification.created`, listagem REST, leitura, resposta e preferências. A primeira resposta válida fica protegida por CAS. Para pedidos de confirmação, a resposta é um voto D-32, não uma decisão por “primeira resposta”. `notification.responded` é persistido na transação da resposta; a regra `confirmation_outcome` aplica limiar de metade, “É minha” imediato e empate/inconclusivo para todos.
- D-32 (#161) está no contrato e nos testes. O senhorio é removido da lista de elegíveis e não vê pedidos de confirmação. P3 tem varrimento periódico de expiração no lifespan (#170); P4 também expira pedidos de atribuição após 24 h e decide o fallback D-32. Não há canal WS de notificações: o `/api/ws` existente ainda pertence ao motor ObjectOS. GET REST permite recuperar a lista, mas não existe reconexão de notificações na UI.
- AGENT-01/02 (#154) e provider seam (#167) estão na `main`. As ferramentas do agente só leem; AGENT-03 (#171) acrescenta ações propostas que só executam após `POST …/confirm` (executor SIMULADO na casa demo), e o #198 junta o histórico por residente (`GET …/agent/messages`) e as propostas a partir de alertas de janela aberta (AGENT-03b). Os providers reais podem ser registados em `app.state.agent_providers`, mas não há provider P1/P4 registado pela composição; o fallback é SIMULADO apenas na casa de demo e casas reais não recebem valores simulados.

### P4 — Amorim: atribuição, orçamento e fatura

- **Na `main`:** BILL-01 (#163) permite pré-visualizar e gravar uma fatura como `draft`; a criação da linha e `billing.bill_created` são atómicas. BILL-04 (#172) adiciona fecho idempotente: a transação guarda alocações, finaliza a fatura e grava `billing.bill_finalized`/`billing.allocation_published` na outbox. Inquilinos só veem faturas finalizadas.
- **Na `main`:** BILL-02/04 (#152/#169/#172) fornece decisão e persistência de atribuições, repartição em cêntimos com reconciliação e fecho idempotente. D-34 (#162) usa desempate SHA-256 reproduzível com casa/período/morador. P3 (#170) consome recibos publicados e cria notificação.
- **Na `main` (atualizado):** ALERT-01 (#174): orçamento pessoal com todos os custos (D-31), gasto desconhecido sem preço, um aviso por limiar e consumidor P3 `notifications.budget_threshold`.

### P5: contratos, app e demo

- **Na `main`:** F0 #135 (contratos, SQLite, event store/bus, `processed_event`, RBAC e fixtures), HOUSE-02 #143 e HOUSE-03 #142. D-19/D-25 são respeitadas pelo bus: entrega pelo menos uma vez, handlers idempotentes, efeito e `processed_event` na mesma transação; `seq` ordena, `correlation_id` agrupa. Não há segundo barramento.
- HOUSE-04 (#145) **fechado sem merge (atualizado)**: duplicava o atribuidor P4 (#169). A política vem de `household` (F0); versionamento temporal fica como extensão futura do atribuidor.
- APP-01 (#141) e DEMO-01 (#144) **estão na `main` (atualizado)**. APP-01 entrega shell/contexto e vistas por papel, não páginas ligadas a notificações, energia, orçamento ou recibos. DEMO-01 fornece preparação/reset/replay offline, ainda não integrada na `main`.

## 2. Mapa obrigatório da integração

| Etapa | Produtor real | Contrato | Consumidor real | Estado | Bloqueio |
|---|---|---|---|---|---|
| 1. Leitura de potência | `McpHome._aplicar_leitura` → `EnergyCollector.ingest` → `reading_from_device`; `McpHome.coletor` é opcional e não ligado pela app | `EnergyReading`, `EnergyReadingRecorded` | `EnergyStepTracker`; consumer ainda sem subscrição de runtime | **PARCIAL** (#139/#168 na main) | Composição não liga MCP ao `EventBus`; leitura não percorre o produto |
| 2. Deteção de variação | #168 `PowerStepTracker.ingest/tick` | `PowerStep`, `EnergyStepDetected` | `make_step_consumer`; testes de bus em #168 | **PARCIAL (na main)** | Não está registado num lifespan; tracker em memória |
| 3. Identificação de aparelho | Nenhum motor entregue; #142 gere catálogo temporal | `ApplianceMatch`, `ApplianceSignature` | Nenhum classificador; #168 deixa `match` vazio | **PLANEADA** | ENERGY-01/03; catálogo não é classificador |
| 4. Encerramento de consumo | Tracker #168 consegue emitir ongoing/closed de sessões | `ConsumptionEvent`, `EnergyConsumptionDetected/Closed` | P4 `attributor.handle`; presença/segurança subscrevem alguns eventos | **PARCIAL (na main)** | P1 não está integrado no arranque; sem localização/dono confiáveis |
| 5. Consulta de catálogo histórico | HOUSE-03 `features/appliances/router.py` e `repo.py` | `Appliance`, `ApplianceSignature` temporal | Nenhum consumidor P1 consulta o catálogo | **IMPLEMENTADA, sem ligação** (#142) | Ligar consulta ao futuro classificador P1 |
| 6. Resolução de política | F0 `household.common_area_rule`; política temporal HOUSE-04 em #145 | `HouseholdPolicy` | P4 `attributor.handle` carrega política da casa | **PARCIAL (na main)** | Política temporal versionada: extensão futura do atribuidor (#145 fechado, atualizado) |
| 7. Pedido de confirmação | P4 `attributor.handle` ao consumir energia | `ConfirmationRequest`, `BillingConfirmationNeeded` | P3 consumer `billing.confirmation_needed` | **COMPATÍVEL (na main)** | Sem classificador/runtime P1, não há pedido derivado de aparelho real |
| 8. Persistência de notificação | P3 `NotificationService.on_confirmation_needed` e `CONFIRMATION_CONSUMER` | `Notification`, `NotificationCreated` | SQLite notification repository; REST GET da lista | **IMPLEMENTADA** (#156) | Só recebe se P4 publicar pedido; sem WebSocket |
| 9. Votação | P3 POST `/api/households/{id}/notifications/{id}/respond` | D-32, `NotificationRespondedData.outcome` | Bus persistente; P4 attributor consome resposta | **IMPLEMENTADA** (#156/#161/#169) | UI ainda não ligada |
| 10. Resolução da votação | D-32 `confirmation_outcome`; P4 `attributor._on_responded`/`expire_pending` | `ConfirmationOutcome`, `BillingAttributionChanged` | P4 attributor | **IMPLEMENTADA (na main)** | Falta integração P1 e E2E completo |
| 11. Atribuição financeira | P4 `attributor.handle` persiste atribuição | `Attribution` | P4 `closing.finalize` usa atribuições persistidas | **IMPLEMENTADA (na main)** | Sem classificação/localização P1, consumos de origem incompletos |
| 12. Orçamento | PR #174 `billing.budgets` avalia gasto e limiares | `Budget`, `BudgetThreshold`, `alerts.threshold_crossed` | Consumidor P3 `notifications.budget_threshold` (#174) | **IMPLEMENTADA (atualizado)** | Falta página de orçamento na UI |
| 13. Entrada da fatura | POST `/api/households/{id}/bills/preview` e POST `/bills` | `BillIn`, `BillView`; `billing.bill_created` | SQLite `billing_bill`; trace DEMO-02 pode observar o evento | **IMPLEMENTADA como draft** (#163) | Dados usados em demo/testes devem ter proveniência SIMULATED explícita |
| 14. Repartição | P4 `closing.finalize` chama `allocation.allocate` e `shares_from_attributions` | `BillAllocation`, D-34 | Transação de fecho e tabelas de alocação | **IMPLEMENTADA (na main)** | Precisa de consumos P1 classificados para valores reais de energia |
| 15. Publicação de recibos | P4 `closing.finalize` grava `billing.allocation_published` | `BillingAllocationPublished`, `BillAllocation` | P3 allocation consumer persiste notificação; endpoints P4 expõem alocações | **IMPLEMENTADA (na main)** | UI APP-01/02 ainda não apresenta recibos |
| 16. Exibição na aplicação | PR #141 shell/contexto, em review; P3 só backend REST | DTOs por papel, OpenAPI | Nenhuma página Conta Certa consome notifications/bills/receipts | **EM REVIEW / incompleta** | APP-01 não integra dados; faltam páginas de notificação, fatura e recibo |
| 17. Reset e replay offline | PR #144 runner; #164 `FakeKit` fornece sessão MCP simulada | Fixtures/dataset DEMO-01 | Nenhum runner DEMO-01 na main | **IMPLEMENTADA (atualizado, #144)** | Reset/replay ainda sem pipeline real de energia (ENERGY-03) |

`features/integration/router.py` continua propositalmente abaixo deste fluxo: lê eventos persistidos por `household_id` + `correlation_id`, não reconstitui payloads nem valida regras financeiras. `missing_event_types` indica apenas ausência de linhas para a correlação; não explica a causa e não é diagnóstico de saúde do negócio.

## 3. Compatibilidade e arquitetura híbrida

- **Compatível na `main`:** P4 consome eventos de consumo e publica confirmação; P3 persiste pedido/votos D-32; P4 resolve/atribui e fecha faturas; P3 consome eventos de recibos. As conexões P3↔P4 e fecho de P4 têm testes dos módulos de origem.
- **Compatibilidade testada:** a composição P3↔P4 foi exercitada com evento `EnergyConsumptionDetected` SIMULADO (sem NILM): P4 criou pedido, P3 persistiu notificação, a resposta REST “É minha” gerou D-32 e P4 persistiu `Attribution`. Resultado local: 1 teste passou. É teste P3↔P4, **não** E2E energético.
- **Compatibilidade #168/#169/#170/#172:** os módulos usam os contratos partilhados e a entrega at-least-once do bus; #168 não classifica aparelhos nem liga MCP/runtime. Nenhum handler artificial foi adicionado.
- **Híbrida confirmada:** BILL-01 e P3 gravam estado/eventos nas mesmas transações; fecho BILL-04 grava recibos/eventos atomicamente e é idempotente; EventBus entrega efeitos idempotentes. O bus não é ledger de dinheiro, e WS não confirma transação. D-32 e D-34 são obrigatórias.
- Não há segundo barramento, serviço de faturação, nem sistema de notificações criado por DEMO-02. O destino dos adaptadores é a composição de P1/P3/P4, por contratos e eventos F0.

## 4. Endpoint `integration/traces`

Mantido: é um diagnóstico técnico sem equivalente no API atual e útil para explicar uma correlação da demo. Não pode servir de prova de que o fluxo, a classificação ou a conta estão corretos.

- `GET /api/households/{household_id}/integration/traces/{correlation_id}` exige membership com papel `operator` via `Resource.device`; inquilino/senhorio recebem 403 e não membro 404.
- A consulta exige `household.source_kind == demo`; uma casa real recebe 403 `demo_only`. Os predicados da query incluem simultaneamente `household_id` e `correlation_id`.
- DTO devolve só tipo/etapa de evento, seq, instante e proveniência. Exclui `payload_json`, ids de moradores/dispositivos, potência, texto de notificação, valores financeiros, IDs MCP e segredos.
- GET não publica nem altera dados. Correlação sem eventos responde 200 com `events=[]` e a lista de tipos sem linha nessa correlação. `evidence_level=persisted_events_only` e nomes de etapas terminados em “persisted/event” limitam a afirmação ao que está guardado. `notification.responded` aparece como resposta persistida, não como votação decidida; `billing.bill_created` é “bill_recorded”, porque BILL-01 só cria drafts.
- Testes cobrem sem autenticação, papéis, casa de outra pessoa, casa real, trace vazio, evento duplicado, não escrita em GET, payload privado ausente, correlação isolada e criação de fatura draft real → evento → trace. Não consulta hardware ou outro serviço.

## 5. DEMO-01 e APP-01 em worktrees isolados

PR #141 e #144 entraram na `main` depois desta auditoria (atualizado). Não foi copiado código para DEMO-02.

- #141 foi combinado com a `origin/main` em `76c16ce` num worktree de auditoria e `make check` passou: 1212 testes, 1 ignorado, lint, geração OpenAPI/TS, build frontend e Compose config. Demonstra compatibilidade de build, não integração de notificações/faturas/recibos. O build emite o aviso Vite de chunk >500 kB.
- #144 foi combinado com a `origin/main` em worktree próprio. A união dos alvos `.PHONY` do Makefile foi resolvida só nesse worktree de teste; `make check` passou: 1225 testes, 1 ignorado e restantes passos de lint/build/Compose. O conflito de Makefile deve ser resolvido no PR #144 antes do merge. A aprovação do check não prova o fluxo de energia Conta Certa.

## 6. Testes e evidência desta revisão

- Base anterior + branch DEMO-02: `make check` passou com 1090 passed, 1 skipped; esta execução antecedeu a chegada de #168–#170/#172.
- Alteração DEMO-02: `make check` passou sobre a base `76c16ce`: **1219 passed, 1 skipped**, Ruff, frontend lint, geração OpenAPI/TS, build frontend e Compose config. Os 7 testes de trace incluem BILL-01 draft real → evento → trace; privacidade, autorização, correlação e GET sem escrita.
- PR #168 isolado: testes de `features/energy/tests` — 45 passed.
- PR #169 com notificações da main: attributor + handlers + votação — 52 passed; teste isolado de composição P3→P4 acima — 1 passed.
- #141/#144: checks de compatibilidade descritos na secção anterior. `make smoke` passou sobre esta base em Compose isolado, com backend, frontend e Authentik saudáveis. Smoke de configuração demo, sem MCP/hardware físico. Os warnings de `TestClient` são depreciação de `anyio` no Starlette.
- CI GitHub: não foi publicado run para os commits finais do PR; o último run bem-sucedido listado é do SHA antigo `288b53a`, portanto não o conto como validação desta revisão. `make check` local passou no código, e os commits posteriores foram apenas documentação.
- Não se executou o ciclo completo energia → aparelho → voto → orçamento → fatura final → recibos, nem se inventou valor/resultado. Nenhum teste chama motor NILM por trás de um nome E2E.

## 7. Ordem de integração e bloqueios para E2E

PRs já integrados relevantes: #135, #139, #142, #143, #149, #151, #152, #153, #155, #156, #159, #160, #161, #162, #163, #164, #167, #168, #169, #170, #172.

PRs que ainda precisam de entrar na `main` ou ser concluídos para a demo:

1. **P1 ENERGY-01/03/04/05 + runtime MCP→bus→tracker** — assinatura/classificador probabilístico, localização, composição do tracker e publicação de consumos reais; não reimplementar em DEMO-02.
2. ~~#145 HOUSE-04~~ — fechado (duplicava #169); versionamento temporal, se necessário, no atribuidor P4.
3. ~~#174 ALERT-01~~ — na `main` (sem preço o gasto é desconhecido, testado).
4. **#141 APP-01 + páginas APP-02/03/recibos/orçamento** — ligar REST; depois decidir WS/reconexão de notificações.
5. ~~#144 DEMO-01~~ — na `main`.
6. Executar em conjunto com proveniência SIMULATED visível, duas casas distintas, isolamento por papel, duplicados, votos/timeout, draft/finalized, reinício, offline/replay e soma exata; depois validar hardware real conforme o guia.

## Classificação

**PARTIAL.** O endpoint seguro e F0 são úteis; P3 e P4 já têm confirmação, atribuição, fecho e publicação de recibos compatíveis na `main`. O circuito completo ainda não é executável a partir de leituras reais: falta classificador e runtime P1 e UI integrada (ALERT-01 já está na `main`). DEMO-02 permanece aberta e este relatório não declara a demo concluída.
