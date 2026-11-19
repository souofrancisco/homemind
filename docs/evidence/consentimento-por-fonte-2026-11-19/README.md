# Consentimento por fonte de presença (PRIV-03 #51, D-37), 2026-11-19

Browser (Playwright/Chromium), Authentik real em Docker (:19000), backend `DEMO=1` (:18000), frontend (:15173); casa de demonstração SIMULADA, pistas de presença injetadas à mão na cópia local da base (`app/.demo-web`, ignorada pelo Git) porque a demo não emite presença. Sem hardware, sem MCP, sem Wi-Fi real. Sem ids nem credenciais nas imagens.

| # | Verificação (Ana, inquilina) | Resultado |
|---|---|---|
| 1 | Definições → «Presença e privacidade», estado inicial ([imagem](01-definicoes-tudo-desligado.png)) | PASS: partilha desligada, 3 fontes «Desligada», os 3 botões «Ligar» desativados |
| 2 | Ligar a partilha (diálogo «não liga nenhuma fonte») | PASS: botões «Ligar» ativos, registo «Partilha da presença ligada» |
| 3 | Ligar Wi-Fi com o texto e confirmação «Aceito e ligo» ([imagem](02-partilha-e-wifi-ligados.png)) | PASS: «Ligada», registo com a versão do texto `2026-11-19.1` |
| 4 | Ligar aparelho e manual; exportação própria | PASS: 4 pistas (2 Wi-Fi, 1 manual, 1 aparelho), estado «em casa», 3 consentimentos ligados |
| 5 | Desligar só o Wi-Fi (diálogo de confirmação) | PASS: pistas Wi-Fi apagadas (2 → 0); manual e aparelho mantêm-se; estado recalculado «em casa» só pela fonte «aparelho»; registo «Wi-Fi desligada (por ti)» |
| 6 | Cancelar o diálogo de desligar a partilha | PASS: nada muda |
| 7 | Desligar a partilha global | PASS (UI e consentimentos): as 3 fontes passam a «Desligada» logo, «Ligar» volta a estar desativado, registo com «ao desligar a partilha da presença» |
| 8 | Eliminação dos dados após desligar a partilha global (varredura ≤ ~10 min) | PASS: na varredura seguinte (≈10 min) o registo de auditoria mostra `erase / opt_in_revoked` (3 eventos, 1 linha de estado); 0 pistas e 0 estados; o registo de consentimentos mantém as 8 linhas (só de acrescentar) |
| 9 | RBAC por API (Bearer de cada conta) | PASS: ana, bruno, carla, diogo: `GET /consents`, `GET /export`, `DELETE /consents/wifi` = 200; senhorio e operador = 403 nas três; casa inexistente = 404; Definições sem o cartão para senhorio e operador |
| 10 | Percurso completo SIMULADO (6 contas): login, Hoje, Contas, Casa, Assistente, Notificações, Definições, `/regras`; «É minha»; alarme SIMULADO armar/desarmar; fatura 120 € | PASS: 22,06 + 45,01 + 28,94 + 23,99 = **120,00 €**; 0 pedidos `/api/*` ≥ 400 além dos 403/404 provocados de propósito e de `GET /api/mcp/tools` = 502 do operador (a demo não tem sessão MCP; já existia) |

Limitações: não testado com Wi-Fi/aparelho reais nem com telemóvel; os textos de consentimento não passaram por jurista (P-24); o registo do opt-in global usa o relógio da base de dados.
