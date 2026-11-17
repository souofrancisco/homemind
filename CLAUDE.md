# Conta Certa — guia operacional para agentes

Aveiro Tech City Hackathon 2026 · Desafio 3, Altice Labs (Connected Home). Guia principal e único para todos os agentes de programação. Detalhes por área: [`app/backend/AGENTS.md`](app/backend/AGENTS.md) e [`app/frontend/AGENTS.md`](app/frontend/AGENTS.md). Índice da documentação: [`docs/README.md`](docs/README.md).

## Estado do repositório (ler primeiro)

- O produto é a **Conta Certa**. O **código na `main` é ainda o do ObjectOS** (modos da casa por gesto); a reorganização feita foi só documental.
- Nunca descrever nem assumir como existente o que está «planeado». Ao escrever código, docs, PRs ou respostas, distinguir sempre **IMPLEMENTADO** de **PLANEADO**.
- Antes de tocar no código antigo, ler [`docs/architecture/migration.md`](docs/architecture/migration.md): diz o que se mantém, adapta, substitui ou remove. **Não remover código do ObjectOS** fora de um PR de migração pedido (fase M4).

## Produto (fechado)

> **Cada um paga o que usa. A casa trata do resto.**

Serviço para casas partilhadas, instalado pelo senhorio sobre o kit Connected Home (via MCP). Três pilares: **Casa Justa** (medição, assinaturas, atribuição, fatura e recibos explicáveis), **Casa Atenta** (orçamentos, picos, aparelhos esquecidos, previsões), **Casa Segura** (presença, entradas e saídas, estados da casa). Personas: senhorio, inquilino, operador ([`docs/product/personas.md`](docs/product/personas.md)). Visão: [`docs/product/vision.md`](docs/product/vision.md). Requisitos: [`docs/product/requirements.md`](docs/product/requirements.md).

**A aplicação substitui o Telegram** ([`docs/decisions.md`](docs/decisions.md) D-01): toda a interação (alertas, perguntas, confirmações, assistente) é feita na aplicação React/Mantine/Capacitor. Não introduzir bots, grupos de mensagens ou Streamlit.

## Arquitetura

### Implementada hoje (ObjectOS)

Monorepo em `app/`. Um processo FastAPI; visão numa thread; eventos por `asyncio.Queue`; persistência só em `rules.json` e `events.jsonl`.

```text
câmara/clip → features/video → features/visao (thread, YOLO) → features/gestos → fila
  → features/engine (regras + estados) → connectors (FakeHome | McpHome) → REST/WS → app/frontend
```

| Onde | O quê |
|---|---|
| `app/backend/src/homemind/core/` | `config.py` (Settings), `errors.py`, `features.py` (descoberta de routers) |
| `…/contracts/` | Modelos partilhados: `video`, `visao`, `eventos`, `home`, `regras` |
| `…/connectors/` | `fake_home`, `mcp_home`, `altice_auth` (OAuth), `write_grant`, `mcp_verify` |
| `…/features/<nome>/` | `auth`, `engine`, `gestos`, `health`, `mcp`, `video`, `visao`: `router.py`, lógica, `tests/` |
| `app/frontend/src/` | `app`, `pages`, `components`, `hooks`, `services`, `mocks`, `types` |

API que existe: [`docs/architecture/api-implementada.md`](docs/architecture/api-implementada.md).

### Planeada (Conta Certa) — **ainda não existe**

Mesmo monólito FastAPI, com **SQLite** e **barramento de eventos em processo**; sem microserviços. Módulos novos: `households` (P5), `devices` + `energy` (P1), `presence` (P2), `billing` + `budgets` + `alerts` (P4), `notifications` + `agent` + `automations` (P3). Documentos: [overview](docs/architecture/overview.md), [data-model](docs/architecture/data-model.md), [contracts](docs/architecture/contracts.md), [event-flow](docs/architecture/event-flow.md), `docs/modules/*`.

Os nomes `homemind` (pacote, cliente OIDC, Compose) são herdados; não renomear. Módulos novos têm nomes em inglês.

## Responsabilidades por módulo (e pessoa)

