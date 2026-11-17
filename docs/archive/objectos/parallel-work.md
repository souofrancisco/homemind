# Trabalho paralelo

> **ARQUIVADO — ObjectOS.** Só consulta histórica; não descreve a Conta Certa. Índice: [README](README.md).

Regras gerais em `CLAUDE.md`. Estado e prioridades em `estado-para-amanha.md`.

## Donos

| Pessoa | GitHub | Área | Código |
|---|---|---|---|
| 1 | `brunovieira88` | Vídeo, visão, integração e demo | `features/video`, `features/visao` |
| 2 | `1Mii` | Gestos, presença, afinador | `features/gestos` |
| 3 | `RafaelMat0s-Dev` | Home, FakeHome, MCP | `connectors/`, `features/mcp` |
| 4 | `Amorim3000` | Motor, regras, LLM, testes | `features/engine`, `contracts/regras.py` |
| 5 | `souofrancisco` | Painel | `app/frontend` |

Ficheiros partilhados (revisão do dono em `.github/CODEOWNERS`): `Makefile`, `app/compose.yaml`, `pyproject.toml`, lockfiles, `core/`, `.github/`.

## Como trabalhar em paralelo

1. Uma issue → um branch → um worktree: `make worktree b=feat/<n>-<nome>`.
2. Não editar o worktree nem a área de outra pessoa sem combinar.
3. Contratos (`contracts/`, modelos da API, `docs/contratos.md`) mudam primeiro por acordo, depois no código.
4. `make check` verde e PR pequeno; integrar cedo e muitas vezes.
5. Portas ocupadas por outra stack: `BACKEND_PORT`, `FRONTEND_PORT`, `AUTHENTIK_PORT` em `app/.env`, ou um projeto Compose próprio (`docker compose -p <nome> …`). Nunca fazer `down -v` no projeto de outra pessoa.
6. Escritas físicas no kit: uma pessoa de cada vez, com autorização explícita e `make mcp-writes-off` no fim.

## Issues abertas

| Issue | Dono | Falta |
|---|---|---|
| #4 YOLO objetos, pose, tracking | P1 | clip MEARI real, fiabilidade do livro, FPS em GPU |
| #5 Gesto objeto levantado | P2 | 10/10 e 0 falsos positivos no clip real |
| #8 Afinador offline | P2 | afinação com o clip real |
| #12 Consumo da tomada | P3 | unidade de `instantPower` |
| #28 Integração e benchmark | P1 + todos | latência real, 10 demos seguidas |
| #29 README, PDF, apresentação | P1 + todos | resumo PDF, PPT, pitch |
| #30, #31 Extras | — | não começar |

As issues #10 e #11 estão fechadas, mas o controlo físico da lâmpada **não está comprovado** (ver `mcp-capabilities.md`).
