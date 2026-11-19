# Leitura real do alarme, SÓ LEITURA (SAFE-02 #115), 2026-11-19

Backend com `HOME_BACKEND=mcp`, `ENABLE_PHYSICAL_WRITES=false`, sem grant, sem lâmpada, `ENERGY_HOUSEHOLD_ID` = casa de uma **cópia local** da base de demonstração (`app/.demo-web`, ignorada pelo Git) cuja casa foi marcada `source_kind='real'` só nessa cópia (sem isso a app usa sempre o painel SIMULADO). Authentik real em Docker (:19000), app :15173, API :18000. Sem ids, tokens nem URLs nas imagens ou neste texto.

| Verificação | Resultado |
|---|---|
| Cartão «Alarme da casa» (ana, Casa) | PASS: «REAL · só leitura», «Desarmado (real)», sem «Propor armar/desarmar» ([imagem](01-casa-alarme-real-so-leitura.png)) |
| `GET …/security` | PASS: `origin=real`, `panel_status=disarmed`, `available=false`, `can_arm=false`, `can_disarm=false`, `pending=null` |
| Proposta forçada por API | PASS (recusada, HTTP 400); nada foi executado |
| Poll de `get_home_devices` e `get_home_security_status` | PASS por inferência: a leitura chegou à app e o log do backend não tem erros, avisos nem tracebacks; o log a INFO não regista cada chamada MCP |
| Escritas MCP | PASS: nenhuma ferramenta de escrita chamada (escritas desligadas, sem grant; o log não mostra escritas) |
| Resto da app | PASS nas páginas Hoje e Casa (`/api/*` todos 2xx, exceto o 400 provocado de propósito) |
| Estado físico do alarme | **NÃO VERIFICADO** por uma pessoa; `ARMED` **NÃO observado** (formato assumido) |

Limitação: `DISARMED` tem uma única observação (mesma que a de 2026-11-19 anterior); o roteiro `~/homemind-testes-manuais/seguranca-leitura-mcp/` continua por executar com o alarme armado.

## Verificação de integração (demo SIMULADA, `origin/main` @ e9bac73, Authentik real, Playwright)

Login OIDC e percurso das rotas por papel com ana, bruno, carla, diogo (Hoje, Contas, Casa, Assistente, Notificações, Definições, `/regras`; `/consumo`, `/orcamento`, `/aparelhos` redirecionam), senhorio (Hoje, Contas, Casa, Notificações, Definições) e operador (Hoje, Casa, Diagnóstico, Definições): PASS, sem erros de página. Pedidos `/api/*` ≥ 400: só `GET /api/mcp/tools` = 502 do operador (a demo FakeHome não tem MCP; esperado, não é regressão). Ana: «É minha» decide o pedido e aparece o seguinte; alarme SIMULADO armado e desarmado com confirmação; senhorio: fatura 120,00 € (pré-visualização, registo, «Finalizar e repartir») → 22,06 + 45,01 + 28,94 + 23,99 = **120,00 €**. `make check`: 1965 passed, 2 skipped.
