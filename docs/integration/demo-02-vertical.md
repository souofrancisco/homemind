# DEMO-02 #28 — Auditoria e integração vertical Conta Certa

**Data da auditoria:** 17/11/2026. **Base:** `main` em `83342f605b10821174b0a53d102baf32624a1f47`. **Estado:** PARCIAL / BLOQUEADO. **Branch:** `feat/demo-02-vertical-integration`. Não é evidência de MVP completo.

## 1. Evidência verificada e limites

| Componente | Fonte efetivamente inspecionada | Estado |
| --- | --- | --- |
| F0: SQLite, migrações, `EventBus`, `processed_event`, RBAC, OIDC, OpenAPI e fixtures | `core/db.py`, `core/events.py`, `core/access.py`, `features/households/`, `contracts/`; PR #135 merged | **Código implementado**; testes da F0 existentes, não reexecutados nesta auditoria |
| HOUSE-02 #85 | Há consultas de memberships e papel por Authentik; rota de escrita incompleta | **Parcial** |
| HOUSE-03 #86 e HOUSE-04 #87 | Há contratos de aparelhos e política `HouseholdPolicy`; não existem serviços de catálogo ou motor de políticas | **Contratos, sem motor** |
| MCP-02 #75 e MCP-05 #78 | Existem `McpHome`, `FakeHome` herdados, mas não um coletor F1 tipado nem dataset DEMO-01 integrado | **Parcial/pendente** |
| ENERGY-01 #79, -02 #80, -03 #81, -05 #83 | Modelos `EnergyReading`, `ConsumptionEvent`, assinaturas, match, localização; sem `features/energy` | **Contratos, sem motor** |
| APP-01 #94, -02 #95, -03 #96 | React/TS/Mantine e Authentik existem, mas a aplicação da `main` ainda expõe ecrãs ObjectOS; sem ações de confirmação Conta Certa | **Parcial/pendente** |
| BILL-01 #89, -02 #90, -04 #92 | Modelos, `validate_allocations` e fixtures A/B, sem `features/billing` ou fecho persistente | **Contratos, sem motor** |
| ALERT-01 #100 | Contratos de orçamento/limiares, sem serviço de orçamento | **Contratos, sem motor** |
| DEMO-01 #121 | `contracts/fixtures.py` (F0), não um runner resetável DEMO-01 | **Base de dados ilustrativa, sem harness** |
| DEMO-02 #28 | `tests/test_foundation_scenario.py` usa stand-ins explícitos de P3/P4 | **Teste de contratos, NÃO E2E do produto** |
| Contratos de presença P2 | PR #138 aberto, proposta D-31 não integrada | **Revisão pendente** |

**Ramos em paralelo no momento da auditoria:** `feat/demo-01-dataset`, `feat/app-01-shell`, `feat/house-02-memberships`, `feat/house-03-appliance-catalog`; sem commits novos relativamente à `main` no momento da consulta (o último estava 2 commits atrás). Não incorporar trabalho não publicado nem modificar ownership dos colegas.

## 2. Decisão: arquitetura C híbrida

Sem microserviços. Um processo FastAPI, serviços do domínio, SQLite e o barramento F0.

| Estratégia | Consistência financeira | Reexecução/idempotência | Debug, latência e custo para a hackathon |
| --- | --- | --- | --- |
| A: eventos para tudo | Ordem e causalidade mais difíceis de provar | `processed_event` resolve duplicados por consumidor, não garante comando financeiro único | Boa desacoplagem, mas exige correlação/retries até para respostas interativas |
| B: serviços síncronos | Mais simples para `respond` e `finalize` transacionais | Índices únicos e CAS na BD; evento/outbox por mutação | Depuração fácil, mas recuperação de reações secundárias exigiria trabalho adicional |
| **C: híbrida (escolhida)** | **Transação local síncrona** é a fonte da verdade | **CAS/unique + eventos persistidos** e consumidores idempotentes | Imediata para UI, recuperável após crash, compatível com F0/SQLite/FakeHome |

### Fronteiras síncronas

