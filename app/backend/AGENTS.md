# Backend ObjectOS

Regras gerais em [`../../CLAUDE.md`](../../CLAUDE.md). Aqui só o específico do backend (`src/homemind/`).

## FastAPI

- **Features:** cada `features/<nome>/router.py` expõe `router = APIRouter(...)`; `core/features.py` descobre-os por ordem alfabética e falha se houver rota duplicada. Não registar routers à mão em `main.py`.
- **Ciclo de vida:** recursos arrancam e param no `lifespan` do router da feature. A ordem é a alfabética das pastas e é usada de propósito: `engine` → `video` → `visao` (a visão precisa de `app.state.engine`). Uma feature nova que dependa do motor tem de vir depois de `engine`. Quem cria uma tarefa ou thread, cancela-a e aguarda-a no `finally`.
- **Dependências:** `CurrentUser` (`features/auth/service.py`) em todas as rotas `/api/*`; `EngineDep` para o motor. Só `/healthz` é público. O WebSocket autentica-se na primeira mensagem; nunca tokens no URL.
- **Modelos:** Pydantic v2 com tipos de retorno nas rotas (geram o OpenAPI). Entradas com `extra="forbid"`.
- **Erros:** `HTTPException(status, {"code": "...", "message": "..."})`; `core/errors.py` devolve sempre `{"error": {"code", "message"}}`. Nunca pôr detalhes de exceções, URLs ou cabeçalhos na resposta ou no log (só o tipo).
- **Event loop:** nada bloqueante em `async def`. I/O bloqueante vai para `def` (threadpool) ou `asyncio.to_thread`. Chamadas externas têm sempre timeout.
- **Configuração:** `core/config.py` (`Settings`) para o comum; `features/engine/config.py` para o motor. Sem `os.environ` espalhado.
- **Logs:** `logging.getLogger(__name__)`; o logger `homemind` está a INFO. Só metadados: nunca frames, URL RTSP, tokens ou dados de pessoas.

## Módulos

| Módulo | Responsabilidade |
|---|---|
| `features/video` | Fonte RTSP/clip numa thread (último frame, reconexão), MJPEG em `GET /api/video` |
| `features/visao` | `DetetorYolo` (extra `visao`), thread de visão, anotação do MJPEG |
| `features/gestos` | Gesto, presença, ponte thread→loop, afinador offline. Lógica pura |
| `features/engine` | Regras (`rules.json`), máquina de estados, energia, registo (`events.jsonl`), NVIDIA, REST e WS |
| `connectors` | `FakeHome`, `McpHome` (sessão única, polling 5 s, whitelist, releitura), OAuth, grant de escritas |

O SDK `mcp` só é importado em `connectors/`. O motor só conhece o protocolo `Home` (`contracts/home.py`).

## Testes

`uv run pytest -q` em `app/backend` (ou `make test`). Testes junto da feature em `tests/`; fakes em `tests/_fakes.py`, `contracts/simulacao.py` e `FakeMcp` (`connectors/tests`). Motor testa-se com `FakeHome` e relógio injetado. Sem rede, hardware, YOLO ou NVIDIA.

Dependências: versões fixas em `pyproject.toml` + `uv.lock`; YOLO/torch só no extra `visao`, fora do Docker e do CI.
