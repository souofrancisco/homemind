# Roadmap, fases e prioridades

**PLANEADO.** Fonte viva: issue [#129](https://github.com/souofrancisco/homemind/issues/129) («Plano mestre») e, quando for criado (D-22, **pendente**), o GitHub Project «Conta Certa — Desenvolvimento». Este ficheiro é o espelho estável; se divergir do GitHub, vale a issue e corrige-se aqui. Âmbito de produto: [decisions.md](../decisions.md) D-14 (MVP e fase 2). **Datas não confirmadas** (P-11).

Cada issue de implementação tem um código estável (`ENERGY-03`, `APP-02`…), um responsável, prioridade (P0 essencial · P1 aprofundamento · P2 extensão) e fase. Mapa completo: [backlog.md](backlog.md).

## Fases

| Fase | Objetivo | Conteúdo (códigos) |
|---|---|---|
| **F0 — Preparação** | Contratos, persistência e decisões acordados | BASE-01…05, HOUSE-01, PRIV-01/02, MCP-01 |
| **F1 — MVP** | Vertical energia → notificação → fatura + presença na porta + assistente | MCP-02…05, ENERGY-01/02/03/05, HOUSE-02/03/04, BILL-01/02/04/05, APP-01…06 (APP-04 incl.), ALERT-01/03/06, PRES-01…04, AGENT-01/02, SAFE-01 (simulado), DEMO-01/02/03 |
| **F2 — Melhorias e ensaio** | Aprofundar e ensaiar | ENERGY-04, HOUSE-05, BILL-03/06/07, APP-07, ALERT-02/05, PRES-05, AGENT-03, SAFE-03, PRIV-03/04, DEMO-04/05/06 |
| **F3 — Fase 2 e piloto** | Segurança AWAY, aparelho esquecido, cenários, piloto | ALERT-04, PRES-06, SAFE-02/04, AGENT-04, PILOT-01…04 |

Nada de F2/F3 bloqueia o MVP. Em particular **AWAY, casa vazia e aparelho esquecido ao sair** (SAFE-02 #115, PRES-06 #131, ALERT-04 #103) são F3. HAN/contador geral não são dependência (PILOT-02 #126, opcional).

## Definição de pronto dos contratos (F0)

> **Estado (17/11/2026):** a fundação técnica está **implementada no PR draft `feat/conta-certa-foundation`** (BASE-02, BASE-03, HOUSE-01 parcial, PRIV-01 parcial: ver [contracts.md](../architecture/contracts.md)); aguarda a revisão da equipa e as decisões D-23…D-30. As issues **não** se fecham com o PR.

Cada pessoa só começa a implementar quando, para o seu módulo:

1. O modelo Pydantic proposto em [architecture/contracts.md](../architecture/contracts.md) foi lido e aceite pelas outras quatro pessoas (comentário no PR de contratos; BASE-03 #73).
2. Os eventos que produz e consome estão na tabela de eventos, com `data` essencial.
3. P5 publicou `contracts/*.py` com os modelos aceites e `make contracts` verde.
4. Existe um simulador ou evento falso do que o módulo consome (MCP-05 #78).

**Reunião de contratos (1 h, todos):** `Provenance`, `EnergyReading`, `ConsumptionEvent`, `Notification`, `Attribution`, `BillAllocation`, envelope de eventos e papéis.

## Hora zero (hardware, em paralelo com a F0)

Baseado no v5.1 §20 e nos bloqueios conhecidos ([risks.md](risks.md)). **Nada é REAL antes de PASS no [guia de validação](guia-validacao-manual.md).**

| # | Verificação | Issue | Dono | Se falhar |
|---|---|---|---|---|
| 1 | OAuth MCP a partir do backend (`make mcp-login`, `make mcp-doctor`) | MCP-01 #12 | P1 | Já provado em leituras; repetir no dia |
| 2 | **Unidade de `instantPower`** com carga conhecida; atraso de atualização | MCP-01 #12 | P1 | `estimated` (potência nominal × estado) ou simulador |
| 3 | **Escrita na tomada e na lâmpada** | MCP-04 #77, DEMO-03 #122 | P1 | Só simulado |
| 4 | Acesso à imagem da câmara (RTSP, telemóvel, clip) | PRES-01 #105 | P2 | Clip/telemóvel; presença manual |
| 5 | Registo manual de presença na aplicação | PRES-03 #107 | P2 + P5 | — |
| 6 | Leitura de contacto/clima/fumo dentro da política MCP | MCP-03 #76 | P1 | `unknown`; SAFE-01 só simulada |

## Bloqueios críticos e dependências

| Bloqueio | Bloqueia | Mitigação |
|---|---|---|
| Contratos acordados (BASE-03 #73) e `core/db` + barramento (BASE-02 #72) | **Tudo** | P5 primeiro; P1/P2 entregam simuladores antes do hardware |
| Unidade de `instantPower` (MCP-01 #12) | `measured` em ENERGY-02/03, DEMO-02 | `estimated`/`simulated` com rótulo |
| MCP-02 #75 (collector) | MCP-03 #76, ENERGY-02 #80 | FakeHome (MCP-05 #78) |
| MCP-03 #76 | SAFE-01 #114, SAFE-03 #116 | Simulado |
| ENERGY-03 #81 → ENERGY-05 #83 | APP-03 #96, BILL-02 #90 | Fixtures de `ConsumptionEvent` |
| HOUSE-04 #87 + BILL-01 #89 | BILL-02 #90, BILL-04 #92 | Seed da casa de demo |
| PRES-04 #108 | BILL-07 #132 (opção C), SAFE-01 | Presença manual (PRES-03) |
| APP-02 #95 (P3, backend) ↔ APP-01/05/06 (P5, UI) | APP-03 #96, AGENT-02 #111 | Contrato `Notification` na BASE-03 |

Dependências são por referência nas issues (e `blocked by` quando o GitHub o permite); **não** se confundem com a hierarquia épico → tarefa (sub-issues nativas).

## Avaliação do excesso de P0 (17/11/2026)

Issues abertas Conta Certa: 68 issues: P0 = 46 (F0: 9, F1: 34, F2: 3), P1 = 13, P2 = 9. É muito para o prazo (v5.1 §26.5), mas o §19.1 do v5.1 lista como «nunca cortar» exatamente o que está em P0 (assinaturas + três regras, câmara + Wi-Fi, orçamento, pico, janela → corte simulado, agente). **Decisão: não alterar etiquetas**; em vez disso, ordem de corte explícita (não reduz o núcleo essencial):

1. AGENT-04, SAFE-04 (já P2/F3); regra escrita pelo júri ao vivo.
2. Previsão do fim do mês (ALERT-02, P1/F2: fica só o aviso por percentagem).
3. Opção C da sala (BILL-07, P1/F2: fica a B «o bot/app pergunta», com fallback A).
4. ALERT-06 (lâmpada RGB) se MCP-04 não tiver PASS: feedback só no ecrã.
5. PRES-03 Wi-Fi: fica a presença manual + porta.

Nunca cortar: ENERGY-01/02/03/05, BILL-01/02/04/05, APP-02/03, ALERT-01/03, PRES-02/04, AGENT-01/02, DEMO-01/02/03/06, PRIV-01/02. Reveja-se após a F0.

## Ordem de trabalho (próxima tarefa)

1. **P5:** BASE-02 → BASE-03 → HOUSE-01 → PRIV-01 (desbloqueiam todos).
2. **P1:** MCP-01 + MCP-05 (FakeHome/fixtures) → MCP-02 → ENERGY-01/02.
3. **P2:** PRES-01 (fontes de vídeo, plano B) → PRES-02/03.
4. **P3:** contrato `Notification` (com BASE-03) → APP-02 → AGENT-01.
5. **P4:** BILL-01 + fixtures A/B → BILL-02 → ALERT-01.