1. `GET /api/me/context` verifica utilizador e membership ativa (já existe).
2. P1 publica episódios e classificação `ApplianceMatch`; nunca atribui quem paga.
3. P4 aplica a política da casa e **na mesma transação** persiste a necessidade de confirmação ou atribuição (a implementar por P4).
4. P3 grava notificação e resposta com *compare-and-set*, devolvendo `409` para segunda resposta válida; `unknown` não é uma confirmação conclusiva (a implementar por P3).
5. P4 aplica efeito por `consumption_event_id` com índice único de atribuição ativa; fatura fechada é imutável com revisão explícita (a implementar por P4).
6. O fecho valida `sum(allocation.amount_cents) == bill.total_cents` em cêntimos inteiros **antes** de efetivar o estado.

### Fronteiras assíncronas

- Leitura/ciclo de consumo: `energy.reading_recorded`, `energy.consumption_detected`, `energy.consumption_closed`.
- Pedido e resposta persistidos: `billing.confirmation_needed`, `notification.created`, `notification.responded`.
- Atualização financeira: `billing.attribution_changed`, `billing.bill_finalized`, `billing.allocation_published`.
- Orçamento: `alerts.threshold_crossed` é um aviso de limiar, **não** prova que o total de orçamento tenha sido atualizado.
- REST é a fonte após refresh/reconexão WS. Um WS não é um ledger e não confirma transação.

**Garantia correta:** pelo menos uma vez na entrega de eventos; uma só mutação financeira efetiva por chave de negócio, protegida por transação e unicidade. Nunca afirmar `exactly-once` ponta a ponta.

## 3. Grafo de dependências para um fluxo real

```text
Authentik → /api/me/context (F0, pronto)
         → Household/Room/Membership (F0 parcial; HOUSE-02/03)
MCP read-only / FakeHome (MCP-02/05) → P1 amostragem/episódios (ENERGY-01/02)
    → P1 classificação e localização (ENERGY-03/05)
    → P4 política (HOUSE-04) → P4 confirmação necessária (BILL-02)
    → P3 inbox/resposta (APP-02/03) → P4 atribuição e fallback (BILL-02)
    → P4 orçamento (ALERT-01) → P4 fatura/reconciliação (BILL-01/04)
    → P5 ecrãs REST/WS (APP-01/02/03/06) → recibo filtrado por papel
                      ↑
               DEMO-01 dataset + reset independente
```

**Portas de integração obrigatórias para o review dos PRs:** identificador idempotente `event.id`; `correlation_id` propagado sem ser usado para ordenação; `consumption_event_id` como chave de negócio; `household_id` isolado; `Provenance{origin,kind}` preservada; contratos DTO próprios; `404` para não membro e `403` para papel indevido; `origin=simulated` nunca entra numa casa real; nenhuma operação física MCP; nenhuma identidade pessoal inferida de posse de aparelho.

## 4. Código entregue nesta branch

`features/integration/router.py` acrescenta **apenas** `GET /api/households/{household_id}/integration/traces/{correlation_id}`.

- Exige Authentik e membership ativa de **operador**; inquilino/senhorio proibidos e não membro recebe 404.
- Exige `source_kind=demo`; nunca diagnostica casas reais.
- Consulta apenas `domain_event` persistido por `household_id` e `correlation_id`, ordenado por `seq`.
- Devolve unicamente etapa, tipo, seq, hora de registo e proveniência; **nunca `payload_json`**, ids de moradores, potência ou valores individuais.
- `evidence_level=persisted_events_only` explícito. Eventos de stand-ins contam como eventos observados, **não** como implementação de P1/P3/P4.
- GET sem efeitos, sem rede e sem MCP. Não há ingestão artificial, nova tabela, dado financeiro inventado ou alteração dos contratos de colegas.

Testes adicionados: vazio honesto, eventos duplicados, resposta sem payload/sem escrita, Authentik falso **apenas no teste**, isolamento por papel/casa e recusa de casa real. Ainda faltam os E2E de produto.

## 5. Critérios E2E / estado da evidência

