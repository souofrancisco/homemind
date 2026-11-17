# Contratos partilhados ObjectOS (issue #1)

**Estado: PROPOSTA.** Só fica fechado depois de validado por P2, P3 e P4. Depois disso, qualquer mudança de assinatura é combinada primeiro.

Código em `app/backend/src/homemind/contracts/`. Só dados e interfaces: nenhuma lógica de gesto, presença, regras ou Home.

```text
FonteVideo ──FrameVideo──▶ visão (P1) ──FrameDeteccoes──▶ gestos/presença (P2) ──Evento──▶ motor (P4)
(video.py)                              (visao.py)                              (eventos.py)

motor (P4) ──Home──▶ FakeHome | McpHome (P3)        motor (P4) ──Status/MensagemWS/Regra──▶ UI (P5)
           (home.py)                                           (painel.py, regras.py)
```

## `video.py` — fonte de vídeo (P1)

`FonteVideo` é implementada pela câmara RTSP e pelo clip de reserva: `iniciar()`, `parar()`, `ultimo_frame() -> FrameVideo | None` (nunca bloqueia) e `camara_ok`.

`FrameVideo`: `imagem` (ndarray BGR do OpenCV), `indice` (contador da fonte; repetido = sem frame novo), `t` (`time.monotonic()` na captura). Frames só em memória.

## `visao.py` — detecções por frame (P1 → P2)

| Modelo | Campos |
|---|---|
| `FrameDeteccoes` | `indice`, `t`, `hora`, `largura`, `altura`, `objetos`, `pessoas` |
| `ObjetoDetetado` | `classe` (`caneca`/`livro`/`comando`), `confianca`, `caixa`, `track_id` |
| `PessoaDetetada` | `confianca`, `caixa`, `track_id`, `keypoints` (sempre 17), `kp(KP.PULSO_DIR)` |
| `Caixa` | `x1`, `y1`, `x2`, `y2`, propriedade `centro` |
| `Keypoint` | `x`, `y`, `confianca` |

Convenções:

- **Coordenadas** em píxeis do frame original, origem em cima à esquerda, **y cresce para baixo**: pulso acima do cotovelo é `pulso.y < cotovelo.y`. `largura`/`altura` vêm no frame para quem quiser normalizar.
- **Keypoints**: os 17 do COCO, na ordem do `yolo11s-pose.pt`; índices no enum `KP` (ombros 5/6, cotovelos 7/8, pulsos 9/10). Esquerda/direita são as da pessoa. Ponto não detetado vem com `confianca=0`.
- **Tempo**: `t` é monotónico em segundos — usar para a janela de 1 s, cooldown de 3 s e ausência de 3 s. `hora` (UTC) é só para registo.
- **`track_id`**: ID efémero do ByteTrack, `None` enquanto a track não estiver confirmada. Não identifica ninguém e não é persistido.
- **Classes**: `COCO_PARA_CLASSE = {41: caneca, 73: livro, 65: comando}`. Outras categorias COCO não chegam a P2. Se o livro falhar e trocarmos por garrafa/telemóvel (plano §9), muda-se aqui.
- Frame sem pessoas: `pessoas == ()`. A presença (P2) deriva daí; a visão não decide presença.
- Modelos imutáveis (`frozen`) e sem campos extra.

## `eventos.py` — eventos (P2 → P4)

Assinaturas do plano §3:

```python
ObjetoLevantado(tipo="objeto_levantado", classe, hora)
Presenca(tipo="presenca", ha_alguem, hora)   # só transições
```

`Evento` é a união discriminada por `tipo`; `evento_adapter.validate_json(...)` lê qualquer um dos dois (WS, `events.jsonl`).

## `simulacao.py` — dados SIMULADOS

Para testes e pipelines sem câmara: `pessoa_simulada(pulso_dir_levantado=...)`, `objeto_simulado(classe, centro)` e `sequencia_simulada(n, fps=, com_pessoa=, classe=, levantado=)`, que gera `FrameDeteccoes` determinísticos.

```python
from homemind.contracts.simulacao import sequencia_simulada

for frame in sequencia_simulada(20, fps=10, classe="caneca", levantado=True):
    ...  # P2: alimentar o detetor de gestos
```

## `home.py` — interface Home (P3 implementa, P4 usa)

```python
class Home(Protocol):
    async def definir_lampada(self, ligada: bool, cor: str | None, brilho: int | None) -> bool: ...
    async def definir_tomada(self, ligada: bool) -> bool: ...
    async def ler_consumo(self) -> float: ...   # W
    async def estado(self) -> EstadoCasa: ...
```

- `definir_*` devolve `True` só se a ação foi aplicada **e confirmada**; `cor`/`brilho` a `None` = não alterar.
- `EstadoCasa`: `lampada` (`ligada`, `cor`, `brilho` 0–100), `tomada` (`ligada`), `consumo_w` (ou `None`), `simulado` (`True` em FakeHome).
- `cor` é texto livre (ex.: `branco_quente`) até P3 documentar as capacidades reais em `docs/mcp-capabilities.md`.

## `regras.py` — regras (P4, editadas pela UI de P5)

