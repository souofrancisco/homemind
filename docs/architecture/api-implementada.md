# Contratos ObjectOS (documento canónico)

> **IMPLEMENTADO — API que existe hoje no código (ObjectOS).** Não descreve a Conta Certa. Os contratos **propostos** da Conta Certa estão em [contracts.md](contracts.md). Os endpoints `/api/state`, `/api/rules`, `/api/off`, `/api/simulate` e o `HomeState` pertencem ao motor antigo e saem na fase M4 de [migration.md](migration.md); `/healthz`, `/api/me`, `/api/status`, `/api/mcp/tools` e o protocolo WebSocket são reutilizados. `/api/video` está desativado por PRIV-02. Por isso este documento **não foi arquivado**: o código ainda o cumpre e o OpenAPI é gerado dele.

Substitui as propostas v1–v3 do contrato frontend↔backend e as extensões do frontend (removidas; ficam no histórico Git). Qualquer mudança faz-se primeiro aqui e nos modelos Pydantic, com acordo da equipa.

**Fontes de verdade no código:** `app/backend/src/homemind/contracts/` (modelos internos) e o **OpenAPI** do backend (`/docs`, `/openapi.json`). `make contracts` gera `app/frontend/src/shared/api/schema.d.ts`; o frontend deriva daí os seus tipos (`src/types/home.ts`). As mensagens do WebSocket não constam do OpenAPI e estão descritas abaixo.

```text
FonteVideo ──FrameVideo──▶ visão ──FrameDeteccoes──▶ gestos/presença ──Evento──▶ motor ──Home──▶ FakeHome | McpHome
 (video.py)                (visao.py)                (eventos.py)              (home.py, regras.py)
                                                              motor ──REST + WS──▶ painel
```

## 1. Contratos internos (`contracts/`)

### Vídeo (`video.py`)

`FonteVideo`: `iniciar()`, `parar()`, `ultimo_frame() -> FrameVideo | None` (nunca bloqueia), `camara_ok`. `FrameVideo`: `imagem` (ndarray BGR), `indice` (igual ao anterior = sem frame novo), `t` (`time.monotonic()`). Frames só em memória.

### Deteções (`visao.py`)

| Modelo | Campos |
|---|---|
| `FrameDeteccoes` | `indice`, `t`, `hora`, `largura`, `altura`, `objetos`, `pessoas` |
| `ObjetoDetetado` | `classe` (`caneca` / `livro` / `comando`), `confianca`, `caixa`, `track_id` |
| `PessoaDetetada` | `confianca`, `caixa`, `track_id`, `keypoints` (17 COCO) |
| `Caixa` / `Keypoint` | `x1,y1,x2,y2` (+ `centro`) / `x,y,confianca` |

- Coordenadas em píxeis, origem em cima à esquerda, **y cresce para baixo** (pulso acima do cotovelo: `pulso.y < cotovelo.y`).
- Keypoints: ombros 5/6, cotovelos 7/8, pulsos 9/10 (enum `KP`). Ponto não detetado: `confianca=0`.
- `t` monotónico para janelas e cooldowns; `hora` (UTC) só para registo.
- `track_id` é efémero (ByteTrack), não identifica ninguém e não é persistido.
- Classes COCO: 41 caneca, 73 livro, 65 comando (`VISAO_LIVRO_COCO` permite trocar o livro).
- `Detetor.detetar(FrameVideo) -> FrameDeteccoes`. Modelos imutáveis, sem campos extra.

### Eventos (`eventos.py`)

```python
ObjetoLevantado(tipo="objeto_levantado", classe, hora)
Presenca(tipo="presenca", ha_alguem, hora)      # só transições
```

`Evento` é a união discriminada por `tipo`. `ProcessadorEventos.processar(frame) -> tuple[Evento, ...]` (síncrono, sem I/O) e `PublicadorEventos.publicar(evento)` (qualquer thread, nunca bloqueia). São internos: o painel só os vê como linhas do registo e pelo efeito no `HomeState`.

