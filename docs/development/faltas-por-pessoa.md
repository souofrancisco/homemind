# O que falta por issue, por pessoa — 2026-11-18

> **Estado: levantamento pontual (2026-11-18, atualizado depois da migração BASE-04; `main` em `928b01e`).** Não substitui o [backlog](backlog.md) nem o [roadmap](roadmap.md): é uma fotografia do que impede **fechar** cada issue aberta. Equipas e prioridades: [team.md](team.md).

**Como ler.** Cada linha diz o que falta *além* do que já está na `main`. **Tipo:** `código` (há que implementar), `validação` (existe, falta prová-lo no browser ou no kit), `decisão` (a equipa, o DPO ou a P5 decidem) ou `externo` (fora do alcance da equipa). **✔** = confirmei no código a 2026-11-18; as restantes vêm dos comentários das issues, do comentário de auditoria de 2026-11-18 e dos PRs.

**Já fechadas hoje:** #104 (ALERT-06), #126 (PILOT-02) e o épico #65 (PRES, com as 6 filhas fechadas).

**Entrou hoje na `main`:** #207, #209 e #211 (P4); a correção da lâmpada (#218); o estudo do contador e MEO Energia (#220); o nome do aparelho no pedido «De quem é esta conta?» (#223); e a **migração BASE-04**, que removeu o ObjectOS (#225, #227, #228, #229, #230).

**Prazos.** O comentário de 17/11 no #29 dá o **PDF de 2 páginas para 18/11/2026 às 19h**. Não conheço mais nenhum prazo.

## Resumo

| Pessoa | Issues abertas | Mais perto de fechar | Mais trabalho de código |
|---|---|---|---|
| **P1** `brunovieira88` | #122 | #122 (só kit) | — |
| **P2** `1Mii` | #51, #115, #117 | — | #115, #117 (fase 3) |
| **P3** `RafaelMat0s-Dev` | #96, #99, #110, #111, #112, #113, #157 | #96 (validação) | #111 (chat), #99 (push) |
| **P4** `Amorim3000` | #55, #103, #120, #132 | **#132**, #120 | #55 |
| **P5** `souofrancisco` | #28, #29, #74, #85, #88, #94, #97, #121, #123, #124, #125, #127, #128 | #74, #94, #121 | #88 (UI de onboarding), #97 |

Os épicos abertos acompanham as filhas: #58 (BASE), #61 (HOUSE), #62 (BILL), #63 (APP), #64 (ALERT), #66 (AGENT), #67 (SAFE), #68 (PRIV), #69 (DEMO), #70 (PILOT) e o mestre #129. Só fecham quando as filhas fecharem.

---

## P1 — `brunovieira88` · MCP, dispositivos, energia

