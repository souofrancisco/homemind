# Gestos e presença (P2)

Lógica pura, sem router e sem I/O. `DetetorGesto` (#5) e `DetetorPresenca` (#6). Ponte e afinador vêm nas issues #7–#8.

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
- Ambiente: sem `uv`, `make check` não foi corrido; usado venv local + `ruff` + `pytest`.

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
- **Arranque com pessoa** gera `Presenca(True)` ao 2.º frame (estado inicial `False`); P4 deve tratar o evento inicial.
- **Ausência medida em tempo de frames reais**: um buraco entre frames > `visao_intervalo_max_s` (1 s) reinicia `t_primeiro_vazio=t` e os positivos. Câmara sem frames nunca desliga a casa; depois do buraco, a ausência conta 3 s a partir do primeiro frame vazio real.
- **Frames positivos separados por buraco** não são «consecutivos» (contador reiniciado).
- **Um frame positivo isolado** apaga a contagem de ausência (vazios intermitentes < 3 s nunca desligam); um falso negativo do detetor de pessoa só desliga a casa se durar 3 s seguidos.
- A ausência de 3 s é a do detetor; o «em espera» de 180 s (10 s no demo) é do motor de P4.
- **Integração:** P1 chama via `ProcessadorObjectOS` (#8), que corre presença antes de gesto. P4 consome `Presenca` pela fila (#7).
- **Pendente:** validar no clip MEARI real (P1 + afinador #8). Testes com dados SIMULADOS.
