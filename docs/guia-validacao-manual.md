# Guia de validação manual do ObjectOS

Tutorial passo a passo, replicável por uma pessoa, para decidir se o produto funciona para o utilizador final. Descreve **apenas o que existe na `main`**. O que ainda não existe está marcado «**Pendente (#N) — saltar por agora**», com o resultado esperado quando entrar.

Convenções: **SIMULADO** = FakeHome, clip ou evento injetado; **REAL** = câmara MEARI e/ou kit Altice via MCP. Nunca apresentar SIMULADO como REAL nas evidências.

Referências: `CLAUDE.md`, `docs/objectos-plano.md`, `app/backend/src/homemind/features/visao/README.md`, `app/backend/src/homemind/features/gestos/README.md`.

## Índice

0. Pré-requisitos, `.env` e privacidade
1. Instalação e arranque
2. Capítulos de teste
   - 2.1 Saúde e autenticação
   - 2.2 Vídeo MJPEG (`GET /api/video`)
   - 2.3 Deteção YOLO (objetos, pose, FPS)
   - 2.4 Gesto «objeto levantado»
   - 2.5 Presença
   - 2.6 Afinador offline
   - 2.7 Motor, modos e estados
   - 2.8 FakeHome vs MCP real
   - 2.9 Desligar tudo
   - 2.10 Interface (frontend)
   - 2.11 Regras e linguagem natural (NVIDIA)
   - 2.12 Latência gesto→luz
   - 2.13 Dez demos seguidas
   - 2.14 Privacidade
3. Folha de resultados
4. Checklist «pronto para a demo»

---

## 0. Pré-requisitos, `.env` e privacidade

### 0.1 O que é preciso

| Item | Para quê | Nota |
|---|---|---|
| Portátil com Python 3.12+ e [uv](https://docs.astral.sh/uv/) | backend | `uv --version` |
| Node 20+ e npm | frontend | `node --version` |
| Docker + Compose | `make dev` (stack completa com login) | opcional se só se testar o backend |
| GPU CUDA (ou Apple Silicon/MPS) | FPS ≥ 10 com `yolo11s` | sem GPU, documentar o FPS obtido e usar `VISAO_VARIANTE=n` |
| Câmara MEARI com RTSP **ou** um clip `.mp4` | fonte de vídeo | o clip é o plano B |
| Caneca, livro e comando de TV | objetos de teste | |
| Kit Altice (lâmpada + tomada) | só para a parte REAL | **Pendente (#11)**: `HOME_BACKEND=mcp` ainda não existe |
| 1 a 2 pessoas que dão consentimento | gravar o clip e testar | |

### 0.2 Privacidade, antes de começar

- O vídeo é processado **localmente** e nunca é enviado para NVIDIA/MCP, nem gravado em disco nem escrito em logs. Só saem metadados textuais.
- Sem identificação ou reconhecimento facial. As pessoas não são contadas nem identificadas.
- Quem aparece no vídeo deu consentimento. Clips e JSONL com pessoas ficam em `app/backend/data/` (ignorado pelo Git). Nunca em commits, issues, chats ou prints partilhados.
- Nenhum segredo real neste guia: usa os placeholders `<...>` e guarda os valores só no teu `app/.env` local.

### 0.3 Template de `.env`

Copia `app/.env.example` para `app/.env` (ficheiro ignorado pelo Git) e ajusta. Para o `uv run` fora do Docker, exporta as mesmas variáveis no terminal (ex.: `set -a; source ../.env; set +a`, a partir de `app/backend`).

```dotenv
APP_MODE=simulation
ENABLE_PHYSICAL_WRITES=false          # NÃO mudar neste guia

# Vídeo: UM dos dois. O RTSP contém credenciais: nunca colar em chats/prints.
VIDEO_SOURCE=data/clip.mp4            # ou rtsp://<utilizador>:<palavra-passe>@<ip-da-camara>/<caminho>

# Visão: só com `uv sync --extra visao` e pesos descarregados
VISAO_DETETOR=homemind.features.visao.detetor:DetetorYolo
VISAO_DEVICE=auto                     # auto = CUDA > MPS > CPU
VISAO_VARIANTE=s                      # n só se o FPS não chegar

# Motor ObjectOS
PROFILE=demo                          # demo: espera de 10 s em vez de 180 s
HOME_BACKEND=fake                     # mcp: Pendente (#11)
# NVIDIA_API_KEY=<a-tua-chave>        # só para o ponto 2.11; sem ela /api/rules/parse dá 503

# Login (Docker / make dev) usa os valores por omissão de app/compose.yaml
```

Limiares ajustáveis (todos em `app/backend/src/homemind/core/config.py`, nome em maiúsculas no `.env`): `GESTO_DISTANCIA_MAX_OMBROS` (0.6), `GESTO_CONFIANCA_MIN` (0.5), `GESTO_JANELA_S` (1.0), `GESTO_FRACAO_MIN` (0.8), `GESTO_MIN_FRAMES` (3), `GESTO_COOLDOWN_S` (3.0), `PRESENCA_AUSENCIA_S` (3.0), `PRESENCA_FRAMES_REGRESSO` (2), `VISAO_INTERVALO_MAX_S` (1.0), `VISAO_CONF_OBJETOS` / `VISAO_CONF_PESSOA` (0.4), `VISAO_LIVRO_COCO` (73), `VISAO_IMGSZ` (640), `VIDEO_FPS_MAX` (15), `VIDEO_JPEG_QUALIDADE` (80), `VIDEO_SEM_FRAME_S` (3.0), `VIDEO_TIMEOUT_ABRIR_MS` (5000).

Tempos do motor (`features/engine/config.py`): `PROFILE`, `ESPERA_S`, `AVISO_S` (5), `BRILHO_AVISO` (20), `SUSPENSO_MAX_S` (1800), `TARIFA_EUR_KWH` (0.16), `RULES_PATH`, `EVENTS_PATH`.

---

## 1. Instalação e arranque

### 1.1 Backend (sem Docker)

```bash
cd app/backend
uv sync --extra visao                                   # instala ultralytics/torch (grande)
uv run python -m homemind.features.visao.pesos          # único passo com download: yolo11s.pt + yolo11s-pose.pt
# uv run python -m homemind.features.visao.pesos --variante n   # modelos n, se o FPS não chegar
uv run uvicorn homemind.main:app --host 127.0.0.1 --port 8000
```

Esperado: `Uvicorn running on http://127.0.0.1:8000`. Se faltar `VISAO_DETETOR` ou `VIDEO_SOURCE`, o log diz «visão desligada: ...» e o servidor arranca na mesma (sem gestos). Se faltarem os pesos, o log diz «visão desligada: detetor indisponível» e indica o comando dos pesos. O arranque nunca descarrega nada.

Sem o extra `visao` (instalação base, só para os pontos que não precisam de YOLO): `uv sync`.

### 1.2 Stack completa (login + frontend)

```bash
make dev        # docker compose -f app/compose.yaml up --build
```

- Frontend: `http://localhost:5173` (porta `FRONTEND_PORT`). O Vite faz proxy de `/api` e `/healthz` para o backend.
- Backend: `http://localhost:8000` (porta `BACKEND_PORT`).
- Login: Authentik em `http://localhost:9000`. Utilizador de bootstrap definido em `app/compose.yaml` (`AUTHENTIK_ADMIN_EMAIL` / `AUTHENTIK_ADMIN_PASSWORD`; valores por omissão só de desenvolvimento).
- O backend em Docker **não** instala o extra `visao` (o `Dockerfile` usa `--no-dev`). Para testar visão real, corre o backend com `uv` (1.1) e o frontend com `npm run dev` em `app/frontend`.

### 1.3 Verificações automáticas antes de testar à mão

```bash
cd app/backend && uv run pytest -q          # lógica pura, FakeHome, fixtures SIMULADAS (sem hardware/rede)
make check                                  # lint + contratos OpenAPI + build + compose config
```

Esperado: tudo verde. Se falhar, não vale a pena começar a validação manual.

### 1.4 Obter um token para as chamadas de API

Todas as rotas `/api/*` do motor exigem `Authorization: Bearer <access token>` (Authentik). **`GET /api/video` e `/healthz` não exigem token.** Para os `curl` abaixo:

1. Abre o frontend, faz login.
2. DevTools do browser → Application → Storage → procura a chave `oidc.user:...` → copia `access_token`.
3. `export TOKEN=<access_token>` no terminal (expira; repete quando der 401).

Nunca coles o token em chats, issues ou prints.

---

## 2. Capítulos de teste

Em cada capítulo: **Objetivo → Preparação → Passos → Resultado esperado → Evidência → Se falhar**.

### 2.1 Saúde e autenticação

**Objetivo.** O backend está vivo e protegido.

**Passos.**
1. `curl -s http://localhost:8000/healthz`
2. `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/state` (sem token)
3. `curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/state`

**Esperado.**
1. `{"status":"ok","mode":"simulation","physical_writes":false}`. `physical_writes` tem de ser `false`.
2. `401`.
3. JSON `HomeState` com `state:"inativo"`, `backend:"fake"`, `mcp_ok:false`, `presence:null` (ainda sem dados da visão), `camera_ok` (`true` só se a fonte estiver a enviar frames), `casa` com `lampada` e `tomada` desligadas.

**Evidência.** Copiar as 3 respostas (sem o token) para a folha de resultados.

**Se falhar.** 401 com token: expirou, repete 1.4. Falha de rede: confirma portas no `.env`.

### 2.2 Vídeo MJPEG (`GET /api/video`)

**Objetivo.** O vídeo aparece com atraso < 1,5 s durante 10 min, sem gravar nada.

**Preparação.** `VIDEO_SOURCE` definido (clip ou RTSP). Backend a correr.

**Passos.**
1. Abre `http://localhost:8000/api/video` num browser (ou `<img src="/api/video">`). Se `VIDEO_SOURCE` estiver vazio, a resposta é 503 «Fonte de vídeo não configurada».
2. Confirma que a imagem se move em tempo real.
3. **Atraso:** põe à frente da câmara um cronómetro (telemóvel ou `https://time.is`), com o ecrã do browser ao lado no mesmo enquadramento da tua câmara de telemóvel. Tira 3 fotos/capturas em que se veja o cronómetro real e o cronómetro no vídeo. Atraso = diferença entre os dois. Repete aos 0, 5 e 10 min.
4. **Estabilidade do lado do backend (10 min):** com o servidor parado (a fonte é aberta pelo próprio comando):
   ```bash
   cd app/backend
   uv run python -m homemind.features.video.medir --minutos 10 --intervalo 10 --rotulo principal
   ```
   Imprime uma linha por intervalo (`fps`, `maior_intervalo`, `camara_ok`, `reconexoes`, `resolucao`) e um `RESUMO` final. Não grava frames nem imprime o URL.
5. **Clip em loop:** com `VIDEO_SOURCE=data/clip.mp4`, deixa correr mais tempo do que a duração do clip. O vídeo recomeça sem quebra e sem o servidor cair.
6. **Reconexão RTSP (só com câmara):** com o vídeo aberto, desliga a câmara da corrente (ou a rede Wi-Fi dela) durante ~15 s e volta a ligar.

**Esperado.**
- Passo 3: atraso < 1,5 s em todas as 3 medições.
- Passo 4: `quedas=0` (ou, se houver, recuperação automática), `fps_medio` próximo de `VIDEO_FPS_MAX`/da câmara, `maior_intervalo` sem picos de vários segundos.
- Passo 6: após ~3 s sem frames (`VIDEO_SEM_FRAME_S`) `camara_ok` passa a `false` (`GET /api/state`), o backend tenta reabrir com esperas 1, 2, 4, 8, 10 s e o vídeo volta sozinho, com `camara_ok:true`.
- Se a câmara estiver em baixo, o servidor **não cai**.

**Evidência.** 3 capturas com os dois cronómetros; o `RESUMO` do `medir`; nota do tempo de recuperação do passo 6.

**Se falhar.** Atraso alto: baixar `VIDEO_JPEG_QUALIDADE` ou `VIDEO_FPS_MAX`; verificar Wi-Fi da câmara/stream secundário de menor resolução; garantir transporte TCP (já é o padrão). Não abre: `VIDEO_TIMEOUT_ABRIR_MS`; confirmar o URL RTSP (sem o expor).

**Caixas e esqueleto no vídeo — esperado após o PR `feat/28-mjpeg-anotado` (ainda não está na `main`; saltar por agora).** Com `VISAO_DETETOR` definido, `/api/video` mostrará caixas dos objetos com classe e confiança, caixas das pessoas e esqueleto (só keypoints com confiança > 0,5), sem texto identificativo nem ID de track. Se a anotação falhar, deve aparecer a imagem crua (sem erro). Hoje `/api/video` mostra sempre a imagem sem anotações.

### 2.3 Deteção YOLO (objetos, pose, FPS)

**Objetivo.** Caneca, livro e comando são reconhecidos, pessoas com pose; ≥ 10 FPS com GPU. (Issue #4.)

**Preparação.** `uv sync --extra visao`, pesos em `app/backend/data/modelos/`, e um clip gravado com consentimento (ver 2.6, passo 1).

**Passos.**
1. Corre o afinador sobre o clip com o detetor real e grava as deteções:
   ```bash
   cd app/backend
   uv run python -m homemind.features.gestos.afinador --video data/clip.mp4 \
     --detetor homemind.features.visao.detetor:DetetorYolo --gravar-jsonl data/clip.jsonl
   ```
2. No resumo final lê `clip: <fps> fps  detetar: <ms> ms/frame`. FPS de inferência = 1000 / ms por frame.
3. Procura nos eventos impressos se cada objeto é detetado (ver 2.4). Até a anotação em `/api/video` existir (ver aviso em 2.2), a verificação visual das caixas **não** é possível; usa o JSONL (`data/clip.jsonl`, só metadados).
4. **Livro:** se o livro não for detetado de forma fiável, repete com `VISAO_LIVRO_COCO=39` (garrafa) ou `67` (telemóvel) e anota qual funcionou. Documenta a escolha.
5. **Modelo n:** se o FPS for < 10, `uv run python -m homemind.features.visao.pesos --variante n` e `VISAO_VARIANTE=n`; repete 1-2.

**Esperado.** `ms/frame` ≤ 100 (≥ 10 FPS) em GPU. Cada objeto de teste aparece nas deteções do JSONL. Sem GPU: regista o FPS real e o fallback usado (critério da issue #4: «≥10 FPS com GPU ou limitação e fallback documentados»).

**Evidência.** Linha `clip: ... detetar: ...` do resumo; hardware (GPU/MPS/CPU) e variante (`s`/`n`).

**Se falhar.** Pessoa não detetada de perfil/longe: `VISAO_CONF_PESSOA` mais baixo; objeto não detetado: `VISAO_CONF_OBJETOS` mais baixo ou `VISAO_IMGSZ` maior (mais lento). `FileNotFoundError` com instruções: faltam pesos.

### 2.4 Gesto «objeto levantado»

**Objetivo.** Levantar caneca, livro ou comando junto ao pulso, com a mão acima do cotovelo ~1 s, gera exatamente um evento; beber não gera nenhum. (Issue #5.)

**Preparação.** Câmara a 2-3 m, pessoa de frente com ombros visíveis. Ou o clip com os cenários abaixo. Critério de aceitação: 10 gestos → 10 eventos.

**Passos (ao vivo, com o backend ligado à visão).** Segue o registo em `GET /api/events` (ver 2.7) ou no ficheiro `app/backend/data/events.jsonl`. Para cada ensaio, anota o resultado.

| # | Ação | Esperado |
|---|---|---|
| 1-4 | Levantar a **caneca** ao pulso ~1 s, baixar, esperar > 3 s | 1 evento «Caneca levantado(a)» por levantamento |
| 5-7 | Levantar o **livro** | 1 evento «Livro levantado(a)» |
| 8-10 | Levantar o **comando** | 1 evento «Comando levantado(a)» |
| 11 | **Beber** da caneca (objeto à boca, sem levantar ao pulso) × 3 | 0 eventos |
| 12 | **Segurar** a caneca levantada 10 s | 1 evento (não repete) |
| 13 | Levantar a caneca 2× em < 3 s | só o 1.º conta (cooldown 3 s por classe) |
| 14 | Levantar caneca e, em seguida, livro | 2 eventos (cooldowns independentes por classe) |
| 15 | Levantar < 0,8 s | 0 eventos |

**Esperado.** 10/10 gestos válidos detetados e 0 falsos positivos em beber. O evento sai ~1 s depois do início do gesto.

**Evidência.** Tabela preenchida por ensaio; `events.jsonl` (sem imagens).

**Se falhar.** Gesto não dispara: `GESTO_DISTANCIA_MAX_OMBROS` ↑ (ex. 0.7), `GESTO_FRACAO_MIN` ↓ (0.75), `GESTO_JANELA_S` ↑ (1.2); verificar que ombros, cotovelo e pulso têm confiança > `GESTO_CONFIANCA_MIN` (pessoa de perfil invalida o frame). Falsos positivos ao beber: `GESTO_DISTANCIA_MAX_OMBROS` ↓, `GESTO_FRACAO_MIN` ↑; se persistir, propor critério extra à equipa. Afinar sempre offline (2.6) antes de voltar ao vivo. A FPS < 3 o gesto nunca confirma (`GESTO_MIN_FRAMES`).

### 2.5 Presença

**Objetivo.** Há alguém / não há ninguém, sem ruído. (Issue #6.)

**Passos.**
1. Entra no enquadramento. Verifica `presence` em `GET /api/state` ou o evento «Entrou alguém na divisão».
2. Sai do enquadramento > 3 s. Esperado: `presence:false`, evento «Divisão vazia».
3. Regressa: `presence:true` ao fim de 2 frames positivos (< 1 s).
4. Sai e volta em < 3 s (ou tapa a câmara 1 s): **não** deve haver «Divisão vazia».
5. Ao arrancar com pessoa já na imagem: `presence` passa de `null` a `true` (1.º evento conta como transição).

**Esperado.** Só transições geram evento; nunca contagem nem identificação. Perdas breves não desligam a casa (só ausência contínua ≥ `PRESENCA_AUSENCIA_S`).

**Evidência.** Linhas do registo com a hora; cronometrar o passo 2 (≈ 3 s).

**Se falhar.** Muito ruído: `PRESENCA_AUSENCIA_S` ↑ ou `VISAO_CONF_PESSOA` ↑. Demora a regressar: `PRESENCA_FRAMES_REGRESSO`.

### 2.6 Afinador offline

**Objetivo.** Reproduzir um clip/JSONL e afinar limiares sem tocar na câmara. (Issue #8: 10/10 e 0 falsos positivos no clip de referência.)

**Preparação.** Grava o clip (consentimento; fora do Git), p. ex. `app/backend/data/clip.mp4`: 10 levantamentos (4 caneca, 3 livro, 3 comando), 3 «beber» e uma saída > 3 s com regresso.

**Passos.**
1. `uv run python -m homemind.features.gestos.afinador --help` lista todas as flags: `--jsonl`, `--video` (exclusivas), `--detetor modulo:Classe`, `--gravar-jsonl`, `--esperar`, `--gesto-*`, `--presenca-*`.
2. Gravar deteções do clip:
   ```bash
   uv run python -m homemind.features.gestos.afinador --video data/clip.mp4 \
     --detetor homemind.features.visao.detetor:DetetorYolo \
     --gravar-jsonl data/clip.jsonl --esperar caneca=4,livro=3,comando=3,presenca=3
   ```
   (`presenca=3` = entrada inicial + saída + regresso.)
3. Afinar sem voltar a correr a visão:
   ```bash
   uv run python -m homemind.features.gestos.afinador --jsonl data/clip.jsonl \
     --esperar caneca=4,livro=3,comando=3,presenca=3 \
     --gesto-distancia-max-ombros 0.7 --gesto-fracao-min 0.75
   ```
4. Fixar os valores finais em `.env` (`GESTO_*`, `PRESENCA_*`).
5. Verificar erros: `--video` sem `--detetor` → sai com mensagem «Detetor real ainda não disponível...» e código 2; clip inexistente → código 2.

**Esperado.** Cada evento impresso como `t=...s hora=... objeto_levantado classe=...`, seguido do resumo (frames, fps médio/mínimo, gestos por classe, transições de presença, parâmetros). **Códigos de saída:** `0` = ok (ou sem `--esperar`); `1` = contagens diferentes de `--esperar` (a linha `DIFERENÇAS:` mostra o quê); `2` = erro de leitura/detetor. Alvo: código `0` com 10/10 e 0 falsos positivos.

**Evidência.** Saída completa do último comando com código 0, e o `echo $?`.

**Se falhar.** Ver «Se falhar» de 2.4 e 2.5.

### 2.7 Motor, modos e estados

**Objetivo.** O modo ativa-se, não se repete, troca com outro objeto, passa a Em espera/Suspenso na ausência e restaura ao regressar. Funciona **sem câmara**, com eventos SIMULADOS.

**Preparação.** `PROFILE=demo`, `HOME_BACKEND=fake`. Regras predefinidas: caneca → «Modo pausa» (luz branco quente 30%), livro → «Modo leitura» (luz 40% + tomada ligada), comando → «Modo cinema» (luz azul 10% + tomada ligada).

**Injetar eventos SIMULADOS** (marcados `[SIMULADO]` no registo):
```bash
curl -s -X POST localhost:8000/api/simulate -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"tipo":"objeto_levantado","classe":"caneca","hora":"2026-11-18T10:00:00Z"}'
curl -s -X POST localhost:8000/api/simulate -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"tipo":"presenca","ha_alguem":false,"hora":"2026-11-18T10:01:00Z"}'
```
Ler o estado: `GET /api/state`; histórico: `GET /api/events?limit=50`.

**Passos e esperado.**

| # | Ação | Esperado em `/api/state` e no registo |
|---|---|---|
| 1 | Simular caneca | `state:"ativo"`, `mode:"pausa"`, lâmpada ligada branco_quente 30%; «[SIMULADO] «Modo pausa» ativado» |
| 2 | Simular caneca outra vez | sem mudança; ««Modo pausa» já está ativo; nada a fazer» |
| 3 | Simular livro | troca: `mode:"leitura"`, lâmpada 40%, tomada ligada |
| 4 | Simular presença `false` | `state:"em_espera"`, `waiting_remaining_seconds` a descer de 10 (profile demo) |
| 5 | Aos 5 s da espera (10 s − `AVISO_S`) | luz baixa para `BRILHO_AVISO` (20%): «Aviso: luz a 20%, suspende em 5 s» |
| 6 | Aos 10 s | `state:"suspenso"`, lâmpada e tomada desligadas; «Suspenso: luz e tomada desligadas (... W)» |
| 7 | Simular presença `true` (estando suspenso) | `state:"ativo"`, estado anterior restaurado (luz e tomada como estavam); «Regresso: estado anterior restaurado» |
| 8 | Repetir 4 e regressar a meio da espera (antes do aviso) | «Regresso: modo mantido», sem mexer na luz |
| 9 | Regressar durante o aviso (luz a 20%) | brilho original reposto |
| 10 | Ficar suspenso 30 min (`SUSPENSO_MAX_S`; para acelerar, `SUSPENSO_MAX_S=60`) | `state:"inativo"`: «Suspenso há demasiado tempo: inativo» |
| 11 | Simular objeto sem regra ativa | «Sem regra ativa para ...; ignorado» |

**Energia.** Em suspensão a poupança acumula: `energy_saved_wh` e `energy_saved_eur` (Wh = W × horas; EUR = Wh/1000 × `TARIFA_EUR_KWH`) sobem em `GET /api/state` enquanto suspenso. A estimativa é do FakeHome (60 W na tomada ligada): SIMULADO.

**WebSocket.** `WS /api/ws`: primeira mensagem `{"type":"auth","token":"<TOKEN>"}` (nunca no URL); depois chega logo `home_state` e, a cada mudança, `home_state` e `event`. Testa com `websocat`/browser; sem auth em 5 s recebe `{"type":"error","data":{"code":"unauthorized"}}` e fecha.

**Evidência.** Saída de `GET /api/events` após a sequência.

**Se falhar.** Tempos errados: confirmar `PROFILE=demo` (ou `ESPERA_S`).

### 2.8 FakeHome vs MCP real

**Objetivo.** Distinguir sempre SIMULADO de REAL.

**Passos.** `GET /api/status` devolve `{camera_ok, mcp_ok, backend, updated_at}`.

**Esperado hoje (FakeHome).** `backend:"fake"`, `mcp_ok:false`. Com `HOME_BACKEND=fake` a lâmpada e a tomada são simuladas em memória: nada acende fisicamente. Qualquer relato de «a luz acendeu» com este modo é falso: é SIMULADO.

**Pendente (#11) — saltar por agora.** `HOME_BACKEND=mcp` ainda falha no arranque («McpHome ainda não disponível (#11)»). Quando existir: `backend:"mcp"`, `mcp_ok:true` após descoberta e confirmação do estado, escritas só em lâmpada e tomada, timeout 5 s, no máximo 1 retry (nunca retry cego se o resultado for desconhecido) e `ENABLE_PHYSICAL_WRITES` só ligado com consentimento operacional. Registar o resultado como **REAL** com fotografia do kit.

### 2.9 Desligar tudo

**Objetivo.** Desligar lâmpada e tomada manualmente, a qualquer momento.

**Passos.** Com um modo ativo (2.7 passo 1/3): `curl -s -X POST localhost:8000/api/off -H "Authorization: Bearer $TOKEN"`.

**Esperado.** HTTP 200 com `success:true`, `state:"inativo"`, `devices:{lampada:"off", tomada:"off"}`, `backend:"fake"`. Em `GET /api/state` lâmpada e tomada desligadas e `mode:null`; registo «Desligar tudo (manual)». Se algum dispositivo falhar: `success:false` com `code` (`partial_failure` / `mcp_unavailable`) e `devices` com `unknown`: nunca falso sucesso.

**Botão na interface: Pendente (#27) — saltar por agora.** Esperado: botão destacado «Desligar tudo» que chama `POST /api/off` e mostra o resultado real (incluindo falha parcial).

### 2.10 Interface (frontend)

**Hoje na `main`** (`app/frontend/src`): login OIDC (Authentik), ecrã **Início** (Mantine) com «Olá, <nome>», cartão **Backend** com o estado (`ok · simulation` em badge amarelo; verde se `real`; «Indisponível» a vermelho se o backend falhar) e o texto «Sem estadias ou espaços por mostrar», e ecrã **Conta**. Há tema claro/escuro.

**Passos.**
1. Abre `http://localhost:5173`; és redirecionado para o login; entra.
2. Confirma o cartão Backend: `ok · simulation`.
3. Pára o backend: o cartão deve mostrar «Indisponível» (após recarregar).
4. Abre **Conta** e termina a sessão.

**Pendente — saltar por agora** (ainda não existe nenhum destes ecrãs/componentes):
- **#24** hook `useHomeSocket` (WS com reconexão, estados loading/offline): esperado, o dashboard atualiza sem refresh com eventos simulados e mostra «offline» ao perder o WS, reconectando sozinho.
- **#25** painel com `<img src="/api/video">`, modo, contagem de Em espera, estados, presença (há alguém/não há ninguém), `camera_ok`/`mcp_ok`, aviso «câmara ativa/processamento local» e origem FAKE/REAL legível. Esperado: visível no projetor, responsivo, erros honestos sem dados falsos.
- **#26** registo (até 50 linhas), poupança Wh/EUR, lista de regras (ativar/desativar/apagar) e editor em linguagem natural.
- **#27** botão «Desligar tudo», alto contraste, navegação por teclado.

Nota: o título ainda diz «HomeMind» e `make smoke` procura «HomeMind Spaces»; não é um defeito do ObjectOS a reportar neste guia.

### 2.11 Regras e linguagem natural (NVIDIA)

**Objetivo.** Gerir regras; a pré-visualização não grava nem executa nada.

**Passos.**
1. `GET /api/rules` → 3 regras predefinidas (pausa, leitura, cinema).
2. `POST /api/rules/parse` com `{"text":"Quando levantar o comando, liga a luz azul a 10%"}`.
3. Confirma que `GET /api/rules` **não mudou**.
4. Guarda explicitamente com `POST /api/rules` (corpo = `proposal`) → 201. `PATCH /api/rules/<id>` com `{"enabled":false}` desativa; `DELETE /api/rules/<id>` → 204.
5. Sem `NVIDIA_API_KEY`: o passo 2 devolve 503 `nvidia_unavailable`, e o resto continua a funcionar.

**Esperado.** `parse` devolve `proposal`, `summary` em PT-PT («Ao levantar o comando, ativa «...»: ...») e `replaces` (regra que seria substituída); nada é guardado. Ativar uma regra desativa as outras do mesmo objeto. Regras ficam em `app/backend/data/rules.json`. Pedido fora de âmbito (ex. alarme): 400 `rule_not_supported`. O texto enviado à NVIDIA é só o pedido escrito; nunca vídeo nem frames.

**Evidência.** Respostas HTTP e `rules.json` antes/depois.

Interface do editor: **Pendente (#26)**.

### 2.12 Latência gesto→luz

**Objetivo.** Gesto → luz < 4 s.

**Ao vivo (SIMULADO com FakeHome, ou REAL após #11).**
1. Liga a visão (1.1) com `PROFILE=demo`. Abre `GET /api/state` em ciclo (`watch -n 0.5 curl ...`) ou o WS.
2. Filma com um telemóvel o gesto e o ecrã/lâmpada. Mede do início do gesto (mão a levantar) até `lampada.ligada:true`.
3. Repete 10 vezes.

**Esperado.** Tempo ≈ 1 s (janela do gesto) + inferência + motor: < 4 s em todas. Com FakeHome mede-se o software; o REAL (lâmpada física) só depois de **#11**.

**Evidência.** Vídeo do telemóvel/tempos por ensaio; indicar SIMULADO ou REAL.

**Se falhar.** Reduzir `GESTO_JANELA_S` (mais falsos positivos), `VISAO_VARIANTE=n`, GPU.

Uma ferramenta automática de medição de latência (`medir_latencia`) é opcional e **pode não estar na `main`**: se `python -m homemind.features.visao.medir_latencia --help` não existir, usa a medição manual.

### 2.13 Dez demos seguidas

**Objetivo.** 10 demos completas consecutivas sem falhas (issue #28).

**Demo completa** (cada uma): arrancar o servidor limpo → pessoa entra → levantar caneca (modo pausa) → trocar para livro (modo leitura) → sair > 3 s → Em espera → Suspenso (luz e tomada desligadas) → regressar (estado restaurado) → **desligar tudo** (`POST /api/off`) → `state:"inativo"`.

**Passos.** Executa as 10 demos seguidas; sem corrigir nada entre elas. Anota hora, SIMULADO/REAL, falhas.

**Esperado.** 10/10 completas; uma falha reinicia a contagem. `/api/off` sempre `success:true` (FakeHome). Plano B: se a câmara falhar, `VIDEO_SOURCE` para o clip em loop e/ou eventos via `/api/simulate` (marcados `[SIMULADO]`).

### 2.14 Privacidade

**Objetivo.** Provar que nada de imagem ou pessoal é gravado ou enviado.

**Passos.**
1. Depois de uma sessão com pessoas: `find app/backend/data -newer app/.env -type f` e `ls -la app/backend/data`. Só devem existir pesos (`modelos/*.pt`), `rules.json`, `events.jsonl` e, se criados por ti, o clip e o JSONL.
2. `file app/backend/data/events.jsonl` e `head app/backend/data/events.jsonl`: só texto («Caneca levantado(a)», «Divisão vazia»...). Nenhuma imagem, nome, ID de pessoa.
3. `grep -ri "rtsp://" app/backend/data` e nos logs do servidor: 0 resultados. A password da câmara nunca aparece.
4. `grep -rEi "(jpg|jpeg|png)" app/backend/data`: sem frames guardados.
5. `git status` na raiz: `app/.env`, `data/`, clips e pesos não aparecem como alterados/novos.
6. Tráfego: confirma que o vídeo só é servido em `GET /api/video` na tua máquina (rede local) e que a única chamada externa é a NVIDIA no `rules/parse`, só com texto.
7. Confirma que `GET /healthz` mostra `physical_writes:false`.

**Esperado.** Tudo conforme acima. Qualquer frame/URL/token em disco, log ou Git = falha crítica.

---

## 3. Folha de resultados

Preencher durante a validação. Data/hora, testador, hardware (GPU/CPU), fonte (clip/RTSP), SIMULADO ou REAL.

| # | Teste | Esperado | Obtido | OK/KO | Notas / evidência |
|---|---|---|---|---|---|
| 1 | `pytest -q` e `make check` | verdes | | | |
| 2 | `/healthz` e 401 sem token | `physical_writes:false`; 401 | | | |
| 3 | Atraso do vídeo aos 0/5/10 min | < 1,5 s | | | |
| 4 | `medir --minutos 10` | `quedas=0` | | | |
| 5 | Clip em loop | sem quebra | | | |
| 6 | Reconexão RTSP | recupera sozinho | | | |
| 7 | FPS de inferência (GPU) | ≥ 10 | | | |
| 8 | Caneca / livro / comando detetados | 3/3 | | | |
| 9 | 10 gestos válidos | 10 eventos | | | |
| 10 | Beber × 3 | 0 eventos | | | |
| 11 | Segurar / cooldown 3 s / troca de objeto | 1 / 1 / 2 eventos | | | |
| 12 | Presença: sair > 3 s e regressar | false → true | | | |
| 13 | Presença: perda breve | sem desligar | | | |
| 14 | Afinador `--esperar` | código 0 | | | |
| 15 | Motor: ativar, já ativo, trocar | conforme 2.7 | | | |
| 16 | Em espera, aviso, Suspenso, restaurar | conforme 2.7 | | | |
| 17 | Energia Wh/EUR a subir em suspensão | sim | | | |
| 18 | `/api/off` | `success:true`, tudo off | | | |
| 19 | Regras: parse sem gravar; guardar; apagar | conforme 2.11 | | | |
| 20 | Latência gesto→luz (10 ensaios) | < 4 s | | | |
| 21 | 10 demos completas seguidas | 10/10 | | | |
| 22 | Privacidade (2.14) | nada gravado | | | |
| 23 | Interface Início/Conta | conforme 2.10 | | | |
| 24 | WS no React (#24), painel (#25), regras (#26), botão (#27) | Pendente | n/a | | |
| 25 | Anotações no vídeo (PR `feat/28-mjpeg-anotado`) | Pendente | n/a | | |
| 26 | McpHome REAL (#11) | Pendente | n/a | | |

## 4. Checklist «pronto para a demo»

- [ ] `pytest -q` e `make check` verdes na `main`
- [ ] `ENABLE_PHYSICAL_WRITES` e `physical_writes` mostram `false` (salvo decisão operacional explícita)
- [ ] Vídeo com atraso < 1,5 s durante 10 min (ensaio 3 e 4)
- [ ] FPS ≥ 10 com GPU, ou limitação e fallback (`n`) documentados
- [ ] 10/10 gestos válidos e 0 falsos positivos ao beber (ensaios 9 e 10; afinador código 0)
- [ ] Presença estável (ensaios 12 e 13)
- [ ] Máquina de estados completa com `PROFILE=demo` (ensaios 15 a 17)
- [ ] `/api/off` fiável (ensaio 18)
- [ ] Latência gesto→luz < 4 s (ensaio 20), indicando SIMULADO ou REAL
- [ ] 10 demos seguidas sem falhas (ensaio 21)
- [ ] Privacidade verificada (ensaio 22): sem frames, sem RTSP nos logs, sem segredos no Git
- [ ] Plano B testado: clip em loop em `VIDEO_SOURCE` e `/api/simulate`, sempre marcado SIMULADO
- [ ] Clip e JSONL com pessoas fora do Git, com consentimento
- [ ] Itens «Pendente» assumidos no pitch (UI #24-#27, McpHome #11, anotações no vídeo), sem os mostrar como feitos
