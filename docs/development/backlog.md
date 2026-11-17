# Proposta de backlog

**Só proposta.** Nenhuma issue foi criada, alterada ou fechada nesta tarefa. A criação e o encerramento fazem-se numa fase posterior, depois de os contratos estarem acordados ([roadmap.md](roadmap.md)). Estado das issues lido a 17/11/2026 (só leitura).

## Destino das issues antigas

| Issue | Título (ObjectOS) | Estado | Proposta | Porquê |
|---|---|---|---|---|
| #1–#3, #6, #7, #9–#11, #13, #14, #22–#27 | Contratos, RTSP, presença, Home/FakeHome, MCP, motor, NVIDIA, painel | Fechadas | **Manter fechadas** | Histórico do ObjectOS. Os resultados reaproveitáveis estão em [migration.md](../architecture/migration.md) |
| #4 | YOLO objetos, pose e tracking | Aberta | **Substituir** por C-P2-02 e fechar | O produto deixa de usar objetos e pose; fica a deteção de pessoa |
| #5 | Deteção do gesto «objeto levantado» | Aberta | **Encerrar** («não será feito») | Funcionalidade descontinuada |
| #8 | Afinador offline de gestos | Aberta | **Encerrar** | Idem |
| #12 | Consumo da tomada e observabilidade MCP | Aberta | **Reaproveitar**: renomear e ligar a C-P1-01 | É o bloqueio central da Conta Certa (unidade de `instantPower`) |
| #28 | Integração completa e benchmark | Aberta | **Substituir** por C-P5-08 | Âmbito e métricas diferentes |
| #29 | README, resumo PDF e apresentação | Aberta | **Reaproveitar** como entregáveis (C-P5-09) | Entregáveis da organização mantêm-se; conteúdo novo |
| #30, #31 | Extras (sugestões de rotinas, extras pós-MVP) | Abertas | **Encerrar** | Fora de âmbito |
| #51 | Ideia: Memory | Aberta | **Encerrar** | Fora de âmbito |
| #52 | Ideia: «Porque aconteceu?» (explicabilidade) | Aberta | **Reaproveitar** como C-P3-05 | Alinha com recibos e assistente explicáveis |
| #53 | Ideia: Laboratório de regras (pré-visualizar) | Aberta | **Reaproveitar** como C-P3-07 | Alinha com automações com pré-visualização |
| #54 | Ideia: Calibração de gestos | Aberta | **Encerrar** | Gestos descontinuados |
| #55 | Ideia: Energy Insights | Aberta | **Reaproveitar** como C-P4-06 | Recomendações explicáveis |
| #56 | Ideia: Controlo inclusivo | Aberta | **Reaproveitar** como requisito de acessibilidade do frontend (C-P5-07) | Acessibilidade mantém-se |

## Épicos propostos

| Épico | Âmbito |
|---|---|
| E0 Contratos e base | Contratos, db, barramento, papéis |
| E1 Energia e MCP | Leituras, assinaturas, hardware |
| E2 Atribuição e fatura | Regras, fatura, recibos |
| E3 Notificações e IA | Centro de notificações, assistente |
| E4 Presença | Porta, fusão |
| E5 Aplicação e demo | UI por papel, plano B, entregáveis |

## Issues propostas (IDs provisórios `C-…`)

Formato: `C-<pessoa>-<n>` · prioridade · pré-requisitos · critério de aceitação resumido (completo no módulo).

### P5 — arquitetura, integração, frontend, demo

| ID | Prio | Título | Aceitação resumida |
|---|---|---|---|
| C-P5-01 | P0 | Contratos acordados e publicados | `contracts/*.py` + `make contracts`; aprovação de P1–P4 |
| C-P5-02 | P0 | `core/db` (SQLite) e migrações | Migrações do zero; testes em memória |
| C-P5-03 | P0 | `core/events` (barramento + `domain_event`) | Idempotência; handler falhado isolado |
| C-P5-04 | P0 | `households`, papéis e DTOs por papel | Matriz papel × rota; senhorio sem presença |
| C-P5-05 | P0 | Seed da casa de demo + reset | Reset < 1 min |
| C-P5-06 | P0 | Navegação por papel e páginas base (casa, recibos) | `make check` verde |
| C-P5-07 | P1 | Acessibilidade e páginas de consumo/orçamento | Estados loading/erro/vazio; contraste |
| C-P5-08 | P0 | Integração ponta a ponta e ensaio da demo | Cenário 2× seguidas; plano B |
| C-P5-09 | P0 | Entregáveis (README, resumo, apresentação) | Prazos confirmados (P-11) |
| C-P5-10 | P2 | Remoção do código ObjectOS (M4) | PRs por módulo; CODEOWNERS limpo |