### [#122](https://github.com/souofrancisco/homemind/issues/122) · DEMO-03 · Verificação de hardware e planos B com evidência
Feito a 2026-11-18 (REAL, com o operador a olhar): MCP-01, 02, 05, 06, 08 e 09 em PASS; MCP-04 em FAIL com a causa apurada e corrigida no código (#218); evidência na Folha de resultados do [guia de validação](guia-validacao-manual.md).

| O que falta | Tipo |
|---|---|
| **Repetir o MCP-04** no kit real com a correção do #218 (`--write lamp`, lâmpada à vista, ~3 min). Só então passa a PASS | validação |
| **MCP-07** (falhas, autorização e reconexão): são passos manuais do guia; o runbook não os faz no kit real | validação |
| **MCP-08:** a latência do contacto ficou «< ~3 s, valor exato não medido» (o relógio do runbook só arranca depois de um bip). Medir com precisão só se a meta «janela → corte < 10 s» o exigir | validação |
| **Ensaiar no kit o `Home` realojado** (`features/energy/home_runtime.py`, com `HOME_BACKEND=mcp`): uma leitura e um comando à lâmpada. Depois da migração BASE-04 o caminho só foi testado com doubles e em modo SIMULADO | validação |
| VID-04 (câmara) continua **BLOQUEADO** pelo PRIV-02 (#119); não executar sem essa autorização | decisão |

Dependências: nenhuma em aberto (#12, #75 e #105 estão fechadas).

---

## P2 — `1Mii` · Visão e presença

### [#51](https://github.com/souofrancisco/homemind/issues/51) · PRIV-03 · Retenção, consentimentos, exportação e eliminação
Feito: opt-in de Wi-Fi e revogação, retenção, eliminação e exportação de dados de presença (#215).

| O que falta | Tipo |
|---|---|
| Consentimento **por fonte** e o seu **registo** (hoje só há um `presence_opt_in`) e a UI | código |
| **Política e restauro de backups** (um backup antigo mantém os dados) | decisão + código |
| Prazos de retenção (hoje PROPOSTA, 30 dias por omissão na presença) | decisão (DPO, P-08) |
| **Gate jurídico** (P-24): nenhuma afirmação de conformidade RGPD; bloqueia o piloto com pessoas e sensores reais | externo |
| Validar no browser e no kit | validação |

Nota: o **#217** apaga a cópia de presença da faturação (`billing_presence_state`) de quem revoga ou sai, na primeira mensagem de presença seguinte da casa; sem tráfego, a linha fica até à seguinte; sem UI de revogação.

### [#115](https://github.com/souofrancisco/homemind/issues/115) · SAFE-02 · Casa vazia/AWAY e segurança MCP com confirmação (fase 3)
| O que falta | Tipo |
|---|---|
| ✔ `safety` **não consome** a casa vazia: o evento já existe (PRES-06, #216; contrato em `contracts/presence.py`) | código |
| Estado AWAY e armamento: **simulação distinta de execução real** | código |
| Segurança por MCP **só com whitelist expandida depois de revisão** (hoje: lâmpada e tomada; nunca alarme, segurança, cenários ou timers) | decisão |
| Ausência de sinais mantém `unknown` (critério a provar com teste) | código |

Já **desbloqueada**: o #131 (PRES-06) está fechado.

### [#117](https://github.com/souofrancisco/homemind/issues/117) · SAFE-04 · Motor de cenários e regras votadas pela casa (fase 3)
| O que falta | Tipo |
|---|---|
| Motor de cenários e votação da casa | código |
| Regras que não sobrepõem a segurança nem alteram a instalação sem grant; controlo visível por casa | código |
| Testes de conflito e concorrência | código |

Depende do #115.

---

## P3 — `RafaelMat0s-Dev` · Agente, notificações, interação na app

### [#96](https://github.com/souofrancisco/homemind/issues/96) · APP-03 · Fluxo «É minha / É de todos / Não sei»
Feito: a votação D-32 na UI e no backend; «É minha» decide e o orçamento passa a «Confirmado (meu)».

| O que falta | Tipo |
|---|---|
| **Provar voto → recibo** na fatura seguinte | validação |
| Testar «É de todos», «Não sei» e «É de outra pessoa» no browser | validação |
| Decidir o **retry**: hoje responder duas vezes dá `409 already_responded` (P-03) | decisão |

### [#99](https://github.com/souofrancisco/homemind/issues/99) · APP-07 · Notificações push, preferências e acesso offline
| O que falta | Tipo |
|---|---|
| ✔ **Push** (não há nada de push no frontend nem dependência Capacitor de push): sem permissões por omissão, deduplicação, entrega de teste e deep-link | código |
| **Acesso offline** | código |
| Mensagens no lockscreen sem detalhes privados | código |

As preferências já persistem. Push em Android/iOS é P2 (PROPOSTA) em `modules/notifications.md`.

### [#110](https://github.com/souofrancisco/homemind/issues/110) · AGENT-01 · Ferramentas tipadas read-only
Feito: 3 ferramentas (consumo, orçamento, recibo), com testes sem rede nem LLM.

| O que falta | Tipo |
|---|---|
| **Providers reais** de P4 (consumo, orçamento, recibos) e P1 (energia), no lugar de `simulated.py`. Sem isto os valores não vêm dos motores | código |
| Ferramentas de **aparelhos**, **explicação da atribuição** e **confirmações pendentes** | código |

### [#111](https://github.com/souofrancisco/homemind/issues/111) · AGENT-02 · Assistente conversacional na app
Feito: backend de mensagens, histórico por residente e fallback quando o LLM está indisponível.

| O que falta | Tipo |
|---|---|
| ✔ A rota `/assistente` existe mas mostra só «A interface do assistente está por integrar»: **falta a conversa** (o chat) | código (com P5) |
| Cada resposta identificar período, origem e incerteza: `AgentToolResult` não tem `period` nem `confidence` | código (contrato, P5) |
| Providers reais (ver #110) | código |
| Decidir o **P-06** (que dados de consumo podem sair para o fornecedor de LLM) antes de ligar `AGENT_LLM_ENABLED` | decisão |

### [#112](https://github.com/souofrancisco/homemind/issues/112) · AGENT-03 · Propostas de ações por IA com confirmação
Feito: ciclo de ações com confirmação e propostas a partir de alertas de conforto (backend, simulado).

| O que falta | Tipo |
|---|---|
| UI das propostas e da confirmação | código (depende do #111) |
| Evidência de que a injeção de prompt não altera dispositivos (testes com FakeHome) | validação |

### [#113](https://github.com/souofrancisco/homemind/issues/113) · AGENT-04 · Regras em português e conversão para cenários
| O que falta | Tipo |
|---|---|
| Parser de regras em português e conversão segura para cenários | código |
| Rejeitar regras com capabilities indisponíveis; nenhuma ação física por teste de texto | código |

Depende do #111.

### [#157](https://github.com/souofrancisco/homemind/issues/157) · BASE-03 · Pedidos de P3 ao contrato
Feito: `BudgetThreshold` já tem `resident_id`, `period` e `limit_cents` (✔).

| O que falta (✔ confirmado ausente no código) | Tipo |
|---|---|
| Evento **`notification.expired`** (para a P4 aplicar o recurso quando ninguém responde) | decisão + código (P5) |
| Modelos de **WebSocket** `notification` e `notification_update` e o gancho em `core` | decisão + código (P5) |
| `AgentTool`: +`pending_confirmations`, `my_appliances`, `attribution_explanation` | código (P5) |
| `AgentToolResult`: +`period`, `confidence`, `lines` | código (P5) |
| `AgentResponse`: +`used_llm` e `degraded_reason` | código (P5) |
| Mover os `Protocol` dos providers para `contracts/agent.py` e registá-los em `app.state` | código (P5) |
| Restantes pontos (audiência por `kind`, operador, «dispensar», rotas por casa): são **decisões** | decisão |

É uma issue de **triagem**: toda a mudança partilhada precisa da aprovação da P5.

---

## P4 — `Amorim3000` · Faturação, orçamentos, alertas

### [#132](https://github.com/souofrancisco/homemind/issues/132) · BILL-07 · Opção C: repartição por presença
**Os critérios do corpo estão cumpridos pelo #211**: cenário «sozinho vs visitas e ausência incerta», recibo explicável e contestável, senhorio sem rastos de presença, fallback claro para a conta comum.

| O que falta | Tipo |
|---|---|
| **Nada do que a issue pede.** Só fechá-la | decisão |
| *Opcional, fora do critério:* dividir só por quem estava em casa (2 de 4). Exige um alvo novo em `Attribution`, e daí mexer no fecho, recibo, explicação, contestação, orçamento e frontend. Abrir issue própria | código |
| Validação com kit real da fusão de presença (P2) e da contagem da porta | validação |

### [#120](https://github.com/souofrancisco/homemind/issues/120) · PRIV-04 · Logs financeiros, auditoria e retenção mínima
Feito: trilho financeiro por `correlation_id` (#205), logs mascarados (`core/redact.py`, #205), anonimização de ex-moradores, desligada por omissão (#213).

| O que falta | Tipo |
|---|---|
| **Decidir** os prazos com o DPO (P-08) e ligar `RETENTION_ANONYMIZE_AFTER_DAYS` | decisão |
| **Revisão da P5** ao trigger `domain_event_no_delete` e ao logging global (tocam em `core/`) | decisão |
| Expurgo **operacional** (notificações, automações, agente): PLANEADO | código |

### [#55](https://github.com/souofrancisco/homemind/issues/55) · ALERT-05 · Energy Insights
| O que falta | Tipo |
|---|---|
| **Histórico**, gráficos com unidades e proveniência, **comparação** e **recomendações explicáveis** (só existe `/energy/overview`, o estado atual) | código |
| Nunca tratar `null` como zero; testes de histórico e de privacidade | código |

Depende do #97 (gráficos no dashboard).

### [#103](https://github.com/souofrancisco/homemind/issues/103) · ALERT-04 · Aparelho potencialmente esquecido (fase 3)
| O que falta | Tipo |
|---|---|
| **Produtor** do alerta `forgotten_appliance` e o texto (só existe o tipo no contrato) | código |
| «Desligar» com permissão e confirmação física, falhas reportadas, nunca assumir abandono se a presença for incerta | código (com P1/P2) |

Já **desbloqueada**: o estado de casa vazia (#131) existe.

---

## P5 — `souofrancisco` · Arquitetura, integração, frontend, demonstração

### [#85](https://github.com/souofrancisco/homemind/issues/85) · HOUSE-02 · Associação OIDC, papéis e acesso por residência
Feito: convites, memberships, RBAC por casa e isolamento por papel (verificados no browser e por HTTP).

| O que falta | Tipo |
|---|---|
| ✔ **Limite de abuso** em `POST /api/invitations/accept` (só existe rate limit no agente) | código |
| SMTP e **`email_verified=true` no access token real** do Authentik (sem forçar o claim) | configuração |
| Teste com login real; manter o *fail-closed* | validação |

### [#88](https://github.com/souofrancisco/homemind/issues/88) · HOUSE-05 · Onboarding e substituição de moradores
| O que falta | Tipo |
|---|---|
| ✔ **Toda a UI** (o frontend não tem nada de convites): emitir e partilhar convite, aceitar, escolher casa, entrada, saída e substituição | código |
| Entrada e saída sem apagar dados contabilísticos; revogação imediata; consentimentos explícitos | código |

Depende do #85.

### [#94](https://github.com/souofrancisco/homemind/issues/94) · APP-01 · Navegação e identidade Conta Certa
Feito: shell em PT-PT por papel; morador, senhorio e operador veem só as suas secções (browser desktop).

| O que falta | Tipo |
|---|---|
| Validar o **layout móvel** e a apresentação em **projetor** | validação |
| Testes de frontend (não existem) | código |

### [#97](https://github.com/souofrancisco/homemind/issues/97) · APP-05 · Dashboard de potência, consumo e REAL/SIMULADO
Feito: dashboard, consumo e aparelhos, «sem dados» em vez de 0, leitura antiga e offline (polling de 15 s).

| O que falta | Tipo |
|---|---|
| ✔ **Reconexão do WebSocket**: o backend **já não tem WebSocket** (o `/api/ws` do motor foi removido na BASE-04) e a app usa polling de 15 s. Implementar o WS novo de notificações (depende do #157, ponto 4) ou rever o critério | decisão + código |
| **Gráfico histórico** | código |
| Validar no browser | validação |

### [#121](https://github.com/souofrancisco/homemind/issues/121) · DEMO-01 · Dataset de inverno e reset determinístico
| O que falta | Tipo |
|---|---|
| **Cenário de inverno completo** e o guião | código + documentação |
| Rever os testes de reset e replay offline com as migrações recentes | validação |

### [#28](https://github.com/souofrancisco/homemind/issues/28) · DEMO-02 · Integrar o fluxo vertical energia → notificação → fatura
Feito: leituras simuladas → pedido de atribuição → voto → fatura de 120 € → 4 recibos (testado, backend real e browser).

| O que falta | Tipo |
|---|---|
| **Gravar o percurso único** (guião #123) e a prova das 3 execuções (#124) | validação |
| Login Authentik com os utilizadores demo (o `sub` não bate com as fixtures) | código |
| ~~Limpeza BASE-04 (engine ligado a visão e conectores)~~ **feita** (#225, #227 a #230) | — |

### [#124](https://github.com/souofrancisco/homemind/issues/124) · DEMO-06 · CI, contratos e testes end-to-end
| O que falta | Tipo |
|---|---|
| **3 execuções E2E determinísticas** com fixtures | validação |
| «Pipeline verde»: **impossível enquanto a CI estiver desativada** (decisão da equipa); reativá-la ou rever o critério | decisão |

### [#29](https://github.com/souofrancisco/homemind/issues/29) · DEMO-05 · README, sumário executivo e apresentação final
| O que falta | Tipo |
|---|---|
| **Sumário executivo**, **slides** no template oficial, **PDF de 2 páginas (prazo 18/11 às 19h)** | documentação |
| Plano B preparado e relato de limitações validado com a equipa | documentação |

O README já foi reescrito.

### [#123](https://github.com/souofrancisco/homemind/issues/123) · DEMO-04 · Guião de 3 minutos, inquérito e perguntas do júri
| O que falta | Tipo |
|---|---|
| **Tudo**: guião cronometrado, respostas sobre privacidade, NILM e MCP reais, limites da tomada e adoção do senhorio | documentação |
| Resultados de inquérito **só se recolhidos** | — |

Depende do #28.

### [#74](https://github.com/souofrancisco/homemind/issues/74) · BASE-04 · Limpeza do código ObjectOS
Feito (#225, #227, #228, #229, #230): removidos o motor ObjectOS (`features/engine`), os gestos e a visão de objetos, o stack ObjectOS do frontend e os contratos órfãos; o `Home` do kit passou para `features/energy/home_runtime.py`; login do Authentik, nome visível do Android e textos renomeados para «Conta Certa». Rotas 86 → 75. Plano e história em [migration.md](../architecture/migration.md).

| O que falta | Tipo |
|---|---|
| **Revisão da P5** ao que entrou sem ela: `core/events.py` (despertar do barramento entre event loops), remoções em `contracts/`, e os ficheiros de Compose e do blueprint do Authentik editados | decisão |
| `client_name="ObjectOS"` no registo OAuth da Altice (`connectors/altice_auth.py`): mudar só quando se puder testar o login com o kit | validação |
| Identificadores `homemind` (`pt.homemind.app`, pacote, cliente OIDC, Compose): P-14, depois da demo | decisão |
| Ensaio do `Home` realojado no kit real (ver #122) | validação |
| **Fechar a issue** quando a P5 confirmar: já não há código ObjectOS vivo | decisão |

### Fase 3 e externas
| Issue | O que falta |
|---|---|
| [#125](https://github.com/souofrancisco/homemind/issues/125) PILOT-01 | Pesquisa com estudantes e senhorios (fase 3) |
| [#127](https://github.com/souofrancisco/homemind/issues/127) PILOT-03 | Produção multi-imóvel, instalação e mudança de inquilino (fase 3) |
| [#128](https://github.com/souofrancisco/homemind/issues/128) PILOT-04 | **Revisão jurídica/AIPD externa** (bloqueada) |

---

## Dependências entre issues

`#85` → `#88` · `#111` → `#112`, `#113` · `#115` → `#117` · `#28` → `#123` → `#29` · `#157` (ponto 4, WebSocket) → `#97` · `#97` → `#55` · `#131` (fechada) desbloqueia `#103` e `#115`.
