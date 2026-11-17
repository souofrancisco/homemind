# features/agent — assistente na app (AGENT-01 registo, AGENT-02 ciclo)

Refs #110 e #111. Detalhe e pedidos pendentes em [`docs/modules/agent.md`](../../../../../../docs/modules/agent.md).

## IMPLEMENTADO

`POST /api/households/{household_id}/agent/messages` (`AgentMessageIn` → `AgentResponse`). Só
inquilinos (`require_access(Resource.agent, write)`); senhorio e operador 403, não-membro 404. O
residente e o papel vêm do token. Ferramentas só de leitura; todos os números vêm delas; sem LLM
(ou com resposta não fundamentada) há um recurso determinístico. Sem tabelas, eventos nem lifespan.

| Ficheiro | O quê |
|---|---|
| `router.py` | O endpoint; `get_complete` (dependência: `None` salvo `AGENT_LLM_ENABLED` e `NVIDIA_API_KEY`) |
| `simulated.py` | **SIMULADO**: `SimulatedProviders` (valores de `contracts/fixtures.py`, só casa demo com `source_kind='demo'`) e `EmptyProviders` (sempre sem dados) |
| `tools.py` | `ToolRegistry`: só leitura; residente do contexto; só moradores; sem dados → `no_data`; erro do fornecedor → `provider_error` (log só com o tipo) |
| `providers.py` | `Protocol` `ConsumptionProvider`, `BudgetProvider`, `ReceiptProvider` (P4/P1 implementam); `ProviderSet` e `REGISTRY_ATTR` |
| `sources.py` | Escolha dos providers por ferramenta e casa (ver «Providers»); `get_registered`, `resolve` |
| `assistant.py` | `Assistant.reply`: ação e senhorio → resposta fixa; ciclo JSON com `max_steps`, timeout, correções e rodapé `Fonte:`; `fallback_reply` |
| `guardrails.py`, `formatting.py`, `prompt.py` | Números inventados e pedidos de ação; texto PT-PT determinístico; prompt |
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

## PLANEADO

Providers reais de P4/P1 (ver acima), histórico por residente, AGENT-03 (ações
propostas), AGENT-04 (automações), decisão P-06 antes de ligar o LLM, frontend.

## Testes

`cd app/backend && python -m pytest -q src/homemind/features/agent` (venv do projeto). Sem rede
nem LLM: `tests/conftest.py` substitui sempre `get_complete`.