### P1 — MCP, dispositivos, energia

| ID | Prio | Título | Aceitação resumida |
|---|---|---|---|
| C-P1-01 | P0 | Unidade de `instantPower` (reaproveita #12) | Unidade registada e `power_w` com proveniência |
| C-P1-02 | P0 | Simulador/replay de leituras | Cenário determinístico em CI |
| C-P1-03 | P0 | Degraus e `ConsumptionEvent` | Testes com FakeHome |
| C-P1-04 | P0 | Assinaturas e registo de aparelhos | `confidence`; `unknown` sem inventar |
| C-P1-05 | P1 | Aprendizagem com confirmações | Atualiza assinatura |
| C-P1-06 | P1 | Verificar escrita da tomada e da lâmpada (MCP-04/05) | Resultado registado no guia |
| C-P1-07 | P1 | Papel `room_meter` e vários dispositivos | Contratos estáveis |
| C-P1-08 | P2 | Clustering de desconhecidos; estimativa da lâmpada; automações físicas | — |

### P2 — visão e presença

| ID | Prio | Título | Aceitação resumida |
|---|---|---|---|
| C-P2-01 | P0 | Presença manual na aplicação e eventos de porta simulados | `PUT /api/presence/me`; simulador |
| C-P2-02 | P1 | Deteção de pessoas e linha na soleira (substitui #4) | N passagens ⇒ N eventos; zero imagens persistidas |
| C-P2-03 | P1 | Fusão de presença | Tolerância 20–30 min; `uncertain` |
| C-P2-04 | P2 | Casa vazia e alerta de entrada; Wi-Fi opt-in; provar acesso à câmara do kit | — |

### P3 — agente, notificações, interação

| ID | Prio | Título | Aceitação resumida |
|---|---|---|---|
| C-P3-01 | P0 | Centro de notificações (API + WS + lista) | Reconexão recupera por `GET` |
| C-P3-02 | P0 | Confirmação «De quem é esta conta?» | Resposta persistida; `409` na repetição |
| C-P3-03 | P1 | Histórico e preferências | Silêncio noturno |
| C-P3-04 | P1 | Assistente que explica recibos | Só valores das ferramentas |
| C-P3-05 | P1 | Explicabilidade («Porque aconteceu?», reaproveita #52) | — |
| C-P3-06 | P2 | Ações sugeridas com confirmação | Nunca executa sem `confirm` |
| C-P3-07 | P2 | Automações em português com pré-visualização (reaproveita #53) | Ativação explícita |
| C-P3-08 | P2 | Push (Capacitor) e leitura de faturas por LLM | — |

### P4 — faturação, orçamentos, alertas

| ID | Prio | Título | Aceitação resumida |
|---|---|---|---|
| C-P4-01 | P0 | Atribuição (A, B) com fallback de 24 h | Testes de regra e prazo |
| C-P4-02 | P0 | Fatura e fixtures A/B/C | Soma ao cêntimo |
| C-P4-03 | P0 | Recibo explicado com proveniência | Linhas por tipo |
| C-P4-04 | P0 | Orçamento pessoal 50/80/100 % | Um aviso por limiar |
| C-P4-05 | P1 | Regra C, limiar de pergunta, previsão, plafond por quarto e solidário, picos, contestação | — |
| C-P4-06 | P1 | Recomendações de poupança explicáveis (reaproveita #55) | — |
| C-P4-07 | P2 | Aparelho esquecido, «não bate certo», bi-horário, anomalias | — |