| Módulo | Pessoa | Documento |
|---|---|---|
| Arquitetura, `core/`, `households`, auth/papéis, frontend, integração, demo | P5 `souofrancisco` | [households](docs/modules/households.md) |
| MCP, `connectors/`, `devices`, `energy`, assinaturas | P1 `brunovieira88` | [energy](docs/modules/energy.md) |
| `video`, `visao`, `presence` | P2 `1Mii` | [presence](docs/modules/presence.md) |
| `notifications`, `agent`, `automations` | P3 `RafaelMat0s-Dev` | [notifications](docs/modules/notifications.md), [agent](docs/modules/agent.md) |
| `billing`, `budgets`, `alerts` | P4 `Amorim3000` | [billing](docs/modules/billing.md) |

Divisão completa, prioridades e critérios de aceitação: [`docs/development/team.md`](docs/development/team.md).

## Fluxo de trabalho

1. Ler a issue e, se tocar em contratos, [`docs/architecture/contracts.md`](docs/architecture/contracts.md) (proposto) e [`docs/architecture/api-implementada.md`](docs/architecture/api-implementada.md) (real).
2. Uma issue por branch e worktree: `make worktree b=feat/<n>-<nome>` (cria `../homemind-<n>-<nome>` a partir de `origin/main`). Nunca trabalhar no worktree de outro agente.
3. Implementar só o pedido, no estilo existente. Sem dependências, abstrações ou funcionalidades extra.
4. `make check` (lint + pytest + contrato OpenAPI→TS + build + compose) tem de passar. `make smoke` quando tocar em Docker, arranque ou proxy.
5. PR pequeno para `main`, com o [template](.github/pull_request_template.md). **Nunca fazer push direto para `main`** sem instrução explícita do utilizador nessa tarefa.

Comandos: só os do `Makefile` (ver [`README.md`](README.md)).

## Desenvolvimento em paralelo — regras para evitar conflitos

- Trabalhar só na própria pasta `features/<módulo>/` e nos seus contratos. **Uma feature não importa outra**: comunica por contratos (`contracts/`) e eventos de domínio.
- **Contratos primeiro**: ninguém implementa um módulo antes de os contratos dele estarem acordados pelas cinco pessoas ([`docs/development/roadmap.md`](docs/development/roadmap.md), «Definição de pronto dos contratos»).
- Ficheiros partilhados (revisão de P5): `core/`, mudanças em `contracts/`, `Makefile`, `app/compose*.yaml`, `pyproject.toml`, lockfiles, `.github/`, `docs/architecture/contracts.md`.
- Nunca depender da ordem de arranque entre features; recursos partilhados vivem em `core/` ([decisão D-06](docs/decisions.md)). Uma feature que precise do motor antigo tem de vir depois de `engine` até ele ser removido.
- Estado de outro módulo altera-se **por evento**, nunca por escrita direta.
- Portas ocupadas por outra stack: `BACKEND_PORT`, `FRONTEND_PORT`, `AUTHENTIK_PORT`. Nunca `down -v` no projeto de outra pessoa.
- Escritas físicas no kit: uma pessoa de cada vez, com autorização explícita e `make mcp-writes-off` no fim.

## Contratos e convenções

- **Implementado:** `contracts/` (Pydantic) e o OpenAPI do backend; `make contracts` gera `app/frontend/src/shared/api/schema.d.ts`; o frontend nunca redefine tipos da API.
- **Proposto:** modelos, eventos e endpoints da Conta Certa em [`docs/architecture/contracts.md`](docs/architecture/contracts.md). Mudam por acordo da equipa e **no mesmo PR** que o código e o documento.
- Entidades e estados: [`docs/architecture/data-model.md`](docs/architecture/data-model.md). Proveniência obrigatória em dados de energia, atribuição e fatura: `measured | estimated | inferred | simulated`.
- Dinheiro em cêntimos inteiros; `Σ` das partes de uma fatura = total. Instantes em UTC ISO 8601. Campos `snake_case`.
- Erros: `{ "error": { "code", "message" } }`; nunca detalhes de exceções, URLs ou cabeçalhos.
- Permissões **no servidor**, com DTOs por papel (senhorio/inquilino/operador). A UI não é a barreira.

## Segurança e privacidade (inegociável)

