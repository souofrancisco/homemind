# Conta Certa — roadmap mestre, versão 5.1 (17/11/2026)

> **Atualização de coordenação · 18/11/2026:** [GitHub Project #1 — Conta Certa · Desenvolvimento](https://github.com/users/souofrancisco/projects/1/views/1) criado pelo responsável. Este Project passa a ser o local de acompanhamento da equipa **quando os seus itens/vistas estiverem configurados**. [PR documental #192](https://github.com/souofrancisco/homemind/pull/192) (Draft) propõe o guia de gestão, triagem e colaboração com IA. A auditoria atual de issues mostra **54 abertas, 53 fechadas e 0 PRs abertos antes do #192**, incluindo épicos e histórico ObjectOS. A auditoria de 17/11 descrita abaixo é histórica: **não usar as contagens ou estados antigos para fechar/atribuir trabalho sem consultar o código e as issues atuais**. O CI permanece desativado por decisão da equipa.


**Fonte atual:** `docs/references/Conta_Certa_Documento_Completo_v5.1.md` já incorporada na `main`, com os PDFs históricos preservados em `docs/references/`. A decisão posterior dos responsáveis tem prioridade: **sem Telegram e sem Streamlit**; notificações, confirmações e assistente na aplicação React/Mantine/Capacitor existente.

**Auditoria do backlog e código (17/11/2026, HEAD observado `adcad8a`):** entre as 70 issues com título `[CC · …]`, **24 estão fechadas (inclui 1 duplicada #173) e 46 abertas**, distribuídas por F0 8/8 concluídas tecnicamente, F1 14 fechadas/20 abertas, F2 2 fechadas (1 duplicada)/16 abertas e F3 0 fechadas/9 abertas. São contagens do GitHub, não métricas de testes. HOUSE-03 #86 e PRIV-02 #119 concluídas; HOUSE-02 #85 tem backend integrado mas aceitação real de convites bloqueada por `email_verified`/rate limit. Alertas pessoais ALERT-01 #100 integrados e fechados em PR #174. Outros módulos da equipa: ENERGY-02 #80, BILL-01 #89, BILL-04 #92, PRES-01…04 #105…108, SAFE-01 #114 e SAFE-03 #116 fechados. **Parciais:** P1 NILM #79/#81/#83; P3 APP-02/03 #95/#96 e AGENT-01/02/03 #110…112 (backend sem UI/provedores reais); P4 BILL-02 #90 (ligação às políticas históricas) e ALERT-03 #102; P5 APP-01 #94 / HOUSE-04 #87 / DEMO-01 #121 ainda em PR, DEMO-02 #28 parcial. Conferir estados atuais antes de novos merges; a última CI verde observada não é necessariamente do HEAD mais recente. Os épicos e issues abertas não devem ser eliminados sem concluir os respetivos critérios.

## 1. Ordem de desenvolvimento e gates

### F0 — preparação, contratos e hora zero (8 issues; 8 concluídas no âmbito técnico)
- [BASE-01 #71](https://github.com/souofrancisco/homemind/issues/71) fixar requisitos v5.1 e a decisão da app; [BASE-05 #130](https://github.com/souofrancisco/homemind/issues/130) sincronizar branch documental, issues e guia de agentes; o plano KEEP/ADAPT/REMOVE está publicado; a limpeza remanescente [BASE-04 #74](https://github.com/souofrancisco/homemind/issues/74) foi diferida para F2.
- [BASE-02 #72](https://github.com/souofrancisco/homemind/issues/72) schema SQLite + idempotência; [BASE-03 #73](https://github.com/souofrancisco/homemind/issues/73) contratos OpenAPI/eventos.
- [PRIV-01 #118](https://github.com/souofrancisco/homemind/issues/118) papéis/isolamento e [PRIV-02 #119](https://github.com/souofrancisco/homemind/issues/119) privacidade da câmara/Wi-Fi.
- [MCP-01 #12](https://github.com/souofrancisco/homemind/issues/12): medir/confirmar a unidade do `instantPower`, latência e alcance. RTSP, sensores e escritas físicas só são considerados reais com teste registado; não usar equipamento em carga fora de condições seguras.
- **Gate:** interfaces acordadas pelas cinco pessoas, acesso/limites validados ou fallback explicitamente SIMULADO, nenhuma alteração física sem autorização.

**Estado F0:** contratos/SQLite/RBAC/OpenAPI pela PR #135; unidade de `instantPower` validada em MCP-01 #12. PRIV-02 #119 fechada no âmbito técnico com hardening fail-closed; [PRIV-03 #51](https://github.com/souofrancisco/homemind/issues/51) continua a bloquear piloto real até retenção, informação, bases legais e eventual AIPD. HOUSE-02 #85 está na `main`, mas convites reais continuam fail-closed até o Authentik verificar emails e existir proteção contra abuso.

### F1 — MVP da hackathon: Casa Justa + Atenta + M1–M4 (34 issues)
- **M1 perceção:** [PRES-01 #105](https://github.com/souofrancisco/homemind/issues/105), [PRES-02 #106](https://github.com/souofrancisco/homemind/issues/106), [PRES-03 #107](https://github.com/souofrancisco/homemind/issues/107), [PRES-04 #108](https://github.com/souofrancisco/homemind/issues/108): RTSP/clip, YOLO porta, Wi-Fi hotspot opt-in, fusão e entrada manual de fallback.
- **M2 energia/assinaturas:** [MCP-02 #75](https://github.com/souofrancisco/homemind/issues/75), [MCP-05 #78](https://github.com/souofrancisco/homemind/issues/78), [ENERGY-01 #79](https://github.com/souofrancisco/homemind/issues/79), [ENERGY-02 #80](https://github.com/souofrancisco/homemind/issues/80), [ENERGY-03 #81](https://github.com/souofrancisco/homemind/issues/81), [ENERGY-05 #83](https://github.com/souofrancisco/homemind/issues/83); distinguir aparelho identificado, provável e desconhecido. Com uma tomada agregada, a localização/quarto não é dedutível sem evidência/declaração.
- **M3 decisão em código:** [HOUSE-01 #84](https://github.com/souofrancisco/homemind/issues/84), [HOUSE-02 #85](https://github.com/souofrancisco/homemind/issues/85), [HOUSE-03 #86](https://github.com/souofrancisco/homemind/issues/86), [HOUSE-04 #87](https://github.com/souofrancisco/homemind/issues/87), [BILL-01 #89](https://github.com/souofrancisco/homemind/issues/89), [BILL-02 #90](https://github.com/souofrancisco/homemind/issues/90), [BILL-04 #92](https://github.com/souofrancisco/homemind/issues/92), [ALERT-01 #100](https://github.com/souofrancisco/homemind/issues/100), [ALERT-03 #102](https://github.com/souofrancisco/homemind/issues/102).
- **M4 interface e agente:** [APP-01 #94](https://github.com/souofrancisco/homemind/issues/94), [APP-02 #95](https://github.com/souofrancisco/homemind/issues/95) e [APP-03 #96](https://github.com/souofrancisco/homemind/issues/96) (P3 backend de notificações + P5 UI), [AGENT-01 #110](https://github.com/souofrancisco/homemind/issues/110), [AGENT-02 #111](https://github.com/souofrancisco/homemind/issues/111), dashboards e recibos [#97](https://github.com/souofrancisco/homemind/issues/97)/[#98](https://github.com/souofrancisco/homemind/issues/98), sem Telegram.
- **Conforto/kit na demo:** [MCP-03 #76](https://github.com/souofrancisco/homemind/issues/76), [MCP-04 #77](https://github.com/souofrancisco/homemind/issues/77), [ALERT-06 #104](https://github.com/souofrancisco/homemind/issues/104), [SAFE-01 #114](https://github.com/souofrancisco/homemind/issues/114) em FakeHome; ações físicas só com condições seguras e confirmação.
- **End-to-end:** [DEMO-01 #121](https://github.com/souofrancisco/homemind/issues/121), [DEMO-02 #28](https://github.com/souofrancisco/homemind/issues/28), [DEMO-03 #122](https://github.com/souofrancisco/homemind/issues/122): 4 moradores → degrau → assinatura provável → notificação «É minha» → orçamento 80% → recibo de 120€ com soma exata.
- **Gate:** fluxo completo 100% offline com dados SIMULADOS; qualquer hardware real tem prova específica. M1 e M4 podem usar fallback, mas o guião deve mostrar se o que se vê é REAL ou SIMULADO.

### F2 — robustez, transparência e ensaio (17 issues, incluindo BASE-04)
- [BASE-04 #74](https://github.com/souofrancisco/homemind/issues/74): limpeza incremental do ObjectOS somente depois de existirem substitutos funcionais, com testes de regressão; não bloqueia o MVP.
- Opção C por presença [BILL-07 #132](https://github.com/souofrancisco/homemind/issues/132), plafond [#91](https://github.com/souofrancisco/homemind/issues/91), contestação [#93](https://github.com/souofrancisco/homemind/issues/93), previsão [#101](https://github.com/souofrancisco/homemind/issues/101), Energy Insights [#55](https://github.com/souofrancisco/homemind/issues/55).
- Visitas anónimas [PRES-05 #109](https://github.com/souofrancisco/homemind/issues/109), melhorias de agente e preferências, privacidade/auditoria.
- [DEMO-04 #123](https://github.com/souofrancisco/homemind/issues/123), [DEMO-05 #29](https://github.com/souofrancisco/homemind/issues/29) e [DEMO-06 #124](https://github.com/souofrancisco/homemind/issues/124): guião de 3 minutos, perguntas do júri, CI e validação.
- **Gate:** 2 ensaios seguidos e critérios de faturação/segurança reproduzíveis. Cortar primeiro extras: regras em linguagem natural, previsão, opção C; não cortar o núcleo da conta justa.

### F3 — fase 2 após MVP e possível piloto (9 issues)
- Aparelhos esquecidos ao sair [ALERT-04 #103](https://github.com/souofrancisco/homemind/issues/103), casa vazia [PRES-06 #131](https://github.com/souofrancisco/homemind/issues/131), modo AWAY/alarme [SAFE-02 #115](https://github.com/souofrancisco/homemind/issues/115), ações avançadas e cenários com validação.
- Integrações de produção e modelo comercial [PILOT #70](https://github.com/souofrancisco/homemind/issues/70); **v5.1 retirou a necessidade de HAN/API de contador geral** do sistema-base. Produção = tomadas por quarto + fatura mensal; total em tempo real apenas na extensão do MVP.
- **Gate:** nada disto pode bloquear nem ser apresentado como entregue na demo da hackathon.

## 2. Os 13 sistemas e responsáveis

| Épico | Issues filhas | Principal |
|---|---:|---|
| [BASE #58](https://github.com/souofrancisco/homemind/issues/58) | 5 | @souofrancisco |
| [MCP #59](https://github.com/souofrancisco/homemind/issues/59) | 5 | @brunovieira88 |
| [ENERGY #60](https://github.com/souofrancisco/homemind/issues/60) | 5 | @brunovieira88 |
| [HOUSE #61](https://github.com/souofrancisco/homemind/issues/61) | 5 | @souofrancisco |
| [BILL #62](https://github.com/souofrancisco/homemind/issues/62) | 7 | @Amorim3000 |
| [APP #63](https://github.com/souofrancisco/homemind/issues/63) | 7 | @souofrancisco |
| [ALERT #64](https://github.com/souofrancisco/homemind/issues/64) | 6 | @Amorim3000 |
| [PRES #65](https://github.com/souofrancisco/homemind/issues/65) | 6 | @1Mii |
| [AGENT #66](https://github.com/souofrancisco/homemind/issues/66) | 4 | @RafaelMat0s-Dev |
| [SAFE #67](https://github.com/souofrancisco/homemind/issues/67) | 4 | @1Mii |
| [PRIV #68](https://github.com/souofrancisco/homemind/issues/68) | 4 | @souofrancisco |
| [DEMO #69](https://github.com/souofrancisco/homemind/issues/69) | 6 | @souofrancisco |
| [PILOT #70](https://github.com/souofrancisco/homemind/issues/70) | 4 | @souofrancisco |

## 3. Regras e dependências críticas
1. **A app substitui Telegram.** Não duplicar a UI num bot, não usar Streamlit. P3 lidera notificações backend; P5 interface e integração; P4 publica alertas.
2. **Números em código, não LLM.** Diferença entre potência W e energia kWh, classificação com confiança e parcelas medidas/estimadas/confirmadas; arredondamentos fecham a fatura.
3. **Só uma tomada no MVP** mede a extensão agregada; não inferir automaticamente quarto, identidade ou proprietário apenas por assinatura/posição. Nunca transformar dúvida em cobrança individual silenciosa.
4. **Proteção e segurança:** não gravar vídeo, sem reconhecimento facial; senhorio não consulta presença/horários/imagens. O quadro jurídico precisa de validação antes do piloto.
5. **MCP:** OAuth e leituras comprovadas, mas unidade `instantPower` desconhecida e escritas físicas sem confirmação conclusiva; whitelist e grants mantidos. Não fazer testes físicos sem autorização.
6. **Idempotência:** consumidor regista todos os `event.id` processados na mesma transação dos efeitos; a garantia de replay documentada foi corrigida na sessão do Claude. Replays apenas em base isolada.
7. **Documentação:** v5.1 e PDFs históricos já integrados na `main` (BASE-05 #130 concluída); contratos, infraestrutura SQLite, RBAC e OpenAPI publicados pela PR #135. A limpeza do ObjectOS é F2, sem apressar remoções.
8. **Entrega:** uma issue = PR pequeno + testes + critérios cumpridos; não fechar com base numa implementação do ObjectOS que já não satisfaz o novo domínio.

## 4. Hierarquia e visualização
- Cada épico possui checklist de filhas, cada filha aponta ao épico e a dependências. Converter a hierarquia para **GitHub sub-issues nativas** e criar **um GitHub Project v2** para acompanhar Status, Prioridade, Fase, Área e Assignee sem duplicar tickets. Ver [GitHub Projects](https://docs.github.com/en/issues/planning-and-tracking-with-projects).
- Não criar um Project por pessoa nem 13 boards; usar 1 Project com vistas por fase, trabalho ativo, responsável, bloqueios e roadmap.
- Status inicial das issues Conta Certa é To do, exceto bloqueios confirmados (hardware); uma issue só passa a Done com PR validado.

## 5. Primeiras cinco entregas em paralelo
- **P1 (@brunovieira88):** MCP-01 #12 concluída (W validado); avançar MCP-05, MCP-02 e ENERGY-01/02 com contratos F0.
- **P2 (@1Mii):** PRES-01/02 e fallback manual, depois Wi-Fi/fusão.
- **P3 (@RafaelMat0s-Dev):** APP-02/03 e AGENT-01, em coordenação com P5.
- **P4 (@Amorim3000):** BILL-01/02/04 e ALERT-01 (aguarda schemas base).
- **P5 (@souofrancisco):** BASE-01/02/03/05 e HOUSE-01 concluídas; avançar HOUSE-02 e APP-01, rever mudanças de contratos em todos os PRs. BASE-04 é F2.

**Progresso real:** a fundação técnica F0 está implementada e a CI do [commit `71c84f7`](https://github.com/souofrancisco/homemind/commit/71c84f71aa41213cd6659844226155228e408585) passou. O PR #135 reporta 345 testes e `make smoke` OK. Os motores P1–P4, os fluxos de onboarding, as rotas WS novas e o MVP funcional **continuam por implementar**. Decisões D-23…D-30 e P-16…P-21 permanecem sujeitas à revisão da equipa. GitHub Project/subissues nativas continuam pendentes de configuração.

