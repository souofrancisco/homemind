# Módulo `presence` — câmara na porta e presença

**Dono: P2 (1Mii).** **PLANEADO**, exceto o estado da câmara (PRES-01) e a contagem na porta (PRES-02), **IMPLEMENTADOS** (ver abaixo), sobre `features/video` e `features/visao` existentes. Entidades: `PresenceEvent`, `PersonPresence` ([data-model.md](../architecture/data-model.md)).

## Responsabilidade

Saber **quando alguém entra ou sai** e, a partir daí, **quem está em casa** — sem reconhecer ninguém pela imagem. A identidade vem de fontes voluntárias (registo na aplicação; futuro: Wi-Fi com opt-in).

## Privacidade (inegociável, PDF §5.3 + [CLAUDE.md](../../CLAUDE.md))

- O vídeo é processado **localmente**; nunca se grava, regista ou envia um frame. Só saem eventos de texto.
- Sem reconhecimento facial nem identificação. `track_id` é efémero e nunca persistido.
- Só a soleira da porta é analisada; o resto da imagem é tapado a preto **antes** de qualquer inferência.
- O senhorio não tem acesso a imagens, entradas, saídas nem horários.
- A câmara só existe na casa se a casa decidir (votação: **PROPOSTA**, prioridade P2).
- Sem câmara, a presença funciona só com o registo manual e (futuro) Wi-Fi.

## Recebe / produz

| Recebe | Produz |
|---|---|
| Frames da câmara/clip (`features/video`, `FonteVideo`) | `DoorCrossed` (sentido, confiança), `presence.door_crossed` |
| Registo manual «cheguei / saí» (`PUT /api/presence/me`, `PresenceMeIn`) | `PresenceEvent(source=manual)` em `presence.cue_recorded` |
| Telemóveis registados no Wi-Fi com opt-in (`PresenceDevice.wifi_opt_in`) | idem, `source=wifi` (só `in`) |
| `energy.consumption_detected` com `appliance_owner_resident_id` (P1) | idem, `source=appliance` (só `in`) |
| Resposta a «estás em casa?» (`notification.responded`, `ref.type=presence_check`, P3) | pista manual |
| `sensor.reading_recorded` (contacto, fumo; P1) | `SafetyAlert` em `safety.alert_raised` (SAFE-01/03) |
| — | `presence.changed` por pessoa; `presence.confirmation_needed` (pistas em conflito); `presence.occupancy_changed` (anónimo; «casa possivelmente vazia» só na fase 2) |

Contratos novos (`PresenceMeIn`, `PresenceConfirmationRequest`, `HouseOccupancy`, `PresenceDevice`, `CameraStatus`, `SensorReading`, `SafetyAlert`): **PROPOSTA** (D-31), em `contracts/{presence,sensors,safety}.py`.

## Passos

| Passo | Descrição | Prioridade |
|---|---|---|
| 1 | Presença por registo manual na aplicação + eventos simulados de porta; permite à P4 testar a regra C e os esquecidos sem câmara | P0 (para destravar) |
| 2 | Detetor de pessoas na soleira (`DetetorYolo` só com a classe «pessoa» + ByteTrack) e linha virtual → `DoorCrossed` | P0 (PRES-02 #106) |
| 3 | Fusão de pistas por pessoa: em casa / fora / incerto, com tolerância de 20–30 min para ausências e confirmação pela porta (PDF §6.8) | P0 (PRES-04 #108) |
| 4 | Estado «casa vazia» e alerta de entrada com casa vazia — **fase 2** | P2 (F3: PRES-06 #131, SAFE-02 #115) |
| 5 | Sinal de presença por Wi-Fi (opt-in) e confirmação manual | P0 (PRES-03 #107) |

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
`door_mask_configured` é `true` quando a soleira (PRES-02) está configurada e válida. `GET /api/video` (MJPEG) mantém-se como estava.

## Contagem na porta (PRES-02) — IMPLEMENTADO (lógica testada com detetor falso)

`features/presence/{door,runner,yolo}.py`. Cadeia: `FonteVideo` → **máscara a preto fora da soleira**
(`mascarar`, sobre uma cópia, antes da inferência) → `DetetorYoloPessoas` (YOLO11 só classe «pessoa» +
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

## Limites reais

- Acesso à imagem da câmara do kit (MEARI) **não está provado** para este caso de uso: só há leitura RTSP de 10 min via relay (medição herdada, ver [altice-mcp.md](../integrations/altice-mcp.md)) e a câmara do kit é fixa. Plano B: telemóvel como câmara IP ou clip gravado — dito sempre como tal.
- A deteção de objetos YOLO e o gesto não estão validados com a câmara real; **não são necessários** para a Conta Certa.
- A contagem na porta, a fusão e a precisão **não estão medidas**; nenhum valor de precisão pode aparecer em documentos ou pitch antes de medido.

## Ficheiros existentes reutilizáveis

`features/video/*`, `features/visao/{detetor,thread,dispositivo,pesos,anotar}.py`, `features/gestos/{ponte,presenca}.py`, `contracts/{video,visao,base}.py`, `connectors/…` (nenhum). Ver destinos em [migration.md](../architecture/migration.md).

## Ficheiros novos previstos

`features/presence/{door,fusion,router,service,tests}`, `contracts/presence.py`. Pesos YOLO e `torch` continuam fora do Docker e do CI (extra `visao`).

## Dependências

P5 (`households`, barramento), P3 (UI e notificações de «estás em casa?»). Alimenta P4 (regra C, esquecidos).

## Critérios de aceitação

- Com um clip ou um detetor falso, N passagens na linha produzem N `DoorCrossed` com o sentido certo e **zero** imagens persistidas (teste que varre o diretório de dados).
- Telemóvel «a dormir» 10 min sem passar a porta continua «em casa» (PDF §21).
- Sair pela porta e passar a tolerância → «fora»; contradição → «incerto».
- O senhorio recebe `403 forbidden_role` em todas as rotas de presença.

## Testes

Lógica pura com detetor falso e relógio simulado (como em `gestos/tests`); nunca YOLO real, rede ou câmara em `pytest`. Câmara real: [guia de validação](../development/guia-validacao-manual.md) (VID-01…03, YOLO-01/02).
