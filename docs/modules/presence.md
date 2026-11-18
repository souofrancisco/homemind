# Módulo `presence` — câmara na porta e presença

**Dono: P2 (1Mii).** **IMPLEMENTADO** (PRES-03 #107, PRES-04 #108): telemóveis com opt-in, pistas Wi-Fi, resposta a «estás em casa?» e fusão em casa/fora/incerto. **Não há check-in manual «cheguei/saí»**: a presença regista-se só pela câmara (porta) e pelo telemóvel no Wi-Fi (decisão do dono). **PLANEADO**: câmara na porta (PRES-01/02; a fusão já consome `presence.door_crossed`, hoje só com fixtures), ocupação (PRES-05). Entidades: `PresenceEvent`, `PersonPresence` ([data-model.md](../architecture/data-model.md)).

## Responsabilidade

Saber **quando alguém entra ou sai** e, a partir daí, **quem está em casa** — sem reconhecer ninguém pela imagem. A identidade vem de fontes voluntárias (registo na aplicação; futuro: Wi-Fi com opt-in).

## Privacidade (inegociável, PDF §5.3 + [CLAUDE.md](../../CLAUDE.md))

- O vídeo é processado **localmente**; nunca se grava, regista ou envia um frame. Só saem eventos de texto.
- Sem reconhecimento facial nem identificação. `track_id` é efémero e nunca persistido.
- Só a soleira da porta é analisada; o resto da imagem é tapado a preto **antes** de qualquer inferência.
- O senhorio não tem acesso a imagens, entradas, saídas nem horários.
- A câmara só existe na casa se a casa decidir (votação: **PROPOSTA**, prioridade P2).
- Sem câmara, a presença funciona só com o Wi-Fi (e o aparelho pessoal a ligar).

## Recebe / produz

| Recebe | Produz |
|---|---|
| Frames da câmara/clip (`features/video`, `FonteVideo`) | `DoorCrossed` (sentido, confiança), `presence.door_crossed` |
| Telemóveis registados no Wi-Fi com opt-in (`PresenceDevice.wifi_opt_in`) — **IMPLEMENTADO** | idem, `source=wifi` (só `in`) |
| `energy.consumption_detected` com `appliance_owner_resident_id` (P1) | idem, `source=appliance` (só `in`) |
| Resposta a «estás em casa?» (`notification.responded`, `ref.type=presence_check`, P3) — consumidor **IMPLEMENTADO**; o produtor (`notifications.presence_check`, APP-02) **IMPLEMENTADO** (backend; UI PLANEADA) | pista manual |
| `sensor.reading_recorded` (contacto, fumo; P1) | `SafetyAlert` em `safety.alert_raised` (SAFE-01/03) |
| — | `presence.changed` por pessoa; `presence.confirmation_needed` (pistas em conflito); `presence.occupancy_changed` (anónimo; «casa possivelmente vazia» só na fase 2) |

Contratos novos (`PresenceMeIn`, `PresenceConfirmationRequest`, `HouseOccupancy`, `PresenceDevice`, `CameraStatus`, `SensorReading`, `SafetyAlert`): **PROPOSTA** (D-31), em `contracts/{presence,sensors,safety}.py`.

## Segurança e conforto (`features/safety`, SAFE-01 #114)

**IMPLEMENTADO (SAFE-01, lógica + consumidor do barramento; sem rotas, sem migrações):**
- `engine.py` (puro): janela (`SensorReading` contacto) aberta **e** aquecimento a decorrer em simultâneo durante ≥ 5 min no mesmo quarto (`ConsumptionEvent` `ongoing` cujo aparelho é de aquecimento) → `SafetyAlert(window_open_heating, warning)` com `suggested_command` = `power=false` na tomada do consumo. É só uma **proposta**: nunca escreve no MCP nem usa `ENABLE_PHYSICAL_WRITES`; a confirmação e a execução são de P3/P1.
- Relógio = `ts` do evento em processamento (determinístico). Um alerta por episódio (`id` estável); resolve-se (mesmo `id`, `resolved`) quando a janela fecha ou o aquecimento acaba; reabre só com novo episódio (janela fechada e reaberta, ou aquecimento religado). `unknown`/`stale` nunca disparam nem resolvem; sensor sem quarto, quarto diferente ou aparelho não-aquecimento não disparam. `coverage()` identifica sensores ausentes (`absent`).
- `service.py`: consumidor `safety` (`sensor.reading_recorded`, `energy.consumption_detected/closed`) → `safety.alert_raised`. O estado refaz-se do registo de eventos ao arrancar.
- `texts.py`: texto pt-PT com origem (SIMULADO/REAL) e o aviso de que a tomada pode alimentar mais do que o aquecedor (na demo, a tomada agregada corta todas as cargas). `simulation.py`: leituras/consumos **SIMULADOS** para demo e testes.
- **Fumo (SAFE-03):** leitura `smoke` `ok` com `smoke_detected=true` → `SafetyAlert(smoke, critical)` deduplicado por episódio, com origem (`provenance`), sem `suggested_command` (nunca sugere cortes) e `notify_landlord=false` por omissão (o contrato não tem política de autorização do senhorio; só se liga por parâmetro do serviço). Resolve-se com leitura `ok` sem fumo. `unknown`/`stale` não geram alerta nem limpam; sensor ausente aparece em `coverage()` (`absent`). O texto diz que o sistema não substitui detetores certificados.

**Decisões para a demo (dono P2; não definitivas):** os 5 min contam desde que **ambas** as condições coincidem (janela aberta há 10 min e aquecedor que liga → só avisa 5 min depois; se o aquecedor desligar e religar, ou a janela fechar, o relógio recomeça); não há resolvedor de aquecedor de demo — **a regra da janela fica inativa até ENERGY-03 #81**; `notify_landlord=false` por omissão (onde vive a política: provavelmente `HouseholdPolicy`, com P5 — em aberto, P-26); o aviso da tomada agregada fica em `texts.py` para P3, sem mudar o contrato (P-27). O consumidor é idempotente por evento: se a transação do barramento falhar depois do handler, o retry reemite o mesmo alerta.

**PLANEADO:** o router arranca o serviço **sem** resolvedor de aquecedores (por omissão nada é «aquecimento»), porque depende de ENERGY-03 #81 (identificar aparelhos/`ApplianceCategory.heating`); sem leituras reais de contacto/fumo até MCP-03 #76 (o fumo funciona já com eventos reais ou simulados, quando existirem); a entrega ao utilizador (`notifications.safety_alert`, APP-02 #95) e a proposta de desligar a tomada (`agent.safety_suggestion`, AGENT-03b #112, confirmada em `POST …/agent/actions/{id}/confirm`) já estão **IMPLEMENTADAS**; a execução física depende do executor real da P1 (MCP-04 #77; hoje só SIMULADO na casa demo). Até ENERGY-03 só os cenários simulados exercitam a regra.

## Passos

| Passo | Descrição | Prioridade |
|---|---|---|
| 1 | ~~Registo manual «cheguei/saí»~~ — **removido** (decisão do dono); eventos simulados de porta + Wi-Fi permitem à P4 testar a regra C | — |
| 2 | Detetor de pessoas na soleira (`DetetorYolo` só com a classe «pessoa» + ByteTrack) e linha virtual → `DoorCrossed` | P0 (PRES-02 #106) |
| 3 | Fusão de pistas por pessoa: em casa / fora / incerto, com tolerância de 20–30 min para ausências e confirmação pela porta (PDF §6.8) | P0 (PRES-04 #108) |
| 4 | Estado «casa vazia» e alerta de entrada com casa vazia — **fase 2** | P2 (F3: PRES-06 #131, SAFE-02 #115) |
| 5 | Sinal de presença por Wi-Fi (opt-in) e resposta à pergunta «estás em casa?» | P0 (PRES-03 #107) |

Regras de fusão (PDF §6.8): presença no Wi-Fi conta muito, ausência conta pouco; só se considera que alguém saiu se houver uma saída pela porta e passarem 20–30 min; um aparelho a continuar ligado não prova presença, só um a **ligar** prova; contradição (entrada + aparelho a ligar sem ninguém «em casa») → `uncertain` e pergunta na aplicação.

## Fontes de vídeo e estado da câmara (PRES-01) — IMPLEMENTADO

`VIDEO_SOURCE` (URL ou caminho; segredo, só em `app/.env`) + `VIDEO_SOURCE_KIND` escolhem a fonte; o
pipeline `features/video` (RTSP/TCP ou clip, reconexão com backoff, só o último frame em memória) é o
mesmo para todas.

| Fonte (`VideoSourceKind`) | Como | Origem |
|---|---|---|
| `kit` | link/stream RTSP partilhado pela app da câmara MEARI; só leitura, sem passar pelo MCP | REAL (só depois de validada, ver guia: **não validada**) |
| `rtsp` | outra câmara IP na porta | REAL |
| `phone` | telemóvel como câmara IP (RTSP ou MJPEG por `http(s)://`) | SIMULADO |
| `clip` | clip pré-gravado da porta, em loop | SIMULADO |

Em dúvida a fonte é SIMULADA: `kit`/`rtsp` sem URL `rtsp://` caem para `clip`; sem tipo declarado,
`http(s)://` é `phone`. Sem `VIDEO_SOURCE` o estado é `clip`/simulada com `camera_ok=false`.

`GET /api/presence/camera/status` devolve `CameraStatus` (fonte, origem, `camera_ok`, `fps`,
`last_frame_at`, `door_mask_configured`), nunca imagem nem URL. Só o papel `operator` em **qualquer** casa (sem `household_id` na rota). **Decisão para a demo (uma casa); definitivo: `household_id` na rota (PLANEADO)**, ver P-28 em `decisions.md`. Senhorio, inquilino e sem membership recebem `403 forbidden_role`. Fonte ausente ou sem frame
há mais de `VIDEO_SEM_FRAME_S` ⇒ `camera_ok=false` e sem `fps`; **nunca** se conclui «casa vazia». O
`fps` é a cadência de frames novos entre duas consultas (`null` na primeira).
`door_mask_configured` é `true` quando a soleira (PRES-02) está configurada e válida. `GET /api/video` (MJPEG): política final desligado por omissão (`ENABLE_DEV_VIDEO_PREVIEW=false`, PR #146) **e**, quando ligado (dev), só `operator` (PR #158); a rota mantém-se (remoção/adaptação: BASE-04).

## Contagem na porta (PRES-02) — IMPLEMENTADO (lógica testada com detetor falso)

`features/presence/{door,runner,yolo}.py`. Cadeia: `FonteVideo` → **recorte à soleira (o resto é descartado)**
(`recortar`: o detetor só recebe o recorte da soleira, uma cópia, e as caixas voltam ao frame inteiro) → `DetetorYoloPessoas` (YOLO11 só classe «pessoa» +
ByteTrack, extra `visao`, mesmos pesos `yolo11{s,n}.pt`) → `ContadorPorta` → `presence.door_crossed`
(`DoorCrossed`, `provenance.kind=inferred`, `origin` da fonte: SIMULADA com clip/telemóvel).

- Só liga com `VIDEO_SOURCE`, `PRESENCE_HOUSEHOLD_ID`, `PRESENCE_DETETOR`, `PRESENCE_DOOR_ROI` e
  `PRESENCE_DOOR_LINE` (coordenadas normalizadas 0–1 `x1,y1,x2,y2`) válidos. `PRESENCE_DOOR_INSIDE_SIGN`
  (`1`/`-1`) diz de que lado da linha orientada fica o interior (ver `door.py`). Ponto usado: os pés.
- Anti-dupla contagem: histerese à volta da linha (oscilar não conta); um cruzamento só é emitido
  após `PRESENCE_DOOR_CONFIRM_S` e, se a mesma pessoa voltar para trás nesse tempo, anulam-se; no mesmo
  sentido uma 2.ª passagem em `PRESENCE_DOOR_COOLDOWN_S` é ignorada (mesma pessoa em duas pistas;
  duas pessoas coladas contam como uma: **limitação conhecida, aceite para a demo**: preferimos contar a menos a inventar entradas).
- A soleira configura-se só por variáveis de ambiente, sem UI: **aceite para a demo**.
- `track_id` vive só em memória e é esquecido; pistas sem ID confirmado não contam. Visitas não são
  distinguidas aqui: são só mais passagens anónimas (o número de visitas é da PRES-05).
- `confidence` é a média da confiança do detetor nessa pessoa, **não** uma precisão medida.
- Sem frames novos não há eventos e nada daqui conclui «casa vazia». O código ObjectOS (`visao`,
  gestos) fica intacto e deixa de ser necessário neste caminho (remoção: BASE-04 #74).

## Pistas por pessoa (PRES-03) — IMPLEMENTADO

`features/presence/{wifi,repo,service,router,hostscan}.py`, migração `core/migrations/0200_presence_tables.sql` (convenção D-29, `02xx` = P2; tabelas `presence_device`, `presence_confirmation`, `presence_state` — a última é a da fusão, PRES-04).

**API** (todas com `?household_id=`; só inquilino com membership ativa; **senhorio e operador `403 forbidden_role`**, não-membro `404`; a pessoa é sempre a da sessão):

| Rota | Efeito |
|---|---|
| `GET /api/presence` | o **meu** `PersonPresence` (PRES-04); mais ninguém o vê |
| `GET /api/presence/devices` | os **meus** telemóveis (`PresenceDeviceView`) |
| `POST /api/presence/devices` | regista um telemóvel: `{label, wifi_address, consent: true}`; só guarda o hash; `409` se já registado ou acima de 5; `503` sem `PRESENCE_MATCH_SALT` |
| `DELETE /api/presence/devices/{id}` | opt-out: deixa de ser reconhecido de imediato e o hash é **apagado** (idempotente) |
| `POST /api/presence/wifi/observations` | só modo `ingest`; token de máquina (`X-Presence-Token`); fora do OpenAPI |

**Wi-Fi.** O morador regista o telemóvel com consentimento explícito; o MAC só existe em memória para calcular `match_key = HMAC-SHA256(PRESENCE_MATCH_SALT, MAC normalizado)` (nunca em base de dados, logs, eventos, respostas nem para o senhorio; o macOS omite zeros nos MACs, por isso normaliza-se antes de comparar). Um varrimento (ping à sub-rede + `ip neigh`/`arp -an`) produz MACs; os que não correspondem a um telemóvel registado com opt-in são **descartados sem rasto** (visitas, vizinhos; nem o hash fica). Quando um telemóvel registado **aparece** grava-se uma pista `in` (`wifi`, confiança 0,8, `real/inferred`; `simulated/inferred` com o scanner falso); a **ausência nunca grava nada**, e um varrimento falhado também não. Cadência: pista ao reaparecer (mínimo 60 s entre pistas) e renovação a cada 5 min enquanto visto. A pista Wi-Fi exige **dois consentimentos**: `PresenceDevice.wifi_opt_in` (o telemóvel) **e** `Membership.presence_opt_in` (a pessoa) e um interruptor global `PRESENCE_WIFI_COLLECTION_ENABLED` (omissão `false`, alinhado com o PRIV-02 #146). Sem qualquer um, as observações desse telemóvel são descartadas sem rasto. A verificação faz-se na mesma transação que grava o evento (a revogação tem efeito imediato). A resposta à pergunta «estás em casa?» e o aparelho a ligar exigem também `Membership.presence_opt_in`.

**Modos** (`PRESENCE_WIFI_MODE`, omissão `off`): `simulated` (scanner falso, MACs fictícios em `PRESENCE_WIFI_SIM_ADDRESSES`; **SIMULADO**), `arp` (o backend varre a rede; só no anfitrião), `ingest` (o varrimento corre no anfitrião e envia hashes: `make presence-wifi-scan`). Sub-rede em `PRESENCE_WIFI_SUBNET` (só privada, até /22), intervalo em `PRESENCE_WIFI_INTERVAL_S` (≥ 10 s, omissão 30).

**Docker no macOS/Windows: o varrimento NÃO funciona no contentor.** O Docker Desktop corre os contentores numa VM com rede virtual NAT: o contentor não vê a tabela ARP do anfitrião (só o gateway virtual) e a imagem do backend nem traz `ping`/`ip`/`arp` (verificado: 0 aparelhos). Por isso, com Docker, usar `PRESENCE_WIFI_MODE=ingest` e correr `make presence-wifi-scan` no anfitrião ligado ao Wi-Fi do hub; o processo calcula os hashes com o mesmo sal e envia só hashes ao backend (`POST /api/presence/wifi/observations`, token em `app/.env`). A rota é a única de `/api/*` sem JWT (autenticação de máquina por token; desligada sem token).

**Evidência do varrimento real.** Medição pontual (17/11/2026, macOS, /24 doméstica real, só leitura): 16 aparelhos vistos em ~12 s com o código de `wifi.py` (`ArpScanner`). Não é a validação do kit: PRW-01…03 do [guia](../development/guia-validacao-manual.md) por executar.

**Resposta a «estás em casa?».** O consumidor `presence.answers` lê `notification.responded` com `ref.type=presence_check`: só aceita respostas a pedidos que presence emitiu (`presence_confirmation`), do próprio morador, uma única vez, com ação `in`/`out`; exige `Membership.presence_opt_in` e grava a pista `manual` (origem herdada da resposta). É a única pista `manual`: resposta a uma pergunta do sistema, não um check-in voluntário. Os pedidos passam a ser emitidos pela fusão (PRES-04).

**Pontos em aberto.** P-19: a resposta à pergunta fica `real/measured` (o que o contrato já faz). `PresenceMeIn` e `PresenceSource.manual` mantêm-se no contrato (a `PresenceMeIn` sem uso; mudança de contrato é com P5). Alinhado com o PRIV-02 #146 (decisão do dono): `Resource.presence` leitura `own`, `presence_wifi_collection_enabled` e os dois consentimentos. Sem dependência do código do #146 (`privacy.py`): ordem de merge, #146 primeiro e este PR faz rebase (conflitos esperados e triviais em `config.py`, `access.py`, `test_authorization.py`, `features/presence/__init__.py`). A retenção dos eventos de pista (P-20) mantém-se por decidir.

## Fusão (PRES-04) — IMPLEMENTADO

`features/presence/fusion.py` (lógica **pura**, `now` injetado) + consumidores em `service.py`. Estado por morador: `PersonPresence` (`in`/`out`/`uncertain`, `since`, `confidence`, `provenance`, `sources`, `reason`).

| Entrada | Tratamento |
|---|---|
| `presence.cue_recorded` (`wifi`, `manual`, `appliance`) | recalcula o morador da pista |
| `presence.door_crossed` (anónimo; PRES-02, hoje só fixtures) | reavalia **todos** os moradores da casa (a câmara não sabe quem) |
| `energy.consumption_detected` com `appliance_owner_resident_id` | consumidor `presence.appliance`: pista `in` (`appliance`, 0,6, `consumption_event_id`) **só se o aparelho ligou há menos de `PRESENCE_APPLIANCE_FRESH_S`** (300 s); um que já estava ligado (PC esquecido) não prova nada; uma pista por consumo |
| `notification.responded` (`presence_check`) | pista manual (PRES-03) |
| passagem do tempo | *ticker* (`PRESENCE_FUSION_TICK_S`, 30 s): a tolerância passa sem eventos |

**Regras.** (1) Wi-Fi e aparelho a ligar contam a favor; a ausência de pistas não conta contra: um telemóvel «a dormir» (10 min, ou horas) sem passar a porta **continua `in`** (a confiança desce a 0,6 passada a tolerância). (2) **`out`** só por saída pela porta (`presence.door_crossed`, sentido `out`, confiança ≥ 0,5) seguida de `PRESENCE_TOLERANCE_MIN` minutos (20–30, omissão **25**) sem nenhuma pista **desse** morador (única exceção: a resposta «não» à pergunta «estás em casa?», para resolver uma contradição); durante a tolerância continua `in` (confiança 0,5, fonte `camera_door`); uma pista dele refuta a saída (era de outra pessoa). (3) A saída pela porta é **anónima**: só se atribui ao morador se o silêncio do seu Wi-Fi é informativo (telemóvel com opt-in **e** varrimento vivo: um varrimento bem-sucedido nos últimos 3 intervalos) ou, sem Wi-Fi, se mais ninguém está `in`. Caso contrário o estado é `uncertain/no_recent_cues` + pergunta, **nunca `out`**: uma falha do Wi-Fi ou da câmara não vira «fora». (4) **Contradição** → `uncertain/conflicting_cues`: uma pista Wi-Fi ou de aparelho depois de o morador estar «fora» sem nenhuma entrada pela porta (a entrada vale desde que ele saiu até 120 s depois da pista). Só a resposta à pergunta (ou a entrada pela porta) a resolve. (5) Sem nenhuma pista → `uncertain/no_recent_cues` na API (nunca se grava nem se publica); a porta sozinha nunca cria um estado.

**Saídas.** `presence.changed` (`PersonPresence`) só quando o estado ou a razão mudam; `presence.confirmation_needed` (`PresenceConfirmationRequest`: só `id`, `resident_id`, `reason`, `expires_at`, validade 30 min) quando há dúvida, no máximo um por morador por 30 min (`presence_confirmation`). P3 transforma-o em notificação pessoal «estás em casa?» (`notifications.presence_check`, APP-02, **IMPLEMENTADO** no backend); a resposta volta por `notification.responded`.

**API.** `GET /api/presence?household_id=` devolve **só o próprio** `PersonPresence` (decisão do dono, alinhada com o PRIV-02 #146: nem colegas, mesmo com `presence_opt_in`); senhorio e operador `403`. Os outros módulos (regra C da P4) recebem o estado por eventos `presence.changed`. **Privacidade:** nada de imagens; o senhorio nunca vê presença nem horários; as pistas e os estados só têm origem em Wi-Fi/aparelho/declaração/porta anónima.

**Consentimento.** Todas as pistas individuais (Wi-Fi, aparelho a ligar, resposta à pergunta) exigem `Membership.presence_opt_in`; o Wi-Fi exige também `wifi_opt_in`. `apply_fusion` não grava estado de quem não tem opt-in. **Câmara em baixo:** caso por tratar (decisão do dono); a fusão limita-se a não inventar «fora» sem saída pela porta.

**Provenance.** `simulated` se qualquer entrada for simulada; `inferred` quando decide a porta ou o tempo; `measured` só quando o estado vem só de uma resposta do morador (P-19).

**Decisões para a demo (aceites pelo dono).** Varrimento Wi-Fi parado (3 intervalos) com telemóvel registado → pergunta (`uncertain/no_recent_cues`), nunca `out`; saída anónima com vários moradores `in` e sem Wi-Fi → pergunta; único `in` → a saída atribui-se-lhe (limite: uma visita a sair engana-o até à PRES-05).

**Limites assumidos.** Com vários moradores em casa e sem Wi-Fi uma saída pela porta nunca fica atribuída (pergunta-se). Um telemóvel que fica em casa com o dono «fora» e Wi-Fi ativo mantém a dúvida (volta a perguntar de 30 em 30 min). A fusão lê as pistas das últimas 48 h. Os parâmetros (0,6; 0,5; 120 s; 30 min) **não estão medidos**: valores iniciais.

## Limites reais

- Acesso à imagem da câmara do kit (MEARI) **não está provado** para este caso de uso: só há leitura RTSP de 10 min via relay (medição herdada, ver [altice-mcp.md](../integrations/altice-mcp.md)) e a câmara do kit é fixa. Plano B: telemóvel como câmara IP ou clip gravado — dito sempre como tal.
- A deteção de objetos YOLO e o gesto não estão validados com a câmara real; **não são necessários** para a Conta Certa.
- A contagem na porta, a fusão e a precisão **não estão medidas**; nenhum valor de precisão pode aparecer em documentos ou pitch antes de medido.

## Ficheiros existentes reutilizáveis

`features/video/*`, `features/visao/{detetor,thread,dispositivo,pesos,anotar}.py`, `features/gestos/{ponte,presenca}.py`, `contracts/{video,visao,base}.py`, `connectors/…` (nenhum). Ver destinos em [migration.md](../architecture/migration.md).

## Ficheiros novos previstos

`features/presence/{door,fusion,router,service,tests}` (`router`, `service`, `repo`, `wifi`, `hostscan`, `fusion` já existem; `door` é da PRES-02), `contracts/presence.py`. Pesos YOLO e `torch` continuam fora do Docker e do CI (extra `visao`).

## Dependências

P5 (`households`, barramento), P3 (UI e notificações de «estás em casa?»). Alimenta P4 (regra C, esquecidos).

## Critérios de aceitação

- Com um clip ou um detetor falso, N passagens na linha produzem N `DoorCrossed` com o sentido certo e **zero** imagens persistidas (teste que varre o diretório de dados).
- Telemóvel «a dormir» 10 min sem passar a porta continua «em casa» (PDF §21).
- Sair pela porta e passar a tolerância → «fora»; contradição → «incerto».
- O senhorio recebe `403 forbidden_role` em todas as rotas de presença.

## Testes

Lógica pura com detetor falso e relógio simulado (como em `gestos/tests`); nunca YOLO real, rede ou câmara em `pytest`. Câmara real: [guia de validação](../development/guia-validacao-manual.md) (VID-01…03, YOLO-01/02).

## PRIV-02 #119 — Investigação e arquitetura de privacidade (17/11/2026)

**Estado:** RECOMENDAÇÃO técnica para MVP; controlos em código identificados como IMPLEMENTADOS abaixo. **Não é parecer jurídico nem declaração de conformidade com RGPD.** Consultar o documento Conta Certa v5.1 §§5, 6.8, 10 e 21; contratos F0 `contracts/presence.py`; matriz em `core/access.py`; fluxo real de vídeo em `features/video/{router,service,fonte}.py`.

### Avaliação comparada (A/B/C)

Pontuação qualitativa de **1 (inadequado) a 5 (favorável)**; pesos refletem proporcionalidade ao objetivo de atribuir consumos e explicar dúvidas na casa partilhada. **Não são medições de precisão nem validação de campo.** A questão jurídica é um critério de incerteza, não uma conclusão de legalidade.

| Critério (peso %) | A Manual | B Câmara efémera | C Câmara + Wi-Fi voluntário |
|---|---:|---:|---:|
| Baixa intrusividade (15) | 5 | 3 | 2 |
| Minimização de dados (10) | 4 | 4 | 2 |
| Baixo risco de reidentificação indireta (10) | 5 | 3 | 1 |
| Proteção de visitantes (10) | 5 | 3 | 2 |
| Segurança e superfície de ataque (10) | 5 | 3 | 2 |
| Robustez perante erros humanos/técnicos (8) | 3 | 3 | 3 |
| Independência de hardware (7) | 5 | 2 | 1 |
| Manutenção (5) | 5 | 2 | 1 |
| Precisão realista para a finalidade (5) | 2 | 3 | 4 |
| Desativação e revogação (5) | 5 | 4 | 2 |
| Adequação ao MVP (5) | 5 | 3 | 1 |
| Menor incerteza jurídica (10) | 4 | 2 | 1 |
| **Total ponderado (/5)** | **4,49** | **2,93** | **1,81** |

- **A — recomendada:** morador opta pela presença e declara «cheguei/saí» na aplicação. Falhas e esquecimentos tornam o estado **incerto**, nunca «fora» por omissão. Não há prova independente de quem atravessou a porta. Não é fonte obrigatória para faturação: as regras **igual** ou **perguntar** continuam a funcionar.
- **B — evolução experimental condicionada:** detetor local, apenas região da soleira mascarada *antes* da inferência, contagem anónima e passageira. Frames só em RAM e descartados; nenhuma imagem é enviada à API ou cliente. Sem identidade, sem armazenamento de `track_id`, sem rosto, pose identificadora ou embeddings. O timestamp e a correlação com outros dados podem ainda ser dados pessoais. Processamento local **não elimina** a aplicação potencial do RGPD nem substitui finalidade, base legal, transparência, segurança e direitos. A precisão não foi medida. Instalação, enquadramento legal, informação a moradores e visitantes, ameaça de exfiltração e retenção têm de ser revistos antes de captar pessoas reais.
- **C — não ativar no MVP/piloto sem revisão:** Wi-Fi voluntário fornece no máximo uma **pista positiva**, não prova de saída; falhas de cobertura, MAC aleatório, standby e telemóveis partilhados afetam inferência. Não ligar nomes, MAC, IP ou identificadores do AP a eventos publicados. Uma eventual tabela de correspondência fica separada, cifrada, com acesso próprio e eliminação imediata à revogação, após desenho e revisão próprios da PRES-03. Não existe coletor Wi-Fi implementado.

**Alternativa sem câmara:** A, com confirmação de consumos na app e fallback A (igual). Presença não é requisito para fechar a fatura; se a regra C da conta depender de informação insuficiente, nunca presumir quem estava em casa. Sem sensor: `uncertain`, não `out`. O senhorio não pode exigir opt-in como condição de acesso às funções base.

### Fluxo de dados e trust boundaries

```mermaid
flowchart LR
    R["Morador autenticado (Authentik)"] --> O["PATCH /households/{id}/memberships/{id}: opt-in próprio"]
    O --> DB["SQLite membership.presence_opt_in (default false)"]
    R -. "Futuro PRES-03: declaração manual" .-> G["Verificação por casa / role / opt-in atual / identidade do token"]
    W["Wi-Fi local (DESATIVADO)"] -. "só pista positiva, sem MAC/IP no evento" .-> G
    G -->|na mesma transação da escrita futura| E["Evento de presença pessoal tipado / estado limitado"]
    C["Câmara local (DESATIVADA por omissão)"] -. "Futuro PRES-02: ROI mascarada em RAM" .-> X["Contagem anónima DoorCrossed"]
    X -. "Sem frames e só depois de aprovação" .-> EV["Evento de passagem, sem resident_id"]
    E --> P["Consumidores autorizados: morador próprio / motores internos mínimos"]
    EV --> P
    U["Vídeo legado /api/video"] --> D["404 incondicional; sem dependência de fonte"]
```

**Controlos técnicos implementados nesta revisão:** `GET /api/video` responde sempre `404`, mesmo com `ENABLE_DEV_VIDEO_PREVIEW=true`; o endpoint já não declara a dependência `Fonte`, pelo que uma tentativa recusada não pode abrir a fonte antes do gate. O lifespan de vídeo não inicia captura. RTSP/URL e ficheiros fora de `app/data/privacy-test-clips` são recusados por `get_fonte`; o processamento de clips exige simultaneamente `PROFILE=demo`, a flag de clip e `HOME_BACKEND=fake`. Isto é uma barreira de desenvolvimento, não autorização para recolher dados reais. A máscara da soleira e a contagem não estão implementadas. As ferramentas CLI antigas de medição continuam fora da API e não são um caminho suportado para recolha de presença.

**A fronteira das pistas pessoais hoje:** `individual_cue_allowed` verifica casa, membership de tenant ativa, datas no fuso da casa, opt-in atual e identidade autenticada para origem manual; recusa proveniência simulada numa casa real. `record_individual_cue` exige transação SQLite ativa, repete a validação e grava o evento na mesma transação. `BEGIN IMMEDIATE` ordena essa escrita com a revogação concorrente: se a revogação confirmar primeiro, a pista é recusada. Wi-Fi é recusado mesmo que a flag global esteja ativa: `PresenceDevice.wifi_opt_in` não tem ainda persistência consultável, e `membership.presence_opt_in` não o substitui. Não existe produtor ou recolha real. Esta interface é **IMPLEMENTADA**, mas não prova legitimidade de base legal nem constitui uma integração de produto.

**Exposição ObjectOS legada:** `/api/state` e mensagens `home_state` em `/api/ws` já não publicam o booleano de presença (`null` até substituição por DTO com escopo de casa e papel); as transições explícitas “Entrou alguém/Divisão vazia” deixaram de ser escritas no `events.jsonl`. A API antiga não conhece uma casa nem papel do utilizador, portanto não pode servir presença individual. Os outros campos do motor continuam sendo legado autenticado e não são uma API Conta Certa; um futuro endpoint deve usar `require_access(Resource.presence, read)` e devolver apenas o estado do próprio morador. A UI ObjectOS deixa de tentar obter MJPEG e mostra que a captura está desativada.

### Modelo de ameaças — estado após hardening PRIV-02

Escalas: gravidade (G) e probabilidade (P) são **antes das correções**; residual descreve os controlos atuais e as lacunas que permanecem. Estimativas qualitativas para a configuração atual, não certificação nem avaliação jurídica.

| Ameaça | G | P | Evidência / controlo técnico | Risco residual |
|---|---|---|---|---|
| Senhorio ou funcionário curioso consulta estado de morador | Alta | Média | `Resource.presence.read=own`; senhorio/operador sem grant; nenhum endpoint novo de presença | Médio: API legada não é escopada por casa/papel; não usar para presença individual |
| Morador consulta presença de terceiro | Alta | Média | grant `own`; membership e `resident_id` vinculados à casa; evento manual compara actor | Baixo no gate; endpoint de leitura continua planeado |
| Captura/extração de frames por MJPEG | Crítica | Média | `/api/video` sempre 404; nenhuma dependência `Fonte`; factory RTSP rejeitada; ferramentas de medição exigem clip sintético allowlisted | Baixo no serviço; classe RTSP permanece no módulo para testes unitários com capturas falsas |
| Correlacionar timestamp de passagem com identidade | Alta | Média | nenhum evento de câmara por pessoa; `DoorCrossed` anónimo; sem feed público | Médio se B for criado: timestamps continuam potencialmente pessoais |
| Reidentificação indireta por contagem, quarto, energia ou rotina | Alta | Média | sem endpoint de ocupação/série temporal; landlord não recebe presença | Médio; minimização e agregação devem ser validadas no desenho PRES-02/05 |
| Segredo RTSP em exceção ou logs | Alta | Baixa | fonte regista apenas tipo da exceção; endpoint responde mensagem genérica; teste injeta URL falsa com credenciais | Baixo para logs FastAPI revistos; observar logs de OpenCV/FFmpeg no deployment antes de piloto |
| Presença em REST/WS sem autorização por papel | Alta | Média | booleano legado removido do DTO/WS; evento textual explícito removido de `events.jsonl` | Médio: estados e timestamps do motor legado ainda não são DTOs escopados; não ligá-los a fonte real |
| Persistência por tempo excessivo | Alta | Alta após futura escrita | eventos F0 append-only; PRIV-02 não apaga nem migra eventos | Alto até P-08/P-20 e política separada, incluindo backups |
| Falha de sensor interpretada como ausência | Alta | Média | função automática devolve `uncertain`; Wi-Fi nunca infere `out` | Baixo no helper; produtor/fusão ainda não implementados |
| Casa errada ou membership revogada | Alta | Média | query usa `household_id`, papel tenant, status active e datas; validação e escrita transacionais | Baixo no helper; futuras rotas devem reusar `core.access`/OIDC |
| Configuração de desenvolvimento ativa em produção | Alta | Média | preview MJPEG inexiste; clip exige `PROFILE=demo`, flag, path allowlist e `HOME_BACKEND=fake`; RTSP recusado | Baixo para API; deployment ainda deve validar env e remover credenciais RTSP não usadas |
| Consentimento revogado, mas histórico continua | Alta | Média | novas gravações consultam opt-in no mesmo commit SQLite | Alto para histórico: sem expurgo implementado; requer política aprovada e issue própria |

### Modelo de privacidade e acessos

**Finalidades separadas:** (1) declaração voluntária para ajudar o morador a corrigir atribuição de consumo (MVP); (2) eventual contagem **não identificada** de entradas/saídas na soleira para contexto de uma casa (F2, sob revisão); (3) eventual pista positiva do telemóvel para presença própria (F2, sob revisão). Não reutilizar qualquer dado para vigilância laboral, cobrança punitiva, verificação disciplinar ou rastreio de rotinas.

**Dados mínimos:** para A: `household_id`, `resident_id`, `state`, `ts`, `source=manual`, proveniência e preferência; B (se aprovado): sentido e timestamp com resolução mínima necessária e proveniência, sem identidade; C (se aprovado): *cue* positivo por morador aderente, sem identificador de rede no evento. **Proibido:** vídeo/fotogramas em disco, armazenamento de imagem/áudio, reconhecimento facial, embeddings biométricos, persistência de `track_id`, serialização de `numpy.ndarray`, IP/MAC/SSID em eventos ou logs e perfis de visitas.

| Perfil | Preferência própria | Estado individual | Passagens anónimas | Imagens / logs brutos |
|---|---|---|---|---|
| Morador aderente | Ler/alterar só a sua | **Só o seu**, se ativo | Nenhum feed público; apenas agregado necessário sob decisão | Não |
| Morador não aderente | Ler/alterar só a sua | Não criar pistas pessoais | Não identificar; não reduzir direitos | Não |
| Outros moradores | Não | Não (regra `Resource.presence.read=own`) | Não expor horários de passagens | Não |
| Senhorio | Não pode editar preferências alheias | **Não**, mesmo da sua casa | Não | Não |
| Operador | Não | Não; só diagnóstico técnico não pessoal | Não | Não |
| Serviço interno P2/P4 | Apenas autorização mínima por finalidade, auditada | Só dados necessários e dentro da casa | Só quando habilitado | Nunca |

**IMPLEMENTADO no F0:** `membership.presence_opt_in` com default `false` e PATCH pelo próprio tenant; `Resource.presence` nega senhorio e operador; isolamento por casa. **Endurecido nesta issue:** leitura `presence` do tenant passa de `household` para **`own`**; nenhuma rota nova de leitura permite contornar isto. Sem qualquer opt-in, não publicar pista individual. A revogação é eficaz para **novas** pistas no predicado, mas não apaga automaticamente histórico antigo. Alterar preferência não é ainda um registo de consentimento juridicamente suficiente.

**Visitantes e não aderentes:** nunca são associados a moradores nem sequer quando a câmara indica entrada simultânea com um telemóvel. Podem originar só contagem anónima após autorização do módulo B. Um visitante pode permitir reidentificação por contexto; por isso não expor série temporal de passagens à casa e definir granularidade/retention. Sem opt-in, nenhuma pista pessoal e nenhuma penalização financeira por não adesão; aplicar confirmação ou divisão igual. Nunca inferir `out` apenas por ausência de rede.

**Falhas:** câmara desligada/sem frames ou Wi-Fi indisponível = `unknown/uncertain` na inferência automática. Não reutilizar cegamente o último estado como medição atual. UI deve informar «presença indisponível/incerta» sem atribuir uma saída. A app e o cálculo base funcionam com `VIDEO_SOURCE` vazio e sem Wi-Fi. A demonstração deve identificar `origin=simulated` e não apresentar contagens reais.

### Transparência, retenção e auditoria — PROPOSTA, não implementada

| Categoria | Prazo inicial **a validar** | Nota |
|---|---|---|
| Frames de B | **0 segundos de persistência** | Apenas RAM; libertação após inferência; sem dump/capture/debug em disco |
| Contagens por passagem B | 24 horas no máximo | Preferir agregado sem horários; evitar individualização |
| Pistas de presença pessoal A/C | Até 7 dias após deixar de ser necessárias para confirmação | Se influenciar fatura/contestação, justificar e separar o histórico imprescindível |
| Estado atual | Até substituição ou expiração do sinal | Incerto se não houver evidência recente |
| Auditoria de opt-in/revogação | 30 dias propostos | Apenas membership, ação booleana, UTC, propósito e ator autenticado, sem IP/MAC/frame |
| Totais financeiros/decisões | Prazo próprio da faturação sujeito a revisão | Não reter presença crua para explicar dinheiro se bastar registar razão e proveniência |

**Bloqueio real:** `domain_event` é imutável e **não tem expurgo**; a tabela atual não implementa estes prazos. Não apagar eventos financeiros nem alterar triggers/migrações nesta issue. Proposta separada: abrir issue **F0 — retenção por categoria de dados pessoais**, ligada a P-08/P-20, para definir armazenamento segregado/expiração seletiva de dados de presença e respetiva política de backups sem eliminar evidência financeira. Não encontrei issue GitHub existente dedicada; a issue deverá ser criada antes do piloto. Enquanto isso: só fixtures sintéticas. Uma revogação bloqueia novas recolhas, mas não apaga histórico nem dados de correspondência Wi-Fi.

**Informação na aplicação:** antes de ativar, explicar por finalidade e por fonte o que é/ não é recolhido, quem vê, se influencia divisão, como optar/revogar, retenção efetiva, contacto do responsável (por confirmar), direitos e política de visitas; consentimento, quando escolhido como fundamento, deve ser granular e livre. Mostrar estado da câmara e opção de desativação; nunca substituir transparência por uma flag técnica.

**Aviso à entrada (RASCUNHO, não afixar sem revisão):**

> Projeto experimental Conta Certa. A deteção de passagens por câmara está atualmente **desativada**. Se algum dia for ativada, será anunciado previamente: processamento local da soleira para contagem de entradas/saídas, sem gravação e sem identificação por imagem, sujeito a informação completa e aprovação. Para questões sobre privacidade, contacte o responsável identificado no aviso final a disponibilizar antes do piloto.

### Questões jurídicas e bloqueios antes de piloto real

| Categoria | Estado | O que significa |
|---|---|---|
| **Controlo técnico implementado** | API MJPEG 404, RTSP recusado, clips sintéticos allowlisted, gate transacional para escrita manual, Wi-Fi recusado, `presence` legado oculto em REST/WS | Reduz caminhos técnicos; não prova licitude nem garante eliminação histórica |
| **Decisão de produto proposta** | A manual como base; B experimental sob condições; C desligada; sem penalização por não aderir; sem uso punitivo | Exige aprovação de produto e dos responsáveis antes de ligar produtores ou sensores |
| **Obrigação sujeita a revisão jurídica** | finalidade e base legal, informação a moradores/visitas, responsável, direitos, retenção, avaliação AIPD e limites legais para câmaras | Não existe parecer jurídico nem certificação de conformidade RGPD nesta issue |

- **Responsável pelo tratamento e subcontratantes:** distinguir equipa demonstradora, prestador, senhorio, administração do imóvel e eventual router/operador; decidir quem define finalidades e meios. Não afirmar que o senhorio é automaticamente o responsável nem pressupor a exceção doméstica.
- **Bases legais:** separar declaração manual, tratamento do contrato/atribuição, contagem por câmara e pista Wi-Fi. Consentimento não é a única base legal possível; quando usado, avaliar liberdade real em relação de arrendamento, informação, prova e retirada sem consequências. O documento v5.1 menciona «interesse legítimo» para câmara, mas **não existe teste de ponderação ou validação jurídica**. Não o tratar como conclusão.
- **AIPD e transparência:** realizar triagem documentada pela aplicação do artigo 35.º, avaliar a lista nacional da CNPD (Regulamento 798/2018), necessidade/proporcionalidade, alternativas menos invasivas, visitantes, captação de áreas comuns e riscos de correlação. Se exigida, finalizar a AIPD **antes** de recolher dados reais; se risco residual elevado, avaliar consulta prévia (art. 36.º). Rever sinalização/aviso com jurista.
- **Habitação partilhada e visitantes:** a orientação pública da CNPD sobre câmaras entre vizinhos restringe a captação à propriedade exclusiva e refere consentimento expresso dos moradores para videovigilância em condomínios. O enquadramento exato de uma casa arrendada/soleira tem de ser confirmado por jurista; não assumir que processamento local ou uma zona privada remove essas condições.
- **Câmara:** confirmar ângulo só para **interior da habitação**, sem rua, patamar, servidões nem entradas de terceiros; máscara ANTES da inferência, sem áudio; segurança local, updates, isolamento de rede e ausência de encaminhamento para cloud. O simples descarte de frames não garante anonimato jurídico.
- **Wi-Fi:** confirmar acesso real ao router/API, retenção de logs do fabricante, aleatorização de endereços MAC, falhas de rede, granularidade de opt-in, capacidade de revogar e eliminar correspondência. A flag `PRESENCE_WIFI_COLLECTION_ENABLED` fica **false** até contrato PRES-03 e validação externa.
- **Produto:** consentimento por fonte/finalidade (o booleano F0 não prova qual foi aceite), necessidade de visão dos demais moradores (este PR restringe a `own`), quorum/voto sobre câmara e as consequências de recusa, precisão e thresholds testados em ambiente autorizado.

**Referências oficiais consultadas (17/11/2026):**
- [RGPD, Regulamento (UE) 2016/679](https://eur-lex.europa.eu/eli/reg/2016/679/oj) — artigos 5, 6, 7, 12–14, 25, 28, 32, 35–36.
- [EDPB, Diretrizes 3/2019 sobre dispositivos de vídeo](https://www.edpb.europa.eu/documents/guideline/guidelines-32019-on-processing-of-personal-data-through-video-devices_pt) — legalidade, transparência e minimização.
- [EDPB, Diretrizes 05/2020 sobre consentimento](https://www.edpb.europa.eu/documents/guideline/guidelines-052020-on-consent-under-regulation-2016679_pt).
- [CNPD, videovigilância](https://www.cnpd.pt/organizacoes/areas-tematicas/videovigilancia/) — condições da captação.
- [CNPD, videovigilância por vizinhos](https://www.cnpd.pt/cidadaos/areas-tematicas/videovigilancia-por-vizinhos/) — limites para propriedade de terceiros, áreas comuns e habitação em condomínio.
- [CNPD, avaliação de impacto](https://www.cnpd.pt/organizacoes/outras-obrigacoes/avaliacao-de-impacto/) — triagem e consulta prévia.
- [CNPD, Regulamento 798/2018](https://www.cnpd.pt/decisoes/regulamentos/) — lista nacional AIPD.

### Testes e estado de entrega

**IMPLEMENTADO nesta revisão:** `Resource.presence.read=own`; `record_individual_cue` verifica e persiste atomicamente; Wi-Fi recusa mesmo com flag global ativa enquanto faltar consentimento persistido por dispositivo; RTSP e caminhos locais fora do allowlist de clip sintético são recusados pelo serviço e pelas ferramentas de medição; MJPEG sempre 404; visão demo não inicia com `HOME_BACKEND=mcp`; estado de presença legado é `null` no REST/WS e a transição explícita não é gravada no event log. Testes de casa, membership/data, opt-in/revogação, actor manual, sinal de falha, simulação, logs e payloads sem imagem.

**AINDA NÃO IMPLEMENTADO / não declarar PASS de integração:** processamento real da câmara; contagem na soleira; sensor de Wi-Fi; endpoint de presença manual; chamadas do predicado pelo futuro produtor PRES-03; retenção/expurgo, gestão de correspondência MAC, UI de consentimento granular, avisos finais e AIPD. Dependências: PRES-02 #106, PRES-03 #107, PRES-04 #108, HOUSE-02 #85, APP-01 #94 e revisão jurídica/PILOT. Não abrir captura real nesta tarefa.

**Integração exigida à PRES-03:** chamar `individual_cue_allowed(conn, cue, now=clock(), actor_resident_id=access.resident_id, wifi_collection_enabled=settings.presence_wifi_collection_enabled)` na **mesma transação** que persistir a pista, verificar novamente `presence_opt_in` em todas as leituras relacionadas e nunca gravar pistas reprovadas. Não usar cache de opt-in; cortar o coletor à revogação; ocultar rotas de diagnóstico do senhorio.

## PRIV-02 #119 — Complemento da P2: câmara, fontes alternativas e Wi-Fi (PROPOSTA / PLANEADO)

> **Âmbito:** só presença e câmara; completa a secção anterior (P5) sem a repetir. Aplica-se a ela quanto a finalidades, acessos, retenção (P-25 desse bloco, P-20), base legal e AIPD. **Não é parecer jurídico.** Código de PRES-01…04 ainda em PRs próprios; nada abaixo está na `main`.

### Decisões do dono (P2) refletidas aqui

1. **Presença individual visível só ao próprio morador.** Nenhum colega vê estados individuais; a fusão é usada **internamente** (ex.: regra C da conta da sala). Em linha com `Resource.presence.read=own`.
2. **Wi-Fi como pista exige os dois consentimentos:** `wifi_opt_in` no telemóvel (`PresenceDevice`) **e** `Membership.presence_opt_in`. Faltando um, a pista não entra.
3. **`GET /api/video` (MJPEG):** desligado por omissão (`ENABLE_DEV_VIDEO_PREVIEW=false`, #146); quando ligado em dev, só operador (PR #158, na `main`). O MJPEG serve o **frame completo, sem máscara**: a máscara de soleira só protege a entrada do detetor, não o que o MJPEG mostra. Por isso nunca se liga com a câmara real.

### Câmara: fonte de vídeo e pipeline (PLANEADO)

- **Fonte, por ordem:** (a) câmara do kit, **só leitura**, por app/link (acesso não provado, ver «Limites reais»); (b) plano B: telemóvel como câmara IP ou clip, **sempre rotulado SIMULADO** (`CameraStatus.origin`) na UI e no pitch; (c) sem câmara: só Wi-Fi, que nunca dá `out`; o caso «câmara em baixo» não é tratado por agora (decisão do dono).
- **Pipeline:** frame → máscara preta fora da soleira → `DetetorYolo` (só «pessoa») + ByteTrack → linha virtual → `DoorCrossed` (sentido, confiança) → frame descartado **a cada ciclo** do detetor. Só a soleira é analisada; sem reconhecimento facial; `track_id` nunca persistido; visitas só como número.
- **Teste exigido (PRES-02):** varrer o diretório de dados e falhar se existir qualquer imagem; nenhum evento com URL, caminho de frame ou identidade.
- Clips de desenvolvimento: só com consentimento de quem aparece, em `app/backend/data/` (fora do Git).
- **Operador** = suporte técnico: vê diagnóstico (`CameraStatus`), **nunca presença**; hoje não está limitado à sua casa (decisão para a demo, P-28).

### Wi-Fi: varrimento ping + ARP (PRES-03, PR #153, já na `main`)

- **Mecanismo:** varrimento ping + ARP numa sub-rede privada configurável (`PRESENCE_WIFI_SUBNET`; na demo, a rede do hub do kit). Recolha desligada por omissão (`PRESENCE_WIFI_COLLECTION_ENABLED=false`, #146).
- **Modo `ingest`:** o anfitrião calcula o HMAC de **todos** os MACs vistos e envia-os; o **backend descarta os não registados** (não persiste, não regista em logs).
- **`match_key`:** HMAC-SHA256 com **um segredo único da instalação** (`PRESENCE_MATCH_SALT`). É **pseudonimização**: quem tenha o segredo pode testar MACs conhecidos. Sal por casa: **PLANEADO**, não existe (P-30). O MAC em claro nunca sai em API.
- **Efeito na fusão:** presença Wi-Fi é pista a favor de `in`. A ausência de Wi-Fi **não renova** o `in` nem o passa a `uncertain`/`out`: só baixa a confiança (Wi-Fi nunca produz `out`, D-30). `out` só pela fusão (PRES-04, PR #159, já na `main`): saída pela porta + tolerância de 20–30 min, e só se a saída for atribuível ao morador (Wi-Fi esperado e vivo, ou nenhum outro morador em casa); caso contrário `uncertain` + pergunta «estás em casa?».
- **Consentimentos:** todas as pistas individuais (Wi-Fi, aparelho a ligar, resposta a «estás em casa?») exigem `presence_opt_in`; o Wi-Fi exige também `wifi_opt_in`.
- **`make presence-wifi-scan`** passa a respeitar `PRESENCE_WIFI_COLLECTION_ENABLED` (a corrigir no PR #153).
- **Revogação** (`DELETE /api/presence/devices/{id}`, PRES-03, PR #153, já na `main`; rotas de presença e o `403` ao senhorio idem): apaga o `match_key` e para novas pistas, mas **não apaga as pistas já gravadas**; `domain_event` é append-only sem expurgo (P-20, P-25 do bloco anterior).

### Plano sem câmara

A presença regista-se **só pela câmara (porta) e pelo Wi-Fi do telemóvel**; não há «cheguei/saí» manual na app (decisão do dono; em remoção no PR #153). Sem câmara, fica só o Wi-Fi, que nunca dá `out`: o estado fica `in` ou `uncertain`, com mais perguntas «estás em casa?» (a resposta mantém-se para resolver contradições). A regra C funciona com menos precisão, dito na UI.

### Informação a prestar e UI (PLANEADO)

Os textos abaixo são **rascunho — não usar até PRES-02 e #146 estarem implementados e validados**; a rever por P5 e jurista (P-24 do bloco anterior; inclui o aviso e o pictograma).

- **Aviso à entrada (visitantes e moradores), rascunho:** «Nesta porta há um sensor ótico que conta entradas e saídas. Não grava nem guarda imagens e não identifica pessoas. Só a pessoa que vive na casa vê o seu próprio estado.»
- **Moradores, rascunho:** finalidades, o que não acontece, como registar e retirar o telemóvel, que recusar não tem consequências.
- **UI (APP):** indicador «Câmara na porta: ativa/desligada · REAL/SIMULADO» (`CameraStatus`); lista de telemóveis com «Retirar»; interruptores separados para `wifi_opt_in` e `presence_opt_in`, com o aviso de que o Wi-Fi precisa dos dois.

### Base legal por finalidade — candidatas, por validar

Contagem na porta: interesse legítimo + votação da casa (PDF §10.2). Wi-Fi: consentimento (PDF §10.2). A resposta a «estás em casa?» é pedido do próprio: base candidata nossa, não consta do §10.2. Nenhuma está validada (P-24 do bloco anterior).
