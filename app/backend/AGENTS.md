# Backend — Conta Certa

Regras gerais em [`../../CLAUDE.md`](../../CLAUDE.md). Aqui só o específico do backend (`src/homemind/`). **O código de produto é ainda o do ObjectOS**; a **fundação F0 está implementada** (contratos, SQLite, barramento, guardas por papel, OpenAPI) e os módulos novos de P1–P4 são **planeados** (ver [`../../docs/architecture/migration.md`](../../docs/architecture/migration.md)).

## FastAPI (implementado)

- **Features:** cada `features/<nome>/router.py` expõe `router = APIRouter(...)`; `core/features.py` descobre-os por ordem alfabética e falha se houver rota duplicada. Não registar routers à mão em `main.py`.
- **Ciclo de vida:** recursos arrancam e param no `lifespan` do router da feature. A ordem é a alfabética das pastas e hoje é usada de propósito: `engine` → `video` → `visao` (a visão precisa de `app.state.engine`). Quem cria uma tarefa ou thread, cancela-a e aguarda-a no `finally`.
- **Dependências:** `CurrentUser` (`features/auth/service.py`) em todas as rotas `/api/*`; `EngineDep` para o motor antigo. Só `/healthz` é público. O WebSocket autentica-se na primeira mensagem; nunca tokens no URL.
- **Modelos:** Pydantic v2 com tipos de retorno nas rotas (geram o OpenAPI). Entradas com `extra="forbid"`.
- **Erros:** `HTTPException(status, {"code": "...", "message": "..."})`; `core/errors.py` devolve sempre `{"error": {"code", "message"}}`. Nunca detalhes de exceções, URLs ou cabeçalhos na resposta ou no log (só o tipo).
- **Event loop:** nada bloqueante em `async def`. I/O bloqueante vai para `def` (threadpool) ou `asyncio.to_thread`. Chamadas externas têm sempre timeout.
- **Configuração:** `core/config.py` (`Settings`) para o comum; `features/engine/config.py` para o motor antigo. Sem `os.environ` espalhado.
- **Logs:** `logging.getLogger(__name__)`; o logger `homemind` está a INFO. Só metadados: nunca frames, URL RTSP, tokens ou dados de pessoas.

## Fundação F0 (implementada)

- `core/db.py` (SQLite: `db.run_sync(fn)` / `await db.run(fn)`, transações explícitas), `core/migrations/*.sql` (por nome; cada módulo cria as suas), `core/events.py` (barramento: `app.state.bus.subscribe(consumidor, handler_sync, tipos)`; `await bus.publish(evento)`), `core/access.py` (`require_access(Resource, Operation)` → `HouseholdAccess`; matriz `PERMISSIONS`), `core/lifespan.py` (core arranca antes de qualquer router), `contracts/` (modelos, `domain_events.py`, `fixtures.py`).
- **Handlers de eventos:** síncronos `(conn, StoredEvent) -> eventos | None`, na transação do efeito; sem I/O externo. Entrega pelo menos uma vez: o efeito tem de ser idempotente por `event.id` (o barramento já o garante pela `processed_event`).
- **Rotas novas** com `{household_id}`: `Annotated[HouseholdAccess, Depends(require_access(Resource.x, Operation.read))]`; nunca ler `resident_id` do cliente; responder com `*View`, nunca com a entidade; teste papel × rota. Não-membro ⇒ 404; membro sem papel ⇒ 403.
- Testes: `DB_PATH=:memory:` (conftest raiz); `features/households/tests/conftest.py` tem a app com duas casas e utilizadores simulados.

## Regras para os módulos novos

