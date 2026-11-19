# Conta Certa

**Aveiro Tech City Hackathon 2026 · Desafio 3, Altice Labs (Connected Home)** — *cada um paga o que usa; a casa trata do resto.*

Serviço para **casas partilhadas**: lê o consumo elétrico por tomada (kit Connected Home via MCP), atribui cada consumo a um morador ou à conta comum — **perguntando na app** quando há dúvida —, divide a fatura de forma explicada e avisa antes de o orçamento de cada um chegar ao limite. O senhorio só reparte o custo real da fatura e nunca vê presença nem horários.

## O que já funciona

Validado no browser com dados **SIMULADOS** (FakeHome + seed de demo; evidência em [`docs/evidence/demo-web-2026-11-18/`](docs/evidence/demo-web-2026-11-18/README.md)):

- Login (Authentik/OIDC) com papéis morador, senhorio e operador, e isolamento de dados entre eles.
- Casa, quartos e zonas comuns; consumo por tomada com proveniência (medido / estimado / simulado).
- Pergunta «De quem é esta conta?» com votação dos moradores (D-32) e efeito no orçamento.
- Fatura do senhorio (pré-visualizar → registar → finalizar), repartição quarto/comum/resíduo, **4 recibos que somam a fatura** e recibo explicado.
- Orçamento mensal com avisos a 50/80/100 %.

**Ainda não / só em testes:** interface do assistente de IA, hardware real (MCP) validado ponta a ponta, push/offline, versionamento de políticas. Detalhe por fluxo: [`docs/functional-flows.md`](docs/functional-flows.md). Trabalho por fazer: [GitHub Project](https://github.com/users/souofrancisco/projects/1) e issue [#129](https://github.com/souofrancisco/homemind/issues/129).

## Começar

Requisitos: Docker (Compose v2), `make`, [`uv`](https://docs.astral.sh/uv/), Node 22+.

```bash
make setup      # dependências + app/.env (uma vez)
make demo-up    # Authentik (Docker) + contas + base de demo + backend/frontend locais, ~20 s
```

| Serviço | URL (omissão; portas em `app/.env`) |
|---|---|
| Aplicação | <http://localhost:5173> |
| API · OpenAPI | <http://localhost:8000/docs> · `/healthz` |
| Authentik | <http://localhost:9000> |

Contas de demonstração (só no Authentik local): `ana`, `bruno`, `carla`, `diogo` (moradores), `senhorio`, `operador` — palavra-passe `demo-conta-certa`.

`make demo-reset` repõe a base de demo; `make down` pára tudo. Desenvolver com reload: `make auth-up`, depois `make backend` e `make frontend` em dois terminais. Detalhes, `.env` e migração dos comandos antigos: [`docs/development.md`](docs/development.md).

> Os URLs/portas acima foram verificados com `BACKEND_PORT=18000 FRONTEND_PORT=15173 AUTHENTIK_PORT=19000` (as de omissão estavam ocupadas por `make dev` na máquina de teste); o mecanismo é o mesmo.

## Percurso da demo (≈5 min)

1. `ana`: Início → Consumo → **Notificações** → «De quem é esta conta?» → «É minha» → Orçamento (definir 35 €).
2. `senhorio`: Contas e recibos → fatura 120 € (01–18/11, fixo 15 €, 400 kWh) → pré-visualizar → registar → **Finalizar e repartir**. A página de consumo mostra «RESTRITO».
3. `ana`, `bruno`, `carla`, `diogo`: Contas e recibos → «Porque pago isto?»; os quatro valores somam 120,00 €.

## Arquitetura

Monorepo `app/`: **FastAPI + SQLite + barramento de eventos** (Python 3.12, Pydantic v2) e **React 19 + Vite + Mantine**; Authentik (OIDC) em Docker. Cada feature (`app/backend/src/homemind/features/<nome>/`) fala com as outras por `contracts/` e eventos de domínio, nunca por imports diretos. Visão geral: [`docs/architecture.md`](docs/architecture.md).

## Equipa

| | Pessoa | Área |
|---|---|---|
| P1 | `brunovieira88` | MCP, energia, identificação de aparelhos |
| P2 | `1Mii` | visão e presença |
| P3 | `RafaelMat0s-Dev` | notificações e assistente |
| P4 | `Amorim3000` | faturação, atribuição, alertas |
| P5 | `souofrancisco` | arquitetura, frontend, integração, demo |

Como trabalhamos (issue → worktree → PR; Claude Code e Codex): [`CLAUDE.md`](CLAUDE.md) e [`docs/ai-workflow.md`](docs/ai-workflow.md). Índice da documentação: [`docs/README.md`](docs/README.md).

## Website / Documentação

Documentação publicada (MkDocs + Material) em **<https://souofrancisco.github.io/homemind/>**. O conteúdo público vive em `docs/content/`; os restantes ficheiros de `docs/` (evidência, arquivo, referências, planos) **não são publicados**.

```bash
docker compose -f docs/compose.yml up docs      # pré-visualização em http://localhost:8100
# sem Docker: python -m pip install -r docs/requirements.txt && mkdocs serve -f docs/mkdocs.yml
mkdocs build -f docs/mkdocs.yml --strict        # validação (a mesma do CI)
```

- **PR para `main`:** `pr-docs.yml` corre `mkdocs build --strict` (check «MkDocs strict») e não publica.
- **Push para `main`** que altere `docs/content/**`, `docs/mkdocs.yml`, `docs/requirements.txt` ou o workflow (ou execução manual): `publish-docs.yml` constrói o site e publica-o no GitHub Pages (ambiente `github-pages`).
- **Manter:** alterar primeiro o documento canónico em `docs/`, depois a página publicada (cada uma indica a sua «Fonte canónica»). O site é **público**: nunca segredos, dados pessoais nem informação operacional sensível. Detalhes: [`docs/content/desenvolvimento/website.md`](docs/content/desenvolvimento/website.md).

## Limitações conhecidas

- Tudo na demo é **SIMULADO**; nada foi validado com hardware real nesta fase.
- O código ObjectOS (motor de regras e gestos) foi removido na BASE-04 (#74); o histórico está em [`docs/architecture/migration.md`](docs/architecture/migration.md).
- Sem CI geral ativa (o workflow `CI` está desativado); a verificação é `make check` local. Só os workflows de documentação (`pr-docs.yml`, `publish-docs.yml`) estão ativos.