Semântica acordada:

- Um `ObjetoLevantado` por gesto confirmado, mesmo com o modo já ativo (o motor regista «já está ativo»).
- Presença começa `False` na visão; no motor começa desconhecida (`null`) e o primeiro `Presenca` conta sempre.
- Sem frames novos não há eventos: câmara em baixo nunca é interpretada como divisão vazia.
- Limiares em `core/config.py` (`GESTO_*`, `PRESENCA_*`); detalhe em `features/gestos/README.md`.

### Casa (`home.py`)

```python
class Home(Protocol):
    async def definir_lampada(self, ligada: bool, cor: Cor | None = None, brilho: int | None = None) -> bool
    async def definir_tomada(self, ligada: bool) -> bool
    async def ler_consumo(self) -> float | None      # W em cache; None = indisponível
    async def estado(self) -> EstadoCasa
```

- As escritas devolvem `True` **só com o estado confirmado** (no `McpHome`, por releitura).
- `cor`/`brilho` a `None` = manter; com `ligada=False` são ignorados. `brilho` 1–100.
- `Cor`: `branco`, `branco_quente`, `branco_frio`, `azul`, `vermelho`, `verde`, `amarelo`, `laranja`, `roxo`, `rosa` (RGB de referência em `CORES`).
- `EstadoCasa`: `backend` (`fake` | `mcp`), `mcp_ok`, `lampada {ligada, cor, rgb, brilho}`, `tomada {ligada, consumo_w, consumo_lido_em}`, `atualizado_em`, `aviso`. **`null` = desconhecido**, nunca «desligado» nem «0 W».

### Regras (`regras.py`)

```json
{ "id": "leitura", "objeto": "livro", "nome": "Modo leitura", "enabled": true,
  "acoes": [ { "dispositivo": "lampada", "ligada": true, "cor": "branco_quente", "brilho": 40 },
             { "dispositivo": "tomada", "ligada": true } ] }
```

- `id`: `^[a-z0-9_-]{1,40}$`; `nome`: 1–60 caracteres; 1–2 ações, no máximo uma por dispositivo.
- Campos desconhecidos são rejeitados (400).
- No máximo uma regra `enabled` por objeto: gravar ou ativar uma desativa as outras do mesmo objeto.
- Predefinidas (criadas no 1.º arranque): `pausa` (caneca: luz branco quente 30 %), `leitura` (livro: luz branco quente 40 % + tomada), `cinema` (comando: luz azul 10 % + tomada).

## 2. API HTTP

Prefixo `/api`. JSON UTF-8, `snake_case`, horas ISO 8601 UTC. Todas as rotas `/api/*` exigem `Authorization: Bearer <access_token>` (Authentik). Só `/healthz` é público.

