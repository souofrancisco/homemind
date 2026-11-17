# Módulo `presence` — câmara na porta e presença

**Dono: P2 (1Mii).** **IMPLEMENTADO** (PRES-03 #107): telemóveis com opt-in, pistas Wi-Fi e resposta a «estás em casa?». **Não há check-in manual «cheguei/saí»**: a presença regista-se só pela câmara (porta) e pelo telemóvel no Wi-Fi (decisão do dono). **PLANEADO**: câmara na porta (PRES-01/02), fusão (PRES-04 #108), ocupação (PRES-05). Entidades: `PresenceEvent`, `PersonPresence` ([data-model.md](../architecture/data-model.md)).

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
| Resposta a «estás em casa?» (`notification.responded`, `ref.type=presence_check`, P3) — consumidor **IMPLEMENTADO**; o produtor (APP-02) **PLANEADO** | pista manual |
| `sensor.reading_recorded` (contacto, fumo; P1) | `SafetyAlert` em `safety.alert_raised` (SAFE-01/03) |
| — | `presence.changed` por pessoa; `presence.confirmation_needed` (pistas em conflito); `presence.occupancy_changed` (anónimo; «casa possivelmente vazia» só na fase 2) |

Contratos novos (`PresenceMeIn`, `PresenceConfirmationRequest`, `HouseOccupancy`, `PresenceDevice`, `CameraStatus`, `SensorReading`, `SafetyAlert`): **PROPOSTA** (D-31), em `contracts/{presence,sensors,safety}.py`.

## Passos

| Passo | Descrição | Prioridade |
|---|---|---|
| 1 | ~~Registo manual «cheguei/saí»~~ — **removido** (decisão do dono); eventos simulados de porta + Wi-Fi permitem à P4 testar a regra C | — |
| 2 | Detetor de pessoas na soleira (`DetetorYolo` só com a classe «pessoa» + ByteTrack) e linha virtual → `DoorCrossed` | P0 (PRES-02 #106) |
| 3 | Fusão de pistas por pessoa: em casa / fora / incerto, com tolerância de 20–30 min para ausências e confirmação pela porta (PDF §6.8) | P0 (PRES-04 #108) |
| 4 | Estado «casa vazia» e alerta de entrada com casa vazia — **fase 2** | P2 (F3: PRES-06 #131, SAFE-02 #115) |
| 5 | Sinal de presença por Wi-Fi (opt-in) e resposta à pergunta «estás em casa?» | P0 (PRES-03 #107) |

Regras de fusão (PDF §6.8): presença no Wi-Fi conta muito, ausência conta pouco; só se considera que alguém saiu se houver uma saída pela porta e passarem 20–30 min; um aparelho a continuar ligado não prova presença, só um a **ligar** prova; contradição (entrada + aparelho a ligar sem ninguém «em casa») → `uncertain` e pergunta na aplicação.

## Pistas por pessoa (PRES-03) — IMPLEMENTADO

`features/presence/{wifi,repo,service,router,hostscan}.py`, migração `core/migrations/0200_presence_tables.sql` (convenção D-29, `02xx` = P2; tabelas `presence_device`, `presence_confirmation`, `presence_state` — a última só é usada pela fusão, PRES-04).

**API** (todas com `?household_id=`; só inquilino com membership ativa; **senhorio e operador `403 forbidden_role`**, não-membro `404`; a pessoa é sempre a da sessão):

| Rota | Efeito |
|---|---|
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

## Limites reais

- Acesso à imagem da câmara do kit (MEARI) **não está provado** para este caso de uso: só há leitura RTSP de 10 min via relay (medição herdada, ver [altice-mcp.md](../integrations/altice-mcp.md)) e a câmara do kit é fixa. Plano B: telemóvel como câmara IP ou clip gravado — dito sempre como tal.
- A deteção de objetos YOLO e o gesto não estão validados com a câmara real; **não são necessários** para a Conta Certa.
- A contagem na porta, a fusão e a precisão **não estão medidas**; nenhum valor de precisão pode aparecer em documentos ou pitch antes de medido.

## Ficheiros existentes reutilizáveis

`features/video/*`, `features/visao/{detetor,thread,dispositivo,pesos,anotar}.py`, `features/gestos/{ponte,presenca}.py`, `contracts/{video,visao,base}.py`, `connectors/…` (nenhum). Ver destinos em [migration.md](../architecture/migration.md).

## Ficheiros novos previstos

`features/presence/{door,fusion,router,service,tests}` (`router`, `service`, `repo`, `wifi`, `hostscan` já existem), `contracts/presence.py`. Pesos YOLO e `torch` continuam fora do Docker e do CI (extra `visao`).

## Dependências

P5 (`households`, barramento), P3 (UI e notificações de «estás em casa?»). Alimenta P4 (regra C, esquecidos).

## Critérios de aceitação

- Com um clip ou um detetor falso, N passagens na linha produzem N `DoorCrossed` com o sentido certo e **zero** imagens persistidas (teste que varre o diretório de dados).
- Telemóvel «a dormir» 10 min sem passar a porta continua «em casa» (PDF §21).
- Sair pela porta e passar a tolerância → «fora»; contradição → «incerto».
- O senhorio recebe `403 forbidden_role` em todas as rotas de presença.

## Testes

Lógica pura com detetor falso e relógio simulado (como em `gestos/tests`); nunca YOLO real, rede ou câmara em `pytest`. Câmara real: [guia de validação](../development/guia-validacao-manual.md) (VID-01…03, YOLO-01/02).
