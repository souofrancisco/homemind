# Backend — Conta Certa

Regras gerais em [`../../CLAUDE.md`](../../CLAUDE.md). Aqui só o específico do backend (`src/homemind/`). A API de produto é a Conta Certa; o motor ObjectOS e as rotas antigas foram removidos na BASE-04 (#74). Ver o estado IMPLEMENTADO/PLANEADO em [`../../docs/architecture/migration.md`](../../docs/architecture/migration.md).

## FastAPI (implementado)

- **Features:** cada `features/<nome>/router.py` expõe `router = APIRouter(...)`; `core/features.py` descobre-os por ordem alfabética e falha se houver rota duplicada. Não registar routers à mão em `main.py`.
- **Ciclo de vida:** recursos arrancam e param no `lifespan` do router da feature. Não depender da ordem alfabética; quem cria uma tarefa ou thread, cancela-a e aguarda-a no `finally`.
- **Dependências:** rotas `/api/*` usam a autenticação e guardas atuais de cada feature. Só `/healthz` é público. Não há WebSocket ativo no backend após BASE-04.
- **Modelos:** Pydantic v2 com tipos de retorno nas rotas (geram o OpenAPI). Entradas com `extra="forbid"`.
- **Erros:** `HTTPException(status, {"code": "...", "message": "..."})`; `core/errors.py` devolve sempre `{"error": {"code", "message"}}`. Nunca detalhes de exceções, URLs ou cabeçalhos na resposta ou no log (só o tipo).
- **Event loop:** nada bloqueante em `async def`. I/O bloqueante vai para `def` (threadpool) ou `asyncio.to_thread`. Chamadas externas têm sempre timeout.
- **Configuração:** `core/config.py` (`Settings`) para a configuração comum. Sem `os.environ` espalhado.
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
| `features/video` | Fontes de vídeo locais e endpoint protegido de diagnóstico | Ver PRIV-02 e [`presence`](../../docs/modules/presence.md) |
| `features/visao` | `dispositivo.py` e `pesos.py`, importados pelo detetor de presença | Sem thread ObjectOS, deteção de objetos ou pose |
| `features/gestos` | `ponte.py` preservada (KEEP), sem consumidor de produção | Não contém processador de gestos nem presença binária |
| `features/agent` (**parcial**, P3) | Assistente só de leitura: `POST /api/households/{id}/agent/messages`, dados SIMULADOS da casa demo, LLM desligado por omissão (`AGENT_LLM_ENABLED`); AGENT-03: ações propostas com confirmação (`agent_action`, `0310`), executor injetado (nesta feature só o simulado), nunca sem `confirm`; AGENT-03b: consumidor `agent.safety_suggestion` (só propõe); histórico `GET …/agent/messages` (`agent_message`, `0311`, só o próprio, nunca ao LLM) | [agent](../../docs/modules/agent.md) |
| `features/notifications` (**parcial**, P3) | Notificações por casa (lista, leitura, resposta, preferências), persistência SQLite e consumidor `notifications.confirmation_needed`. WebSocket, limiares e picos PLANEADOS | [notifications](../../docs/modules/notifications.md) |
| `features/auth`, `features/health`, `features/mcp` | JWT Authentik, healthz, diagnóstico MCP | KEEP/ADAPT |
| `connectors` | `FakeHome`, `McpHome` (sessão única, polling 5 s, whitelist, releitura), OAuth, grant de escritas | KEEP/ADAPT |

### Planeados

| Módulo | Dono | Documento |
|---|---|---|
| Funcionalidades planeadas em cada módulo | Vários | Consultar o estado por módulo em [`docs/modules`](../../docs/modules/). |

O SDK `mcp` só é importado em `connectors/`. O resto do código só conhece o protocolo `Home` (`contracts/home.py`).

## Testes

Os testes usam `python -m pytest -q` em `app/backend` (ou `make test`). Testes junto da feature em `tests/`; lógicas de integração usam fakes e relógios injetados. Sem rede, hardware, YOLO, NVIDIA/LLM ou MCP real. Estratégia: [`docs/development/testing.md`](../../docs/development/testing.md).

Dependências: versões fixas em `pyproject.toml` + `uv.lock` (revisão de P5); YOLO/torch só no extra `visao`, fora do Docker e do CI. Nova dependência (ex.: biblioteca SQLite, P-05) exige acordo.
