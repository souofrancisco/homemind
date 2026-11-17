# ObjectOS — guia operacional para agentes

Aveiro Tech City Hackathon 2026 · Desafio 3, Altice Labs (Connected Home). Regras comuns a todos os agentes; detalhes por área em `app/backend/AGENTS.md` e `app/frontend/AGENTS.md`.

## Produto (fechado)

Uma câmara RTSP observa a divisão. Levantar **caneca, livro ou comando** junto ao pulso (mão acima do cotovelo, ~1 s) ativa um modo. O mesmo objeto não repete a ação; outro objeto troca o modo. Divisão vazia → Em espera → aviso (luz a 20 %) → Suspenso (luz e tomada desligadas) → restauro no regresso. Botão manual **Desligar tudo**.

## Arquitetura

Monorepo em `app/`. Um processo FastAPI; visão numa thread; eventos por `asyncio.Queue`.

```text
câmara/clip → features/video → features/visao (thread, YOLO) → features/gestos → fila
  → features/engine (regras + estados) → connectors (FakeHome | McpHome) → REST/WS → app/frontend
```

| Onde | O quê |
|---|---|
| `app/backend/src/homemind/core/` | `config.py` (Settings), `errors.py`, `features.py` (descoberta de routers) |
| `…/contracts/` | Modelos partilhados: `video`, `visao`, `eventos`, `home`, `regras` |
| `…/connectors/` | `fake_home`, `mcp_home`, `altice_auth` (OAuth), `write_grant`, `mcp_verify` |
| `…/features/<nome>/` | `router.py`, lógica e `tests/` da feature |
| `app/frontend/src/` | `app`, `pages`, `components`, `hooks`, `services`, `mocks`, `types` |

Os nomes `homemind` (pacote, cliente OIDC, Compose) são herdados; não renomear.

## Fluxo de trabalho

1. Ler a issue e, se tocar em contratos, `docs/contratos.md`.
2. Uma issue por branch e worktree: `make worktree b=feat/<n>-<nome>` (cria `../homemind-<n>-<nome>` a partir de `origin/main`). Nunca trabalhar no worktree de outro agente.
3. Implementar só o pedido, no estilo existente. Sem dependências, abstrações ou funcionalidades extra.
4. `make check` (lint + pytest + contrato OpenAPI→TS + build + compose) tem de passar. `make smoke` quando tocar em Docker, arranque ou proxy.
5. PR pequeno para `main`. **Nunca fazer push direto para `main`** sem instrução explícita do utilizador nessa tarefa.

Comandos: só os do `Makefile` (ver `README.md`).

## Contratos partilhados

`contracts/`, os modelos de `features/engine` expostos na API e `docs/contratos.md` mudam juntos e só com acordo da equipa. O frontend nunca redefine tipos da API: usa os gerados por `make contracts`.

## Segurança e privacidade (inegociável)

- Vídeo só local: nunca gravar, registar ou enviar frames; sem reconhecimento facial nem identificação de pessoas. Só eventos de texto.
- Segredos (`MCP_API_KEY`, tokens OAuth, `NVIDIA_API_KEY`, URL RTSP) só em `app/.env` e `app/.mcp-auth/` (ignorados pelo Git). Nunca em logs, erros, testes, issues ou docs.
- MCP: só `get_home_devices`, `get_device_details`, `update_device_capabilities`; só lâmpada (`power`, `brightness`, `color_rgb`) e tomada (`power`). Nunca alarme, segurança, cenários ou timers.
- Escritas físicas: `ENABLE_PHYSICAL_WRITES=false` por omissão e grant temporário obrigatório. Um agente **não executa escritas físicas** sem autorização explícita do utilizador nessa tarefa. Uma escrita de resultado incerto nunca é repetida; só se relê.
- Nunca inventar resultados, medições, IDs, capacidades ou confirmações físicas. Distinguir sempre SIMULADO (FakeHome, clip, mocks) de REAL em UI, docs e pitch.
- Em dúvida que afete segurança, autenticação ou hardware: escolher o comportamento mais restritivo.

## Testes

- Lógica pura com fakes e relógio simulado; nunca depender de hardware, rede, NVIDIA ou MCP real em `pytest`.
- Correção de bug traz um teste que falha sem ela.
- Hardware valida-se à mão por `docs/guia-validacao-manual.md`; o resultado regista-se lá, sem marcar PASS o que não foi executado.

## Documentação

| Preciso de… | Ler |
|---|---|
| Estado atual, bloqueios, prioridades | `docs/estado-para-amanha.md` |
| Modelos, rotas, WebSocket, erros | `docs/contratos.md` |
| Arquitetura e decisões | `docs/architecture.md` |
| Operar o MCP / capacidades reais | `docs/mcp-demo.md`, `docs/mcp-capabilities.md` |
| Gestos, presença, afinador | `app/backend/src/homemind/features/gestos/README.md` |
| YOLO, pesos, FPS | `app/backend/src/homemind/features/visao/README.md` |
| Testes manuais | `docs/guia-validacao-manual.md` |

Atualizar o documento correspondente no mesmo PR que muda o comportamento. Não criar documentos novos para o que cabe num existente.

## Fora de âmbito

Extras das issues #30 e #31 (sugestões de rotinas, editor completo, brilho por gesto, treino de objetos, cenários MCP) só com pedido explícito, depois do MVP estável.
