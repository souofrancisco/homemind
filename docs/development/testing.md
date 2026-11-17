# Testes e critérios de qualidade

Regras herdadas do ObjectOS (mantidas) e acrescentos para a Conta Certa. **IMPLEMENTADO** = existe hoje; **PLANEADO** = a criar.

## Comandos (só os do `Makefile`)

| Comando | O que faz |
|---|---|
| `make check` | Lint (ruff + eslint) + pytest + contrato OpenAPI→TS + build + validação do Compose. **Tem de passar antes de pedir revisão** |
| `make test` | Só `pytest` |
| `make smoke` | Stack Docker isolada; obrigatório quando se toca em Docker, arranque ou proxy |
| `make contracts` | Regenera os tipos TypeScript a partir do OpenAPI |

## Princípios

1. **Lógica pura com fakes e relógio simulado.** Nunca depender de hardware, rede, NVIDIA/LLM ou MCP real em `pytest`.
2. **Uma correção de bug traz um teste que falha sem ela.**
3. O hardware valida-se à mão pelo [guia de validação](guia-validacao-manual.md); o resultado regista-se lá e **nunca** se marca PASS o que não foi executado.
4. Testes ao lado da feature (`features/<nome>/tests/`), com fakes em `tests/_fakes.py` e `contracts/simulacao.py`.
5. Sem frames reais, sem segredos, sem IDs de dispositivos nos testes, logs ou fixtures.

## Por módulo (PLANEADO)

| Módulo | Obrigatório |
|---|---|
| `core` (db, eventos) | Migrações do zero; `publish/subscribe`; handler falhado isolado; idempotência |
| `households` / auth | **Matriz papel × rota** (L/T/O): senhorio sem presença nem aparelhos; inquilino só o seu; `403 forbidden_role` |
| `energy` | Degraus, histerese, identificação com `confidence`/`unknown`, dois aparelhos simultâneos, ciclos de termóstato, `power_unit=unknown` ⇒ nunca `measured` |
| `presence` | Detetor falso + relógio: passagens, tolerância 20–30 min, contradição ⇒ `uncertain`; **teste que garante zero imagens persistidas** |
| `billing` | Fixtures A, B, C ([billing.md](../modules/billing.md)); `Σ = total` por propriedade; regras A/B/C; prazo de 24 h; saída a meio do mês; resíduo negativo ⇒ `422`; `finalize` idempotente |
| `budgets` / `alerts` | Limiar 50/80/100 uma só vez; previsão linear; pico e janela de tempo |
| `notifications` | Resposta idempotente (`409`), expiração, deduplicação, preferências, destinatários por papel |
| `agent` | LLM falso: só valores das ferramentas; sem dados ⇒ «não sei»; ação só após `confirm`; senhorio `403` |
| `connectors` (MCP) | `FakeMcp` já existente: whitelist, releitura, escrita incerta nunca repetida, OAuth |

## Integração e demo

- **Teste de cenário** (PLANEADO): o cenário de [mvp.md](mvp.md) corre com `FakeHome` + simulador, sem rede, e termina com a fixture A. Corre em CI.
- **Replay determinístico** de `domain_event` para reproduzir bugs da demo.
- 2 execuções seguidas do cenário sem intervenção antes da demo (critério de aceitação do MVP).

## Frontend

Não há testes unitários hoje (**IMPLEMENTADO**: `eslint`, `tsc -b`, `vite build` em `make check`). Validação manual: capítulos UI/WS do guia. Avaliar testes de componentes para notificações interativas (pendente P-12). Sempre: estados de loading, erro, vazio, offline; rótulo SIMULADO; só mostrar sucesso quando o backend o confirma.

## Critérios de qualidade (revisão de PR)

- [ ] `make check` verde (e `make smoke` se tocou em Docker/arranque/proxy)
- [ ] Sem segredos; REAL vs SIMULADO identificado
- [ ] Só a minha feature (ou ficheiros partilhados justificados)
- [ ] Contratos partilhados inalterados ou acordados, e `docs/architecture/contracts.md` atualizado no mesmo PR
- [ ] Documento do módulo atualizado se o comportamento mudou
- [ ] Permissões por papel testadas em rotas novas
- [ ] Nenhum valor numérico sem proveniência

## Estado do ambiente (validado a 17/11/2026, branch documental sobre `main` 7d931d8)

| Verificação | Resultado |
|---|---|
| `make check` (ruff check + format, ESLint, pytest, OpenAPI→TS, `tsc -b` + build Vite, `docker compose config`) | **PASSOU** (exit 0) |
| `pytest` backend | **221 passed**, 1 aviso de depreciação (`anyio.abc.BlockingPortal`, Starlette) |
| Contrato OpenAPI → TypeScript (`make contracts`, dentro do `check`) | Gerado sem diferenças no Git |
| Compose (`app/compose.yaml`, com `compose.mcp.yaml`) | `config -q` sem erros |
| `make smoke` (stack completa, Authentik) | **Não executado** nesta tarefa (sem alterações a Docker, arranque ou proxy) |
| MCP real, câmara, escritas físicas | **Não executados** (fora do âmbito; ver [guia-validacao-manual.md](guia-validacao-manual.md)) |
| CI (`.github/workflows/ci.yml`) | Corre `make check` em PR e push para `main`; `main` **sem proteção** de branch (a convenção é PR por issue, CLAUDE.md) |
| `.gitignore` | Cobre `.env*`, `app/.mcp-auth/`, `.venv/`, `node_modules/`, `graphify-out/` |
| Falhas conhecidas | Nenhuma de teste. Pendente: `docs/` ainda tem apontadores nos caminhos antigos (P-13) |

Os testes de `engine` e `gestos` saem quando esses módulos forem removidos (fase M4 em [migration.md](../architecture/migration.md), BASE-04 #74).
