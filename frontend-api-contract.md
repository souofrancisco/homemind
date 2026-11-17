# ObjectOS — Contrato frontend ↔ backend (proposta para validação)

**Projeto:** HomeMind / ObjectOS — Aveiro Tech City Hackathon 2026  
**Estado:** **PROPOSTA — não implementar como contrato definitivo antes de validação**  
**Referências:** [`docs/objectos-plano.md`](https://github.com/souofrancisco/homemind/blob/main/docs/objectos-plano.md), [`CLAUDE.md`](https://github.com/souofrancisco/homemind/blob/main/CLAUDE.md) e issues [#24](https://github.com/souofrancisco/homemind/issues/24), [#25](https://github.com/souofrancisco/homemind/issues/25), [#26](https://github.com/souofrancisco/homemind/issues/26), [#27](https://github.com/souofrancisco/homemind/issues/27).

> **Objetivo:** permitir que a Pessoa 5 desenvolva o frontend React/Mantine com dados simulados (`mock`) e, posteriormente, substitua a fonte de dados pelo backend real sem reescrever os componentes. Este documento **não afirma que as rotas, payloads ou operações já existem**.

## 1. Responsáveis pela validação

| Pessoa | GitHub | Validar |
|---|---|---|
| 1 | `brunoviera88` | `GET /video`, disponibilidade da câmara e comportamento do stream MJPEG |
| 2 | `1Mii` | Eventos `objeto_levantado` e `presenca`, classes e temporização |
| 3 | `RafaelMat0s-Dev` | Interface `Home`, `FakeHome`/`McpHome`, estado dos dispositivos, execução e falhas do `POST /off` |
| 4 | `Amorim3000` | WebSocket, máquina de estados, regras, energia, registo, API REST e proposta da NVIDIA |
| 5 | `souofrancisco` | Consumo dos contratos no React, UX, estados de carregamento/erro e mocks |

**Prioridade de desbloqueio:** Pessoa 4 + Pessoa 3 devem validar primeiro as secções 2–7; Pessoas 1 e 2 confirmam vídeo/eventos em paralelo.

## 2. Convenções gerais — por confirmar

- **Prefixo das rotas:** todos os caminhos abaixo são *lógicos* (`/ws`, `/status`, etc.). Confirmar o prefixo real na aplicação existente (`/api/v1` ou outro), no proxy Vite e no OpenAPI. **Não criar rotas duplicadas só para corresponder aos exemplos.**
- **Formato:** JSON UTF-8; `snake_case` nos campos e valores de enum estáveis.
- **Hora:** ISO 8601 com fuso/UTC, por exemplo `2026-11-17T15:20:00Z`.
- **IDs:** strings opacas; não inferir IDs de dispositivos MCP nem expô-los desnecessariamente na UI.
- **Autenticação:** reutilizar Authentik/OIDC e o cliente autenticado existentes. Confirmar proteção das rotas REST, autenticação do WebSocket e autorização do MJPEG, incluindo a limitação de `<img src>` para enviar headers `Authorization`. **Não colocar tokens no URL nem nos logs.** Se necessário, usar proxy autenticado de mesma origem ou mecanismo seguro acordado.
- **CORS/origens:** preferir mesma origem via proxy; confirmar política para web e Capacitor. Android **não bloqueia o MVP**.
- **Origem dos dados:** `fake` ou `mcp` de forma visível no dashboard. Nunca apresentar simulações como resultados de dispositivos reais.
- **Falhas:** o frontend nunca mostra «sucesso» só porque o pedido foi enviado; deve receber confirmação explícita do backend e tratar timeout, estado offline, e falha parcial.

## 3. Modelo de estado enviado ao frontend

### 3.1. Estado do sistema (`HomeState`) — **formato proposto**

```json
{
  "mode": "leitura",
  "state": "ativo",
  "presence": true,
  "camera_ok": true,
  "mcp_ok": false,
  "backend": "fake",
  "waiting_remaining_seconds": null,
  "energy_saved_wh": 12.5,
  "energy_saved_eur": 0.003,
  "updated_at": "2026-11-17T15:20:00Z"
}
```

- `mode`: `null` ou ID de uma regra/modo (`leitura`, `cinema`, `cafe`, etc.). A lista deve vir das regras, não ficar codificada no frontend.
- `state`: `inativo | ativo | em_espera | suspenso` (estados definidos no plano; serialização exata a confirmar).
- `presence`: booleano de presença na divisão, **sem identificação ou contagem de pessoas**.
- `camera_ok`: a câmara está a disponibilizar frames válidos.
- `mcp_ok`: estado de saúde da ligação MCP; em `fake` pode ser `false` sem impedir a demo simulada. Confirmar se é preciso um estado separado para `FakeHome`.
- `backend`: `fake | mcp` (preferível a `real`, que é ambíguo).
- `waiting_remaining_seconds`: `number | null`; se não existir no backend, combinar uma deadline (`waiting_until`) para calcular o temporizador no cliente.
- `energy_saved_wh`, `energy_saved_eur`: números estimados, não medições auditadas; definir período de acumulação (sessão/demo/total).

**Decisões a fechar:** enumerados definitivos, significado exato de `mode: null`, campo do temporizador, período da energia e campos mínimos obrigatórios.

### 3.2. Eventos de domínio (da visão) — **já descritos no plano; serialização proposta**

```json
{ "tipo": "objeto_levantado", "classe": "livro", "hora": "2026-11-17T15:20:00Z" }
```

```json
{ "tipo": "presenca", "ha_alguem": false, "hora": "2026-11-17T15:20:03Z" }
```

Classes previstas: `caneca | livro | comando`. Estes eventos são internos ao motor e **não têm de ser publicados diretamente no WebSocket**, desde que a UI receba o estado e o registo necessários. A Pessoa 2 e a Pessoa 4 devem decidir esta fronteira.

## 4. WebSocket — `WS /ws` (issue #24)

### 4.1. Envelope proposto

Em vez de enviar JSONs diferentes sem identificação, usar sempre:

```json
{
  "type": "home_state",
  "data": {
    "mode": "leitura",
    "state": "ativo",
    "presence": true,
    "camera_ok": true,
    "mcp_ok": false,
    "backend": "fake",
    "waiting_remaining_seconds": null,
    "energy_saved_wh": 12.5,
    "energy_saved_eur": 0.003,
    "updated_at": "2026-11-17T15:20:00Z"
  }
}
```

**Tipos propostos para MVP:**

| `type` | `data` | Uso |
|---|---|---|
| `home_state` | `HomeState` completo | Estado inicial, reconexão e transições; **obrigatório** |
| `event` | `EventLogItem` | Inserir linha no histórico em tempo real |
| `error` | `{ "code": "...", "message": "..." }` | Erro recuperável, sem segredos nem stack traces |

**Simplificação recomendada:** para a hackathon, mandar um `home_state` completo sempre que o estado muda (e logo após conectar), em vez de patches parciais; eventos do histórico podem chegar separadamente. Não é obrigatório criar `energy_update` ou `rule_changed` se o backend emitir snapshots completos ou a UI atualizar a lista de regras após mutações.

### 4.2. Ciclo de vida

1. Cliente abre a ligação autenticada (estratégia por confirmar).
2. Backend envia **imediatamente um snapshot `home_state` completo**.
3. Backend envia alterações e novos eventos; frontend atualiza sem refresh.
4. Se a ligação cair: interface mostra **offline/desatualizado**, conserva o último estado com indicação visual e tenta reconectar com *backoff*.
5. Depois da reconexão: backend envia novo snapshot; cliente não depende de ter recebido todas as mensagens anteriores.

**Confirmar:** frequência de emissão, necessidade de `ping`/heartbeat e se os dados de energia chegam no snapshot ou noutro evento.

## 5. REST: estado e vídeo (issue #25)

### `GET /status` — **formato proposto**

Resposta `200`:

```json
{
  "camera_ok": true,
  "mcp_ok": false,
  "backend": "fake",
  "updated_at": "2026-11-17T15:20:00Z"
}
```

Esta rota pode devolver só a saúde das integrações; o estado dinâmico completo continua a vir do WebSocket. **Confirmar se existe necessidade de `GET /state` para carregar o dashboard quando o WebSocket estiver indisponível.**

### `GET /video` — MJPEG

- `Content-Type: multipart/x-mixed-replace; boundary=...` (boundary definido pelo backend).
- A UI apresenta-o numa tag `<img>` ou componente equivalente, com estado de carregamento/erro.
- Não guardar nem enviar frames para serviços externos.
- Se o stream falhar, mostrar câmara indisponível; não confundir placeholder/vídeo gravado com transmissão real.
- **Pessoa 1 deve confirmar:** rota final, autenticação para `<img>`, estratégia de reconexão, `camera_ok` e compatibilidade com proxy.

## 6. REST: regras e NVIDIA (issue #26)

### Modelo `Rule` — baseado no exemplo do plano

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

`enabled` é **proposto** para suportar ativar/desativar regras; não consta do JSON-base no plano. Confirmar valores admissíveis de `cor`, intervalo de `brilho` (`0–100` proposto) e validação das ações com capacidades reais da casa.

| Método | Rota lógica | Pedido | Resposta proposta |
|---|---|---|---|
| `GET` | `/rules` | — | `{ "rules": [Rule] }` |
| `POST` | `/rules/parse` | `{ "text": "Quando levantar o livro, ligar a luz a 40%" }` | `{ "proposal": RuleDraft, "summary": "..." }` |
| `POST` | `/rules` | `RuleDraft` validada | `201` + `Rule` persistida |
| `DELETE` | `/rules/{id}` | — | `204` sem corpo |
| `PATCH` | `/rules/{id}` | `{ "enabled": false }` | `200` + `Rule` atualizada |

**Nota:** `PATCH /rules/{id}` é uma **proposta adicional** — o plano prevê ativar/desativar regras, mas não fecha o método. Caso não seja implementado no MVP, a UI deve ocultar/desativar essa ação em vez de a fingir.

**Regras de segurança/UX:**

- `POST /rules/parse` só **interpreta e devolve uma proposta**; **não grava nem executa** nada.
- Apresentar a proposta e pedir confirmação explícita antes de `POST /rules`.
- O backend valida IDs, campos, dispositivos e capacidades; o frontend também valida para melhorar UX, mas não substitui validação no servidor.
- Se a NVIDIA estiver indisponível, devolver erro informativo e manter as regras/presets existentes utilizáveis.
- Confirmar como se evita que a proposta crie ações não suportadas por `FakeHome`/`McpHome`.

## 7. REST: histórico, energia e desligar tudo (issues #26–#27)

### Histórico — **endpoint novo proposto**

O plano prevê mostrar até 50 linhas de `events.jsonl`, mas **não define rota REST de listagem**. Para carregar o histórico ao abrir a página, propõe-se:

`GET /events?limit=50` → `200`:

```json
{
  "events": [
    {
      "id": "evt-001",
      "timestamp": "2026-11-17T15:20:00Z",
      "level": "info",
      "message": "Modo leitura ativado",
      "source": "fake"
    }
  ]
}
```

`EventLogItem` é **proposto**; se o backend preferir devolver entradas no snapshot inicial do WebSocket, acordar esse mecanismo e eliminar esta rota. Eventos textuais apenas; **nunca frames, reconhecimento facial ou dados sensíveis**.

### Energia

Reutilizar `energy_saved_wh` e `energy_saved_eur` no `home_state`, atualizados pelo motor de estados. Definir **período da estimativa**, tarifa configurada e o comportamento quando o consumo real não estiver disponível (não inventar medição).

### `POST /off` — **resposta proposta**

Pedido: `{}` ou corpo vazio (**a confirmar**).

Sucesso confirmado `200`:

```json
{
  "success": true,
  "state": "inativo",
  "backend": "fake",
  "devices": {
    "lampada": "off",
    "tomada": "off"
  }
}
```

Falha parcial `200` ou código de erro acordado (o exemplo abaixo é **proposta**, não comportamento existente):

```json
{
  "success": false,
  "code": "partial_failure",
  "message": "A lâmpada desligou, mas não foi possível confirmar a tomada",
  "devices": {
    "lampada": "off",
    "tomada": "unknown"
  }
}
```

- O frontend apresenta confirmação de utilizador antes da operação, indicador de execução e resultado **efetivamente reportado** pelo backend.
- O backend controla a autorização e confirma por leitura de estado quando possível; em timeout MCP ambíguo, não fazer retry cego de escrita.
- Escrever apenas em lâmpada/tomada permitidas; não controlar alarme/segurança.

## 8. Erros HTTP — formato proposto

Para as novas rotas, usar um envelope consistente e compatível com os erros existentes da FastAPI:

```json
{
  "detail": {
    "code": "device_unavailable",
    "message": "Não foi possível contactar a tomada"
  }
}
```

Mapeamento sugerido: `400/422` pedido inválido; `401/403` não autenticado/sem permissão; `404` regra não encontrada; `409` conflito de estado, se relevante; `503` dependência indisponível; `500` erro interno sem expor detalhes. **Confirmar formato final** para não entrar em conflito com a gestão de erros já existente.

## 9. Mocks e integração no frontend

**Local:** `app/frontend/src/` (reutilizar `App.tsx`, Auth/OIDC, Mantine, cliente HTTP e contratos OpenAPI gerados). **Não criar uma segunda aplicação.**

Separar componentes visuais de acesso a dados:

- `types.ts` — interfaces provisórias (`HomeState`, `Rule`, `EventLogItem`, etc.).
- `mockHome.ts` — serviço com estados simulados determinísticos (modos, ausência, regras, eventos, off).
- `homeApi.ts` — serviço real; trocar implementação por configuração, não por lógica dentro dos componentes.
- `useHomeSocket.ts` — subscrição/reconexão e snapshot de estado.

**Contrato comum:** as duas implementações (`mock` e `real`) devem devolver os **mesmos tipos** e estados de erro. O mock não é um dispositivo real; a UI mostra sempre `SIMULADO` ou `REAL`/`MCP` de forma explícita.

### Comportamentos a testar sem backend

1. Mudança de modo ao levantar um objeto simulado.
2. Presença/ausência: `ativo → em_espera → suspenso → ativo`.
3. Desligar tudo: confirmação, `loading`, sucesso e falha parcial simulada.
4. Criar regra: proposta → pré-visualizar → confirmar → guardar; cancelar não grava.
5. Perda de WebSocket: offline visível + reconexão + novo snapshot.
6. Câmara indisponível: erro honesto; nunca apresentar vídeo de reserva como feed real.
7. Layout responsivo e navegável por teclado para desktop/projetor/mobile.

**Android/Capacitor:** já existe infraestrutura no repo, mas **não é pré-requisito** para aprovar o contrato web. Validar APK, OIDC mobile e rede apenas se sobrar tempo ou a demo exigir.

## 10. Perguntas que precisam de resposta (checklist de aprovação)

- [ ] **P4:** Qual é o prefixo real das rotas e o formato de autenticação do WebSocket?
- [ ] **P4:** Aceitamos o envelope `type` + `data` e um snapshot completo na conexão/reconexão?
- [ ] **P4:** Confirmamos os enums de estado, `mode`, temporizador e período da energia?
- [ ] **P4:** O histórico inicial será servido por `GET /events?limit=50` ou pelo WebSocket?
- [ ] **P4:** Confirmamos payload/resposta de `GET/POST/DELETE /rules` e `POST /rules/parse`? Haverá `PATCH` para `enabled`?
- [ ] **P3:** Qual o formato da confirmação/erro do `POST /off` e como representar falhas parciais?
- [ ] **P3:** Como distinguimos saúde MCP, backend `fake|mcp` e estados reais dos dispositivos?
- [ ] **P1:** Confirmamos `GET /video`, autenticação do MJPEG, `camera_ok` e recuperação de stream?
- [ ] **P2/P4:** Que eventos de gesto/presença são expostos à UI e que eventos ficam internos?
- [ ] **Todos:** Confirmamos estes contratos como base do MVP e evitamos alterar esquemas sem coordenar?

## 11. Critério de aprovação

Aprovar este documento (com as correções necessárias) **antes de a Pessoa 5 ligar os componentes às APIs reais**. Pode começar já a UI e os mocks, mas deve centralizar os tipos e evitar assumir endpoints ainda não confirmados. Após consenso, atualizar os schemas Pydantic/OpenAPI e gerar os tipos TypeScript a partir do contrato efetivamente implementado.

**Decisão da equipa:** ☐ Aprovado sem alterações · ☐ Aprovado com alterações documentadas · ☐ Pendente  
**Observações:** __________________________________________
