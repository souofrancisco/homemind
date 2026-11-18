# features/agent — assistente na app (AGENT-01 registo, AGENT-02 ciclo, AGENT-03 ações)

Refs #110, #111 e #112. Detalhe e pedidos pendentes em [`docs/modules/agent.md`](../../../../../../docs/modules/agent.md).

## IMPLEMENTADO

`POST /api/households/{household_id}/agent/messages` (`AgentMessageIn` → `AgentResponse`). Só
inquilinos (`require_access(Resource.agent, write)`); senhorio e operador 403, não-membro 404. O
residente e o papel vêm do token. Ferramentas só de leitura; todos os números vêm delas; sem LLM
(ou com resposta não fundamentada) há um recurso determinístico. A leitura não tem eventos.

`GET …/agent/messages?limit=1..100` (#111) devolve o histórico do **próprio** residente (`list[AgentMessage]`,
cronológico); cada `POST` grava a troca. Dados pessoais, retenção curta (50 mensagens e 30 dias por
residente, P-25; `history.py`, tabela `agent_message` da `0311`). **Nunca** é enviado ao LLM (P-06).

| Ficheiro | O quê |
|---|---|
| `router.py` | Os endpoints `POST`/`GET …/messages`; `get_complete` (dependência: `None` salvo `AGENT_LLM_ENABLED` e `NVIDIA_API_KEY`) |
| `simulated.py` | **SIMULADO**: `SimulatedProviders` (valores de `contracts/fixtures.py`, só casa demo com `source_kind='demo'`) e `EmptyProviders` (sempre sem dados) |
| `tools.py` | `ToolRegistry`: só leitura; residente do contexto; só moradores; sem dados → `no_data`; erro do fornecedor → `provider_error` (log só com o tipo) |
| `providers.py` | `Protocol` `ConsumptionProvider`, `BudgetProvider`, `ReceiptProvider` (P4/P1 implementam); `ProviderSet` e `REGISTRY_ATTR` |
| `sources.py` | Escolha dos providers por ferramenta e casa (ver «Providers»); `get_registered`, `resolve` |
| `assistant.py` | `Assistant.reply`: ação e senhorio → resposta fixa; ciclo JSON com `max_steps`, timeout, correções e rodapé `Fonte:`; `fallback_reply` |
| `guardrails.py`, `formatting.py`, `prompt.py` | Números inventados e pedidos de ação; texto PT-PT determinístico; prompt |
| `history.py` | Histórico por residente: `record_exchange` (grava a troca e corta por número e idade) e `list_messages` |
| `llm.py`, `config.py` | `nvidia_complete`, `extract_json`; `AgentSettings` (`agent_llm_enabled=False` por omissão: P-06 pendente) |

**Limite dos dados SIMULADOS:** só cobrem o período `2026-11` (fixtures). O período por omissão é o
mês corrente, por isso a partir de 1 de dezembro de 2026 a resposta é «Não tenho dados» até
existirem os *providers* reais de P4.

Prazos: cada chamada ao LLM tem `AGENT_LLM_TIMEOUT_S`; a resposta inteira tem ainda
`AGENT_TOTAL_TIMEOUT_S` (menor entre este e timeout × `AGENT_MAX_STEPS`); ao esgotar, ou perante
qualquer erro inesperado do LLM, há o recurso determinístico (log só com o tipo da exceção).

## Providers

**IMPLEMENTADO (encaixe):** `sources.resolve` escolhe, por ferramenta, a cadeia de fontes:

