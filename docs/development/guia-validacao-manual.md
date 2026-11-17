# Guia de validação manual — roteiro oficial

> **Nota (Conta Certa):** guia herdado do ObjectOS. **Continuam válidos:** blocos A (arranque, login), B (API, WebSocket), E (MCP), F (vídeo e RTSP, YOLO de pessoas), PRIV-01 e as regras de evidência. **Só do ObjectOS (não aplicáveis ao produto novo):** bloco D (motor, regras, NVIDIA, «Desligar tudo»), bloco G (gestos), POSE-01, LAT-01/02 e DEMO-01/PB-01 na forma atual. Os testes manuais da Conta Certa (leituras, confirmações, recibos) serão acrescentados quando existirem ([mvp.md](mvp.md)). Só se marca PASS o que foi executado.

Roteiro dos testes a executar à mão. Os testes automáticos (`make check`, `make smoke`) não o substituem: validam a lógica com simulações, não o hardware.

**Regras**

- Só se marca **PASS** um teste executado nesse dia, com evidência anotada. Não executado = em branco.
- Indicar sempre **REAL** (câmara, kit, serviços reais) ou **SIMULADO** (FakeHome, clip, cenários).
- Nunca colar tokens, URL RTSP, chaves ou IDs de dispositivos em chats, issues ou prints.
- Testes com escrita física (marcados ⚠️): uma pessoa de cada vez, com a lâmpada/tomada à vista, e `make mcp-writes-off` no fim.
- Quem aparece em vídeo deu consentimento; clips e JSONL com pessoas ficam em `app/backend/data/` (fora do Git).

## Índice