| Caso solicitado | Situação |
| --- | --- |
| Fluxo feliz completo e duas execuções | **BLOQUEADO** até P1, P3, P4, P5 e DEMO-01 |
| Dois aparelhos semelhantes; desconhecido | **BLOQUEADO** por ENERGY-03 |
| `mine`, `everyone`, `unknown` | **BLOQUEADO** por APP-03/P3 e BILL-02/P4 |
| Timeout e duplo clique | **BLOQUEADO** por persistência CAS de P3 |
| Eventos duplicados, reinício | Infraestrutura F0 coberta por testes existentes; **não** prova produtos |
| WS desligado/reconectado; refresh | **BLOQUEADO** por APP-02/03 |
| Dispositivo indisponível, sem internet | **BLOQUEADO** pelo harness e collector; não simular sucesso |
| Troca de casa e acesso de senhorio | Guardas F0 presentes; DTOs específicos de faturação **pendentes** |
| Soma exata da fatura | `validate_allocations` + fixtures A/B existentes; fecho real **pendente** |
| Reset da demo e segunda execução sem resíduos | **BLOQUEADO** por DEMO-01 e módulos de persistência |
| Offline completo, zero escritas físicas | Código novo é read-only/offline; demo completa **não verificada** |

## 6. Guião pretendido (não confundir com teste executado)

1. Arrancar stack local e DEMO-01; resetar exclusivamente a BD de **demo**, nunca casas reais.
2. Autenticar Carla no Authentik local e escolher a casa via `/api/me/context`.
3. FakeHome reproduz sequência de chaleira/tomada agregada e aquecedor do Bruno, na sala; P1 preserva `location=common` e a confiança.
4. P4 aplica a política B e solicita confirmação; P3 persiste notificação elegível a Carla; Carla seleciona `mine`.
5. Duplo clique/reenvio causa `409`, sem duplicar atribuição. Testar `everyone`, `unknown` e timeout em execuções isoladas.
6. P4 gera orçamento e **fatura ilustrativa** de 12 000 cêntimos. **Nunca** inserir esse valor no código de produção.
7. P5 mostra dados REST reais dos motores, rótulo SIMULADO, recibo privado, vista agregada de senhorio; conferir `Σ recibos = 120,00 €`.
8. Consultar o trace como operador técnico para explicar onde falha um evento, nunca como prova de correção dos cálculos.
9. Resetar, repetir o percurso e comparar contagens/unicidades. Verificar funcionamento sem internet externa e sem chamadas de escrita MCP.

Os exemplos de fatura continuam distintos: **A (§7.1)** = 45,12 / 29,76 / 24,64 / 20,48 €; **B (três regras)** = 46,80 / 27,60 / 24,40 / 21,20 €. Ambos fecham 120 €, são dados do documento e não resultados de cálculo de produção.

## 7. Qualidade, tempos e bloqueios

- **CI GitHub Actions**: `make check` **PASSOU** no commit `423e00645fe7a3bb48f10ec8cdbf3897ec66387a` ([run #44185597864](https://github.com/souofrancisco/homemind/actions/runs/44185597864)): `ruff check`/`ruff format --check` (120 ficheiros formatados), ESLint, `pytest` (**384 passed, 1 warning**), OpenAPI→TypeScript, `tsc -b`, build Vite e `docker compose config -q`. Isto valida o código e contratos, **não** demonstra o fluxo financeiro de ponta a ponta.
- **Execução local / smoke Docker com containers**: **NÃO EXECUTADOS** nesta sessão; não existe checkout autorizado do repositório privado no ambiente local desta execução. O smoke e os E2E com dataset DEMO-01 continuam por fazer.
- **Tempos medidos:** nenhum. Não são inventados p50/p95 nem sucesso de demo.
- **Segurança:** sem alterações a MCP, tokens, imagens, regras de domínio ou base real; nenhuma escrita física efetuada.
- **Próximo merge:** aguardar as PRs dos módulos; verificar os contratos efetivos; ligar serviços reais, testes E2E do produto, OpenAPI/UI e runner DEMO-01 numa atualização deste Draft PR; não assinalar #28 concluída antes disso.
- **Sem Telegram** e sem microserviços.
