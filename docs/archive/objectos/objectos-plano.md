# ObjectOS — Plano de implementação

> **ARQUIVADO — ObjectOS.** Só consulta histórica; não descreve a Conta Certa. Índice: [README](README.md).

Aveiro Tech City Hackathon 2026 · Desafio 3 (Altice Labs, Connected Home)

> Plano de referência (especificação original, secções 1–11). O **estado real** está na tabela abaixo e em [estado-para-amanha.md](estado-para-amanha.md); os contratos em vigor em [contratos.md](../../architecture/api-implementada.md). Onde o plano e o código divergirem, vale o código.

## 0. Estado por área (17/11/2026)

Legenda: **Implementado** = código na `main` com testes automáticos · **Validado** = comprovado com hardware/serviço real · **Simulado** = só comprovado com fakes · **Bloqueado** = depende de terceiros.

| Área | Implementado | Validado (REAL) | Notas |
|---|---|---|---|
| RTSP, reconexão, clip de reserva (#2, #3) | sim | leitura RTSP 10 min sem quedas | atraso câmara→ecrã por medir |
| YOLO objetos + pose + ByteTrack (#4) | sim (extra `visao`) | FPS em MPS/CPU com imagem sintética | falta clip MEARI, livro, GPU da demo |
| Gesto e presença (#5, #6) | sim | não | **Simulado**: só dados sintéticos |
| Ponte visão → motor, MJPEG anotado (#7, #28) | sim | não | **Simulado**: clip sintético + detetor falso, ponta a ponta |
| Afinador offline (#8) | sim | não | falta clip real |
| `Home` + FakeHome (#9) | sim | n/a | é o modo simulado |
| MCP: OAuth, descoberta, leituras (#10) | sim | **sim**, leituras e renovação de sessão | |
| MCP: escrita na lâmpada/tomada (#11) | sim | **não** | **Bloqueado**: o MCP aceita a escrita, a lâmpada não reage |
| Consumo da tomada (#12) | sim | não | **Bloqueado**: unidade não declarada; `consumo_w` fica `null` |
| Regras, estados, energia, registo (#13, #22, #23) | sim | n/a | **Simulado** com FakeHome; ponta a ponta em processo real |
| NVIDIA texto → regra (#14) | sim | não verificado nesta auditoria | precisa de `NVIDIA_API_KEY` |
| Painel: WS, vídeo, estado, regras, off (#24–#27) | sim | login Authentik real verificado; UI por validar à mão | |
| Integração e benchmark (#28) | sim | não | latência real e 10 demos por fazer |
| Entregáveis (#29) | README e docs | — | PDF, PPT e pitch por fazer |
| Extras (#30, #31) | não | — | não começar |

## 1. Produto e decisões

Com a MEARI em RTSP continuamente ligada numa habitação própria, levantar **caneca, livro ou comando** ativa um modo de casa. O gesto requer objeto junto do pulso, mão acima do cotovelo e estabilidade durante 1 segundo; repetir o mesmo modo não o reativa. Levantar outro objeto troca o modo. A presença é binária. Após ficar vazia, a divisão passa a espera e depois suspende a luz/tomada, restaurando-as no regresso; há botão «desligar tudo». Vídeo só em processamento local; sem gravar frames, reconhecimento facial ou cloud de vídeo; apenas eventos textuais.

## 2. Stack e arquitetura

- Processo Python único (versão do repo **3.12+**), FastAPI, Uvicorn, WebSocket, Pydantic v2, `asyncio.Queue`.
- MEARI RTSP/TCP via OpenCV/FFmpeg; clip da MEARI com `VIDEO_SOURCE` como fallback; último frame sempre substituído para evitar atraso.
- YOLO `yolo11s.pt` + `yolo11s-pose.pt` em CUDA, ByteTrack (`track(persist=True)`); reduzir para «n» se GPU exigir.
- MCP Altice SDK Python `mcp` Streamable HTTP com cabeçalhos X-API-Key/X-Client-Type e OAuth conforme serviço real; nunca inventar tokens/esquemas.
- NVIDIA via `openai` (`base_url=https://integrate.api.nvidia.com/v1`), só na configuração de regras.
- Regras `rules.json`; histórico textual `events.jsonl`; sem BD nova. Frontend React/Vite/TS existente com Mantine.
- Reutilizar `app/backend/src/homemind` (main, config, auth, MCP), `app/frontend/src`, Docker, Authentik e CI. Os caminhos `backend/*.py` do plano original correspondem a módulos NOVOS na árvore real; não criar uma segunda app paralela.

```text
MEARI RTSP → VideoSource → YOLO objetos + pose → Gesture/Presence → asyncio.Queue
                                                           ↓
React/Mantine ← WebSocket/FastAPI ← RuleEngine → Home (FakeHome | McpHome)
                                          ↑                    ↓
                                   NVIDIA texto→regra     Altice MCP
```

## 3. Contratos — acordar primeiro

**Eventos Pydantic:**
```python
class ObjetoLevantado(BaseModel):
    tipo: Literal["objeto_levantado"]
    classe: Literal["caneca", "livro", "comando"]
    hora: datetime

class Presenca(BaseModel):
    tipo: Literal["presenca"]
    ha_alguem: bool
    hora: datetime
```

**Interface Home (assíncrona):**
```python
class Home(Protocol):
    async def definir_lampada(self, ligada: bool, cor: str | None, brilho: int | None) -> bool: ...
    async def definir_tomada(self, ligada: bool) -> bool: ...
    async def ler_consumo(self) -> float: ...
    async def estado(self) -> EstadoCasa: ...
```

Implementações `FakeHome` (memória) e `McpHome` (hardware). Regra JSON:

```json
{"id":"leitura","objeto":"livro","nome":"Modo leitura","acoes":[{"dispositivo":"lampada","ligada":true,"cor":"branco_quente","brilho":40},{"dispositivo":"tomada","ligada":true}]}
```

Endpoints lógicos do plano: `GET /video`, `WS /ws`, `GET /status`, `GET/POST/DELETE /rules`, `POST /rules/parse`, `POST /off`. **Implementados com prefixo `/api`** e com `ler_consumo() -> float | None`; ver [contratos.md](../../architecture/api-implementada.md).

## 4. Pessoa 1 — vídeo, visão, integração

- **1.1 RTSP:** `cv2.VideoCapture(url,cv2.CAP_FFMPEG)`, `OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"`, `CAP_PROP_BUFFERSIZE=1`. Thread que protege o último frame com Lock; medir atraso <1,5 s durante 10 min.
- **1.2 Recuperação e backup:** detetar ausência de frame em 3 s, reconectar com 1/2/4/8/10 s; `camara_ok`; ler clip MEARI em loop pela mesma interface; clip contendo os três gestos e saída de plano.
- **2.1 Objetos:** COCO 41 caneca, 73 livro e 65 comando, `conf=0.4`; livro é incerto, validar cedo (alternativas garrafa 39 ou telemóvel 67). Chaves não pertencem ao COCO.
- **2.2/2.3 Pose e tracking:** ombros 5/6, cotovelos 7/8, pulsos 9/10; pose também dá presença; `persist=True` e ByteTrack; objetivo ambos os modelos ≥10 FPS na GPU.
- **1.4 Vídeo anotado:** `GET /video` por `StreamingResponse` `multipart/x-mixed-replace` com caixas e esqueleto; browser usa `<img>`.
- **8.1–8.5 Integração/entregáveis:** arranque coordenado por FastAPI, HOME_BACKEND=fake|mcp, evento→luz <4 s; PDF 2 páginas até **18/11 19h**, pitch de 3 e 5 min, PPT, README, router próprio, perfil demo, clip reserva e 10 demonstrações seguidas.

## 5. Pessoa 2 — gestos e presença

- **3.1 Gesto:** objeto centrado a menos de 0,6 × largura de ombros de um pulso; pulso acima do cotovelo; ambos pontos com confiança >0,5. Disparar se válido em ≥80% dos frames na janela de 1 segundo; cooldown 3 s por classe. Limiares configuráveis.
- **3.2 Repetição:** emitir evento mesmo se modo já ativo; o motor ignora a ação e regista «já ativo».
- **3.3 Presença:** marcar falso após 3 s seguidos sem pessoas; marcar verdadeiro após 2 frames consecutivos com pessoa. Emitir só transições.
- **3.4 Ponte:** thread visão → event loop com `loop.call_soon_threadsafe(queue.put_nowait, evento)`.
- **3.5 Afinador:** script offline sobre clip; 10 levantamentos = 10 eventos; beber de caneca sem gesto completo = 0.

## 6. Pessoa 3 — interface e MCP

- **5.7 prioritário:** `FakeHome` totalmente funcional sem hardware, mesma interface Home.
- **5.1 Auth:** `streamablehttp_client` + `ClientSession` com API key e OAuth próprio (`mcp-client`; callback na porta 5434) em `connectors/altice_auth.py`: login interativo no host, renovação automática. Nunca divulgar tokens.
- **5.2 Descoberta:** registar nomes e schemas reais de `tools/list`, `GET_HOME_DEVICES`, `GET_DEVICE_DETAILS`, `UPDATE_DEVICE_CAPABILITIES` em `docs/mcp-capabilities.md`.
- **5.3 McpHome:** descobrir IDs ao arrancar, implementar quatro métodos, permitir apenas lâmpada/tomada e três tools autorizadas. Nunca alarme/segurança.
- **5.4 Consumo:** polling a cada 5 s, `ler_consumo()` devolve o último valor.
- **5.5 Falhas:** timeouts (implementado: abrir 10 s, ler 8 s, escrita com releituras 14 s), confirmar ações por leitura de volta; nunca repetir uma escrita de resultado incerto. Expor `mcp_ok`.

## 7. Pessoa 4 — motor, LLM, eventos

- **4.1 Regras:** validação Pydantic e persistência `rules.json`; defaults caneca→quente 30%, livro→leitura, comando→cinema azul/fraco.
- **4.2 Estados:** Inativo (arranque, off, 30 min suspenso), Ativo (gesto/regresso), Em espera (ausência; 180 s normal, 10 s demo), Suspenso (guardar/restaurar estado; luz e tomada off). Avisar com brilho 20% 5 s antes; trocar de modo por novo gesto; timers asyncio canceláveis.
- **4.3 Energia:** consumo W ao suspender, acumular W×h em Wh e EUR com tarifa configurável.
- **4.4–4.6:** linhas de registo em PT-PT para cada evento/ação; `events.jsonl` só texto; `pytest` de estados/temporizadores com FakeHome e relógio simulado.
- **6.1–6.3 NVIDIA:** modelo configurável e chave local; prompt inclui objetos/capacidades reais e schema; JSON Pydantic e uma correção em erro; pré-visualização descritiva via `POST /rules/parse`, sem guardar nem executar. Apenas `POST /rules` após aceitação.
  
## 8. Pessoa 5 — frontend

- **7.1:** `useHomeSocket` reconecta e gere estado em `WS /ws`.
- **7.2:** vídeo MJPEG, modo atual, estados da máquina, timer, presença, câmara e MCP, aviso processamento local.
- **7.3:** últimas 50 linhas do registo; Wh e euros estimados.
- **7.4:** listar/ativar/desativar/apagar regras; campo texto → proposta LLM → confirmação explícita antes de criar.
- **7.5:** botão desligar tudo `POST /off`; legibilidade à distância/projetor, contraste e foco acessível. Usar componentes Mantine existentes.

## 9. Riscos / planos B

| Risco | Plano B |
|---|---|
| OAuth MCP indisponível | mentor/token de serviço ou token válido de cliente suportado; nunca afirmar integração real sem prova |
| Pose ilegível a 2–3 m | zona alta de enquadramento sem pose, explicitamente assumida como fallback |
| Latência >5 s | stream secundário, diminuir buffer/modelo, ajustar janela de gesto |
| RTSP instável | clip gravado da MEARI e router próprio |
| Livro detectado <8/10 | garrafa ou telemóvel (documentar alteração) |
| NVIDIA 429 | regras pré-definidas continuam a funcionar; LLM é só configuração |

## 10. Extras — só após MVP estável

**E1 Sugestões de rotinas** (Pessoa 4 + UI Pessoa 5): padrões em `events.jsonl` na janela 7 dias; mesma hora em ≥4 dos últimos 5 dias, ou entrada→objeto <2 min repetida ≥4 vezes; trigger entrada/hora, texto LLM só explicativo; aceitar/ignorar; dados simulados de demo devem ser explicitamente rotulados. Nunca aplicar sem consentimento.

Outros: editor completo de regras, gestos de brilho em degraus de 25%, objeto ensinado por foto e cenários persistentes `POST_NEW_SCENARIO` (capacidade não validada).

## 11. Distribuição, integração e definição de feito

| Pessoa | Primeira entrega |
|---|---|
| 1 | RTSP estável, caixas e esqueleto |
| 2 | gestos e presença fiáveis no clip |
| 3 | FakeHome, depois MCP real com mudança da lâmpada |
| 4 | máquina de estados e testes com FakeHome |
| 5 | painel com WebSocket e dados simulados |

Começar por contratos e FakeHome, desenvolver os cinco módulos paralelamente, integrar cedo. Executar `make check`, testes unitários da lógica sem rede/hardware, e 10 demonstrações consecutivas antes de extras. Não eliminar a infraestrutura anterior só porque tem nome antigo; a migração do código pode ser incremental.
