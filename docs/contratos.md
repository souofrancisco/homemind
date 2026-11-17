# Contratos partilhados — vídeo, visão e eventos (issue #1)

**Estado: PROPOSTA.** Só fica fechado depois de validado por P2, P3 e P4. Depois disso, qualquer mudança de assinatura é combinada primeiro.

Código em `app/backend/src/homemind/contracts/`. Só dados e interfaces: nenhuma lógica de gesto, presença, regras ou Home.

```text
FonteVideo ──FrameVideo──▶ visão (P1) ──FrameDeteccoes──▶ gestos/presença (P2) ──Evento──▶ motor (P4)
(video.py)                              (visao.py)                              (eventos.py)
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

## Por decidir com a equipa

- P2: `t` monotónico + `hora` chega, ou preferem só um relógio?
- P2: coordenadas em píxeis servem (a regra usa a largura dos ombros como escala) ou preferem normalizadas 0–1?
- P3/P4: a interface `Home` e o modelo de regra (plano §3) ficam em `contracts/` por PR dos respetivos donos.
