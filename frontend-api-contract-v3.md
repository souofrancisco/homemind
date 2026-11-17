# ObjectOS — Contrato frontend ↔ backend (v3)

**Projeto:** HomeMind / ObjectOS — Aveiro Tech City Hackathon 2026  
**Estado:** **PROPOSTA v3: implementada pela Pessoa 4 no branch `backend-engine`; aguarda validação de P3/P5**  
**Base:** `frontend-api-contract-novo.md` (v2, P5 + P3). Esta versão **mantém a v2** e responde às perguntas da P4 (secção 10). Só altera 3 pontos que contradiziam o próprio documento ou o código existente (ver «O que mudou»).  
**Referências:** [`docs/objectos-plano.md`](https://github.com/souofrancisco/homemind/blob/main/docs/objectos-plano.md), [`CLAUDE.md`](https://github.com/souofrancisco/homemind/blob/main/CLAUDE.md), issues #13, #14, #22–#27, PR #32 (contratos de visão/eventos, P1).

> A fonte de verdade dos tipos é o **OpenAPI** do backend: `make contracts` gera `app/frontend/src/shared/api/schema.d.ts` com `HomeState`, `Rule`, `RuleList`, `ParseResponse`, `OffResult`, `EventList`, `EventLogItem`, `EstadoCasa` e `Status`. As mensagens do WebSocket não entram no OpenAPI; estão descritas na secção 4, e o `data` de cada uma usa os mesmos tipos.

## O que mudou em relação à v2

| # | v2 | v3 | Porquê |
|---|---|---|---|
| 1 | Erros `{"detail": {"code", "message"}}` | **`{"error": {"code", "message"}}`** (formato já existente), `400` para pedido inválido | O backend (`core/errors.py`) e o `client.ts` do frontend já usam `error.message`. A v2 pedia «confirmar para não entrar em conflito». O `code` passa a ser específico (ex.: `rule_not_found`). |
| 2 | Autenticação do WS «por confirmar»; «não colocar tokens no URL» | **1.ª mensagem do WS = `{"type":"auth","token":"<access_token>"}`** | O browser não envia `Authorization` num WebSocket e o token no URL ficaria nos logs do uvicorn. |
| 3 | Rotas lógicas (`/ws`, `/status`, …) | **Prefixo `/api`** (sem `/v1`), igual a `/api/me` e `/api/mcp/tools`, já coberto pelo proxy do Vite | Resposta à pergunta P4. |

**Adições compatíveis** (campos e rotas novos; nada removido):
- `GET /api/state`: o `HomeState` completo por REST, para carregar a página e para o caso de o WS cair (era pergunta da v2).
- `HomeState.mode_name`: o nome da regra ativa, para a UI não ter de cruzar com a lista de regras.
- `ParseResponse.replaces`: o nome da regra ativa que será desativada se a proposta for gravada.
- `POST /api/simulate`: injeta um evento **SIMULADO** (desenvolvimento e plano B da demo), marcado `[SIMULADO]` no registo.
- O exemplo do WS na v2 não tinha `casa`. Na v3, o `home_state` do WS e o `GET /api/state` são **o mesmo objeto**.

## 1. Responsáveis pela validação

| Pessoa | GitHub | Validar |
|---|---|---|
| 1 | `brunoviera88` | `GET /video`, `camera_ok` (escreve `app.state.engine.camara_ok`) |
| 2 | `1Mii` | Envio de eventos para o motor: `app.state.engine.publicar_de_thread(evento)`, ou `engine.fila` + `engine.loop` para o seu `PublicadorEventos` (tipos de `contracts/eventos.py`, PR #32) |
| 3 | `RafaelMat0s-Dev` | `EstadoCasa`, `CORES`, `Home` em `contracts/home.py`: **a v3 adota a especificação da v2 tal e qual** (secções 3.1, 6, 7) |
| 4 | `Amorim3000` | **Respondido: secções 2–4, 6–8 e 10** |
| 5 | `souofrancisco` | Consumo no React: envelope `{"error"}`, autenticação do WS, `GET /api/state` e `GET /api/events` |

## 2. Convenções gerais — **decididas**

- **Prefixo:** `/api`. A exceção é `/healthz` (público). O MJPEG (`/video`, P1) também deve ficar sob `/api` para passar pelo proxy.
- **Proxy Vite (P5):** `"/api": { target, ws: true }`, para o WebSocket funcionar através do proxy.
- **Formato:** JSON UTF-8. Campos em `snake_case`. Os campos da casa e das regras ficam em português, como no plano (`casa`, `acoes`, `ligada`); os do estado e do registo ficam em inglês, como na v2.
- **Hora:** ISO 8601 UTC.
- **Autenticação:** todas as rotas `/api/*` exigem `Authorization: Bearer <access_token>` (Authentik), incluindo as `/api/home/*` da P3. O WebSocket autentica-se na 1.ª mensagem (secção 4.2). **Nunca há tokens no URL.**
- **Origem dos dados:** `backend: "fake" | "mcp"` sempre visível. Com `fake`, a UI mostra **SIMULADO**.
- **Falhas:** a UI só mostra sucesso quando o backend o confirma (ver `POST /api/off`).

## 3. Modelo de estado

### 3.1. `HomeState`

Devolvido pelo `GET /api/state` e enviado no WS (`home_state`). É o mesmo objeto nos dois.

```json
{
  "mode": "leitura",
  "mode_name": "Modo leitura",
  "state": "em_espera",
  "presence": false,
  "camera_ok": true,
  "mcp_ok": false,
  "backend": "fake",
  "waiting_remaining_seconds": 7.5,
  "energy_saved_wh": 12.5,
  "energy_saved_eur": 0.002,
  "updated_at": "2026-11-17T15:20:00Z",
  "casa": {
    "backend": "fake",
    "mcp_ok": false,
    "lampada": { "ligada": true, "cor": "branco_quente", "rgb": [255, 170, 90], "brilho": 40 },
    "tomada": { "ligada": true, "consumo_w": 60.0, "consumo_lido_em": "2026-11-17T15:19:58Z" },
    "atualizado_em": "2026-11-17T15:20:00Z",
    "aviso": null
  }
}
```

| Campo | Tipo | Significado (decidido) |
|---|---|---|
| `mode` | `string \| null` | `id` da regra que ativou o modo atual. `null` = nenhum modo (estado `inativo`). |
| `mode_name` | `string \| null` | **novo**: `nome` dessa regra. |
| `state` | `"inativo" \| "ativo" \| "em_espera" \| "suspenso"` | Estados do plano §4.2. |
| `presence` | `bool \| null` | `null` = ainda sem dados da visão desde o arranque. Sem identificação nem contagem. |
| `camera_ok` | `bool` | Escrito pela visão (P1). `false` até a câmara arrancar. |
| `mcp_ok`, `backend` | | Cópias de `casa.mcp_ok` e `casa.backend` (P3). |
| `waiting_remaining_seconds` | `number \| null` | Só com `em_espera`: segundos que faltam para suspender, **no instante `updated_at`**. A UI faz a contagem decrescente localmente; recebe um novo `home_state` em cada transição (incluindo o aviso). |
| `energy_saved_wh`, `energy_saved_eur` | `number` | **Estimativa** (W da tomada no momento da suspensão × horas suspensas), **acumulada desde o arranque do servidor**. Durante a suspensão, inclui a parte em curso. Se o consumo estiver indisponível (`null`), a suspensão **não conta** e aparece um evento `warning`. A tarifa vem de `TARIFA_EUR_KWH` (0,16 €/kWh por omissão). |
| `updated_at` | ISO 8601 | Hora do snapshot. |
| `casa` | `EstadoCasa \| null` | Especificação da P3 (v2 §3.1), sem alterações. É `null` só se `Home.estado()` falhar. |

**Comportamento do motor** (para a UI e para os mocks):
- **Gesto com regra ativa:** aplica as ações e o estado passa a `ativo`.
- **Mesmo objeto com o modo já ativo:** é ignorado e fica um evento «já está ativo».
- **Outro objeto:** troca de modo.
- **Divisão vazia:** passa a `em_espera` durante 180 s (10 s com `PROFILE=demo`). 5 s antes do fim a luz baixa para 20%, e depois passa a `suspenso` (luz e tomada desligadas, estado guardado).
- **Regresso:** volta a `ativo`, repondo o estado guardado.
- **Mais de 30 min em `suspenso`:** passa a `inativo`.
- **`POST /api/off`:** passa a `inativo` e cancela os temporizadores.

### 3.2. Eventos de domínio (visão → motor)

Ficam como no PR #32 (`contracts/eventos.py`): `ObjetoLevantado{tipo, classe, hora}` e `Presenca{tipo, ha_alguem, hora}`.

**Fronteira decidida (P2/P4):** estes eventos são **internos**. A UI vê-os apenas como linhas do registo («Livro levantado(a)», «Divisão vazia») e pelo efeito no `HomeState`.

## 4. WebSocket — `WS /api/ws` (issue #24)

### 4.1. Envelope (adotado da v2)

```json
{ "type": "home_state", "data": HomeState }
{ "type": "event",      "data": EventLogItem }
{ "type": "error",      "data": { "code": "unauthorized", "message": "Não autenticado" } }
```

- **`home_state`**: enviado logo após a autenticação e depois de **cada** mudança (transições, aviso, regras alteradas, off). É sempre o snapshot completo.
- **`event`**: enviado por cada linha nova do registo. Uma ação gera vários `event` e depois um `home_state`.
- **`error`**: usado hoje só quando a autenticação falha, imediatamente antes de fechar.
- Não há `energy_update` nem `rule_changed`: a energia vem no `home_state`. Depois de alterar regras, a UI volta a pedir `GET /api/rules`.

### 4.2. Ciclo de vida

1. O cliente abre `ws(s)://<origem>/api/ws` e envia como **1.ª mensagem**: `{"type": "auth", "token": "<access_token>"}`. Tem 5 s para o fazer.
2. Se o token for inválido, o servidor envia `{"type":"error","data":{"code":"unauthorized",…}}` e fecha com o código **1008**. A UI deve então renovar a sessão e não reconectar em ciclo.
3. Se for válido, recebe **logo** um `home_state`, seguido de `event` e `home_state` à medida que as coisas acontecem.
4. Outras mensagens do cliente são ignoradas. Não há heartbeat. Se a ligação cair, a UI mostra offline e reconecta com backoff, e na reconexão recebe um snapshot novo.
5. Ao abrir a página, o histórico é carregado com `GET /api/events`; o WS só traz as linhas novas.

## 5. REST: estado e vídeo (issue #25)

### `GET /api/status` → `200 Status`

Só a saúde das integrações (como na v2):

```json
{ "camera_ok": true, "mcp_ok": false, "backend": "fake", "updated_at": "2026-11-17T15:20:00Z" }
```

### `GET /api/state` → `200 HomeState` — **novo**

O mesmo objeto da secção 3.1. Serve para o primeiro render e como recurso (polling) quando o WS está em baixo.

### `GET /api/home/status` e `GET /api/home/estado` (P3)

Sem alterações em relação à v2. **Decisão P4:** ficam autenticadas como o resto de `/api`; só `/healthz` é pública.

### `GET /video` — MJPEG (P1)

Mantém-se como na v2. **Nota:** um `<img>` não envia `Authorization`. A P1 deve decidir entre deixar o MJPEG sem autenticação (é só local) ou usar um mecanismo próprio. **Nunca usar um token de longa duração no URL.**

## 6. REST: regras e NVIDIA (issue #26)

### Modelo `Rule` (v2, com `enabled`)

```json
{
  "id": "leitura",
  "objeto": "livro",
  "nome": "Modo leitura",
  "enabled": true,
  "acoes": [
    { "dispositivo": "lampada", "ligada": true, "cor": "branco_quente", "brilho": 40 },
    { "dispositivo": "tomada", "ligada": true }
  ]
}
```

- **Valores admissíveis:** os definidos pela P3 na v2, sem alterações: as 10 cores incluindo `rosa`, `brilho` de 1 a 100, `cor`/`brilho` a `null` para manter o valor atual.
- **Outras validações:**
  - `id` só pode ter `^[a-z0-9_-]{1,40}$` e `nome` tem de 1 a 60 caracteres.
  - `objeto` é um de `caneca | livro | comando`.
  - Cada ação é `AcaoLampada` ou `AcaoTomada` (tipos TS separados, discriminados por `dispositivo`, como proposto no PR #32). O JSON não muda.
  - **Campos desconhecidos são rejeitados** (`400 invalid_request`): por exemplo, `ativa` em vez de `enabled`.
  - Cada regra tem 1 a 2 ações, no máximo uma por dispositivo, e a tomada não tem `cor` nem `brilho`.
- **No máximo uma regra `enabled` por objeto.** Gravar ou ativar uma regra desativa as outras do mesmo objeto.
- **Predefinidas** (criadas no 1.º arranque, em `rules.json`):

  | Regra | Objeto | Ações |
  |---|---|---|
  | `pausa` | caneca | luz branco quente a 30% |
  | `leitura` | livro | luz branco quente a 40% + tomada ligada |
  | `cinema` | comando | luz azul a 10% + tomada ligada |

| Método | Rota | Pedido | Resposta |
|---|---|---|---|
| `GET` | `/api/rules` | — | `200 { "rules": [Rule] }` |
| `POST` | `/api/rules/parse` | `{ "text": "…" }` (3–300 caracteres) | `200 { "proposal": Rule, "summary": "…", "replaces": "Modo leitura" \| null }` |
| `POST` | `/api/rules` | `Rule` | `201 Rule` (cria, ou substitui se o `id` for igual) |
| `PATCH` | `/api/rules/{id}` | `{ "enabled": bool }` | `200 Rule` · `404 rule_not_found` |
| `DELETE` | `/api/rules/{id}` | — | `204` · `404 rule_not_found` |

**`POST /api/rules/parse`:**
- **Não grava nem executa nada.**
- **Resumo e identificador:** o `summary` é gerado pelo backend a partir da regra validada, não pelo LLM, por isso descreve exatamente o que vai acontecer. Se o `id` proposto já existir, o backend acrescenta `-2`, `-3`, …, para nunca sobrescrever uma regra.
- **O que o LLM recebe:** só o texto e o schema da regra; nunca imagens, histórico nem tokens. Recusa alarmes, horários, outros objetos e pedidos ambíguos.
- **Erros:**

  | Código | `error.code` | Quando |
  |---|---|---|
  | `400` | `rule_not_supported` | A mensagem explica porquê; a UI mostra-a tal e qual. |
  | `502` | `invalid_proposal` | O modelo falhou duas vezes; pedir ao utilizador que reformule. |
  | `503` | `nvidia_unavailable` | Sem chave ou sem rede. As regras existentes continuam a funcionar. |

## 7. REST: histórico, energia e desligar tudo (issues #26–#27)

### `GET /api/events?limit=50` → `200 { "events": [EventLogItem] }`

`limit` vai de 1 a 50 (50 por omissão). Os eventos vêm por ordem cronológica, do mais antigo para o mais recente. São só os da memória desde o arranque; o `events.jsonl` guarda o histórico completo.

```json
{
  "id": "evt-3f9c2a1b7d4e",
  "timestamp": "2026-11-17T15:20:00Z",
  "level": "info",
  "message": "«Modo leitura» ativado",
  "source": "fake"
}
```

- `level` é `info`, `warning` (por exemplo, consumo indisponível) ou `error` (por exemplo, ação não confirmada).
- `source` é o backend da casa nesse momento.
- Eventos injetados por `/api/simulate` levam `[SIMULADO]` na mensagem.
- Só texto: nunca frames nem dados de pessoas.

### Energia

Está no `HomeState` (ver secção 3.1).

### `POST /api/off` → sempre `200 OffResult`

O comportamento é o definido pela P3 na v2, sem alterações: corpo vazio, `off` ou `unknown` por dispositivo, e os códigos `partial_failure` e `mcp_unavailable`. Os campos `code` e `message` vêm sempre presentes (`null` em caso de sucesso).

```json
{ "success": true, "state": "inativo", "backend": "fake",
  "devices": { "lampada": "off", "tomada": "off" }, "code": null, "message": null }
```

### `POST /api/simulate` → `200 HomeState` — **novo, só desenvolvimento e plano B**

Corpo: um evento da secção 3.2, por exemplo `{"tipo":"objeto_levantado","classe":"livro","hora":"2026-11-17T15:20:00Z"}`. Passa pelo mesmo motor que os eventos reais e fica marcado `[SIMULADO]`. Serve para a P5 testar contra o backend real sem câmara, e para um plano B honesto na demo.

## 8. Erros HTTP — **formato existente mantido**

```json
{ "error": { "code": "rule_not_found", "message": "Regra não encontrada" } }
```

- Pedido inválido (validação): `400` com `invalid_request`.
- Sem login: `401` com `http_401`.
- Códigos específicos: `rule_not_found` (404), `rule_not_supported` (400), `invalid_proposal` (502), `nvidia_unavailable` (503).
- Para usar um código específico noutra rota, basta `HTTPException(status, {"code": …, "message": …})`.

## 9. Mocks e integração no frontend

Mantém-se como na v2. Notas da P4:
- O `mockHome.ts` pode seguir à risca a secção «Comportamento do motor» (3.1).
- Alternativa ao mock: correr o backend com `PROFILE=demo` e usar `POST /api/simulate`. Assim, a UI testa contra o motor real, com o rótulo SIMULADO.
- O `api()` de `features/auth/client.ts` só faz GET. Para usar `POST`, `PATCH` e `DELETE` tem de aceitar `method` e `body`, e tratar o `204` sem corpo.

## 10. Perguntas da v2 — respostas

- [x] **P4: prefixo e autenticação do WS?** Fica `/api`. O WS autentica-se na 1.ª mensagem `{"type":"auth","token"}` (secções 2 e 4.2).
- [x] **P4: envelope `type` + `data` e snapshot na (re)conexão?** Sim, as duas coisas (secção 4).
- [x] **P4: enums, `mode`, temporizador e período da energia?** Respondidos na secção 3.1: o temporizador é `waiting_remaining_seconds` no instante `updated_at`, e a energia acumula desde o arranque.
- [x] **P4: histórico inicial?** Vem do `GET /api/events?limit=50`; as linhas novas chegam pelo WS como `event`.
- [x] **P4: payloads de regras? Há `PATCH`?** Sim, os da v2 (secção 6), com o `PATCH {enabled}` implementado.
- [x] **P3: `POST /off`, saúde do MCP e `fake|mcp`?** Fica como a P3 definiu na v2.
- [ ] **P1:** rota e autenticação do MJPEG, e escrita de `camara_ok`.
- [x] **P2/P4: eventos expostos à UI?** Nenhum diretamente; aparecem só como linhas do registo (secção 3.2).
- [ ] **Todos:** aprovar a v3.

## 11. Critério de aprovação

A v3 já está implementada (branch `backend-engine`, a pedir merge depois do PR #32). Se a P3 e a P5 aprovarem, a P5 pode ligar os componentes às rotas reais com os tipos de `make contracts`. Qualquer alteração passa a ser feita primeiro neste documento e depois nos modelos Pydantic.

**Decisão da equipa:** ☐ Aprovado sem alterações · ☐ Aprovado com alterações documentadas · ☐ Pendente  
**Observações:** __________________________________________
