# Visão (P1) — detetor YOLO local (#4)

`DetetorYolo` (`detetor.py`) implementa o contrato `Detetor` (`contracts/visao.py`): por cada
`FrameVideo` devolve `FrameDeteccoes` com objetos (caneca, livro, comando) e pessoas (caixa +
17 keypoints COCO) com `track_id` efémero do ByteTrack. Corre **localmente**; o vídeo nunca sai da
máquina nem é guardado. A thread de visão (`thread.py`, #28) já o consome.

## Instalar (extra opcional)

O ultralytics traz o `torch` (centenas de MB), por isso fica fora da instalação base, do CI e do
Docker (`uv sync --frozen --no-dev` não o instala).

```bash
cd app/backend
uv sync --extra visao
uv run python -m homemind.features.visao.pesos            # descarrega yolo11s.pt + yolo11s-pose.pt
uv run python -m homemind.features.visao.pesos --variante n   # modelos n, se o FPS não chegar
```

Os pesos vão para `data/modelos/` (ignorado pelo Git; `*.pt` e `*.onnx` também). O arranque do
servidor e os testes **nunca descarregam**: sem pesos, `preparar()` levanta `FileNotFoundError` com
esta instrução e a thread de visão fica indisponível sem derrubar o servidor.

Ligar ao motor: `VIDEO_SOURCE=<rtsp ou clip>` e
`VISAO_DETETOR=homemind.features.visao.detetor:DetetorYolo`. O afinador aceita o mesmo
(`--detetor homemind.features.visao.detetor:DetetorYolo`).

## Configuração (`core/config.py`, bloco «P1 — visão»; variáveis `VISAO_*`)

| Variável | Omissão | Nota |
|---|---|---|
| `VISAO_PASTA_MODELOS` | `data/modelos` | |
| `VISAO_VARIANTE` | `s` | `n` = mais rápido, menos preciso |
| `VISAO_MODELO_OBJETOS` / `VISAO_MODELO_POSE` | vazio | vazio = `yolo11{variante}.pt` / `-pose.pt` |
| `VISAO_CONF_OBJETOS` / `VISAO_CONF_PESSOA` | 0.4 | |
| `VISAO_LIVRO_COCO` | 73 | se o livro falhar: 39 (garrafa) ou 67 (telemóvel) |
| `VISAO_DEVICE` | `auto` | CUDA > MPS > CPU; ou `cpu` / `mps` / `cuda:0` |
| `VISAO_IMGSZ` | 640 | |
| `VISAO_TRACKER` | `bytetrack.yaml` | |

## Comportamento a conhecer

- Dois modelos (objetos e pose), cada um com o seu ByteTrack (`track(persist=True)`). Objetos:
  categorias COCO 41/73/65 (o livro configurável); pose: só pessoas. Pose a 2-3 m pode perder
  pulsos: ver os limiares de gesto (P2).
- O ByteTrack só devolve tracks confirmadas: um objeto/pessoa que aparece só é emitido a partir do
  2.º frame em que é visto (~1 frame de atraso na aparição).
- `preparar()` (carregar modelos + aquecer com um frame preto) é idempotente; `detetar()` chama-o
  se for preciso. Na thread de visão isso acontece fora do event loop.
- `hora` do resultado é o instante de captura do frame (UTC), não o de fim de inferência.
- Telemetria do ultralytics desligada (`settings sync=False`); os resultados não incluem imagem.

## Licença

`ultralytics` e os pesos YOLO11 são **AGPL-3.0**. Usamo-los como dependência opcional num projeto
de hackathon; distribuir/oferecer o serviço em rede implica cumprir a AGPL (código-fonte
disponível). Está isolado no extra `visao` justamente para o resto do projeto não o exigir.

## OpenCV

`ultralytics` depende de `opencv-python` (com GUI), que colide com o `opencv-python-headless` do
projeto (ambos instalam o pacote `cv2`). Em `pyproject.toml`, `[tool.uv] override-dependencies`
anula `opencv-python`; fica só o headless (testado com OpenCV 5.0.0.93). O `lap` (ByteTrack) está
fixado no extra para o ultralytics não o tentar instalar com `pip` em runtime.

## Testes

`uv run pytest` (sem o extra): fakes de resultados e modelos; sem pesos, torch, rede ou hardware.
