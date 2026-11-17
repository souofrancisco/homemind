# Backlog: mapa de issues e destino das antigas

**IMPLEMENTADO no GitHub** (lido a 17/11/2026): 13 épicos (#58–#70), 68 issues de implementação `[CC · CÓDIGO]` e a roadmap mestre #129. Os IDs provisórios `C-Px-nn` das versões anteriores deste ficheiro **ficam substituídos** por estes códigos. Prioridades, fases e dependências: [roadmap.md](roadmap.md); responsabilidades: [team.md](team.md). Cada épico agrupa as suas tarefas como **sub-issues nativas** (ver [roadmap.md](roadmap.md) e a issue do épico).

## Épicos e tarefas

| Épico | # | Responsável | Tarefas (issue #) |
|---|---|---|---|
| BASE | 58 | P5 | BASE-01 #71 · BASE-02 #72 · BASE-03 #73 · BASE-04 #74 · BASE-05 #130 |
| MCP | 59 | P1 | MCP-01 #12 · MCP-02 #75 · MCP-03 #76 · MCP-04 #77 · MCP-05 #78 |
| ENERGY | 60 | P1 | ENERGY-01 #79 · -02 #80 · -03 #81 · -04 #82 · -05 #83 |
| HOUSE | 61 | P5 | HOUSE-01 #84 · -02 #85 · -03 #86 · -04 #87 · -05 #88 |
| BILL | 62 | P4 | BILL-01 #89 · -02 #90 · -03 #91 · -04 #92 · -05 #52 · -06 #93 · -07 #132 |
| APP | 63 | P5 (UI) / P3 (backend e confirmações) | APP-01 #94 · -02 #95 (P3) · -03 #96 (P3) · -04 #56 · -05 #97 · -06 #98 · -07 #99 |
| ALERT | 64 | P4 | ALERT-01 #100 · -02 #101 · -03 #102 · -04 #103 · -05 #55 · -06 #104 |
| PRES | 65 | P2 | PRES-01 #105 · -02 #106 · -03 #107 · -04 #108 · -05 #109 · -06 #131 |
| AGENT | 66 | P3 | AGENT-01 #110 · -02 #111 · -03 #112 · -04 #113 |
| SAFE | 67 | P2 | SAFE-01 #114 · -02 #115 · -03 #116 · -04 #117 |
| PRIV | 68 | P5 | PRIV-01 #118 · -02 #119 · -03 #51 · -04 #120 |
| DEMO | 69 | P5 (DEMO-03: P1) | DEMO-01 #121 · -02 #28 · -03 #122 · -04 #123 · -05 #29 · -06 #124 |
| PILOT | 70 | P5 (PILOT-02: P1) | PILOT-01 #125 · -02 #126 · -03 #127 · -04 #128 |

Issues antigas **reaproveitadas** (mantêm número e histórico): #12 → MCP-01, #28 → DEMO-02, #29 → DEMO-05, #51 → PRIV-03, #52 → BILL-05, #55 → ALERT-05, #56 → APP-04.

## Issues antigas do ObjectOS

Todas as restantes (#1–#11, #13, #14, #22–#27, #30, #31, #53, #54) estão **fechadas** e **mantêm-se fechadas**: histórico do ObjectOS. Não reabrir tarefas dos gestos descontinuados (objeto levantado, afinador, calibração). Os resultados reaproveitáveis estão em [migration.md](../architecture/migration.md).

## Notas de alinhamento v5.1

- #130 (BASE-05) é esta sincronização documental; #131 (PRES-06) e #132 (BILL-07) existem e estão em F3/F2 (opção C **sem** bloquear o MVP).
- Fase 2 do v5.1 (AWAY, aparelho esquecido ao sair): SAFE-02, PRES-06, ALERT-04, todas F3.
- Notificações: backend em `features/notifications` (P3, APP-02/03); páginas e componentes em `app/frontend` (P5, APP-01/05/06) sobre o contrato `Notification` ([contracts.md](../architecture/contracts.md)).
