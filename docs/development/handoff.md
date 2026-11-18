# Handoff — 2026-11-18 → 2026-11-19

Estado real: [`../functional-flows.md`](../functional-flows.md). Tarefas, dependências e estados: [Project](https://github.com/users/souofrancisco/projects/1) (este ficheiro é só o resumo do dia; o Project manda). Fluxo de trabalho: [`../ai-workflow.md`](../ai-workflow.md). **Reatribuições abaixo são PROPOSTAS: dependem de acordo da equipa, não foram aplicadas.**

## Plano por pessoa

| Pessoa | Tarefa principal (Pronto/Review) | Próxima (independente) | Ficheiros preferenciais |
|---|---|---|---|
| **P1** `brunovieira88` | **#122 DEMO-03** — correr o [guia de validação](guia-validacao-manual.md) no kit real: leituras primeiro; escritas só com autorização explícita e grant temporário; registar PASS/FAIL/BLOQUEADO com hora e dispositivo | **#82 ENERGY-04** — feedback explícito dos moradores em desconhecidos recorrentes | `features/energy/`, `connectors/`, `docs/integrations/` |
| **P2** `1Mii` | **#109 PRES-05** — contador agregado de visitas exposto à app, sem identidade, nunca ao senhorio (teste papel × rota) | Proposta: assumir **#56 APP-04** (modo sem câmara, check-in manual só como resposta a pergunta do sistema) | `features/presence/`, `features/safety/` |
| **P3** `RafaelMat0s-Dev` | **#111 AGENT-02** — interface do assistente na app (backend e fallback já existem; a página é placeholder) | **#96 APP-03** — provar voto → recibo na fatura seguinte; depois **#110** (ferramentas: aparelhos, atribuição, notificações) | `features/agent/`, `features/notifications/`, `app/frontend/src/pages/` (só a página do assistente) |
| **P4** `Amorim3000` | **#104 ALERT-06** — cue RGB/texto de orçamento e conforto (efeito físico só com autorização) | **#101 ALERT-02** — previsão mensal e tarifário; proposta: assumir **#87 HOUSE-04** (versionamento de políticas) | `features/billing/` |
| **P5** `souofrancisco` | **#28 DEMO-02 / #123 DEMO-04** — percurso único gravado, guião de 3 min; **#124** três execuções E2E; rever PRs (#195 primeiro) | **#94 / #97** — layout móvel e reconexão WebSocket; manter `core/`, `contracts/`, Makefile | `core/`, `contracts/`, `app/frontend/`, `docs/` |

Dependências ativas (*blocked by*): #88←#85, #112←#111, #113←#111, #115←#131, #117←#115, #123←#28, #29←#123, #124←#28.

## Propostas de redistribuição (P5 tem a maioria das issues abertas)

| Issue | Atual | Proposta | Porquê |
|---|---|---|---|
| #87 HOUSE-04 | P5 | P4 | política de atribuição vive em `billing/attribution.py` |
| #99 APP-07 | P5 | P3 | push/preferências = notificações |
| #56 APP-04 | P5 | P2 | modo sem câmara / presença manual |
| #51 PRIV-03 | P5 | P2 | consentimentos/retenção de Wi-Fi e presença |
| #120 PRIV-04 | P5 | P4 | auditoria de decisões financeiras |
| #157 BASE-03 | — | P5 (contratos) com P3 | sem responsável |

## Demonstração ao orientador (≈5 min, SIMULADA)

`make demo-up` → ver o percurso no [README](../../README.md). Dizer claramente: tudo SIMULADO; hardware real por validar (#122); assistente ainda sem UI. Plano B: `make demo-web-up` (Docker, :25173).

## Decisões e bloqueios que exigem pessoas

1. **Merge** dos PRs #195 (ambiente) e do de documentação, por esta ordem; testar `make demo-up` com as portas de omissão numa máquina livre.
2. Aceitar/recusar as reatribuições acima.
3. #85: verificação de email e limite de abuso para convites reais (decisão externa).
4. #128: revisão jurídica/AIPD (externa).
5. Chrome para o Playwright MCP (`/opt/google/chrome/chrome` não existe): `npx playwright install chrome`.
6. Volume Docker antigo `homemind_authentik-db` com palavra-passe desconhecida (o fluxo novo usa `homemind-auth`): apagar só se ninguém precisar.
