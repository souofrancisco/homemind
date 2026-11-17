# Módulo `presence` — câmara na porta e presença

**Dono: P2 (1Mii).** **IMPLEMENTADO**: declaração manual, telemóveis com opt-in e pistas Wi-Fi, resposta a «estás em casa?» (PRES-03 #107) e fusão em casa/fora/incerto (PRES-04 #108). **PLANEADO**: câmara na porta (PRES-01/02; a fusão já consome `presence.door_crossed`, hoje só com fixtures), ocupação (PRES-05). Entidades: `PresenceEvent`, `PersonPresence` ([data-model.md](../architecture/data-model.md)).

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
| Registo manual «cheguei / saí» (`PUT /api/presence/me`, `PresenceMeIn`) — **IMPLEMENTADO** | `PresenceEvent(source=manual)` em `presence.cue_recorded` |
| Telemóveis registados no Wi-Fi com opt-in (`PresenceDevice.wifi_opt_in`) — **IMPLEMENTADO** | idem, `source=wifi` (só `in`) |
| `energy.consumption_detected` com `appliance_owner_resident_id` (P1) | idem, `source=appliance` (só `in`) |
| Resposta a «estás em casa?» (`notification.responded`, `ref.type=presence_check`, P3) — consumidor **IMPLEMENTADO**; o produtor (APP-02) **PLANEADO** | pista manual |
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

## Pistas por pessoa (PRES-03) — IMPLEMENTADO

`features/presence/{wifi,repo,service,router,hostscan}.py`, migração `core/migrations/0200_presence_tables.sql` (convenção D-29, `02xx` = P2; tabelas `presence_device`, `presence_confirmation`, `presence_state` — a última é a da fusão, PRES-04).

**API** (todas com `?household_id=`; só inquilino com membership ativa; **senhorio e operador `403 forbidden_role`**, não-membro `404`; a pessoa é sempre a da sessão):

| Rota | Efeito |
|---|---|
| `PUT /api/presence/me` | `PresenceMeIn` (`in`/`out`) → `PresenceEvent(source=manual)` em `presence.cue_recorded`; devolve o `PersonPresence` fundido |
| `GET /api/presence` | o **meu** `PersonPresence` (PRES-04); mais ninguém o vê |
| `GET /api/presence/devices` | os **meus** telemóveis (`PresenceDeviceView`) |
| `POST /api/presence/devices` | regista um telemóvel: `{label, wifi_address, consent: true}`; só guarda o hash; `409` se já registado ou acima de 5; `503` sem `PRESENCE_MATCH_SALT` |
| `DELETE /api/presence/devices/{id}` | opt-out: deixa de ser reconhecido de imediato e o hash é **apagado** (idempotente) |
| `POST /api/presence/wifi/observations` | só modo `ingest`; token de máquina (`X-Presence-Token`); fora do OpenAPI |

**Wi-Fi.** O morador regista o telemóvel com consentimento explícito; o MAC só existe em memória para calcular `match_key = HMAC-SHA256(PRESENCE_MATCH_SALT, MAC normalizado)` (nunca em base de dados, logs, eventos, respostas nem para o senhorio; o macOS omite zeros nos MACs, por isso normaliza-se antes de comparar). Um varrimento (ping à sub-rede + `ip neigh`/`arp -an`) produz MACs; os que não correspondem a um telemóvel registado com opt-in são **descartados sem rasto** (visitas, vizinhos; nem o hash fica). Quando um telemóvel registado **aparece** grava-se uma pista `in` (`wifi`, confiança 0,8, `real/inferred`; `simulated/inferred` com o scanner falso); a **ausência nunca grava nada**, e um varrimento falhado também não. Cadência: pista ao reaparecer (mínimo 60 s entre pistas) e renovação a cada 5 min enquanto visto. A pista Wi-Fi exige **dois consentimentos**: `PresenceDevice.wifi_opt_in` (o telemóvel) **e** `Membership.presence_opt_in` (a pessoa) e um interruptor global `PRESENCE_WIFI_COLLECTION_ENABLED` (omissão `false`, alinhado com o PRIV-02 #146). Sem qualquer um, as observações desse telemóvel são descartadas sem rasto. A verificação faz-se na mesma transação que grava o evento (a revogação tem efeito imediato). A declaração manual só exige membership ativa de inquilino.

**Modos** (`PRESENCE_WIFI_MODE`, omissão `off`): `simulated` (scanner falso, MACs fictícios em `PRESENCE_WIFI_SIM_ADDRESSES`; **SIMULADO**), `arp` (o backend varre a rede; só no anfitrião), `ingest` (o varrimento corre no anfitrião e envia hashes: `make presence-wifi-scan`). Sub-rede em `PRESENCE_WIFI_SUBNET` (só privada, até /22), intervalo em `PRESENCE_WIFI_INTERVAL_S` (≥ 10 s, omissão 30).

**Docker no macOS/Windows: o varrimento NÃO funciona no contentor.** O Docker Desktop corre os contentores numa VM com rede virtual NAT: o contentor não vê a tabela ARP do anfitrião (só o gateway virtual) e a imagem do backend nem traz `ping`/`ip`/`arp` (verificado: 0 aparelhos). Por isso, com Docker, usar `PRESENCE_WIFI_MODE=ingest` e correr `make presence-wifi-scan` no anfitrião ligado ao Wi-Fi do hub; o processo calcula os hashes com o mesmo sal e envia só hashes ao backend (`POST /api/presence/wifi/observations`, token em `app/.env`). A rota é a única de `/api/*` sem JWT (autenticação de máquina por token; desligada sem token).

**Evidência do varrimento real.** Medição pontual (17/11/2026, macOS, /24 doméstica real, só leitura): 16 aparelhos vistos em ~12 s com o código de `wifi.py` (`ArpScanner`). Não é a validação do kit: PRW-01…03 do [guia](../development/guia-validacao-manual.md) por executar.

**Resposta a «estás em casa?».** O consumidor `presence.answers` lê `notification.responded` com `ref.type=presence_check`: só aceita respostas a pedidos que presence emitiu (`presence_confirmation`), do próprio morador, uma única vez, com ação `in`/`out`; grava a pista manual (origem herdada da resposta). Os pedidos passam a ser emitidos pela fusão (PRES-04).

**Pontos em aberto.** P-19: a declaração manual fica `real/measured` (o que o contrato já faz). Alinhado com o PRIV-02 #146 (decisão do dono): `Resource.presence` leitura `own`, `presence_wifi_collection_enabled` e os dois consentimentos. Sem dependência do código do #146 (`privacy.py`): ordem de merge, #146 primeiro e este PR faz rebase (conflitos esperados e triviais em `config.py`, `access.py`, `test_authorization.py`, `features/presence/__init__.py`). A retenção dos eventos de pista (P-20) mantém-se por decidir.

## Fusão (PRES-04) — IMPLEMENTADO

`features/presence/fusion.py` (lógica **pura**, `now` injetado) + consumidores em `service.py`. Estado por morador: `PersonPresence` (`in`/`out`/`uncertain`, `since`, `confidence`, `provenance`, `sources`, `reason`).

| Entrada | Tratamento |
|---|---|
| `presence.cue_recorded` (`wifi`, `manual`, `appliance`) | recalcula o morador da pista |
| `presence.door_crossed` (anónimo; PRES-02, hoje só fixtures) | reavalia **todos** os moradores da casa (a câmara não sabe quem) |
| `energy.consumption_detected` com `appliance_owner_resident_id` | consumidor `presence.appliance`: pista `in` (`appliance`, 0,6, `consumption_event_id`) **só se o aparelho ligou há menos de `PRESENCE_APPLIANCE_FRESH_S`** (300 s); um que já estava ligado (PC esquecido) não prova nada; uma pista por consumo |
| `notification.responded` (`presence_check`) | pista manual (PRES-03) |
| passagem do tempo | *ticker* (`PRESENCE_FUSION_TICK_S`, 30 s): a tolerância passa sem eventos |

**Regras.** (1) Wi-Fi e aparelho a ligar contam a favor; a ausência de pistas não conta contra: um telemóvel «a dormir» (10 min, ou horas) sem passar a porta **continua `in`** (a confiança desce a 0,6 passada a tolerância). (2) **`out`** só por declaração manual (imediato) ou por saída pela porta (`presence.door_crossed`, sentido `out`, confiança ≥ 0,5) seguida de `PRESENCE_TOLERANCE_MIN` minutos (20–30, omissão **25**) sem nenhuma pista **desse** morador; durante a tolerância continua `in` (confiança 0,5, fonte `camera_door`); uma pista dele refuta a saída (era de outra pessoa). (3) A saída pela porta é **anónima**: só se atribui ao morador se o silêncio do seu Wi-Fi é informativo (telemóvel com opt-in **e** varrimento vivo: um varrimento bem-sucedido nos últimos 3 intervalos) ou, sem Wi-Fi, se mais ninguém está `in`. Caso contrário o estado é `uncertain/no_recent_cues` + pergunta, **nunca `out`**: uma falha do Wi-Fi ou da câmara não vira «fora». (4) **Contradição** → `uncertain/conflicting_cues`: uma pista Wi-Fi ou de aparelho depois de o morador estar «fora» sem nenhuma entrada pela porta (a entrada vale desde que ele saiu até 120 s depois da pista). Só uma declaração manual (ou a entrada pela porta) a resolve. (5) Sem nenhuma pista → `uncertain/no_recent_cues` na API (nunca se grava nem se publica); a porta sozinha nunca cria um estado.

**Saídas.** `presence.changed` (`PersonPresence`) só quando o estado ou a razão mudam; `presence.confirmation_needed` (`PresenceConfirmationRequest`: só `id`, `resident_id`, `reason`, `expires_at`, validade 30 min) quando há dúvida, no máximo um por morador por 30 min (`presence_confirmation`). P3 transforma-o em notificação pessoal «estás em casa?» (APP-02, **PLANEADO**); a resposta volta por `notification.responded`.

**API.** `GET /api/presence?household_id=` devolve **só o próprio** `PersonPresence` (decisão do dono, alinhada com o PRIV-02 #146: nem colegas, mesmo com `presence_opt_in`); senhorio e operador `403`. Os outros módulos (regra C da P4) recebem o estado por eventos `presence.changed`. **Privacidade:** nada de imagens; o senhorio nunca vê presença nem horários; as pistas e os estados só têm origem em Wi-Fi/aparelho/declaração/porta anónima.

**Provenance.** `simulated` se qualquer entrada for simulada; `inferred` quando decide a porta ou o tempo; `measured` só quando o estado vem só de uma declaração (P-19).

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
