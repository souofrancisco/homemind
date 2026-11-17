# Módulo `presence` — câmara na porta e presença

**Dono: P2 (1Mii).** **PLANEADO**, sobre `features/video` e `features/visao` existentes. Entidades: `PresenceEvent`, `PersonPresence` ([data-model.md](../architecture/data-model.md)).

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

## Segurança e conforto (`features/safety`, SAFE-01 #114)

**IMPLEMENTADO (SAFE-01, lógica + consumidor do barramento; sem rotas, sem migrações):**
- `engine.py` (puro): janela (`SensorReading` contacto) aberta **e** aquecimento a decorrer em simultâneo durante ≥ 5 min no mesmo quarto (`ConsumptionEvent` `ongoing` cujo aparelho é de aquecimento) → `SafetyAlert(window_open_heating, warning)` com `suggested_command` = `power=false` na tomada do consumo. É só uma **proposta**: nunca escreve no MCP nem usa `ENABLE_PHYSICAL_WRITES`; a confirmação e a execução são de P3/P1.
- Relógio = `ts` do evento em processamento (determinístico). Um alerta por episódio (`id` estável); resolve-se (mesmo `id`, `resolved`) quando a janela fecha ou o aquecimento acaba; reabre só com novo episódio (janela fechada e reaberta, ou aquecimento religado). `unknown`/`stale` nunca disparam nem resolvem; sensor sem quarto, quarto diferente ou aparelho não-aquecimento não disparam. `coverage()` identifica sensores ausentes (`absent`).
- `service.py`: consumidor `safety` (`sensor.reading_recorded`, `energy.consumption_detected/closed`) → `safety.alert_raised`. O estado refaz-se do registo de eventos ao arrancar.
- `texts.py`: texto pt-PT com origem (SIMULADO/REAL) e o aviso de que a tomada pode alimentar mais do que o aquecedor (na demo, a tomada agregada corta todas as cargas). `simulation.py`: leituras/consumos **SIMULADOS** para demo e testes.

**Decisões para a demo (dono P2; não definitivas):** os 5 min contam desde que **ambas** as condições coincidem (janela aberta há 10 min e aquecedor que liga → só avisa 5 min depois; se o aquecedor desligar e religar, ou a janela fechar, o relógio recomeça); não há resolvedor de aquecedor de demo — **a regra da janela fica inativa até ENERGY-03 #81**; `notify_landlord=false` por omissão (onde vive a política: provavelmente `HouseholdPolicy`, com P5 — em aberto, P-26); o aviso da tomada agregada fica em `texts.py` para P3, sem mudar o contrato (P-27). O consumidor é idempotente por evento: se a transação do barramento falhar depois do handler, o retry reemite o mesmo alerta.

**PLANEADO:** o router arranca o serviço **sem** resolvedor de aquecedores (por omissão nada é «aquecimento»), porque depende de ENERGY-03 #81 (identificar aparelhos/`ApplianceCategory.heating`); sem leituras reais de contacto até MCP-03 #76; entrega ao utilizador e confirmação da proposta em APP-02 #95 / MCP-04 #77. Até lá só os cenários simulados exercitam a regra.

## Passos

| Passo | Descrição | Prioridade |
|---|---|---|
| 1 | Presença por registo manual na aplicação + eventos simulados de porta; permite à P4 testar a regra C e os esquecidos sem câmara | P0 (para destravar) |
| 2 | Detetor de pessoas na soleira (`DetetorYolo` só com a classe «pessoa» + ByteTrack) e linha virtual → `DoorCrossed` | P0 (PRES-02 #106) |
| 3 | Fusão de pistas por pessoa: em casa / fora / incerto, com tolerância de 20–30 min para ausências e confirmação pela porta (PDF §6.8) | P0 (PRES-04 #108) |
| 4 | Estado «casa vazia» e alerta de entrada com casa vazia — **fase 2** | P2 (F3: PRES-06 #131, SAFE-02 #115) |
| 5 | Sinal de presença por Wi-Fi (opt-in) e confirmação manual | P0 (PRES-03 #107) |

Regras de fusão (PDF §6.8): presença no Wi-Fi conta muito, ausência conta pouco; só se considera que alguém saiu se houver uma saída pela porta e passarem 20–30 min; um aparelho a continuar ligado não prova presença, só um a **ligar** prova; contradição (entrada + aparelho a ligar sem ninguém «em casa») → `uncertain` e pergunta na aplicação.

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
