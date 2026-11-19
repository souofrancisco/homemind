# Guia de validação manual — roteiro oficial

> **Nota (Conta Certa):** guia adaptado de um roteiro do ObjectOS. **Continuam válidos:** blocos A (arranque, login), B (API REST), E (MCP), F (vídeo e presença), PRIV-01 e as regras de evidência. Os cenários do motor, regras, NVIDIA, gestos e demos antigas estão retirados na BASE-04 e não se executam. Os blocos atuais de validação da Conta Certa devem ser lidos com os estados IMPLEMENTADO/PLANEADO do produto. Só se marca PASS o que foi executado.

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
| [B. API e tempo real](#b-api-e-tempo-real) | API-01 e WebSocket planeado |
| [C. Painel](#c-painel) | validação da interface atual |

| [E. MCP Altice](#e-mcp-altice) | MCP-01 … MCP-09 |
| [F. Vídeo e visão](#f-vídeo-e-visão) | PRES-01, PRES-02, VID-01, VID-02, VID-03, VID-04, YOLO-01, YOLO-02, POSE-01, TRK-01 |

| [H. Demo](#h-demo) | ALR-06 e PRIV-01 |
| [I. Presença (Conta Certa)](#i-presença-conta-certa) | PRW-01 … PRW-04, PRF-01 … PRF-04 |
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
- **Esperado:** `{"status":"ok","backend":"fake","physical_writes":false}`; painel abre em <http://localhost:5173>; log do backend sem erros.
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
  curl -s -o /dev/null -w "%{http_code}\n" $API/api/video
  curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer lixo" $API/api/me
  auth -o /dev/null -w "%{http_code}\n" $API/api/me
  ```
- **Esperado:** `401`, `401`, `200` (sem token, token inválido e sessão válida).
- **PASS** se os códigos coincidirem e a API exigir sessão nas rotas protegidas.

## B. API e tempo real

### API-01 — Leituras REST
- **Issue:** #25 · **Tipo:** SIMULADO ou REAL (indicar `backend`)
- **Passos:** `auth $API/api/me`; abrir `$API/openapi.json` e procurar os caminhos ativos.
- **Esperado:** `/api/me` devolve a identidade autenticada; o OpenAPI lista a API Conta Certa e lista as rotas ativas da Conta Certa.
- **PASS** se os resultados corresponderem ao contrato atual.

### API-02 — Erros no formato único — RETIRADO (BASE-04)

Teste do motor removido; não há passos executáveis. A API ativa da Conta Certa é documentada em
[api-implementada.md](../architecture/api-implementada.md).

### WS-01 — Estado em tempo real — RETIRADO (BASE-04)

O WebSocket do motor foi removido; não há passos executáveis. O WebSocket de notificações da
Conta Certa continua planeado.

### WS-02 — Reconexão — RETIRADO (BASE-04)

Dependia do WebSocket do motor removido; não há passos executáveis.

## C. Painel

### UI-01/02 — Interface antiga — RETIRADO (BASE-04)

Os testes das páginas ObjectOS foram removidos com a interface antiga. A interface atual é a aplicação Conta Certa; seguir os fluxos atuais documentados em [functional-flows.md](../functional-flows.md).

## D. Motor, regras e NVIDIA — RETIRADO (BASE-04)

Os testes MOT-01/02, REG-01, NV-01 e OFF-01 pertenciam ao motor ObjectOS e foram retirados. Não há passos executáveis para estes testes.

## E. MCP Altice

Operação detalhada em [mcp-demo.md](../integrations/mcp-demo.md); hipóteses para a lâmpada em [mcp-capabilities.md](../integrations/mcp-capabilities.md).

**Runbook automático (DEMO-03, #122) — IMPLEMENTADO.** Corre as verificações, mede e imprime as linhas desta Folha de resultados prontas a colar (PASS / FAIL / BLOQUEADO, hora UTC e local, evidência sem IDs, nomes, URL nem tokens). Só leitura por omissão.

```bash
cd app/backend
uv run python -m homemind.connectors.runbook --simulated            # ensaio sem kit (tudo SIMULADO)
uv run --env-file ../.env python -m homemind.connectors.runbook     # kit REAL, só leitura
#   --interactive        mede a latência do contacto (MCP-08), com o operador junto ao sensor
#   --write lamp plug    escritas físicas (MCP-04/05), cada uma com «AUTORIZO …» e grant privado de 2 min
#   --camera             abre VIDEO_SOURCE para VID-04 (ver bloco F e PRIV-02)
#   --samples-s 90       duração da amostragem de MCP-06 (uma leitura a cada 5 s)
#   --out relatorio.json JSON do relatório (por omissão vai para o stdout; nunca para o repositório)
#   --update-guide       preenche as linhas MCP-01/02/04/05/06/08/09 e VID-04 desta Folha
```

- Código de saída ≠ 0 se houver algum FAIL. Sem `--write`, MCP-04/05 ficam BLOQUEADO («não autorizado nesta sessão»); no kit real, o PASS de uma escrita exige a releitura **e** o operador confirmar o que viu.
- `--update-guide` só altera as colunas REAL / SIM, PASS / FAIL e Evidência das linhas com o mesmo ID; um BLOQUEADO não apaga um resultado já registado. Um ensaio `--simulated` só atualiza um guia indicado com `--guide`.
- O «MCP-03» do runbook é o **inventário** (tipos e identificação inequívoca); não substitui o MCP-03 manual abaixo (leitura acompanha a app oficial) e não é escrito nesta folha. O MCP-07 do runbook só corre no simulador; no kit real seguem-se os passos manuais.

### MCP-01 — OAuth
- **Issue:** #10 · **Tipo:** REAL
- **Pré-requisitos:** `MCP_ENDPOINT`, `MCP_API_KEY` em `app/.env`; conta da equipa.
- **Passos:** `make mcp-login`; concluir no browser; `ls -la app/.mcp-auth`.
- **Esperado:** «Autenticação MCP concluída»; diretoria `drwx------`, `tokens.json` `-rw-------`; `git status` não mostra a pasta.
- **PASS** se os três pontos se verificarem.

### MCP-02 — Descoberta de ferramentas e dispositivos
- **Issue:** #10 · **Tipo:** REAL, só leitura
- **Passos:** `make mcp-doctor`; depois consultar `auth $API/api/mcp/tools`.
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
- **Passos:** com a carga ligada e depois desligada, correr `make mcp-doctor`; na linha «Tomada» ler `instantPower`, `instantVoltage` e `instantCurrent` (value/min/max e chaves de unidade declaradas, sem IDs). Depois consultar `auth $API/api/mcp/tools`; comparar com a potência nominal e com a app oficial.
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

### MCP-08 — Contacto: estado e latência
- **Issue:** #122 · **Tipo:** REAL, só leitura
- **Pré-requisitos:** MCP-03 do runbook com um único sensor de contacto; operador junto ao sensor.
- **Passos:** runbook com `--interactive`; a cada pedido, carregar Enter e logo a seguir abrir (depois fechar) o sensor.
- **Esperado:** estado atual `aberto`/`fechado` e idade do último contacto; latência de ABRIR e de FECHAR medida com amostras a cada 2 s (timeout 90 s). A latência inclui o tempo de reação do operador (por excesso).
- **Evidência:** as duas latências; decidem se a meta «janela → corte < 10 s» é realista.
- **PASS** com estado conhecido e, com `--interactive`, as duas mudanças vistas em ≤ 90 s.

### MCP-09 — Clima: temperatura e humidade
- **Issue:** #122 · **Tipo:** REAL, só leitura
- **Passos:** runbook (sem opções extra).
- **Esperado:** temperatura (°C) e humidade (%) atuais e idade do último contacto (o clima reporta com pouca frequência: ≥ ~11 min).
- **PASS** com os dois valores conhecidos; leitura com mais de 2 h fica BLOQUEADO.

## F. Vídeo e visão

**Bloqueado por PRIV-02 #119:** não executar validações com câmara real, RTSP, pessoas ou clips de origem real. `GET /api/video` está desativado, `criar_fonte` recusa RTSP e a visão só aceita clips sintéticos allowlisted com perfil demo e FakeHome. Reabrir estas validações exige os controlos PRES-02/03 e revisão de produto/jurídica.

### PRES-01 — Câmara da porta (kit via app/link) e plano B
- **Issue:** #105 · **Tipo:** REAL (kit) / SIMULADO (clip, telemóvel) · **Estado: NÃO EXECUTADO**
- **Pré-requisitos:** `app/.env` com `VIDEO_SOURCE=<link RTSP partilhado pela app MEARI>` e `VIDEO_SOURCE_KIND=kit`; um utilizador com papel `operator`.
- **Passos:** 1) arrancar o backend; 2) `GET /api/presence/camera/status` com o token do operador; 3) repetir com o link inválido e com a câmara desligada 15 s; 4) plano B: `VIDEO_SOURCE_KIND=phone` com o URL da app do telemóvel (IP Webcam / similar) e, sem rede, `VIDEO_SOURCE=data/porta.mp4` + `VIDEO_SOURCE_KIND=clip`.
- **Esperado:** kit ligado: `source=kit`, `origin=real`, `camera_ok=true`, `fps>0` (2.ª consulta). Link inválido ou câmara desligada: `camera_ok=false`, sem `fps`, e **nenhum** estado de «casa vazia». Telemóvel e clip: `origin=simulated`. O URL nunca aparece na resposta, nos logs nem nos erros. Se a app MEARI não partilhar um stream utilizável, registar «kit sem stream» e usar o plano B.
- **PASS** só com a evidência do kit (ou «kit sem stream» registado) e os dois planos B a funcionar.

### PRES-02 — Contagem na soleira (YOLO + linha virtual)
- **Issue:** #106 · **Tipo:** REAL com câmara / SIMULADO com clip · **Estado: NÃO EXECUTADO**
- **Pré-requisitos:** PRES-01 a funcionar; `uv sync --extra visao` e pesos; `app/.env` com `PRESENCE_HOUSEHOLD_ID` (casa existente na base), `PRESENCE_DETETOR=homemind.features.presence.yolo:DetetorYoloPessoas`, `PRESENCE_DOOR_ROI` e `PRESENCE_DOOR_LINE`; `GET /api/presence/camera/status` com `door_mask_configured:true`.
- **Passos:** 10 passagens combinadas (5 a entrar, 5 a sair, ritmos normais), 2 voltas atrás a meio da linha e uma passagem de duas pessoas lado a lado; contar à mão e comparar com os `presence.door_crossed` gravados (`domain_event`).
- **Esperado:** sentido certo em cada passagem; voltas atrás sem evento; nenhuma imagem em disco (`find app/backend/data -type f` só mostra a base de dados). Se o sentido vier trocado, inverter `PRESENCE_DOOR_INSIDE_SIGN`.
- **Evidência:** contagem certa/total registada **só se medida**; nenhum valor de precisão sem esta medição.
- **PASS** só com a contagem registada e zero imagens em disco.

### VID-01 — RTSP estável (BLOQUEADO)
- **Issue:** #2 · **Tipo:** REAL
- **Pré-requisitos:** `VIDEO_SOURCE=<rtsp>` em `app/.env`.
- **Passos:** `cd app/backend && uv run --env-file ../.env python -m homemind.features.video.medir --minutos 10`.
- **Esperado:** 0 quedas de `camara_ok`; FPS estável; o URL RTSP nunca aparece na saída.
- **Evidência:** linha final do resumo.
- **PASS** com 0 quedas em 10 min.

### VID-02 — Atraso câmara → ecrã (BLOQUEADO)
- **Issue:** #2, #25 · **Tipo:** REAL
- **Passos:** pôr um cronómetro (telemóvel) em frente à câmara; fotografar o cronómetro real e o painel no mesmo plano, aos 0, 5 e 10 min.
- **Esperado:** diferença < 1,5 s nas três fotografias.
- **PASS** se as três forem < 1,5 s.

### VID-03 — Queda e reconexão da câmara (BLOQUEADO)
- **Issue:** #3 · **Tipo:** REAL
- **Passos:** com o vídeo no painel, desligar a câmara da corrente 15 s e voltar a ligar.
- **Esperado:** `camera_ok:false` em ≤ 5 s e evento «Câmara indisponível»; a casa **não** entra em espera por causa disso; o vídeo volta sozinho e aparece «Câmara disponível».
- **PASS** se recuperar sem reiniciar o backend e sem transições de presença falsas.

### VID-04 — Câmara: abertura e FPS (runbook)
- **Issue:** #122 · **Tipo:** REAL (kit/RTSP) / SIMULADO (clip, telemóvel ou `--simulated`) · **Estado: só com autorização (PRIV-02)**
- **Pré-requisitos:** `VIDEO_SOURCE` em `app/.env`; autorização explícita para abrir a câmara real (PRIV-02 #119).
- **Passos:** runbook com `--camera`.
- **Esperado:** abre a fonte, lê frames **só em memória** durante ~5 s e descarta-os logo; mede resolução, FPS, atraso de abertura e do primeiro frame. Nada é gravado nem enviado; o URL nunca aparece na saída. Sem `VIDEO_SOURCE` ou sem `--camera`: BLOQUEADO.
- **PASS** se chegar pelo menos um frame. Não substitui o VID-01 (10 min sem quedas).

### YOLO-01/02, POSE-01 e TRK-01 — RETIRADOS (BASE-04)

Eram testes de objetos, pose e tracking do ObjectOS removido. A presença na soleira tem validação própria nos blocos F e I.

## G. Gestos e presença binária — RETIRADO (BASE-04)

GES-01/02 e PRE-01 pertenciam ao processador antigo de gestos/presença. Não há passos executáveis; a presença da Conta Certa é validada nos blocos F e I.

## H. Demo

### LAT-01/02 — Latência do motor — RETIRADO (BASE-04)

Estas medições dependiam da cadeia gesto → luz, removida com o ObjectOS; não há passos executáveis.

### ALR-06 — ⚠️ Cor do orçamento na lâmpada real
- **Issue:** #104 · **Tipo:** REAL — só depois de MCP-04 com PASS; uma pessoa, lâmpada à vista.
- **Preparação:** `HOME_BACKEND=mcp`, `ENERGY_HOUSEHOLD_ID` = casa real de teste, `MCP_LAMP_ROOM_ID` = quarto do morador de teste (ou uma zona comum), `ENABLE_PHYSICAL_WRITES=true` e `make mcp-writes-on` só para `lamp`.
- **Passos:** definir um orçamento baixo para o morador; esperar o aviso de 80 %; na página Orçamento carregar em «Mudar a cor»; observar a lâmpada; repetir com `make mcp-writes-off` antes de confirmar.
- **Esperado:** com grant: lâmpada amarela e mensagem de sucesso só depois da releitura (`confirmed`); sem grant: `blocked`, a lâmpada não muda e nada é repetido. Se a lâmpada não mudar mas o MCP disser «device updated»: `uncertain`, sem nova tentativa.
- **PASS** só com as duas observações feitas à mão. Fim: `make mcp-writes-off`.

### DEMO-01 e PB-01 — Demos antigas — RETIRADOS (BASE-04)

Estes cenários dependiam do motor ObjectOS e foram removidos. Usar o fluxo de demo da Conta Certa em [mvp.md](mvp.md).

### PRIV-01 — Privacidade
- **Issue:** #28 · **Tipo:** REAL
- **Passos:** depois de uma sessão com pessoas:
  ```bash
  ls -R app/backend/data
  grep -ri "rtsp://" app/backend/data; echo "rtsp: $?"
  git status --short
  ```
- **Esperado:** em `data/` não há imagens, frames nem segredos; `grep` sem resultados (`rtsp: 1`); `git status` sem `.env`, `data/`, clips, pesos ou `.mcp-auth`.
- **PASS** se nada de imagem, URL ou segredo estiver em disco fora do previsto, nos logs ou no Git.

## I. Presença (Conta Certa)

Pistas por pessoa (PRES-03, **IMPLEMENTADO**). Pré-requisitos: backend no **anfitrião** ligado ao Wi-Fi do hub do kit (o contentor Docker não vê a ARP do anfitrião; ver [presence.md](../modules/presence.md)), `PRESENCE_WIFI_COLLECTION_ENABLED=true`, `PRESENCE_MATCH_SALT`, `PRESENCE_WIFI_MODE=ingest`, `PRESENCE_INGEST_TOKEN` e `PRESENCE_WIFI_SUBNET` em `app/.env`, e um telemóvel de teste cuja dona deu consentimento (telemóvel registado **e** `presence_opt_in` da membership a `true`). Nunca copiar MACs, IPs nem hashes para chats, issues ou prints. Rotas: `?household_id=<casa>` + `Authorization` de um inquilino.

### PRW-01 — Telemóvel registado aparece
- **Tipo:** REAL (varrimento da rede do hub) · **Issue:** #107
- **Passos:** `make presence-wifi-scan` (noutra janela); registar o telemóvel (`POST /api/presence/devices`, `consent=true`, `wifi_address` = endereço Wi-Fi do telemóvel nessa rede); desligar e voltar a ligar o Wi-Fi do telemóvel; esperar um ciclo (30 s por omissão).
- **Esperado:** um evento `presence.cue_recorded` com `source=wifi`, `state=in`, `origin=real`, em nome do morador; nenhuma pista dos outros aparelhos da rede (visitas, vizinhos) e nenhum MAC ou hash deles na base.
- **PASS** se as três observações coincidirem.

### PRW-02 — Opt-out imediato
- **Tipo:** REAL · **Issue:** #107
- **Passos:** `DELETE /api/presence/devices/{id}`; religar o Wi-Fi do telemóvel; esperar um ciclo.
- **Esperado:** `204`; **nenhuma** pista nova; `GET /api/presence/devices` mostra `wifi_opt_in=false` e `revoked_at`.
- **PASS** se não surgir nenhuma pista depois do `DELETE`.

### PRW-03 — Wi-Fi desligado não é saída
- **Tipo:** REAL · **Issue:** #107
- **Passos:** com o telemóvel registado e visto, desligar o Wi-Fi do telemóvel 30 min.
- **Esperado:** nenhum evento `presence.cue_recorded` com `state=out`; o Wi-Fi nunca produz `out`.
- **PASS** com zero pistas `out`.

### PRW-04 — Isolamento por papel
- **Tipo:** REAL (API) · **Issue:** #107
- **Passos:** repetir `GET /api/presence/devices` com a sessão do senhorio e do operador; sem `presence_opt_in` na membership, registar o telemóvel e voltar a ligá-lo ao Wi-Fi.
- **Esperado:** `403 forbidden_role` em todas as rotas de presença para senhorio e operador; **nenhuma** pista Wi-Fi enquanto a membership não tiver `presence_opt_in=true`.
- **PASS** se as duas observações coincidirem.

### PRF-01 — Telemóvel a dormir mantém «em casa»
- **Tipo:** REAL (Wi-Fi do hub) com porta SIMULADA · **Issue:** #108
- **Passos:** com o telemóvel registado e visto (`GET /api/presence` → `in`), pô-lo em modo de poupança/sem Wi-Fi 10 min.
- **Esperado:** continua `in` (sem `presence.changed`); nunca `out`.
- **PASS** se o estado não mudar durante os 10 min.

### PRF-02 — Saída pela porta + tolerância
- **Tipo:** SIMULADO (a porta ainda não tem produtor real: PRES-02; publicar `presence.door_crossed` direção `out` por script/fixture) · **Issue:** #108
- **Passos:** com o telemóvel visto (`in`), publicar a saída; esperar `PRESENCE_TOLERANCE_MIN` minutos (usar 20 para encurtar) sem pistas.
- **Esperado:** antes do fim da tolerância `in` (confiança 0,5); depois `out` com `sources=["camera_door"]` e um `presence.changed`.
- **PASS** se as duas fases coincidirem.

### PRF-03 — Contradição gera pergunta, não acusação
- **Tipo:** REAL (Wi-Fi) + SIMULADO (porta) · **Issue:** #108
- **Passos:** com o Wi-Fi do telemóvel desligado, publicar uma saída simulada e esperar a tolerância (`out`); ligar o Wi-Fi do telemóvel sem passar a porta.
- **Esperado:** `uncertain` com `reason=conflicting_cues` e um `presence.confirmation_needed` (só `id`, `resident_id`, `reason`, `expires_at`); a resposta «estás em casa?» (quando a APP-02 existir) resolve.
- **PASS** se houver exatamente um pedido.

### PRF-04 — Falha do Wi-Fi nunca vira «fora»
- **Tipo:** REAL · **Issue:** #108
- **Passos:** com o telemóvel registado, parar `make presence-wifi-scan`; esperar 3 intervalos; publicar uma saída pela porta; esperar a tolerância.
- **Esperado:** `uncertain` com `reason=no_recent_cues` e um pedido de confirmação; **nunca** `out`.
- **PASS** se não houver `out`.

---

## Folha de resultados

Data: ________ · Testador(es): ________ · Hardware (GPU/CPU): ________ · Commit: ________

| ID | Teste | REAL / SIM | PASS / FAIL | Evidência / valor medido | Issue |
|---|---|---|---|---|---|
| INS-01 | Arranque FakeHome | | | | #28 |
| AUTH-01 | Login e logout | | | | #24 |
| AUTH-02 | API recusa sem sessão | | | | #24 |
| API-01 | Leituras REST | | | | #25 |
| MCP-01 | OAuth | REAL | PASS | 2026-11-18 15:24:07 UTC (15:24:07 local) · sessão aberta com os tokens persistidos, sem login (750 ms) | #10 |
| MCP-02 | Descoberta | REAL | PASS | 2026-11-18 15:24:10 UTC (15:24:10 local) · 18 ferramentas (get_device_details, get_device_recommendations, get_device_timers, get_home, get_home_detail_report, get_home_devices, get_home_rooms, get_home_scenarios, get_home_security_alarm_history, get_home_security_status, get_home_status_brief, get_scenario, patch_home_security_status, patch_scenario_activation, post_execute_scenario, post_new_scenario, post_timer_device, update_device_capabilities); as 3 usadas têm schema compatível | #10 |
| MCP-03 | Leitura acompanha a realidade | | | | #11 |
| MCP-04 | ⚠️ Lâmpada RGB | REAL | FAIL | 2026-11-18 15:07:24 UTC (15:07:24 local) · releitura: alteração confirmada, restauro confirmado; estado final: ligada=True, brilho=1; última escrita 6109 ms; operador viu a lâmpada ficar vermelha (efeito físico observado), mas ela NÃO voltou à cor inicial: ficou vermelha a 1 % (a nuvem devolvia color_rgb bruto 3,0,0 com brilho=1, igual ao que o operador via). O «restauro confirmado» era um falso positivo: a tolerância de cor (_RGB_TOL=3) a brilho 1 aceita qualquer cor. Causa apurada com dois ensaios autorizados às ~15:35–15:42 UTC: escrever `brightness` DEPOIS de `color_rgb` anula a cor enviada e repõe a cor antiga (restauro e 1.º ensaio: cor azulada vista e depois vermelho a brilho 40); com `brightness` ANTES de `color_rgb` ficam as duas (branco-azulado a 40 %, visto pelo operador, releitura 80,80,102). Ver mcp-capabilities.md; workMode antes: colour | #11 |
| MCP-05 | ⚠️ Tomada | REAL | PASS | 2026-11-18 15:13:55 UTC (15:13:55 local) · releitura: alteração confirmada, restauro confirmado; ligada inicial=True, final=True; última escrita 4312 ms; mudança física observada pelo operador | #11 |
| MCP-06 | Consumo | REAL | PASS | 2026-11-18 15:25:41 UTC (15:25:41 local) · 18/18 amostras em 88 s; instantPower bruto 119–143; V 233–234; I 582–779 mA; unidade declarada: ausente; MCP_INSTANTPOWER_UNIT: W; lastCommunicationTime mudou 3× (intervalos: 43,1 s, 59,0 s, 1,9 s); P/(V·I) mediana 0,87 (mín. 0,78, máx. 0,87) | #12 |
| ALR-06 | ⚠️ Cor do orçamento na lâmpada real | | | com grant: ____ · sem grant: ____ | #104 |
| MCP-07 | ⚠️ Falhas e reconexão | | | | #11, #12 |
| MCP-08 | Contacto: estado e latência | REAL | PASS | 2026-11-18 15:28:00 UTC (15:28:00 local) · estado: aberto; último contacto há 2 min; fechar e abrir: mudança já visível na 1.ª leitura, por isso o runbook devolve 0,0 s nos dois (o relógio só arranca no fim de um bip de 0,9 s e a 1.ª leitura demora ~1–2 s). Valor exato NÃO medido; a latência ficou abaixo de ~3 s com um ensaio anterior a dar fechar = 2,9 s. Sinal sonoro no lugar do Enter, inclui a reação do operador; poucas amostras | #122 |
| MCP-09 | Clima: temperatura e humidade | REAL | PASS | 2026-11-18 15:28:03 UTC (15:28:03 local) · temperatura 27,4 °C; humidade 54 %; último contacto há 80 s | #122 |
| PRES-01 | Câmara da porta: kit e plano B | | | kit: ____ · FPS: ____ | #105 |
| PRES-02 | Contagem na soleira | | | certas/total: ____ | #106 |
| VID-01 | RTSP 10 min | | | quedas: ____ · FPS: ____ | #2 |
| VID-02 | Atraso câmara → ecrã | | | 0/5/10 min: ____ / ____ / ____ s | #2 |
| VID-03 | Reconexão da câmara | | | | #3 |
| VID-04 | Câmara: abertura e FPS (runbook) | REAL | BLOQUEADO | 2026-11-18 15:11:01 UTC (15:11:01 local) · PRIV-02: câmara só com --camera e autorização | #122 |
| PRIV-01 | Privacidade | | | | #28 |
| PRW-01 | Telemóvel registado aparece (Wi-Fi) | | | | #107 |
| PRW-02 | Opt-out imediato | | | | #107 |
| PRW-03 | Wi-Fi desligado não é saída | | | | #107 |
| PRW-04 | Isolamento por papel; sem opt-in sem pista | | | | #107 |
| PRF-01 | Telemóvel a dormir mantém «em casa» | | | | #108 |
| PRF-02 | Saída pela porta + tolerância | | | | #108 |
| PRF-03 | Contradição → pergunta | | | | #108 |
| PRF-04 | Falha do Wi-Fi não vira «fora» | | | | #108 |

**Pronto para a demo** quando: INS-01, AUTH-01, MOT-01, MOT-02, OFF-01, PB-01 e PRIV-01 têm PASS; DEMO-01 tem 10/10; e o guião (`demo-script.md`) só apresenta como REAL os testes REAL com PASS.