| Método | Rota | Resposta |
|---|---|---|
| `GET` | `/healthz` | `{ "status": "ok", "backend": "fake"\|"mcp", "physical_writes": bool }` |
| `GET` | `/api/me` | `User` do token |
| `GET` | `/api/status` | `Status`: `camera_ok`, `mcp_ok`, `backend`, `updated_at` |
| `GET` | `/api/state` | `HomeState` (igual ao do WebSocket) |
| `GET` | `/api/events?limit=1..50` | `{ "events": [EventLogItem] }`, do mais antigo para o mais recente |
| `POST` | `/api/off` | sempre `200 OffResult` |
| `POST` | `/api/simulate` | `HomeState`; só com `HOME_BACKEND=fake` (senão `403 simulation_disabled`) |
| `GET` | `/api/rules` | `{ "rules": [Rule] }` |
| `POST` | `/api/rules` | `201 Rule` (cria ou substitui pelo `id`) |
| `PATCH` | `/api/rules/{id}` | corpo `{ "enabled": bool }` → `Rule` · `404 rule_not_found` |
| `DELETE` | `/api/rules/{id}` | `204` · `404 rule_not_found` |
| `POST` | `/api/rules/parse` | corpo `{ "text": "…" }` (3–300) → `ParseResponse` |
| `GET` | `/api/presence/camera/status` | `CameraStatus` (PRES-01): só papel `operator` (`403` aos restantes); sem imagem nem URL; fonte em falha ⇒ `camera_ok=false` |
| `GET` | `/api/video` | Endpoint legado desativado: autenticado recebe sempre `404`; sem dependência de fonte MJPEG. Não iniciar captura por esta rota. |
| `GET` | `/api/mcp/tools` | `tools/list` do MCP (diagnóstico); `502` se indisponível |
| `GET` | `/api/me/context` | `MeContext`: o residente ligado ao `sub` e as suas memberships ativas (**Conta Certa, F0**) |
| `GET` | `/api/households/{id}` | `HouseholdView` · `404 household_not_found` (não-membro ou casa inexistente) · `403 forbidden_role` |
| `GET` | `/api/households/{id}/rooms` | `[RoomView]` |
| `GET` | `/api/households/{id}/members` | `[MemberView]`: senhorio vê todos os estados, inquilino só ativos; operador `403`; nunca `presence_opt_in` nem `sub` |
| `PATCH` | `/api/households/{id}/memberships/{mid}` | corpo `{ "presence_opt_in": bool }` (`extra=forbid`) → `MembershipSelfView`; só a própria membership de um inquilino (`403` a de outro, `404` se não é desta casa) |
| `POST` | `/api/households/{id}/agent/messages` | corpo `{ "text": "…" }` → `AgentResponse` (`proposed_actions` vazio); só inquilino (`403 forbidden_role` ao senhorio e ao operador) · `404 household_not_found` (não-membro). Dados **SIMULADOS** (casa demo); LLM desligado por omissão (`AGENT_LLM_ENABLED`), sem escritas (**Conta Certa, P3**) |

### `HomeState`

```json
{ "mode": "leitura", "mode_name": "Modo leitura", "state": "em_espera", "presence": null,
  "camera_ok": true, "mcp_ok": false, "backend": "fake",
  "waiting_remaining_seconds": 7.5, "energy_saved_wh": 12.5, "energy_saved_eur": 0.002,
  "updated_at": "2026-11-17T15:20:00Z", "casa": { "…": "EstadoCasa" } }
```

| Campo | Significado |
|---|---|
| `mode`, `mode_name` | `id` e `nome` da regra ativa; `null` sem modo |
| `state` | `inativo` · `ativo` · `em_espera` · `suspenso` |
| `presence` | `null` = ainda sem dados da visão |
| `mcp_ok`, `backend` | cópias de `casa`; com `fake`, `mcp_ok` é sempre `false` e a UI mostra **SIMULADO** |
| `waiting_remaining_seconds` | só em `em_espera`, no instante `updated_at`; a UI conta localmente |
| `energy_saved_wh` / `_eur` | **estimativa** desde o arranque do servidor (W da tomada ao suspender × horas suspensas × `TARIFA_EUR_KWH`); não conta com consumo desconhecido |
| `casa` | `EstadoCasa`; `null` só se a leitura falhar |

### `EventLogItem`

`{ id, timestamp, level, message, source }` — `level`: `info` | `warning` | `error`; `source`: backend da casa no momento. Só texto. Eventos injetados por `/api/simulate` levam `[SIMULADO]` na mensagem. Em memória ficam os últimos 50; `events.jsonl` guarda o histórico.

### `OffResult`

```json
{ "success": true, "state": "inativo", "backend": "fake",
  "devices": { "lampada": "off", "tomada": "off" }, "code": null, "message": null }
```

`devices.*` é `off` (confirmado) ou `unknown`. `code`: `partial_failure` (um falhou) ou `mcp_unavailable` (nenhum confirmado; `message` diz porquê). A UI só mostra sucesso com `success: true`.

### `ParseResponse` (NVIDIA)

