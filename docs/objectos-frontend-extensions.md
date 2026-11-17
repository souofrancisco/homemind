# ObjectOS — extensões de contrato do frontend

Este documento regista as extensões necessárias para a Pessoa 4 validar. São propostas; a UI continua a suportar o contrato atual (`HomeState`, `EventLogItem`, `/ws`, `/events`, `/rules` e `/off`) e não presume que novos endpoints já existam.

## Comparação com `frontend-api-contract-v3.md`

O v3 foi lido; ainda está marcado como proposta à espera de validação de P3/P5. A integração real fica pendente. O frontend desta branch continua selecionado em modo mock por omissão.

| Área | Código atual | v3 | Próximo passo antes da integração |
|---|---|---|---|
| Proxy Vite | `/api` aponta ao backend sem configuração `ws: true`; `/ws` tem regra própria | `/api` deve encaminhar HTTP e WebSocket | Atualizar o proxy ao integrar `/api/ws`; validar também Capacitor/origem absoluta. |
| WebSocket | `homeApi.ts` abre `/ws`, sem autenticação de primeira mensagem | `/api/ws`, primeira mensagem `{"type":"auth","token":"…"}` | Validar fluxo OIDC, token expirado, erro `unauthorized` + close 1008 e reconexão sem ciclo. Não colocar token na URL. |
| Snapshot inicial | Estado vem apenas do primeiro `home_state` WS | `GET /api/state` para o primeiro render e fallback | Implementar após confirmação do endpoint e dos tipos OpenAPI. |
| Eventos REST | `GET /events?limit=50`, código normaliza para mais recente primeiro | `GET /api/events?limit=50`, mais antigo → mais recente; WS acrescenta novos | Confirmar prefixo e manter a ordem cronológica do payload REST, apresentando a vista recente sem perder eventos. |
| Regras e desligar | `/rules`, `/rules/parse`, `/rules/{id}`, `/off` | `/api/rules`, `/api/rules/parse`, `/api/rules/{id}`, `/api/off` | `request()` não acrescenta `/api`; esperar rota v3 validada antes de alterar. |
| Erros HTTP | `request()` aceita `error.message` e mantém compatibilidade com `detail` | `{ "error": { "code", "message" } }` | A forma v3 já é lida; adicionar tratamento específico de `error.code`/401 para não reconectar WS em ciclo. |
| OpenAPI | `schema.d.ts` gerado só inclui `/api/me`, `/api/mcp/tools` e `/healthz` | Deve gerar `HomeState`, `Rule`, `RuleList`, `ParseResponse`, `OffResult`, `EventList`, `EventLogItem`, `EstadoCasa`, `Status` | Integrar depois de os endpoints/modelos existirem na branch base; não editar o ficheiro gerado à mão. |
| Simulação | Cenários locais em `mockHome.ts`; nenhuma chamada de rede | `POST /api/simulate` no backend `PROFILE=demo` | Continuar a usar mock local. Decidir depois se a demo muda para backend simulado e como marca `[SIMULADO]`. |
| Energia e dispositivos | Mock rotulado; energia inicial demonstrativa e incrementa apenas suspenso; UI suporta consumo medido opcional | Estimativa acumulada desde arranque, consumo W da tomada e estado detalhado em `casa` | O tipo frontend aceita `casa`, `mode_name` e presença `null`. Validar `consumo_w: null`, timestamp e estimativa durante suspensão antes de mostrar dados reais. |
| Câmara MJPEG | `/video` só preparado para API; não há endpoint validado | §2 sugere `/api/video`, §5 ainda descreve `GET /video`; autenticação também pendente de P1 | Incompatibilidade interna do v3 e decisão pendente de P1. Não ativar feed real até confirmar rota, auth e `camera_ok`. |

O v3 mantém `EventLogItem` nos campos atuais. `category`, `correlation_id`, `details` e `result` continuam extensões opcionais propostas, não são emitidos pelos mocks nem exigidos do backend. Sem `correlation_id` recebido, a UI apresenta eventos individuais e não infere sequências. FPS/latência e estado de processamento detalhado também não são inventados.

## Evento estruturado

Manter compatibilidade com os campos obrigatórios atuais de `EventLogItem` (`id`, `timestamp`, `level`, `message`, `source`). Validar se o backend pode acrescentar, opcionalmente:

```json
{
  "category": "presence | object | gesture | mode | rule | device | energy | system",
  "correlation_id": "id-opaco",
  "details": { "campos": "sanitizados e não sensíveis" },
  "result": "verified | failed | unverified | unsupported"
}
```

