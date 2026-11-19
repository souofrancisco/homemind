# Módulos `agent` e `automations` — assistente de IA e automações

**Dono: P3 (RafaelMat0s-Dev); execução física: P1.** **IMPLEMENTADO (backend parcial: leitura com dados SIMULADOS, histórico da conversa por residente (#111), ações propostas com confirmação (AGENT-03) e propostas a partir de alertas de janela aberta (AGENT-03b)); o resto PLANEADO** (ver «Estado de implementação» no fim). Substitui o agente que vivia no Telegram: o assistente está **dentro da aplicação** (D-01).

## Responsabilidade

1. **Assistente conversacional** que explica consumo, recibos e orçamentos («porque pago mais 5 € que a Carla?»), em português.
2. **Ações sugeridas** (ex.: «desligar o aquecedor às 23 h»), sempre com **confirmação do utilizador** antes de executar.
3. **Automações** escritas em português e convertidas em `AutomationRule`, com pré-visualização e ativação explícita.

## Guarda-corpos (obrigatórios; PDF §9)

| Regra | Como se cumpre |
|---|---|
| **O modelo nunca inventa números** | Todos os valores vêm de funções (ferramentas) do backend; o LLM só redige; as contas são feitas em código ([billing.md](billing.md)) |
| Respeita o papel | As ferramentas executam com as permissões do utilizador autenticado; o senhorio não usa o assistente de consumo individual (**PROPOSTA**) |
| Confirmação humana | Uma ação sugerida cria `agent_action` e só se executa em `POST /api/households/{id}/agent/actions/{aid}/confirm` (**IMPLEMENTADO**; só o próprio residente; o LLM nunca propõe: o pedido é interpretado em código). Sensíveis (segurança, cortes fora de regras aprovadas) pedem sempre confirmação |
| Sem vídeo | O LLM nunca recebe imagens, frames nem URLs de câmara; só texto |
| Dados mínimos | Enviar ao modelo apenas o necessário e sem identificadores externos de dispositivos. Qual o fornecedor de LLM e que dados podem sair: decisão P-06 |
| Sem escritas físicas sem autorização | A execução é uma porta injetada (`ActionExecutor`, P1) que aplica flag + grant + whitelist e relê; esta feature não importa conectores nem o motor. Casa demo: só executor SIMULADO |
| Proveniência | As respostas indicam se um valor é medido, estimado, inferido ou simulado |

## Ferramentas (funções) propostas

| Ferramenta | Devolve | Dono do dado |
|---|---|---|
| `get_my_consumption(period)` | kWh e custo individuais, por proveniência | P4 |
| `get_receipt(bill_id)` / `explain_difference(resident_a, resident_b)` | Linhas do recibo | P4 |
| `get_budget_status()` | Gasto, limiares, previsão | P4 |
| `list_pending_confirmations()` | Pedidos abertos | P3 |
| `who_is_home()` | Só para o próprio e com opt-in; nunca para senhorio | P2 |
| `propose_device_action(role, capability, value)` | Cria ação a confirmar | P1/P3 |
| `propose_automation(nl_text)` | `AutomationRule` em `proposed` | P3 |

Fora das ferramentas, o modelo não responde com números; em dúvida diz que não sabe.

## Fluxo de uma ação sugerida

```mermaid
sequenceDiagram
  participant U as Utilizador (aplicação)
  participant A as agent (P3)
  participant F as Ferramentas (P4/P2)
  participant H as Home (P1)
  U->>A: «Desliga o aquecedor às 23h»
  A->>F: get_budget_status(), propose_device_action(...)
  F-->>A: dados e ação proposta (id)
  A-->>U: resposta + cartão «Confirmar / Cancelar»
  U->>A: confirm(action_id)
  A->>H: definir_tomada(False) só com flag + grant
  H-->>A: True só se releitura confirmou
  A-->>U: «Desligado» ou falha explicada (nunca assumir sucesso)
```

## Automações

- Modelo `AutomationRule` ([data-model.md](../architecture/data-model.md)): gatilho, condição, ações, confirmação, estado `draft → proposed → active`.
- O assistente atual usa `features/agent/llm.py` e ferramentas tipadas próprias. O cliente NVIDIA e a rota de propostas de regras do motor foram removidos em BASE-04; automações futuras precisam de contrato próprio.
- **Âmbito do MCP:** só lâmpada (`power`, `brightness`, `color_rgb`) e tomada (`power`). Gatilhos por sensores de contacto/clima exigem **leitura** de dispositivos hoje fora da seleção do `McpHome` — **PROPOSTA** de extensão só de leitura (P-01). **Cenários** do Connected Home (`post_new_scenario`), alarme e segurança **continuam proibidos** até decisão explícita da equipa.
- A votação da casa (PDF §12: 👍/👎) passa a ser aprovação na aplicação (**PROPOSTA**, P2).
- **SAFE-04 (#117), PROPOSTA D-35:** o **contrato** já está em `contracts/agent.py` (**IMPLEMENTADO** só como modelos e testes): `AutomationRule.actions` só pode «desligar a tomada» (`power=False`), `AutomationVote` e `rule_approval_outcome` (maioria absoluta = mais de metade; 24 h; sem maioria = rejeitada, `proposed→draft`), e os eventos `automation.vote_decided` e `automation.status_changed` (+ `automation.proposed`/`automation.executed` já existentes). **IMPLEMENTADO** (`features/automations`, migração `0320_automations.sql`, testado com bases em memória e relógio simulado; nunca visto no browser nem com hardware): persistência (`automation_rule`, `automation_vote`, `automation_log` só de acrescentar), votação, suspensão, reativação e rotas.
  - **Propor** (só inquilino ativo): a regra fica `proposed` e emite `automation.proposed`; o proponente **vota a favor ao propor** (1 voto; com a maioria já atingida, ex.: 1 morador, fecha aprovada no próprio pedido). No máximo 3 votações abertas por morador, contando propostas e reativações que pediu (409 `too_many_open`). O alvo e o `trigger.device_id` têm de ser **tomadas** conhecidas da casa (nunca de outra casa nem a lâmpada; `invalid_target`) e a única ação é desligar o alvo. O alvo pode ser a tomada **agregada** (a extensão, que alimenta vários aparelhos): a UI da onda 4 tem de avisar disso a quem vota. O corpo é `{name, trigger, target_device_id}`; o autor vem do token.
  - **Votar** (`POST …/vote`, `{approve}`): um voto por morador, só os inquilinos elegíveis (gravados à abertura da ronda), prazo fixo de 24 h; depois de cada voto aplica-se `rule_approval_outcome` (maioria absoluta). Aprovada: `active`, `approved_by_resident_id` = quem deu o voto decisivo, eventos `vote_decided` + `status_changed`. Maioria impossível: `proposed→draft` e só `vote_decided`. Votos fora de prazo nunca contam; a ronda sem maioria no prazo é **rejeitada de forma preguiçosa** (na leitura ou ao votar), idempotente. Cada fecho é um compare-and-set.
  - **Suspender** (`PATCH …/{id}` com `{status:"disabled"}`): qualquer inquilino, na hora, `active→disabled`, evento `status_changed`. **Reativar** (`POST …/{id}/reactivate`): conta para o limite de 3 votações abertas de quem reativa (409 `too_many_open`); abre uma ronda nova com votos limpos (o reativador não vota sozinho) e reemite `automation.proposed` com a regra `disabled` (id estável por regra+ronda) para avisar os moradores; a regra continua `disabled` até a maioria votar (`active` nunca é direto) e uma ronda sem maioria deixa-a `disabled`.
  - Respostas (`AutomationView`) só têm contagens e o voto do próprio; nunca quem votou o quê. Senhorio e operador: 403; fora da casa: 404 (`Resource.automation`). O aviso `automation_proposal` à casa vem de `automation.proposed` (`notifications.automation_proposal`; só inquilinos; um por ronda) e fecha ao decidir a votação (`automation.vote_decided`, `notifications.automation_decided`).
  - **Motor de execução (onda 3), IMPLEMENTADO só SIMULADO** (`features/automations/{engine,runner}.py`; testado com bases em memória, `SimulatedExecutor`/executores falsos e relógio simulado; nunca visto no browser nem com hardware). `engine.py` é lógica pura (o «agora» é o `ts` do evento); `runner.py` liga-o ao barramento (consumidor `automations`, lifespan do router) e executa.
    - **Gatilhos:** `power_above` usa `energy.reading_recorded` (potência instantânea do dispositivo do gatilho), porque `ConsumptionEvent` só traz `peak_w`/`energy_wh` e não prova que a potência se manteve; dispara quando a potência fica **estritamente acima** de `threshold_w` sem interrupção durante `duration_s`. Uma leitura sem potência utilizável, um intervalo > 5 min entre leituras, uma leitura abaixo do limiar ou `energy.consumption_closed` quebram a sequência. `presence_changed` só dispara em transições in↔out face ao estado imediatamente anterior do morador; a primeira observação e qualquer transição que envolva `uncertain` só registam o estado (decisão do utilizador).
    - **Só regras `active` e aprovadas** (`status=active`, sem votação aberta, `approved_by_resident_id`), e só eventos desde a ativação. A **confirmação humana é a votação já feita**: a `ProposedAction` nasce `confirmed`, confirmada por quem deu o voto decisivo, com a justificação «aprovada por votação»; não se pede confirmação nova. Antes de executar relê-se a regra: uma suspensão posterior vale na hora (o disparo é descartado).
    - **Execução:** `select_executor` + `run_execution` (`features/agent/execution.py`; dependência feature→feature declarada). Casa de demonstração: SEMPRE o `SimulatedExecutor`; casa real: `app.state.agent_action_executor` (P1/MCP-04, que aplica flag + grant e relê) ou nenhum → `blocked` (`executor_unavailable`), sem tentar. O executor físico real continua **PLANEADO/bloqueado** sem grant; `ENABLE_PHYSICAL_WRITES` mantém-se falso. Só desliga tomadas; a lâmpada nunca é alvo.
    - **Guardas:** um disparo por episódio; cooldown por regra (1 h) e por dispositivo (`AGENT_ACTION_COOLDOWN_S`); duas regras sobre o mesmo dispositivo no mesmo evento executam uma vez (lidera a de menor id); `uncertain` nunca se repete e bloqueia o dispositivo `AGENT_ACTION_LOCKOUT_S` (um novo episódio nesse prazo fica `blocked`/`uncertain_lockout`). O bloqueio volta a consultar-se mesmo antes de chamar o executor (um disparo já decidido não passa). Reentrega do barramento e reinício não duplicam.
    - **Auditoria:** `automation.executed` (id estável por regra+evento+dispositivo, resultado REAL, `blocked` incluído, com `code`). Sem migração nova: o `automation_log` só aceita os tipos da votação. O estado reconstrói-se do registo de eventos (`restore`); um disparo decidido mas ainda não executado quando o processo morre perde-se (preferível a repetir). O `restore` só relê a janela recente de leituras (24 h + folgas) e toda a presença.
    - **Limitações conhecidas:** há uma janela mínima entre a releitura da regra e a chamada ao executor (uma suspensão nesse instante não a pára; só importa se vier a ligar-se um executor FÍSICO, P1/MCP-04); se `bus.publish` falhar depois de executar, perde-se o registo `automation.executed` (o episódio fica marcado e não repete); um `handle` que levante depois de mutar o motor perde o disparo. Em todos os casos preferimos não executar a repetir.
  - **PLANEADO:** UI (onda 4) e regras vindas do assistente (AGENT-04).
- Prioridade: P2. Nada disto bloqueia o MVP.

## Ficheiros existentes reutilizáveis

`features/agent/llm.py` e `features/agent/config.py` (cliente NVIDIA do assistente, separado do motor removido), mais as ferramentas tipadas existentes. As páginas antigas do frontend foram removidas na BASE-04; a interface atual está na aplicação Conta Certa.

## Ficheiros novos previstos

`features/agent/{tools,router,service,tests}`, `features/automations/{repo,service,engine,runner,simulation,router,tests}` (o motor só simulado), `contracts/agent.py` (existe na `main`), frontend `pages/AssistantPage.tsx`.

## Dependências

P4 (dados de consumo, recibos), P1 (ações), P2 (presença), P5 (papéis, UI).

## Critérios de aceitação

- Em testes com um LLM falso, o assistente responde só com valores devolvidos pelas ferramentas; uma pergunta sem dados devolve «não sei», nunca um valor.
- Uma ação sugerida nunca chama `Home` sem `confirm`; com grant inexistente a ação falha com mensagem clara.
- Um senhorio recebe `403` ao pedir dados individuais ao assistente.
- Sem `NVIDIA_API_KEY` o resto da aplicação funciona (comportamento atual) e o assistente indica que está indisponível.

## Estado de implementação (na `main`, refs #110, #111 e #112)

Tipos reais de `contracts/agent.py` e `contracts/common.py` (já não há `_provisional.py`). Leitura: sem eventos; o histórico (#111) e as ações propostas (AGENT-03, abaixo) têm tabelas; as ações têm o evento `agent.action_proposed` e rotas próprias.

### IMPLEMENTADO

| O quê | Onde |
|---|---|
| Registo de ferramentas só de leitura (`consumption_summary`, `budget_status`, `receipt`); o residente vem do contexto, nunca dos argumentos; só inquilinos; sem dados → `no_data` (nunca zero) | `features/agent/tools.py` |
| Ciclo do assistente: pedido de ação e senhorio → resposta fixa; senão JSON `{"tool"}`/`{"answer"}` com `max_steps`, timeout, 1 correção de JSON, 1 de números, rodapé `Fonte:` | `assistant.py`, `guardrails.py`, `formatting.py`, `prompt.py` |
| **Recurso determinístico** sem LLM (indisponível, JSON inválido, números não suportados, passos esgotados): mostra os factos das ferramentas formatados em código | `assistant.py::fallback_reply` |
| Endpoint `POST /api/households/{household_id}/agent/messages` (corpo `AgentMessageIn`, resposta `AgentResponse`; `proposed_actions` só tem a proposta de um pedido de ação, ver abaixo). `require_access(Resource.agent, write)`: só inquilino; senhorio e operador 403 `forbidden_role`; não-membro e membership terminada 404 `household_not_found`; corpo inválido 400 `invalid_request` | `router.py` |
| Providers **SIMULADOS** derivados de `contracts/fixtures.py`, só para a casa `fixtures.HOUSEHOLD` com `source_kind='demo'`; qualquer outra casa, período ou residente → «Não tenho dados» | `simulated.py` (`SimulatedProviders`, `EmptyProviders`) |
| LLM **desligado por omissão**: só há chamada com `AGENT_LLM_ENABLED=true` **e** `NVIDIA_API_KEY`; `get_complete` é uma dependência substituível (testes) | `config.py`, `router.py` |

Os números da casa de demonstração vêm todos das fixtures (alocação da Ana na fatura A, orçamento e gasto da Carla, total do recibo) e são mostrados como **SIMULADO**. O gasto do orçamento é o `spent_cents` da amostra do evento `alerts.threshold_crossed` das fixtures (o `Budget` só tem o limite).

**Limite dos dados SIMULADOS:** só cobrem o período `2026-11`. O período por omissão é o mês corrente, por isso a partir de 1 de dezembro de 2026 a resposta por omissão é «Não tenho dados» até existirem os *providers* reais de P4.

Prazo total da resposta: `AGENT_TOTAL_TIMEOUT_S` (30 s; efetivo = mínimo entre este e `AGENT_LLM_TIMEOUT_S` × `AGENT_MAX_STEPS`). Ao esgotar, ou com qualquer erro inesperado do LLM, usa-se o recurso determinístico (log só com o tipo da exceção).

### IMPLEMENTADO — AGENT-03 (ações propostas com confirmação, refs #112)

Uma ação só se executa depois de `confirm` humano; o assistente **propõe**, nunca executa.

| O quê | Onde |
|---|---|
| Parser PT determinístico (sem LLM): desligar/ligar a lâmpada, brilho 1–100, cor de `contracts.home.CORES`, **desligar** a tomada. Recusas com código: `forbidden_kind` (alarme, cenário, segurança, temporizador), `plug_turn_on_not_allowed` (o agente nunca liga uma tomada), `ambiguous_device`, `no_device`, `unsupported` (agendar, valores inválidos, mais de um comando). Só imperativo/infinitivo (nunca particípios como «desligada»); perguntas («?», «quanto/qual/está…», salvo «podes…?») e frases com negação nunca são ação; «mudar/pôr/colocar» exigem um dispositivo. A justificação (≤300) nomeia o dispositivo, avisa quando a tomada é a extensão agregada e diz «SIMULADO» | `intents.py` |
| `ActuatorDevice` e porta `DeviceDirectory`; `DemoDevices` (**SIMULADO**: «Tomada da extensão» e «Lâmpada da sala» só na casa `fixtures.HOUSEHOLD` com `source_kind='demo'`); `NoDevices` nas outras | `devices.py` |
| Porta `ActionExecutor`, `SimulatedExecutor` (estado em memória, relê-o), `select_executor` (demo → sempre simulado, **nunca** o registado; casa real → o registado ou `None`) e `run_execution`: prazo `AGENT_ACTION_TIMEOUT_S`; exceção, prazo ou resultado inválido → `uncertain` (**nunca repete**); sem executor → `blocked` `executor_unavailable` | `execution.py` |
| Serviço sobre SQLite: `propose` (linha + log + `agent.action_proposed` no outbox, mesma transação), `confirm` (CAS `proposed→confirmed`, COMMIT **antes** de executar), `record_execution` (CAS `confirmed→executed`), `reject`; `expired` derivado na leitura; vista local `AgentActionView` com `message` honesta por estado | `actions.py` |
| Rotas `GET …/agent/actions[?status]`, `GET …/agent/actions/{id}`, `POST …/{id}/confirm`, `POST …/{id}/reject`; `Resource.agent` (só inquilino); a ação de outro residente é `404 action_not_found`; `409 action_not_pending` / `409 action_expired` | `actions_router.py` |
| Tabelas `agent_action` e `agent_action_log` (só a acrescentar: gatilhos) | `core/migrations/0310_agent_actions.sql` |

Limites (por dispositivo, espelham `connectors/write_policy.py` sem o importar; `config.py`): validade da proposta 600 s, no máximo 3 abertas por residente, *cooldown* 60 s, 6 por hora, bloqueio de 300 s após um resultado `uncertain`. Um limite violado grava a ação como `executed` com `blocked` (`cooldown`, `hourly_limit`, `uncertain_lockout`) e **não chama o executor**; só contam tentativas (confirmadas, falhadas, incertas e em curso), não as bloqueadas.

Honestidade: `confirmed` exige releitura (o contrato recusa o contrário); `uncertain` diz «Não repito a ação»; **SIMULADO** aparece em todas as mensagens da casa demo. Casas reais: sem diretório ficam sem dispositivos (recusa `no_device`); com diretório mas sem executor, `blocked` `executor_unavailable`.

**Ligação com a P1 — IMPLEMENTADA para a lâmpada (`features/energy/kit_actuators.py`, registada no arranque do engine só com `HOME_BACKEND=mcp` e `ENERGY_HOUSEHOLD_ID`):** `KitLampDirectory` (a lâmpada do kit, id interno derivado do id MCP, divisão de `MCP_LAMP_ROOM_ID`) e `KitLampExecutor` (`McpHome.definir_lampada`: flag + grant + whitelist + releitura; guardas → `blocked`; erro MCP → `failed`; resto → `uncertain`; cores só do vocabulário `CORES`). Texto original da proposta: registar em `app.state.agent_action_executor` um `ActionExecutor` (`async execute(action, confirmation) -> ActionExecutionResult`: aplica flag + grant + whitelist e `RuleWritePolicy` se quiser, escreve **uma vez**, relê, e devolve `confirmed` só com releitura) e em `app.state.agent_device_directory` um `DeviceDirectory` (`actuators(household_id) -> list[ActuatorDevice]`, ids internos; o id do MCP resolve-se no executor). Enquanto não existirem, uma casa real nunca executa.

Não há ainda os eventos `agent.action_confirmed`/`agent.action_executed` (só `agent.action_proposed`): o rasto completo está em `agent_action_log`. Uma execução interrompida (cancelamento do pedido) grava logo `executed/uncertain` com código `interrupted`; uma ação `confirmed` há mais de prazo do executor + 30 s (crash entre o COMMIT e o desfecho) é resolvida da mesma forma, de forma preguiçosa, na leitura e antes de verificar os limites (linha de log em `agent_action_log`). Nunca se reexecuta e o dispositivo fica bloqueado 300 s. A coluna `executed_at` (usada pelos limites) é sempre a hora do servidor; a do executor fica só em `execution_json` e, se fora de [confirmação − 5 s, agora + 5 s], o resultado é `uncertain/invalid_result`.

### IMPLEMENTADO — cor do orçamento na lâmpada (ALERT-06, refs #104)

Consumidor `agent.budget_light` (nome permanente) de `alerts.threshold_crossed` (`budget_light_consumer.py`, subscrito no mesmo `lifespan`). Segue o caminho seguro do AGENT-03b: **só propõe**; executa `POST …/confirm` depois da confirmação humana.

- **Cor:** `contracts.billing.budget_light(pct)`, a mesma da página Orçamento: 80 % → âmbar `(255, 200, 0)`, 100 % → vermelho. Abaixo de 80 % (verde) não se propõe nada. Comando `color_rgb`.
- **Destinatário:** só o dono do orçamento, se for inquilino ativo hoje. Senhorio e operador nunca.
- **Privacidade (que lâmpada):** `ActuatorDevice.room_id` (novo, opcional). Primeiro uma lâmpada no quarto do morador; senão uma de zona comum, e a `rationale` avisa que a cor fica à vista de quem lá estiver (o morador decide); nunca a lâmpada de outro quarto nem uma de divisão desconhecida (`choose_bulb`, puro). A lâmpada da casa demo é a da sala (`room_id = ROOM_SALA`).
- **Idempotente:** id `stable_id("agent.budget_light", evento, residente)`. Um limiar novo retira a proposta anterior ainda por confirmar (`system_reject`, `code="superseded"`). Evento com mais de `AGENT_ACTION_TTL_S` (600 s) ignorado. Uma casa real ignora eventos e dispositivos simulados.
- **App:** a página Orçamento mostra a proposta aberta com «Mudar a cor» / «Agora não» e, depois, a `message` do servidor (SIMULADO etiquetado; sucesso só com releitura).
- **Ressalva (runtime real):** o diretório e o executor da lâmpada do kit existem (testados só com o FakeMcp). Sem `HOME_BACKEND=mcp` + `ENERGY_HOUSEHOLD_ID` não se registam e uma casa real fica `blocked` (`executor_unavailable`); sem `MCP_LAMP_ROOM_ID` a lâmpada não tem divisão e nunca recebe a cor do orçamento. **A lâmpada física ainda não foi validada à mão** (guia: ALR-06).

### IMPLEMENTADO — AGENT-03b (propostas a partir de alertas de conforto, refs #112)

Consumidor `agent.safety_suggestion` (nome permanente) de `safety.alert_raised`, subscrito no `lifespan` de `features/agent/router.py` (`safety_consumer.py`). Um alerta `active` `window_open_heating` com `suggested_command` («desligar a tomada») e quarto gera **uma proposta por inquilino ativo** (`source="safety"`, justificação «Janela aberta com o aquecimento ligado. Queres desligar a tomada do aquecedor?») e o evento `agent.action_proposed`. Nunca executa: o consumidor só propõe, não chama o executor; só `POST …/confirm` executa, depois da confirmação humana.

- **Destinatários:** os inquilinos ativos do quarto (quarto) ou todos os inquilinos ativos (zona comum). Senhorio e operador nunca recebem propostas. Consulta própria sobre `membership` (cópia da lógica de `notifications/directory.py`; uma feature não importa outra, D-06).
- **Só com dispositivo conhecido:** o alvo tem de estar em `DeviceDirectory.actuators()` (`select_directory`) e ser uma **tomada**; senão nada (log sem ids do MCP). Casa demo: os dispositivos **SIMULADOS** e proposta `origin=simulated` (executor simulado, nunca hardware). Casa real: só o diretório registado pela P1 em `app.state.agent_device_directory`, só dispositivos não simulados e nunca a partir de um alerta simulado; sem diretório, não há propostas.
- **Idempotente:** o id da proposta é `stable_id("agent.safety", alerta, residente)` (`propose(…, action_id=…)`); reprocessar o alerta não duplica. Um alerta com mais de `AGENT_ACTION_TTL_S` (600 s) é ignorado (reprocessamento tardio).
- **Alerta resolvido** (`status=resolved`, mesmo `id`): as propostas ainda **por confirmar e dentro do prazo** passam a `rejected` pelo sistema (`actions.system_reject`: CAS, linha em `agent_action_log` com `by_resident_id` nulo e `code="alert_resolved"`); uma confirmação seguinte dá `409 action_not_pending`. Uma já confirmada, decidida ou expirada fica como está.
- **Ressalva (runtime real):** em produção o alerta de janela só existe quando a feature `safety` tiver o resolvedor de aquecedores (ENERGY-03, ver `features/safety/router.py`: hoje só as regras de fumo estão ativas) e a P1 registar o diretório e o executor. Até lá o caminho só se exerce na casa de demonstração (SIMULADO) e nos testes.
- Pendente (contrato, fora desta feature): o evento `agent.action_proposed` não distingue a origem da proposta (chat ou `safety`); só a coluna `agent_action.source` o faz.

### IMPLEMENTADO — histórico da conversa (#111)

Cada `POST …/agent/messages` grava a **troca** (a pergunta e a resposta) no histórico do próprio residente, nos dois caminhos (pergunta normal e pedido de ação). `GET /api/households/{household_id}/agent/messages?limit=1..100` (omissão 50) devolve `list[AgentMessage]` do **próprio**, do mais antigo para o mais recente: nunca o de outro residente nem o de outra casa; `require_access(Resource.agent, read)` (senhorio e operador 403 `forbidden_role`; não-membro 404 `household_not_found`; `limit` fora de 1..100 → 400 `invalid_request`).

- **Dados pessoais, retenção curta (P-25):** ao gravar, cortam-se as mensagens acima de `AGENT_HISTORY_KEEP` (50) por residente e casa e as com mais de `AGENT_HISTORY_DAYS` (30) dias. Tabela `agent_message` em `core/migrations/0311_agent_messages.sql`; lógica em `features/agent/history.py`.
- **Nunca vai para o LLM (P-06):** o histórico serve só para a app o mostrar. O assistente e o LLM recebem apenas a pergunta atual (teste dedicado).
- O histórico guarda o texto da resposta tal como foi mostrado (inclui o rótulo **SIMULADO** e o rodapé `Fonte:`); não guarda números à parte.

### PLANEADO

- *Providers* reais de P4 (consumo, orçamento, recibos) e P1 (energia), registados no arranque sem a feature importar outra; trocar `simulated.py`.
- AGENT-04 (automações), `who_is_home`, `explain_difference`, `list_pending_confirmations`.
- **P-06** (que dados de consumo podem sair para o fornecedor de LLM): decidir antes de ligar `AGENT_LLM_ENABLED` em qualquer ambiente.
- Frontend `AssistantPage`.

### Pedidos pendentes (para a revisão do contrato e do `core/`)

1. **`AgentToolResult` pobre:** sem `period`, `confidence` nem linhas de detalhe; «porque pago mais?» precisa de linhas do recibo.
2. **Só três ferramentas** em `AgentTool`; AGENT-01 pede também aparelhos, explicação da atribuição e notificações pendentes.
3. **`receipt` exige `bill_id`:** hoje o `ReceiptProvider.latest_bill` resolve «o último recibo» (PROPOSTA a rever).
4. **Interface dos *providers*:** os `Protocol` vivem em `features/agent/providers.py`; propor movê-los para `contracts/agent.py` e registá-los em `app.state`.
5. **`AgentMessage` sem `resident_id`:** o histórico é por residente (a tabela guarda-o; o contrato não o expõe, o que é o desejado: só o próprio lê as suas). A linha `GET …/agent/messages` já consta de `contracts.md` (estado IMPLEMENTADO; falta a revisão da P5).
6. **`AgentResponse` sem `used_llm`/`degraded`:** a app não distingue resposta do LLM de recurso determinístico.
7. **Definições do LLM** em `features/agent/config.py`; o assistente continua a ler `NVIDIA_API_KEY` e `NVIDIA_MODEL`.
8. **OpenAPI:** o FastAPI anuncia 422 `HTTPValidationError` para corpos inválidos, mas `core/errors.py` responde 400 `invalid_request` (vale para todas as rotas).
9. **Rota por casa:** o caminho de `contracts.md` era `POST /api/agent/messages`; a rota é por casa, como as outras (D1).
10. **AGENT-03 (contrato):** falta `ErrorCode` para `action_not_found`, `action_not_pending` e `action_expired` (hoje strings); `AgentActionView` é local a `features/agent/actions.py` e devia estar em `contracts/agent.py`; faltam os eventos `agent.action_confirmed` e `agent.action_executed` e o *schema* da proveniência (`origin`) em `ProposedAction`.

O senhorio não usa o assistente (matriz `PERMISSIONS[agent]`); uma versão futura só com totais fica por decidir.

## Testes

`cd app/backend && python -m pytest -q src/homemind/features/agent`. `FakeLLM` com guião e *providers* falsos em `tests/_fakes.py`; `tests/conftest.py` substitui **sempre** `get_complete`, por isso uma `NVIDIA_API_KEY` do ambiente nunca chega à rede.