`Regra`: `id` (minúsculas, dígitos, `_`/`-`), `objeto`, `nome`, `acoes` (≥1), `ativa` (por omissão `true`). Cada ação é `AcaoLampada` (`ligada`, `cor`, `brilho`) ou `AcaoTomada` (`ligada`), distinguidas por `dispositivo`. Qualquer outro dispositivo é rejeitado. O JSON de exemplo do plano §3 valida tal como está.

`PedidoRegra` (`texto`) e `PropostaRegra` (`regra`, `descricao`) são o corpo e a resposta de `POST /rules/parse`.

## `painel.py` — backend → frontend (P4 → P5)

- `Status` (`GET /status`): `camara_ok`, `mcp_ok`, `home_backend` (`fake` = SIMULADO, `mcp` = REAL).
- `WS /ws` envia mensagens discriminadas por `tipo`:
  - `MensagemEstado` (`tipo="estado"`): fotografia completa, ao ligar e a cada mudança — `estado` (`inativo`/`ativo`/`em_espera`/`suspenso`), `modo` (id da regra), `modo_nome`, `ha_alguem`, `segundos_para_suspender`, `status`, `casa`, `poupanca_wh`, `poupanca_eur`.
  - `MensagemRegisto` (`tipo="registo"`): uma `LinhaRegisto` (`hora`, `texto` em PT-PT). É também o formato de cada linha de `events.jsonl`.

## Gestos, presença e fila (P2) — semântica acordada na proposta

Interfaces: `Detetor` (`visao.py`, P1), `ProcessadorEventos` e `PublicadorEventos` (`eventos.py`, P2).

```text
Detetor.detetar(FrameVideo) ─▶ FrameDeteccoes ─▶ ProcessadorEventos.processar ─▶ PublicadorEventos.publicar ─▶ asyncio.Queue[Evento] ─▶ motor (P4)
```

- **Thread de visão (P1)** chama `detetar` e `processar` em série e entrega cada evento a `publicar`. O afinador offline usa as mesmas interfaces sobre o clip, sem fila.
- **Fila (P4)**: P4 cria a `asyncio.Queue[Evento]` (e o loop) no arranque e entrega-a a P2, que implementa `PublicadorEventos` com `loop.call_soon_threadsafe(fila.put_nowait, evento)`. Ordem preservada, sem bloquear. No encerramento P4 pára o consumo e P1 pára a thread; eventos já na fila podem ser descartados.
- **Só frames reais**: P1 só emite `FrameDeteccoes` para frames novos (`FrameVideo.indice` mudou). Com `camara_ok=False` não emite nada; P2 não infere ausência de pessoas sem frames, só `pessoas == ()` em frames reais durante 3 s.
- **Tempo**: janelas, cooldown (3 s por classe) e ausência (3 s) usam `t` monotónico; funcionam com fps variável. `hora` dos eventos = `frame.hora` do frame que confirmou o gesto/transição (UTC, com fuso).
- **Gesto**: um `ObjetoLevantado` por gesto confirmado, mesmo que o modo já esteja ativo (o motor ignora e regista «já ativo»). Várias pessoas: serve o pulso de qualquer uma, sem as identificar nem contar.
- **Presença**: estado inicial `ha_alguem=False`; a primeira transição para `True` (2 frames com pessoa) emite `Presenca(True)`, mesmo no arranque. Só transições são publicadas.
- **Formato de repetição offline**: um `FrameDeteccoes` por linha em JSON (`model_dump_json()`, sem imagens) permite afinar sem GPU nem câmara.
- **Limiares** em `core/config.py` (P2 acrescenta os campos: 0,6×ombros, confiança 0,5, 80 %/1 s, cooldown 3 s, ausência 3 s, 2 frames).

## Rotas e modelos (proposta; prefixos por confirmar)

| Rota | Entrada | Saída | Dono |
|---|---|---|---|
| `GET /video` | — | MJPEG `multipart/x-mixed-replace` | P1 |
| `WS /ws` | — | `MensagemEstado` \| `MensagemRegisto` | P4 |
| `GET /status` | — | `Status` | P4 |
| `GET /rules` | — | `list[Regra]` | P4 |
| `POST /rules` | `Regra` | `Regra` | P4 |
| `DELETE /rules/{id}` | — | 204 | P4 |
| `POST /rules/parse` | `PedidoRegra` | `PropostaRegra` | P4 |
| `POST /off` | — | `MensagemEstado` | P4 |

Nenhuma destas rotas existe ainda; este PR só define os modelos.

## Por decidir com a equipa

- ~~P2: `t` + `hora`; coordenadas em píxeis~~ — P2: servem ambos.
- P4: confirmar a ponte da fila e a presença inicial `False` descritas acima.
- P3: `cor` como texto livre ou lista fechada, depois da descoberta MCP? `ler_consumo()` sem leitura devolve `0.0` ou lança erro?
- P4: uma regra por objeto, ou várias com `ativa`? Ativar/desativar faz-se com `POST /rules` (substitui pelo `id`)?
- P4/P5: `MensagemEstado` completa a cada mudança chega para o temporizador, ou a UI precisa de ticks por segundo?
- P5: `POST /off` devolve o estado novo ou só 204?
