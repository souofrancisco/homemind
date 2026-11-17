# Gestos e presença (P2)

Lógica pura, sem router e sem I/O. `DetetorGesto` (#5) e `DetetorPresenca` (#6). Ponte (#7), processador e afinador offline (#8).

```python
from homemind.core.config import get_settings
from homemind.features.gestos.gesto import DetetorGesto
from homemind.features.gestos.parametros import ParametrosGesto

detetor = DetetorGesto(ParametrosGesto.de_settings(get_settings()))
eventos = detetor.processar(frame)  # tuple[ObjetoLevantado, ...]; hora = frame.hora
```

Limiares em `core/config.py` (bloco «P2 — gestos/presença»). Só se guarda `(t, válido)` por classe; nunca pessoas, caixas ou imagens.

## Algoritmo
Frame válido por classe: existe um objeto da classe e um pulso (esq. ou dir., de qualquer pessoa) com pulso, cotovelo e ambos os ombros com confiança > 0,5, `pulso.y < cotovelo.y` e distância centro-pulso < 0,6 × largura dos ombros. Dispara quando armado, com ≥ 1 s desde o primeiro frame válido, ≥ `gesto_min_frames` válidos e fração ≥ 80 % na janela; desarma e só rearma quando a fração desce abaixo de 80 %.

## Assunções e pontos de integração
- **Segurar o objeto = 1 evento.** Repetir exige baixar e levantar de novo; o evento repetido é emitido mesmo com modo ativo (P4 decide «já ativo»).
- **Cooldown consome o gesto.** Um gesto completo dentro do cooldown (3 s, por classe) não emite nem fica pendente: não dispara mais tarde só por continuar levantado. Classes diferentes têm cooldowns independentes.
- **Duração mínima = janela.** O evento sai ~1 s depois de o gesto começar (no frame que o confirma). Com 10 fps, um levantamento de 1,0 s dispara no 1.º frame seguinte; < 0,8 s nunca dispara.
- **Buraco entre frames** > `visao_intervalo_max_s` (1 s) limpa a janela e rearma. P1 deve emitir só frames reais com `t` monotónico (contrato).
- **`gesto_min_frames=3`** conta frames válidos; a fps < 3 o gesto nunca confirma. Config nova: `gesto_min_frames` e `visao_intervalo_max_s`.
- **Vários utilizadores:** qualquer pulso serve; não se conta nem identifica ninguém. P1 filtra pessoas por confiança.
- **Ombros obrigatórios:** ombro com confiança ≤ 0,5 (pessoa de perfil) invalida o frame (risco de falsos negativos; ver no clip real).
- **Beber:** só afinação por config; se o clip real der falsos positivos, propor critério extra (ex. pulso acima do ombro) à equipa.
- **Integração:** P1 chama `processar` por frame novo (via `ProcessadorObjectOS` em #8); P4 consome os eventos pela fila (#7).
- **Pendente:** validar 10/10 e 0 «beber» no clip MEARI real (P1 + afinador #8). Os testes usam dados SIMULADOS.
- Ambiente: `make check` corrido com sucesso (uv no venv local). O CI só corre `make check`, não `pytest`: correr `pytest` à parte.

## Presença binária (#6)

```python
from homemind.features.gestos.parametros import ParametrosPresenca
from homemind.features.gestos.presenca import DetetorPresenca

det = DetetorPresenca(ParametrosPresenca.de_settings(get_settings()))
eventos = det.processar(frame)  # tuple[Presenca, ...] (0 ou 1); hora = frame.hora
det.ha_alguem  # só leitura
```

Inicial `False`. Frame com pessoas: regresso confirmado após `presenca_frames_regresso` (2) frames positivos seguidos. Frame sem pessoas: ausência confirmada quando `t - t_primeiro_vazio >= presenca_ausencia_s` (3 s). Só transições. Só se guardam contadores e tempos.

### Assunções (presença)
- **Qualquer pessoa conta**, sem confiança mínima própria: P1 filtra pessoas por confiança antes de entregar. Nada de contagem, IDs ou caixas.
- **Arranque com pessoa** gera `Presenca(True)` ao 2.º frame (estado inicial `False`); P4 aceita-o (confirmado: a presença do motor começa desconhecida e o primeiro `Presenca`, `True` ou `False`, conta como transição).
- **Ausência medida em tempo de frames reais**: um buraco entre frames > `visao_intervalo_max_s` (1 s) reinicia `t_primeiro_vazio=t` e os positivos. Câmara sem frames nunca desliga a casa; depois do buraco, a ausência conta 3 s a partir do primeiro frame vazio real.
- **Frames positivos separados por buraco** não são «consecutivos» (contador reiniciado).
- **Um frame positivo isolado** apaga a contagem de ausência (vazios intermitentes < 3 s nunca desligam); um falso negativo do detetor de pessoa só desliga a casa se durar 3 s seguidos.
- A ausência de 3 s é a do detetor; o «em espera» de 180 s (10 s no demo) é do motor de P4.
- **Integração:** P1 chama via `ProcessadorObjectOS` (#8), que corre presença antes de gesto. P4 consome `Presenca` pela fila (#7).
- **Pendente:** validar no clip MEARI real (P1 + afinador #8). Testes com dados SIMULADOS.

## Ponte thread de visão -> asyncio (#7)

`ponte.py`: `PublicadorFila(loop, fila)` implementa `PublicadorEventos`; `PublicadorLista` guarda eventos (afinador, testes).

```python
# P4 cria a fila e guarda o loop em `Engine.iniciar()` (lifespan da feature `engine`,
# `app.state.engine`). P1 liga assim, depois de o motor arrancar:
engine = app.state.engine
publicador = PublicadorFila(engine.loop, engine.fila)   # fila sem limite, criada pelo motor
# equivalente: engine.publicar_de_thread(evento) (call_soon_threadsafe(fila.put_nowait, ...))
```

`publicar` faz `loop.call_soon_threadsafe(...)`: nunca bloqueia, preserva a ordem (FIFO) e não duplica. A fila e o loop são de P4; a thread de visão é de P1 (os testes usam mocks em `tests/_fakes.py`: `DetetorFalso`, `FonteVideoFalsa`, `ThreadVisaoFalsa`).

### Assunções (ponte)
- **Fila sem limite** (confirmado por P4: `asyncio.Queue()` do motor). Com `maxsize` e fila cheia, o evento é descartado com `logger.warning` (só o tipo).
- **Loop fechado** (`RuntimeError` no encerramento): descarta com `logger.debug` (só o tipo); a thread nunca recebe a exceção. Eventos pendentes no loop ao fechar perdem-se (contrato).
- **Encerramento:** P4 pára o consumo, P1 pára a thread (`threading.Event`); a ordem entre os dois é indiferente para a ponte. `engine.loop` é `None` antes de `iniciar()`: construir o publicador só depois do arranque do motor.
- **Ordem de lifespans:** a feature `gestos` não tem router nem lifespan, logo a ordem alfabética (`engine` < `gestos`) não a afeta. Quem arranca a thread de visão (P1, `features/video`) deve garantir que corre depois de `engine`.
- **Só se regista o tipo do evento**; nunca hora, classe, frames ou pessoas.
- **Pendente (integração):** `Detetor` real de P1 (ainda inexistente; `features/video` só tem `FonteVideo`) ligado a `ProcessadorObjectOS` (#8) na thread de visão. O consumidor e o lifespan de P4 já existem na `main`. Medição «atraso do WS com inferência real» só com o Detetor real; os testes usam inferência SIMULADA (300 ms).

## Processador e afinador offline (#8)

`ProcessadorObjectOS` (`processador.py`) implementa `ProcessadorEventos`: presença primeiro, depois gesto, devolve um tuplo ordenado. Ignora frames com `indice` repetido ou anterior. `ha_alguem` só leitura. Construção: `ProcessadorObjectOS.de_settings(get_settings())`.

`repeticao.py`: `ler_jsonl(caminho)` (ignora linhas vazias; `ValueError` com nº da linha se inválida) e `escrever_jsonl(frames, caminho) -> int`. Formato: uma `FrameDeteccoes` por linha (`model_dump_json()`), só metadados (caixas, keypoints, tempos); nunca imagens.

```bash
cd app/backend
.venv/bin/python -m homemind.features.gestos.afinador --jsonl data/clip.jsonl \
  --esperar caneca=4,livro=3,comando=3 --gesto-janela-s 1.2 --gesto-cooldown-s 3
```

- Fontes exclusivas: `--jsonl FICHEIRO` (funcional) ou `--video CLIP` (**pendente**: sai com código 2 e «Detetor real ainda não disponível (P1)»; ponto de extensão `_frames_de_video` em `afinador.py`). `--gravar-jsonl SAIDA` só com `--video`.
- Overrides por flag para todos os campos: `--gesto-*` (`distancia-max-ombros`, `confianca-min`, `janela-s`, `fracao-min`, `min-frames`, `cooldown-s`, `intervalo-max-s`) e `--presenca-*` (`ausencia-s`, `frames-regresso`, `intervalo-max-s`), partindo de `core/config.py`.
- Imprime cada evento (`t` relativo ao 1.º frame, `hora` ISO, tipo, classe/`ha_alguem`) e um resumo: frames, duração, fps médio e mínimo (pior intervalo), gestos por classe, transições de presença, parâmetros.
- `--esperar caneca=4,livro=3,comando=3[,presenca=N]`: código 1 com a diferença impressa se não bater; 0 se bater. Erro de leitura/fonte: código 2. `presenca=N` conta **todas** as transições (a 1.ª, a entrada inicial, incluída).
- Sem rede, sem dependências novas, nunca grava imagens.

### Privacidade
JSONL de clips reais pode conter keypoints de pessoas: manter fora do Git em `data/` (já no `.gitignore`, confirmado) ou noutro caminho local. No Git só fixtures sintéticas geradas nos testes.

### Assunções (#8)
- `ProcessadorObjectOS` é partilhado por thread de visão e afinador; sem lock (uma só thread chama).
- Frames ignorados por `indice` não contam para o resumo de eventos, mas contam para frames/fps do afinador.
- `--esperar` só compara as chaves indicadas.
- `--video`: liga-se em `_frames_de_video` (`afinador.py`); o afinador chamará o `Detetor` real de P1 sobre o clip e passará as `FrameDeteccoes` ao mesmo processador; assume `Detetor.detetar(FrameVideo) -> FrameDeteccoes` do contrato.

### Pendente de integração
| Pendente | Quem |
|---|---|
| `Detetor` real + `FonteVideo` de clip -> implementar `_frames_de_video` / `--video` | P1 |
| Validar 10/10 gestos e 0 «beber» no clip MEARI real (gravar JSONL com `--gravar-jsonl`, afinar limiares) | P1 + P2 |
| Instanciar `ProcessadorObjectOS.de_settings(get_settings())` na thread de visão e chamar `publicar` por evento | P1 |
| Ligar `PublicadorFila(engine.loop, engine.fila)` (ou `engine.publicar_de_thread`) ao arranque da thread de visão, depois de `engine` | P1 |

Os testes (10 levantamentos + 3 «beber» + saída/regresso) usam dados SIMULADOS; **não** validam o clip real.
