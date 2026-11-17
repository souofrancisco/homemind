# Trabalho paralelo — ObjectOS (5 pessoas)

Ler `CLAUDE.md`, `docs/objectos-plano.md` e a issue. Cada pessoa assume um módulo. Mapeamento GitHub: P1 `brunovieira88`, P2 `1Mii`, P3 `RafaelMat0s-Dev`, P4 `Amorim3000`, P5 `souofrancisco`. A issue de extras #30 é partilhada por P4/P5; #31 por P1/P2/P3/P5 (P1 incluída).

| Pessoa | Área | Primeira entrega |
|---|---|---|
| 1 | RTSP, YOLO, MJPEG, integração e demo | frames estáveis e caixas/esqueleto |
| 2 | gestos, presença, queue e afinador | eventos reproduzíveis sobre clip |
| 3 | Home, FakeHome e MCP real | FakeHome e script real de alteração da lâmpada |
| 4 | contratos, motor, regras, LLM e testes | máquina de estados e testes com FakeHome |
| 5 | UI em React/Mantine | dashboard com WebSocket simulado |

## Contratos partilhados primeiro
Eventos `objeto_levantado` (classe/hora), `presenca` (ha_alguem/hora); interface `Home` com quatro métodos; regra tipada com objeto e ações; endpoints /video, /ws, /status, /rules, /rules/parse, /off. Confirmar convenções de prefixo em FastAPI antes de gerar frontend via `make contracts`.

## Regras de integração
Uma issue por branch/worktree; não editar em paralelo modelos, config, lockfiles, Main ou mesmo ficheiro; abrir PR pequeno e integrar cedo. Usar `make check`; `pytest` em componentes puros. `FakeHome` antes do MCP real; sem acessos reais sem permissão e validação de tools. Os extras só após 10 demos consecutivas sem falhas. Dono de entregáveis: Pessoa 1 com colaboração de todos, deadline PDF 18/11/2026 às 19h.