- **Recursos partilhados** (SQLite, barramento de eventos) vivem em `core/` (dono P5) e arrancam antes de qualquer feature. Nenhuma feature nova depende da ordem de arranque de outra nem importa outra feature: comunica por `contracts/` e por eventos de domínio ([decisão D-06](../../docs/decisions.md), [`event-flow`](../../docs/architecture/event-flow.md)).
- **Contratos primeiro:** modelos em `contracts/<domínio>.py`, propostos em [`contracts.md`](../../docs/architecture/contracts.md). Mudar um contrato partilhado exige acordo e atualizar esse documento no mesmo PR.
- **Permissões** no servidor por papel (`landlord` | `tenant` | `operator`) com DTOs distintos; o senhorio nunca recebe presença nem aparelhos. Rota nova ⇒ teste papel × rota.
- **Proveniência** `Provenance{origin, kind}` em leituras, consumos, atribuições e alocações. Dinheiro em cêntimos inteiros; energia em Wh inteiros; ausência = `None`.
- **Eventos:** imutáveis, consumidores idempotentes, sem imagens nem IDs externos de dispositivos no payload.
- Nomes de módulos novos em inglês.

## Módulos

### Implementados hoje

| Módulo | Responsabilidade | Destino (ver migração) |
|---|---|---|
| `features/video` | Último frame local de clip de teste; RTSP recusado no serviço e `GET /api/video` responde sempre 404 (PRIV-02) | ADAPT; não reabrir stream sem contrato/autorização e revisão |
| `features/visao` | `DetetorYolo` (extra `visao`), thread de visão, anotação | ADAPT: só pessoa + linha na porta |
| `features/gestos` | Gesto, presença, ponte thread→loop, afinador. Lógica pura | Gesto/afinador REMOVE; ponte KEEP; presença ADAPT |
| `features/engine` | Regras (`rules.json`), máquina de estados, energia, registo (`events.jsonl`), NVIDIA, REST e WS | Motor REMOVE; `llm.py` e WS ADAPT |
| `features/agent` (**parcial**, P3) | Assistente só de leitura: `POST /api/households/{id}/agent/messages`, dados SIMULADOS da casa demo, LLM desligado por omissão (`AGENT_LLM_ENABLED`), sem ações. Sem persistência | [agent](../../docs/modules/agent.md) |
| `features/notifications` (**parcial**, P3) | Notificações por casa (lista, leitura, resposta, preferências), persistência SQLite e consumidor `notifications.confirmation_needed`. WebSocket, limiares e picos PLANEADOS | [notifications](../../docs/modules/notifications.md) |
| `features/auth`, `features/health`, `features/mcp` | JWT Authentik, healthz, diagnóstico MCP | KEEP/ADAPT |
| `connectors` | `FakeHome`, `McpHome` (sessão única, polling 5 s, whitelist, releitura), OAuth, grant de escritas | KEEP/ADAPT |

### Planeados

| Módulo | Dono | Documento |
|---|---|---|
| `households` (leituras e `core/*` implementados; escrita por REST planeada) | P5 | [households](../../docs/modules/households.md) |
| `devices`, `energy` | P1 | [energy](../../docs/modules/energy.md) |
| `presence` | P2 | [presence](../../docs/modules/presence.md) |
| `billing`, `budgets`, `alerts` | P4 | [billing](../../docs/modules/billing.md) |
| `automations` | P3 | [notifications](../../docs/modules/notifications.md) |

O SDK `mcp` só é importado em `connectors/`. O resto do código só conhece o protocolo `Home` (`contracts/home.py`).

## Testes

`uv run pytest -q` em `app/backend` (ou `make test`). Testes junto da feature em `tests/`; fakes em `tests/_fakes.py`, `contracts/simulacao.py` e `FakeMcp` (`connectors/tests`). Lógica testa-se com `FakeHome`, relógio injetado e simuladores. Sem rede, hardware, YOLO, NVIDIA/LLM ou MCP real. Estratégia: [`docs/development/testing.md`](../../docs/development/testing.md).

Dependências: versões fixas em `pyproject.toml` + `uv.lock` (revisão de P5); YOLO/torch só no extra `visao`, fora do Docker e do CI. Nova dependência (ex.: biblioteca SQLite, P-05) exige acordo.