1. o provider **real** registado em `app.state.agent_providers` (um `ProviderSet`; **PROPOSTA**
   de nome, #157 item 15), lido em tempo de pedido, por isso pode ser registado depois do arranque;
2. os dados **SIMULADOS**, só para `fixtures.HOUSEHOLD` com `source_kind='demo'`;
3. senão, sem dados (`EmptyProviders`).

Só se recua ao elo seguinte quando o anterior devolve `None`; uma exceção nunca recua (resposta
`provider_error`). Numa casa real (`source_kind='real'`) qualquer valor com proveniência simulada é
descartado (`no_data`). O recibo vem sempre do mesmo provider que respondeu a `latest_bill`.
Sem nada registado o comportamento é o de antes.

**PLANEADO:** os providers reais. Esta feature não importa `billing`, `engine` nem outra feature
(D-06). Pedido a P4/P1: implementar os `Protocol` de `providers.py` (valores já calculados em
código, `None` = sem medição, proveniência verdadeira, sem I/O bloqueante lento) e registar um
`ProviderSet(consumption=…, budget=…, receipt=…)` em `app.state.agent_providers` na composição.

## IMPLEMENTADO — ações propostas (AGENT-03, #112)

Um pedido de ação («desliga a luz», «põe a luz azul», «desliga a tomada») **nunca chega ao LLM nem
executa nada**: `send_message` interpreta-o em código (`intents.py`) e devolve **uma proposta por
confirmar** em `proposed_actions` (ou um texto de recusa). Só `POST …/agent/actions/{id}/confirm`
executa, uma vez, por um `ActionExecutor` injetado; `confirmed` exige releitura, `uncertain` nunca
se repete e **SIMULADO** vem sempre etiquetado. A casa demo usa só o executor simulado.

| Ficheiro | O quê |
|---|---|
| `intents.py` | Parser PT puro: lâmpada (ligar/desligar/brilho/cor), tomada (só desligar) e recusas com código; só imperativo/infinitivo, perguntas e negações nunca são ação |
| `devices.py` | `ActuatorDevice`, porta `DeviceDirectory`, `DemoDevices` (SIMULADO) e `NoDevices` |
| `execution.py` | Porta `ActionExecutor`, `SimulatedExecutor`, `select_executor`, `run_execution` (prazo, incerteza, nunca repete) |
| `actions.py` | Serviço SQLite: propor, confirmar (CAS, COMMIT antes de executar), registar o desfecho (`executed_at` = hora do servidor; execução interrompida ou `confirmed` perdida → `uncertain/interrupted`), rejeitar; limites por dispositivo; `AgentActionView` |
| `actions_router.py` | `GET …/agent/actions[/{id}]`, `POST …/{id}/confirm`, `POST …/{id}/reject` (montado por `router.py`) |
| `safety_consumer.py` | AGENT-03b: consumidor `agent.safety_suggestion` de `safety.alert_raised` (ver abaixo) |

Tabelas em `core/migrations/0310_agent_actions.sql`. PROPOSTA para a P1: registar
`app.state.agent_action_executor` e `app.state.agent_device_directory`; sem eles uma casa real não
executa nada. Limites e detalhe em [`docs/modules/agent.md`](../../../../../../docs/modules/agent.md).

### AGENT-03b — propostas a partir de alertas de janela (IMPLEMENTADO)

`safety_consumer.py`, subscrito no `lifespan` do `router.py`. Um alerta ativo `window_open_heating`
com `suggested_command` («desligar a tomada») gera **uma proposta por inquilino ativo** (os do
quarto, ou todos se for zona comum; `source="safety"`) e `agent.action_proposed`. **Só propõe:**
nunca chama o executor; só `POST …/confirm` executa. Só com a tomada no diretório de dispositivos
(demo: SIMULADO; casa real: o diretório da P1, senão nada), id da proposta derivado de (alerta,
residente) (idempotente), alerta além de `AGENT_ACTION_TTL_S` ignorado. Alerta `resolved` → as
propostas por confirmar passam a `rejected` pelo sistema (`code="alert_resolved"`).
Ressalva: em runtime real só dispara quando a `safety` tiver o resolvedor de aquecedores
(ENERGY-03; `features/safety/router.py`). Hoje, só na demo e nos testes.

## PLANEADO

Providers reais de P4/P1 (ver «Providers»), executor real e diretório de dispositivos da P1 (e o resolvedor de aquecedores da `safety` para o AGENT-03b em runtime real), AGENT-04 (automações), decisão P-06 antes de ligar o LLM, frontend.

## Testes

`cd app/backend && python -m pytest -q src/homemind/features/agent` (venv do projeto). Sem rede
nem LLM: `tests/conftest.py` substitui sempre `get_complete`.