| Bloco | Testes |
|---|---|
| [A. Arranque e login](#a-arranque-e-login) | INS-01, AUTH-01, AUTH-02 |
| [B. API e tempo real](#b-api-e-tempo-real) | API-01, API-02, WS-01, WS-02 |
| [C. Painel](#c-painel) | UI-01, UI-02 |
| [D. Motor, regras e NVIDIA](#d-motor-regras-e-nvidia) | MOT-01, MOT-02, REG-01, NV-01, OFF-01 |
| [E. MCP Altice](#e-mcp-altice) | MCP-01 … MCP-07 |
| [F. Vídeo e visão](#f-vídeo-e-visão) | VID-01, VID-02, VID-03, YOLO-01, YOLO-02, POSE-01, TRK-01 |
| [G. Gestos e presença](#g-gestos-e-presença) | GES-01, GES-02, PRE-01 |
| [H. Demo](#h-demo) | LAT-01, LAT-02, DEMO-01, PB-01, PRIV-01 |
| [Folha de resultados](#folha-de-resultados) | tabela para preencher |

## Preparação comum

```bash
cp app/.env.example app/.env     # se ainda não existir
make check                       # tem de estar verde antes de começar
```

**Token para `curl`** (expira em 10 min; repetir quando der 401): com sessão iniciada no painel, DevTools → Application → Session Storage → chave `oidc.user:…:homemind` → copiar `access_token`.

```bash
export TOKEN='<access_token>'
export API=http://localhost:8000
auth() { curl -s -H "Authorization: Bearer $TOKEN" "$@"; }
```

---

## A. Arranque e login

### INS-01 — Instalação e arranque em FakeHome
- **Issue:** #28, #29 · **Tipo:** SIMULADO
- **Pré-requisitos:** Docker, `make`; `app/.env` copiado do exemplo, sem alterações.
- **Passos:** `make dev`; esperar os serviços; `curl -s localhost:8000/healthz`.
- **Esperado:** `{"status":"ok","backend":"fake","physical_writes":false}`; painel abre em <http://localhost:5173>; log do backend com «visão desligada: falta VISAO_DETETOR e/ou VIDEO_SOURCE» e sem erros.
- **Evidência:** saída do `curl` e hora.
- **PASS** se os três pontos se verificarem sem editar nada além do `.env`. **FAIL** caso contrário.

### AUTH-01 — Login e logout no Authentik
- **Issue:** #24 · **Tipo:** REAL (Authentik local)
- **Pré-requisitos:** INS-01.
- **Passos:** abrir o painel; iniciar sessão com `akadmin` / `homemind-dev` (ou a palavra-passe de `AUTHENTIK_ADMIN_PASSWORD`); abrir **Perfil**; terminar sessão; tentar abrir `/events`.
- **Esperado:** depois do login volta à página pedida; **Perfil** mostra o utilizador; depois do logout qualquer página pede login outra vez.
- **Evidência:** nome mostrado no Perfil.
- **PASS** se login, perfil e logout funcionarem. **FAIL** se ficar em ciclo de redirecionamentos ou entrar sem login.

### AUTH-02 — A API recusa pedidos sem sessão
- **Issue:** #24 · **Tipo:** REAL
- **Passos:**
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" $API/api/state
  curl -s -o /dev/null -w "%{http_code}\n" $API/api/video
  curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer lixo" $API/api/rules
  auth -o /dev/null -w "%{http_code}\n" $API/api/me
  ```
- **Esperado:** `401`, `401`, `401`, `200`.
- **PASS** se os quatro códigos coincidirem. **FAIL** se alguma rota `/api/*` responder sem token.

## B. API e tempo real

### API-01 — Leituras REST
- **Issue:** #25 · **Tipo:** SIMULADO ou REAL (indicar `backend`)
- **Passos:** `auth $API/api/status`; `auth $API/api/state`; `auth "$API/api/events?limit=5"`; `auth $API/api/rules`.
- **Esperado:** `status` e `state` com o mesmo `backend`; `state.state` é `inativo` após arranque; `rules` contém `pausa`, `leitura`, `cinema`; eventos só com `id, timestamp, level, message, source`.
- **PASS** se tudo coincidir. **FAIL** se faltar um campo ou vier um campo com imagem/dados pessoais.

### API-02 — Erros no formato único
- **Issue:** #23 · **Tipo:** SIMULADO
- **Passos:**
  ```bash
  auth -X PATCH -H 'Content-Type: application/json' -d '{"enabled":true}' $API/api/rules/nao-existe
  auth -X POST -H 'Content-Type: application/json' \
    -d '{"id":"x","objeto":"livro","nome":"n","acoes":[{"dispositivo":"lampada","ligada":true,"brilho":500}]}' $API/api/rules
  ```
- **Esperado:** `{"error":{"code":"rule_not_found",…}}` (404) e `{"error":{"code":"invalid_request","message":"Pedido inválido (…brilho)"}}` (400). A regra `x` não aparece em `GET /api/rules`.
- **PASS** se ambos vierem no envelope `error` e nada for gravado.

### WS-01 — Estado em tempo real
- **Issue:** #24 · **Tipo:** SIMULADO
- **Pré-requisitos:** `HOME_BACKEND=fake`, sessão iniciada.
- **Passos:** abrir o painel com DevTools → Network → WS → `ws`; na página **Câmara**, executar o cenário do livro.
- **Esperado:** 1.ª mensagem enviada `{"type":"auth",…}`; recebe `home_state`; depois do cenário chegam `event` e um `home_state` com `state:"ativo"`, `mode:"leitura"`. O URL do WebSocket **não** contém o token.
- **PASS** se a sequência e a ausência de token no URL se verificarem.

### WS-02 — Reconexão
- **Issue:** #24 · **Tipo:** SIMULADO
- **Passos:** com o painel aberto, `docker compose -f app/compose.yaml restart backend`; observar; esperar o backend voltar.
- **Esperado:** indicador offline em poucos segundos; religa sozinho (até ~15 s depois de o backend estar pronto) e mostra o estado atual, sem recarregar a página.
- **PASS** se recuperar sozinho. **FAIL** se for preciso recarregar ou se entrar em ciclo de login.

## C. Painel

### UI-01 — Páginas e estados
- **Issue:** #25, #26, #27 · **Tipo:** SIMULADO
- **Passos:** percorrer **Início, Câmara, Eventos, Automações, Perfil**; em FakeHome executar os cenários livro → sair → regressar.
- **Esperado:** rótulo **SIMULADO** sempre visível em FakeHome; Início mostra modo, estado, presença, lâmpada, tomada, contagem em espera e poupança; Eventos lista as linhas por ordem, com filtros; sem fonte de vídeo a Câmara diz que não há fonte (não fica em branco).
- **PASS** se nenhuma página ficar em branco ou com erro e a origem dos dados for sempre visível.

### UI-02 — Legibilidade e telemóvel
- **Issue:** #27 · **Tipo:** SIMULADO
- **Passos:** ver o painel num projetor ou a 3 m; repetir com a janela a 390 px de largura; navegar só com o teclado até **Desligar tudo**.
- **Esperado:** modo e estado legíveis à distância; sem scroll horizontal; foco visível; o botão pede confirmação.
- **PASS** se os três pontos se verificarem.

## D. Motor, regras e NVIDIA

### MOT-01 — Modos por objeto
- **Issue:** #13 · **Tipo:** SIMULADO
- **Pré-requisitos:** `HOME_BACKEND=fake`, `PROFILE=demo`.
- **Passos:** cenários (ou `POST /api/simulate`): livro → livro outra vez → comando.
- **Esperado:** 1) `ativo`, modo leitura, luz branco quente 40 %, tomada ligada; 2) evento «já está ativo; nada a fazer», sem novas ações; 3) modo cinema, luz azul 10 %.
- **PASS** se os três passos coincidirem com o registo.

### MOT-02 — Espera, aviso, suspensão e regresso
- **Issue:** #13, #22 · **Tipo:** SIMULADO
- **Pré-requisitos:** MOT-01 feito (modo ativo), `PROFILE=demo`.
- **Passos:** cenário «sair»; cronometrar; depois de suspender esperar 30 s; cenário «regressar».
- **Esperado:** `em_espera` com contagem a partir de 10 s; aos ~5 s a luz baixa para 20 %; aos ~10 s `suspenso`, luz e tomada desligadas; no regresso `ativo` com luz e tomada como antes; evento «Poupança estimada» e `energy_saved_wh > 0`.
- **Evidência:** tempos cronometrados.
- **PASS** se a ordem e os tempos (± 2 s) coincidirem.

### REG-01 — Gerir regras
- **Issue:** #26 · **Tipo:** SIMULADO
- **Passos:** em **Automações**: desativar «Modo leitura»; executar o cenário do livro; reativar; apagar uma regra criada para teste.
- **Esperado:** com a regra desativada o livro gera «Sem regra ativa para livro; ignorado»; reativada volta a funcionar; nunca há duas regras ativas para o mesmo objeto; as alterações sobrevivem a `restart backend`.
- **PASS** se os quatro pontos se verificarem.

### NV-01 — Regra por linguagem natural
- **Issue:** #14 · **Tipo:** REAL (NVIDIA) — sem chave, marcar «não executado»
- **Pré-requisitos:** `NVIDIA_API_KEY` em `app/.env`, backend reiniciado.
- **Passos:** **Automações → nova**; escrever «Quando pego no comando, luz roxa a 50 %»; ver a proposta; confirmar; depois pedir «desliga o alarme quando pego no livro».
- **Esperado:** proposta com resumo em português e sem ser gravada antes da confirmação; depois de confirmar aparece na lista **desativada**; o pedido do alarme é recusado com explicação. Sem chave: erro `nvidia_unavailable` legível e o resto do painel continua a funcionar.
- **PASS** se nada for gravado nem executado sem confirmação e o pedido de alarme for recusado.

### OFF-01 — Desligar tudo
- **Issue:** #27 · **Tipo:** SIMULADO (em MCP ver MCP-07)
- **Passos:** com um modo ativo ou em espera, carregar em **Desligar tudo** e confirmar.
- **Esperado:** `success:true`, estado `inativo`, luz e tomada desligadas, contagem cancelada (não suspende mais tarde).
- **PASS** se ficar tudo desligado e não houver transições depois.

## E. MCP Altice

Operação detalhada em [mcp-demo.md](../integrations/mcp-demo.md); hipóteses para a lâmpada em [mcp-capabilities.md](../integrations/mcp-capabilities.md).

### MCP-01 — OAuth
- **Issue:** #10 · **Tipo:** REAL
- **Pré-requisitos:** `MCP_ENDPOINT`, `MCP_API_KEY` em `app/.env`; conta da equipa.
- **Passos:** `make mcp-login`; concluir no browser; `ls -la app/.mcp-auth`.
- **Esperado:** «Autenticação MCP concluída»; diretoria `drwx------`, `tokens.json` `-rw-------`; `git status` não mostra a pasta.
- **PASS** se os três pontos se verificarem.

### MCP-02 — Descoberta de ferramentas e dispositivos
- **Issue:** #10 · **Tipo:** REAL, só leitura
- **Passos:** `make mcp-doctor`; depois `make mcp-demo` e `auth $API/api/state`.
- **Esperado:** `tools/list` inclui `get_home_devices`, `get_device_details`, `update_device_capabilities`; `mcp_ok:true`; `casa.aviso` não diz «inequivocamente» (uma lâmpada RGB e uma tomada identificadas); `lampada.ligada` e `tomada.ligada` não são `null`.
- **PASS** se os quatro pontos se verificarem.

### MCP-03 — Leitura acompanha a realidade
- **Issue:** #11 · **Tipo:** REAL, só leitura
- **Passos:** com `make mcp-demo` a correr, ligar/desligar a lâmpada pela **app oficial** da Altice; observar o painel.
- **Esperado:** o painel reflete a mudança em ≤ 10 s, sem recarregar.
- **Evidência:** tempo medido e a linha «Lâmpada: … último contacto» de `make mcp-doctor` antes e depois.
- **PASS** se refletir em ≤ 10 s. **FAIL** aponta para a lâmpada sem ligação à cloud (hipótese H1).

### MCP-04 — ⚠️ Lâmpada RGB (escrita física)
- **Issue:** #11 · **Tipo:** REAL com escrita
- **Pré-requisitos:** MCP-02 e MCP-03 com PASS; lâmpada à vista; correr `make mcp-doctor` e anotar a linha «Lâmpada» (`workMode` e «último contacto»).
- **Passos:** `make mcp-verify what=lamp`; ler a alteração proposta; escrever `AUTORIZO LAMPADA`; **olhar para a lâmpada**.
- **Esperado:** a lâmpada fica vermelha a 40 %; a saída tem `"applied_confirmed": true` e `"restored_confirmed": true`; no fim volta ao estado inicial.
- **Evidência:** JSON impresso (sem IDs) e o que se viu fisicamente.
- **PASS** só se a lâmpada mudar **fisicamente** e `applied_confirmed` for `true`. Se `failure_reason` disser «sem contactar a cloud há N min», registar N: confirma a hipótese H1.

### MCP-05 — ⚠️ Tomada (escrita física)
- **Issue:** #11 · **Tipo:** REAL com escrita
- **Pré-requisitos:** MCP-02; carga segura ligada à tomada (ex.: candeeiro), nada que não possa perder energia.
- **Passos:** `make mcp-verify what=plug`; escrever `AUTORIZO TOMADA`; observar a carga.
- **Esperado:** a carga desliga e volta a ligar; `applied_confirmed` e `restored_confirmed` a `true`.
- **PASS** só com efeito físico observado e ambos `true`.

### MCP-06 — Consumo
- **Issue:** #12 · **Tipo:** REAL, só leitura
- **Pré-requisitos:** carga de potência conhecida (ex.: lâmpada de 60 W) na tomada.
- **Passos:** com a carga ligada e depois desligada, correr `make mcp-doctor`; na linha «Tomada» ler `instantPower`, `instantVoltage` e `instantCurrent` (value/min/max e chaves de unidade declaradas, sem IDs). Depois `auth $API/api/state`; comparar com a potência nominal e com a app oficial.
- **Esperado (hoje):** `consumo_w: null` e aviso «Unidade de instantPower não declarada». Anotar o valor bruto de `instantPower` (e de tensão/corrente) mostrado por `make mcp-doctor` com a carga ligada.
- **PASS** se o sistema **não** inventar watts. A unidade só se fecha com a resposta dos mentores ou com a comparação com a carga conhecida.

### MCP-07 — ⚠️ Falhas, autorização e reconexão
- **Issue:** #11, #12 · **Tipo:** REAL
- **Passos:**
  1. Sem grant: `make mcp-writes-status stack=demo`; carregar em **Desligar tudo**.
  2. `make mcp-writes-on stack=demo minutes=2 roles=lamp`; levantar um objeto (ou esperar um gesto); passados 2 min repetir.
  3. Desligar a rede do portátil 20 s e voltar a ligar.
- **Esperado:** 1) «Escritas BLOQUEADAS»; o painel mostra falha com o motivo e **não** afirma que desligou. 2) Só a lâmpada é comandada; a tomada é recusada («dispositivo fora da autorização»); depois de expirar tudo é recusado. 3) `mcp_ok:false` e estados desconhecidos durante a falha; recupera sozinho em ≤ 15 s; nenhuma escrita é repetida.
- **PASS** se os três comportamentos se verificarem. No fim: `make mcp-writes-off stack=demo`.

## F. Vídeo e visão

Backend no host com o extra de visão (ver README, «Visão real»).

### VID-01 — RTSP estável
- **Issue:** #2 · **Tipo:** REAL
- **Pré-requisitos:** `VIDEO_SOURCE=<rtsp>` em `app/.env`.
- **Passos:** `cd app/backend && uv run --env-file ../.env python -m homemind.features.video.medir --minutos 10`.
- **Esperado:** 0 quedas de `camara_ok`; FPS estável; o URL RTSP nunca aparece na saída.
- **Evidência:** linha final do resumo.
- **PASS** com 0 quedas em 10 min.

### VID-02 — Atraso câmara → ecrã
- **Issue:** #2, #25 · **Tipo:** REAL
- **Passos:** pôr um cronómetro (telemóvel) em frente à câmara; fotografar o cronómetro real e o painel no mesmo plano, aos 0, 5 e 10 min.
- **Esperado:** diferença < 1,5 s nas três fotografias.
- **PASS** se as três forem < 1,5 s.

### VID-03 — Queda e reconexão da câmara
- **Issue:** #3 · **Tipo:** REAL
- **Passos:** com o vídeo no painel, desligar a câmara da corrente 15 s e voltar a ligar.
- **Esperado:** `camera_ok:false` em ≤ 5 s e evento «Câmara indisponível»; a casa **não** entra em espera por causa disso; o vídeo volta sozinho e aparece «Câmara disponível».
- **PASS** se recuperar sem reiniciar o backend e sem transições de presença falsas.

### YOLO-01 — Objetos reconhecidos
- **Issue:** #4 · **Tipo:** REAL
- **Pré-requisitos:** `uv sync --extra visao`, pesos descarregados, `VISAO_DETETOR=homemind.features.visao.detetor:DetetorYolo`.
- **Passos:** mostrar à câmara caneca, livro e comando, um de cada vez, a 2–3 m, 10 s cada; observar as caixas no vídeo do painel.
- **Esperado:** cada objeto com caixa e nome certo na maior parte do tempo. Se o livro falhar, repetir com `VISAO_LIVRO_COCO=39` (garrafa) ou `67` (telemóvel) e anotar a escolha.
- **PASS** com os três objetos reconhecidos (indicar o objeto usado em vez do livro, se for o caso).

### YOLO-02 — FPS de inferência
- **Issue:** #4 · **Tipo:** REAL
- **Pré-requisitos:** clip gravado da MEARI em `app/backend/data/clip.mp4`.
- **Passos:**
  ```bash
  cd app/backend
  uv run python -m homemind.features.gestos.afinador --video data/clip.mp4 \
    --detetor homemind.features.visao.detetor:DetetorYolo --gravar-jsonl data/clip.jsonl
  ```
- **Esperado:** no resumo, `detetar` ≤ 100 ms/frame (≥ 10 FPS) com GPU. Sem GPU: anotar o valor e repetir com `--variante n` (`python -m homemind.features.visao.pesos --variante n`, `VISAO_VARIANTE=n`).
- **Evidência:** linha do resumo, hardware e variante.
- **PASS** com ≥ 10 FPS, ou com a limitação e o fallback anotados.

### POSE-01 — Esqueleto
- **Issue:** #4 · **Tipo:** REAL
- **Passos:** pessoa de frente, de perfil e a 3 m; levantar um braço.
- **Esperado:** esqueleto desenhado com ombros, cotovelos e pulsos a acompanhar o braço. Anotar a que distância/ângulo os pulsos deixam de aparecer.
- **PASS** se de frente a 2–3 m os pulsos forem seguidos de forma estável.

### TRK-01 — Tracking
- **Issue:** #4 · **Tipo:** REAL
- **Passos:** mover um objeto devagar pela imagem durante 10 s; entrar uma segunda pessoa.
- **Esperado:** a caixa acompanha o objeto sem piscar; duas pessoas têm caixas distintas. Não aparecem nomes nem identificação de pessoas.
- **PASS** se o seguimento for contínuo e sem identificação.

## G. Gestos e presença

### GES-01 — Dez gestos válidos
- **Issue:** #5 · **Tipo:** REAL
- **Passos:** levantar caneca ×4, livro ×3, comando ×3 (objeto junto ao pulso, mão acima do cotovelo, ~1,5 s), baixando entre cada um e esperando 4 s.
- **Esperado:** 10 eventos «… levantado(a)» no registo, com a classe certa.
- **Evidência:** contagem por classe.
- **PASS** com 10/10. Com menos, afinar com o afinador (`features/gestos/README.md`) e repetir.

### GES-02 — Sem falsos positivos
- **Issue:** #5, #8 · **Tipo:** REAL
- **Passos:** beber da caneca ×3 sem levantar ao nível do gesto; pousar e pegar em objetos na mesa; segurar um objeto levantado 10 s.
- **Esperado:** 0 eventos ao beber e ao mexer na mesa; **1** só evento ao segurar levantado.
- **PASS** com 0 falsos positivos.

### PRE-01 — Presença
- **Issue:** #6 · **Tipo:** REAL
- **Passos:** entrar; sair do enquadramento 10 s; regressar; tapar a pessoa 1 s (passar atrás de algo).
- **Esperado:** «Entrou alguém na divisão» ao entrar; «Divisão vazia» ~3 s depois de sair; de novo «Entrou» ao regressar; a oclusão de 1 s **não** gera «Divisão vazia».
- **PASS** se as quatro observações coincidirem.

## H. Demo

### LAT-01 — Latência do software
- **Issue:** #28 · **Tipo:** SIMULADO (FakeHome)
- **Passos:**
  ```bash
  cd app/backend
  uv run --env-file ../.env python -m homemind.features.visao.medir_latencia \
    --detetor homemind.features.visao.detetor:DetetorYolo --gestos 10
  ```
  e fazer 10 gestos em frente à câmara.
- **Esperado:** todos < 4 s; código de saída 0.
- **Evidência:** linha min/média/máx.
- **PASS** com 10/10 < 4 s.

### LAT-02 — ⚠️ Latência gesto → lâmpada real
- **Issue:** #28 · **Tipo:** REAL — só depois de MCP-04 com PASS
- **Passos:** filmar com o telemóvel o gesto e a lâmpada no mesmo plano, 10 vezes; contar no vídeo do início do gesto até a lâmpada mudar.
- **Esperado:** < 4 s nas 10.
- **PASS** com 10/10 < 4 s. Se MCP-04 falhou: **não executado**.

### DEMO-01 — Dez demonstrações seguidas
- **Issue:** #28 · **Tipo:** indicar REAL ou SIMULADO
- **Uma demo:** arrancar de fresco → entrar → caneca (pausa) → livro (leitura) → sair → espera → suspenso → regressar (restaurado) → **Desligar tudo** → `inativo`.
- **Passos:** 10 demos seguidas sem corrigir nada entre elas; anotar hora e falhas.
- **Esperado:** 10/10. Uma falha reinicia a contagem.
- **PASS** com 10 consecutivas.

### PB-01 — Plano B
- **Issue:** #3, #28 · **Tipo:** SIMULADO
- **Passos:** 1) `VIDEO_SOURCE=<clip MEARI>` e reiniciar: o clip corre em ciclo e gera gestos. 2) `HOME_BACKEND=fake`: executar a demo só com os cenários da página Câmara. 3) Cronometrar a troca do modo real para o plano B.
- **Esperado:** ambos funcionam; o painel mostra SIMULADO e os eventos dos cenários levam `[SIMULADO]`; a troca demora < 1 min.
- **PASS** se os dois caminhos funcionarem e estiverem identificados como simulação.

### PRIV-01 — Privacidade
- **Issue:** #28 · **Tipo:** REAL
- **Passos:** depois de uma sessão com pessoas:
  ```bash
  ls -R app/backend/data
  head -5 app/backend/data/events.jsonl
  grep -ri "rtsp://" app/backend/data; echo "rtsp: $?"
  git status --short
  ```
- **Esperado:** em `data/` só pesos, `rules.json`, `events.jsonl`, o grant e os clips/JSONL criados de propósito; eventos só com texto; `grep` sem resultados (`rtsp: 1`); `git status` sem `.env`, `data/`, clips, pesos ou `.mcp-auth`.
- **PASS** se nada de imagem, URL ou segredo estiver em disco fora do previsto, nos logs ou no Git.

---

## Folha de resultados

Data: ________ · Testador(es): ________ · Hardware (GPU/CPU): ________ · Commit: ________

| ID | Teste | REAL / SIM | PASS / FAIL | Evidência / valor medido | Issue |
|---|---|---|---|---|---|
| INS-01 | Arranque FakeHome | | | | #28 |
| AUTH-01 | Login e logout | | | | #24 |
| AUTH-02 | API recusa sem sessão | | | | #24 |
| API-01 | Leituras REST | | | | #25 |
| API-02 | Formato de erros | | | | #23 |
| WS-01 | Estado em tempo real | | | | #24 |
| WS-02 | Reconexão do WebSocket | | | | #24 |
| UI-01 | Páginas e estados | | | | #25–#27 |
| UI-02 | Legibilidade e telemóvel | | | | #27 |
| MOT-01 | Modos por objeto | | | | #13 |
| MOT-02 | Espera, suspensão, regresso | | | | #13, #22 |
| REG-01 | Gerir regras | | | | #26 |
| NV-01 | Regra por texto (NVIDIA) | | | | #14 |
| OFF-01 | Desligar tudo | | | | #27 |
| MCP-01 | OAuth | | | | #10 |
| MCP-02 | Descoberta | | | | #10 |
| MCP-03 | Leitura acompanha a realidade | | | | #11 |
| MCP-04 | ⚠️ Lâmpada RGB | | | workMode: ____ · sem contacto: ____ min | #11 |
| MCP-05 | ⚠️ Tomada | | | | #11 |
| MCP-06 | Consumo | | | valor bruto: ____ com carga de ____ W | #12 |
| MCP-07 | ⚠️ Falhas e reconexão | | | | #11, #12 |
| VID-01 | RTSP 10 min | | | quedas: ____ · FPS: ____ | #2 |
| VID-02 | Atraso câmara → ecrã | | | 0/5/10 min: ____ / ____ / ____ s | #2 |
| VID-03 | Reconexão da câmara | | | | #3 |
| YOLO-01 | Objetos | | | objeto do «livro»: ____ | #4 |
| YOLO-02 | FPS de inferência | | | ____ ms/frame · variante ____ | #4 |
| POSE-01 | Esqueleto | | | | #4 |
| TRK-01 | Tracking | | | | #4 |
| GES-01 | 10 gestos válidos | | | ____ / 10 | #5 |
| GES-02 | Sem falsos positivos | | | falsos: ____ | #5, #8 |
| PRE-01 | Presença | | | | #6 |
| LAT-01 | Latência software | | | min/média/máx: ____ | #28 |
| LAT-02 | ⚠️ Latência lâmpada real | | | | #28 |
| DEMO-01 | 10 demos seguidas | | | ____ / 10 | #28 |
| PB-01 | Plano B | | | troca em ____ s | #3, #28 |
| PRIV-01 | Privacidade | | | | #28 |

**Pronto para a demo** quando: INS-01, AUTH-01, MOT-01, MOT-02, OFF-01, PB-01 e PRIV-01 têm PASS; DEMO-01 tem 10/10; e o guião (`demo-script.md`) só apresenta como REAL os testes REAL com PASS.