`{ proposal: Rule, summary, replaces }`. **Não grava nem executa.** O `summary` é gerado pelo backend a partir da regra validada. Se o `id` já existir acrescenta-se `-2`, `-3`… `replaces` = nome da regra ativa do mesmo objeto que será desativada ao gravar. O modelo só recebe o texto e o schema; nunca imagens, histórico ou tokens. O frontend grava a proposta aceite com `enabled: false`; a ativação é um passo explícito.

### Erros

```json
{ "error": { "code": "rule_not_found", "message": "Regra não encontrada" } }
```

| HTTP | `code` | Quando |
|---|---|---|
| 400 | `invalid_request` | validação; a mensagem indica os campos (nunca os valores) |
| 400 | `rule_not_supported` | pedido de regra fora do suportado (a mensagem explica) |
| 401 | `http_401` | sem token ou token inválido/expirado |
| 403 | `simulation_disabled` | `/api/simulate` com `HOME_BACKEND=mcp` |
| 404 | `rule_not_found` | |
| 500 | `internal_error` | erro não previsto (sem detalhes) |
| 502 | `invalid_proposal` · `http_502` | o modelo falhou duas vezes · MCP indisponível em `/api/mcp/tools` |
| 503 | `nvidia_unavailable` · `http_503` | sem chave/rede NVIDIA · sem fonte de vídeo |

## 3. WebSocket `WS /api/ws`

```json
{ "type": "home_state", "data": HomeState }
{ "type": "event",      "data": EventLogItem }
{ "type": "error",      "data": { "code": "unauthorized", "message": "Não autenticado" } }
```

1. O cliente abre a ligação e envia, em 5 s, `{"type":"auth","token":"<access_token>"}`. **Nunca token no URL.**
2. Token inválido: `error` e fecho com código **1008**. O cliente renova a sessão uma vez; se falhar volta ao login (sem ciclo de reconexões).
3. Token válido: `home_state` imediato; depois um `event` por linha nova do registo e um `home_state` completo a cada mudança.
4. Outras mensagens do cliente são ignoradas. Sem heartbeat. Em queda, o cliente reconecta com backoff (1 s → 15 s) e recebe um snapshot novo; o histórico recupera-se por `GET /api/events`.
5. Cliente lento: fila de 200 mensagens por ligação; as mais antigas são descartadas (o `home_state` seguinte repõe o estado).

## 3b. Modelos partilhados no OpenAPI (Conta Certa, F0)

Além dos modelos das rotas, `app.openapi()` inclui os de `contracts/api.py::OPENAPI_MODELS` (`install_shared_schemas`, `core/openapi_models.py`), sem rotas falsas: `HouseholdView`, `MemberView`, `MeContext`, `DeviceView`, `Appliance`, `EnergyReading`, `ConsumptionEvent`, `EnergySummary`, `PersonPresence`, `Attribution`, `ElectricityBill`, `BillAllocation`, `LandlordBillView`, `Budget`, `Contestation`, `NotificationView`, `NotificationPreferences`, agente e automações, `Provenance`, `ApiErrorBody` e os enums. **Não** entram `Device`, `Resident`, `Membership`, `ApplianceSignature`, `PresenceEvent`, `ConfirmationRequest` nem os eventos de domínio (dados privados). Os schemas e rotas existentes não mudaram (verificado por diferença com o OpenAPI anterior). Respostas: campos com valor por omissão são obrigatórios (`null` ≠ ausente), por isso o TypeScript gerado não os marca opcionais. Erros novos: [contracts.md](contracts.md) §8.

## 4. Extensões propostas e não implementadas

Existem só no mock do frontend, nunca no backend; não as apresentar como reais.

- `EventLogItem` com `category`, `correlation_id`, `details`, `result` (opcionais nos tipos do frontend).
- Memória e sugestões de rotinas (`MemorySnapshot`, `RoutineSuggestion`): issues #30/#31, fora do MVP.
- Diagnóstico da câmara (FPS, latência) na API.
