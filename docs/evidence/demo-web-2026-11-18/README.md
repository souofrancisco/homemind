# Evidência — demo web (2026-11-18)

Validação no browser (Chromium real, Playwright) com dados **SIMULADOS** (FakeHome + seed DEMO-01).
Duas execuções:

- **A** — `make demo-web-up` (Docker, `main` @ `4245e58`): Authentik :29000, API :28000, app :25173.
- **B** — `make demo-up` (anfitrião, `origin/main` @ `d94f430`, PR #193): Authentik :19000, API :18000, app :15173 (portas alternativas porque as de omissão estavam ocupadas por `make dev`).

O Playwright MCP não arrancou (`Chromium distribution 'chrome' is not found at /opt/google/chrome/chrome`); o percurso correu com um script Playwright sobre o Chromium de `~/.cache/ms-playwright`.

| # | Passo | Conta | Resultado observado | Run | Estado |
|---|---|---|---|---|---|
| 1–3 | Login OIDC (PKCE), casa e papel | ana | Início; papel «MORADOR»; «Casa da Rua Direita (demo)» | A, B | VALIDADO no browser |
| 4–5 | Início, Casa, Consumo | ana | quartos/zonas, tomada medida, sessões «Consumo não identificado», tudo SIMULADO | A, B | VALIDADO |
| — | Aparelhos | ana | «Ainda não há aparelhos registados» (o seed não cria catálogo) | A | LIMITAÇÃO |
| 6 | Notificações | ana, bruno | «De quem é esta conta?» (0,64 € estimados, «0 de 4 votos (decide-se com 2)») | B | VALIDADO |
| 7–8 | Responder «É minha» | ana | decisão imediata: «Decidido: assumido por quem o usou»; Bruno vê «Esta utilização não fica a teu cargo»; Orçamento de Ana passa a «Confirmado (meu) 0,64 €» | B | VALIDADO (D-32: um «É minha» basta) |
| 9 | Orçamento | ana | 35 € → «85 % do orçamento utilizado» após a fatura; notificação «Orçamento a 80 %» | A | VALIDADO |
| 10–12 | Fatura 120 € | senhorio | 01–18/11/2026, fixo 15 €, 400 kWh: pré-visualizar («nada foi gravado») → registar (rascunho) → «Finalizar e repartir» | A, B | VALIDADO |
| 13–15 | Recibos | ana, bruno, carla, diogo | A: 30,00 + 29,99 + 30,00 + 30,01 = **120,00 €** · B (após `demo-reset`): 29,99 + 29,99 + 30,01 + 30,01 = **120,00 €**; recibo explicado («Porque pago isto?»); notificação «Recibo disponível» | A, B | VALIDADO |
| 16 | Isolamento (HTTP, Bearer de cada conta) | todos | ver abaixo | A | VALIDADO |
| 17 | Reset e repetição | todos | `make demo-reset`: pedido «0 de 4 votos» regressa; fatura repetida soma 120,00 € | B | VALIDADO |

## Isolamento (HTTP com Bearer de cada conta; esperado = obtido)

Sem token → 401. Senhorio: 403 em `/receipt` (recibo é pessoal), `/energy/overview`, `/api/presence`, `/appliances`, `/budgets/me`; 200 em `bills/{id}/summary`; a página `/consumo` mostra só «RESTRITO». Morador: 403 em `bills/preview`, `finalize`, `bills/{id}/summary`, `/devices`. Operador: 403 em `bills`, `energy/overview`, `/api/presence`; 200 em `/devices`. Casa inexistente → 404.

## Limitações

- Os pedidos de atribuição só aparecem a partir da `main` com PR #193 (run B); em A não havia pedido.
- Votação testada só com «É minha»; «É de todos», «Não sei», «É de outra pessoa» e o prazo de 24 h estão cobertos por `features/notifications/tests/test_voting.py`, não pelo browser.
- Assistente: sem interface (placeholder). Aparelhos: catálogo vazio na demo.
- A página de login do Authentik ainda diz «ObjectOS».
- Screenshots: `ana-home`, `senhorio-preview`, `senhorio-finalizada`, `ana-recibo-explicado`, `ana-orcamento`, `vote-ana`, `senhorio_consumo`.