- Confirmar nomes dos campos, enumerações, origem (`fake`/`mcp` ou `SIMULATION`/`REAL`) e timestamps UTC ISO-8601.
- Eventos sem `category` aparecem como não categorizados/sistema. A UI não os converte em eventos estruturados com base no texto.
- Se um contrato posterior fornecer o mesmo `correlation_id` em vários eventos, a UI poderá formar uma operação explicativa. Sem esse campo, apresenta eventos separados. A UI só calcula duração se pelo menos dois timestamps reais forem válidos.
- Não incluir imagens, frames, identificação pessoal, credenciais, logs brutos MCP ou informação privada sem autorização.
- Validar autorização e visibilidade OPERATIONAL/PRIVATE da US-13. O frontend não consegue corrigir uma fuga de eventos do backend.

## Saúde da câmara

O frontend usa `GET /video` como MJPEG quando `HomeState.camera_ok` é verdadeiro e o fornecedor é API. Validar disponibilidade, prefixo/proxy, autenticação por cookie de mesma origem, reconexão e se o stream já contém anotações. `<img>` não permite acrescentar o bearer token do cliente OIDC; não colocar tokens em URLs.

FPS, latência, processamento local e timestamp específico da câmara não existem no contrato atual. Se necessários, validar um objeto de diagnóstico opcional, sem criar métricas no frontend. Nunca armazenar frames.

## Estado e energia

- Confirmar serialização dos estados `inativo`, `ativo`, `em_espera`, `suspenso` e `waiting_remaining_seconds`.
- `energy_saved_wh` e `energy_saved_eur` são estimativas. O v3 define acumulação desde o arranque do servidor com base na potência da tomada durante suspensão; consumo medido (`casa.tomada.consumo_w`) é mostrado separadamente quando existir. Não apresentar estimativa como leitura do contador.
- O mock só acumula poupança durante o estado simulado `suspenso`; não usa aleatoriedade.
- Confirmar se `POST /off` devolve confirmação explícita e resultados por dispositivo. Sem confirmação, a UI não deve afirmar sucesso real.

## Regras

O frontend atual usa `GET /rules`, `PATCH /rules/{id}`, `DELETE /rules/{id}`, `POST /rules/parse` e `POST /rules`. Validar que:

- `POST /rules/parse` apenas cria uma proposta e nunca persiste nem executa.
- Uma regra aceite pelo utilizador é guardada desativada (`enabled: false`) até o utilizador a ativar explicitamente. O frontend envia esse campo em `POST /rules`; confirmar que o backend o valida e respeita.
- `PATCH` apenas altera `enabled`; não executa a regra durante a edição.
- Erros do parser/NVIDIA são legíveis e deixam a lista de regras utilizável.
- Uma proposta não pode inventar dispositivos, capacidades nem valores fora dos suportados.

## ObjectOS Memory e sugestões

Não existe endpoint real de memória nem sugestões no contrato atual. A demo mantém os exemplos apenas em memória do processo frontend e não usa `localStorage`.

Validar um contrato futuro associado ao utilizador OIDC e à habitação, com operações separadas para:

- Ler estado de consentimento, eventos textuais elegíveis, padrões inferidos, preferências explicitamente confirmadas e sugestões pendentes/ignoradas.
- Atualizar consentimento de aprendizagem, consultar/exportar os dados e solicitar eliminação com confirmação do servidor.
- Listar, aceitar ou ignorar sugestões sem as ativar automaticamente.

Modelo conceptual proposto:

```ts
interface MemorySnapshot {
  profileId: string;
  updatedAt: string;
  learningEnabled: boolean;
  observedEvents: ObservedEvent[];
  inferredPatterns: InferredPattern[];
  confirmedPreferences: ConfirmedPreference[];
  pendingSuggestions: string[];
  ignoredSuggestions: string[];
}
```

Cada padrão deve apresentar a janela de observação, frequência, período horário e IDs/textos de evidência sanitizados. Preferências confirmadas exigem ação explícita do utilizador; não são deduzidas de eventos. Presença não é associada a uma identidade. A exportação Markdown é uma vista derivada dos dados estruturados, nunca a fonte primária.

## Partilha frontend

`HomeDataProvider` abre uma única ligação WebSocket enquanto a shell autenticada está montada. Normaliza eventos antigos ao receber REST e WebSocket, preserva campos opcionais novos e partilha estado, eventos e conectividade pelas páginas. Não adicionar endpoints nem alterar o backend nesta tarefa.