- Vídeo só local: nunca gravar, registar ou enviar frames; sem reconhecimento facial nem identificação de pessoas pela imagem. Só eventos de texto.
- O **senhorio nunca vê** presença, entradas/saídas, horários, curvas horárias, aparelhos individuais nem imagens: só totais por quarto, recibos e alertas.
- Presença por Wi-Fi ou telemóvel só com opt-in do próprio morador.
- Segredos (`MCP_API_KEY`, tokens OAuth, `NVIDIA_API_KEY`, URL RTSP) só em `app/.env` e `app/.mcp-auth/` (ignorados pelo Git). Nunca em logs, erros, testes, issues ou docs. IDs de dispositivos nunca em docs.
- Dados enviados a um LLM externo: o mínimo, só texto, sem identificadores de dispositivos nem imagens (decisão pendente P-06).
- Em dúvida que afete segurança, autenticação, privacidade ou hardware: escolher o comportamento mais restritivo.

## MCP Altice (regras inalteradas)

- Só `get_home_devices`, `get_device_details`, `update_device_capabilities`; só lâmpada (`power`, `brightness`, `color_rgb`) e tomada (`power`). **Nunca** alarme, segurança, cenários ou timers (alargar exige a decisão P-01).
- Escritas físicas: `ENABLE_PHYSICAL_WRITES=false` por omissão **e** grant temporário obrigatório. Um agente **não executa escritas físicas** sem autorização explícita do utilizador nessa tarefa.
- Escrita confirmada **só por releitura**. Uma escrita de resultado incerto **nunca é repetida**; só se relê.
- Não declarar uma ferramenta como funcional sem evidência. Estado conhecido: leituras REAIS; escrita na lâmpada/tomada **não comprovada**; unidade de `instantPower` **não declarada** (sem `measured`). Ver [`docs/integrations/altice-mcp.md`](docs/integrations/altice-mcp.md).
- O SDK `mcp` só é importado em `connectors/`.

## Simulação vs hardware real

- Nunca inventar resultados, medições, IDs, capacidades ou confirmações físicas. Distinguir sempre **SIMULADO** (FakeHome, replay, clip, mocks, seed da demo) de **REAL** em UI, docs, recibos e pitch.
- Leituras `simulated` nunca se apresentam como `measured`. A fatura da demo é simulada e rotulada.
- O **plano B** (tudo com `HOME_BACKEND=fake` + leituras simuladas, sem rede nem hardware) é parte do produto: [`docs/development/mvp.md`](docs/development/mvp.md).
- Os valores do PDF (preços, poupanças, exemplos de fatura) são ilustrativos; nunca os citar como resultados nossos.
- Assistente de IA: **nunca inventa números**; tudo vem de funções do backend; ações sugeridas só se executam após confirmação do utilizador.

## Testes e critérios de qualidade

- Lógica pura com fakes e relógio simulado; nunca hardware, rede, NVIDIA/LLM ou MCP real em `pytest`.
- Correção de bug traz um teste que falha sem ela. Rotas novas têm teste de permissões por papel.
- Hardware valida-se à mão por [`docs/development/guia-validacao-manual.md`](docs/development/guia-validacao-manual.md); o resultado regista-se lá, sem marcar PASS o que não foi executado.
- Estratégia completa: [`docs/development/testing.md`](docs/development/testing.md).

## Documentação

| Preciso de… | Ler |
|---|---|
| Índice, estado e convenções | `docs/README.md` |
| Visão, personas, requisitos | `docs/product/` |
| Arquitetura, contratos, modelo de dados, fluxo de eventos | `docs/architecture/` |
| Código ObjectOS → destino | `docs/architecture/migration.md` |
| Um módulo | `docs/modules/<nome>.md` |
| Equipa, roadmap, MVP, riscos, backlog | `docs/development/` |
| MCP e hardware real | `docs/integrations/` |
| Decisões e pontos por resolver | `docs/decisions.md` |
| Gestos, presença, YOLO (código atual) | `app/backend/src/homemind/features/gestos/README.md`, `…/visao/README.md` |
| PDFs originais da proposta | `docs/references/` (históricos; não editar) |

Atualizar o documento correspondente no mesmo PR que muda o comportamento. Não criar documentos novos para o que cabe num existente. Etiquetar sempre IMPLEMENTADO / PLANEADO / PROPOSTA.

## Fora de âmbito

Sem pedido explícito e decisão da equipa: reconhecimento facial, gravação de vídeo, venda de dados, Telegram/bots, armar alarmes e cenários do Connected Home (P-01), sugestões de rotinas e Memory (issues #30, #31, #51), brilho por gesto, treino de objetos.
