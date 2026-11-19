# Módulo `notifications` — centro de notificações

**Dono: P3 (RafaelMat0s-Dev).** UI: páginas desenhadas por P5 com P3. **Estado: IMPLEMENTADO (backend parcial)**: persistência SQLite, lista, leitura, votação/resposta, preferências e os consumidores de `billing.confirmation_needed`, `presence.confirmation_needed`, `safety.alert_raised`, `billing.attribution_changed`, `billing.allocation_published`, `billing.contestation_changed`, `energy.identification_needed`, `alerts.threshold_crossed` (orçamento), `alerts.alert_raised` (só picos), `alerts.cold_room` e `agent.action_proposed` (ver «Estado de implementação»); UI, WebSocket e push são **PLANEADO**.

> **REGRA B = VOTAÇÃO (D-32, prevalece):** em `confirmation_request` cada inquilino vota uma vez; um «É minha» fecha; atribuir a outro exige ≥ metade dos elegíveis com o mesmo alvo (fecha antes se o próprio assumir); todos votaram sem decisão ou 24 h → por todos. Fonte única: `confirmation_outcome` em `contracts/notification.py`. **Quem fizer merge (pessoa ou agente) adapta o código de P3/P5/billing a esta regra; não reintroduzir «primeira resposta vence» nas confirmações.** Substitui todas as interações que o PDF previa no Telegram (D-01 em [decisions.md](../decisions.md)).

## Responsabilidade

Ser o **único canal de comunicação com o utilizador**: avisos, perguntas interativas e confirmações. Guarda notificações e respostas, aplica preferências e entrega em tempo real.

## Tipos (`Notification.kind`)

| Tipo | Origem | Âmbito | Interativa | Exemplo (PT-PT) |
|---|---|---|---|---|
| `confirmation_request` | `billing.confirmation_needed` | Casa (moradores autorizados) | Sim | «O aquecedor está ligado numa zona comum, cerca de 0,64 € estimados. Parece ser do Bruno (aparelho identificado a 87 %); confirma.» [É minha] [É de todos] [Não sei] [É de outra pessoa → escolher] (dica **PROPOSTA**, P-18) |
| `budget_alert` | `alerts.threshold_crossed` | Pessoal | Não | «Já gastaste 20 € dos teus 25 € (80 %). Ao ritmo atual chegas aos 31 €.» |
| `peak_alert` | `alerts.alert_raised` | Casa | Opcional | «Pico na sala: 2 kW há 40 min.» |
| `forgotten_appliance` | `alerts.alert_raised` | Pessoal (dono) | Sim | «Saíste há 1 h e o aquecedor continua ligado. Desligo?» [Desliga] [Deixa estar] |
| `security_alert` | `safety.alert_raised` (fumo; P2) | Casa | Não | «Detetor de fumo em alarme. Se houver perigo, sai de casa e liga 112. Este sistema não substitui um detetor de fumo certificado.» |
| `comfort_alert` | `safety.alert_raised` (janela aberta com aquecimento; P2) | Pessoal (inquilino do quarto) ou casa | Não | «A janela do teu quarto está aberta há mais de 5 minutos com o aquecimento ligado.» |
| `presence_check` | `presence.confirmation_needed` (P2) | Pessoal | Sim | «Não temos a certeza se estás em casa. Podes confirmar?» [Estou em casa] [Estou fora] |
| `appliance_identification` | `energy.identification_needed` (P1, ENERGY-04) | Casa (inquilinos ativos) | Sim, a primeira resposta fecha | «Um aparelho de ~800 W liga muitas vezes por volta das 8h. O que é?» [É meu] [É da casa] [Ignorar] |
| `saving_tip` | `alerts`/agente | Pessoal | Não | Recomendação de poupança |
| `automation_proposal` | `automations` | Casa | Sim | Proposta de regra para aprovar |
| `agent_action` | `agent.action_proposed` (assistente, AGENT-03) | Pessoal (só o inquilino a quem se propõe) | Não na notificação (sem botões): a app usa o `ref` (`agent_action`) para chamar `POST …/agent/actions/{id}/confirm\|reject` | «Ação por confirmar»: «Janela aberta com o aquecimento ligado. Queres desligar a tomada do aquecedor? Nada é executado sem a tua confirmação.» |
| `info` | `billing.attribution_changed`, `billing.allocation_published` | Pessoal | Não | «Registado na tua conta», «Dividido por todos», «Recibo disponível» |

Um aviso «da casa» é o que o PDF punha no grupo; um aviso «pessoal» é o que punha em privado.

## Recebe / produz

| Recebe | Produz |
|---|---|
| **IMPLEMENTADO:** `billing.confirmation_needed` (`notifications.confirmation_needed`), `presence.confirmation_needed` (`notifications.presence_check`), `safety.alert_raised` (`notifications.safety_alert`), `billing.attribution_changed` (`notifications.attribution_changed`), `billing.allocation_published` (`notifications.allocation_published`), `alerts.threshold_crossed` (`notifications.budget_threshold`), `alerts.alert_raised` (`notifications.peak_alert`), `alerts.cold_room` (`notifications.cold_room`), `billing.contestation_changed` (`notifications.contestation`), `energy.identification_needed` (`notifications.appliance_identification`), `agent.action_proposed` (`notifications.agent_action`). PLANEADO: `billing.bill_*`, `automation.proposed` | `Notification`, `notification.created` (→ WebSocket, PLANEADO) |
| `POST /api/households/{household_id}/notifications/{id}/respond` (**IMPLEMENTADO**) | `notification.responded` (→ billing/agente/automações) |
| `PUT /api/households/{household_id}/notification-preferences` (**IMPLEMENTADO**) | Preferências guardadas (a aplicação ao push é PLANEADO) |

Rotas por casa (o papel e o `resident_id` vêm de `core/access`): `GET …/notifications?status&scope&limit`, `POST …/notifications/{id}/read`, `POST …/notifications/{id}/respond`, `GET|PUT …/notification-preferences`.

## Regras

- **Confirmações = votação (D-32):** cada inquilino elegível vota uma vez (`409 already_responded` ao repetir); a notificação fica aberta até `confirmation_outcome` decidir e fecha (`actioned`) com o voto decisivo em `response` e todos em `responses`. Persistência: *compare-and-set* sobre o n.º de votos lido (perdeu → reler e reaplicar). Cada voto aceite emite `notification.responded` com `outcome`. A app mostra `NotificationView.voting` (votos, necessários, atribuições por alvo, o meu voto; nunca quem votou).
- **Restantes tipos:** a primeira resposta válida fixa o estado; repetir devolve `409 already_responded`. Registo: autor, hora, ação.
- **Quem responde:** inquilinos ativos da casa (confirmações); o **senhorio nunca** vê nem responde a pedidos de confirmação de consumo.
- **Dica de dono provável (APP-03 #96, P-18): PROPOSTA a aprovar pela P5.** `ConfirmationRequest` pode trazer `likely_owner_resident_id` e `match_confidence`; só se mostra a dica com ambos e com o nome devolvido por `ResidentDirectory.resident_name` para um inquilino ativo. Texto sempre inferencial («Parece…; confirma»), confiança arredondada em percentagem; se o nome do aparelho já contém o dono, só indica a confiança. Sem nome de morador, omite a dica. A dica não pré-seleciona resposta nem altera D-32. Não inclui presença, horas de casa/fora ou nomes de outras pessoas; o senhorio continua fora dos destinatários.
- **Audiência (allow-list):** o senhorio só vê os tipos de uma lista permitida (hoje só `info`, `_SENHORIO_PODE_VER` em `service.py`), quer a notificação seja da casa quer lhe esteja endereçada a título pessoal; qualquer outro tipo (incluindo `confirmation_request`, `security_alert` e tipos novos) fica escondido (404) até ser acrescentado de propósito. O operador não tem permissões de notificações.
- **Expiração:** `expires_at` por tipo (omissão 24 h para confirmações); ao expirar, o produtor aplica o fallback.
- **Deduplicação:** uma notificação por `(kind, ref_type, ref_id, destinatário)` aberta de cada vez. Um `billing.confirmation_needed` repetido para o mesmo consumo, enquanto o primeiro pedido ainda está aberto, devolve a notificação existente **sem prolongar o prazo**: a P4 não deve contar com a reemissão para estender a expiração.
- **Preferências:** por residente **e por casa** (`notification_preferences` com chave `(resident_id, household_id)`; o silêncio noturno é a hora local de cada casa), silêncio noturno (PDF §6.9) e tipos desligáveis (guardados; a aplicação ao push é PLANEADO). Os limiares de orçamento (50/80/100 %) são `Budget.thresholds`, da P4, não preferências da P3. Todo o `security_alert` ignora o silêncio (qualquer severidade) e não se desliga; só afeta o push, a notificação persiste sempre.
- **Privacidade:** o texto nunca contém o endereço de dispositivos, URLs, tokens nem identificadores externos; notificações pessoais só chegam ao destinatário; nada vai para serviços externos.
- **Proveniência:** se o consumo é `simulated`, a notificação indica-o («SIMULADO»).
- **Ações físicas:** uma ação numa notificação («Desliga») só chama `Home` depois de confirmada pelo utilizador e com as protecções existentes (flag + grant). Nada se dá como feito sem releitura confirmada.

## Entrega

| Canal | Estado |
|---|---|
| Centro de notificações na aplicação (lista + contador) | P0; API **IMPLEMENTADA**, UI PLANEADA |
| Tempo real por WebSocket (caminho ainda por acordar) | P0, **PLANEADO**; não existe rota WebSocket ativa |
| Histórico com filtros | P1 |
| Push em Android/iOS via Capacitor | P2 (**PROPOSTA**; exige serviço de push; sem acesso a dados pessoais no texto) |

## Ficheiros existentes reutilizáveis

O protocolo e o transporte WebSocket ainda não estão implementados. O backend atual mantém REST, autenticação das rotas, `core/errors.py` e entrega persistente das notificações.

## Ficheiros (backend IMPLEMENTADO; frontend PLANEADO)

`features/notifications/` (`router`, `service`, `sqlite`, `handlers`, `directory`, `compose`, `ports`, `repository`, `preferences`, `sweeper`, `config`, `tests`) e `core/migrations/0300_notifications_core.sql` já existem; falta o frontend: `pages/NotificationsPage.tsx`, `components/notifications/*`, `hooks/useNotifications.ts`.

## Dependências

P5 (barramento, papéis), P4 (pedidos e alertas), P1 (ações físicas), P2 (alertas de presença).

## Critérios de aceitação

- Fluxo completo com simulador: pedido → notificação no ecrã do inquilino A → resposta «É minha» → `Attribution` atualizada → confirmação mostrada; pedido não chega ao senhorio.
- Votação: 2 de 4 votam «É de outra pessoa → Bruno» → atribuído ao Bruno; o Bruno assume antes → fecha com ele; votos divididos/«Não sei» até ao fim ou 24 h → por todos.
- Votar duas vezes: segundo voto `409`.
- Expiração sem resposta aciona o fallback (verificado por P4).
- Reconexão do WebSocket recupera as notificações por `GET`.
- Preferências de silêncio aplicadas a alertas não críticos.

## Testes

Serviço com relógio injetado e barramento falso; permissões por papel; idempotência; expiração; preferências; votação (`tests/test_voting.py`: os quatro veredictos, um voto por pessoa, alvos inválidos, anonimato, eventos por voto e corridas de votos simultâneos em memória e em SQLite: sem votos perdidos nem duplicados e uma só decisão). Sem rede.

## Estado de implementação (backend parcial)

Refs #95 (APP-02), #96 (APP-03) e #112 (AGENT-03); não as fecham (faltam UI e WebSocket). Detalhe e ficheiros em [`features/notifications/README.md`](../../app/backend/src/homemind/features/notifications/README.md).

| Feito (**IMPLEMENTADO**) | Como |
|---|---|
| Persistência | SQLite (`0300_notifications_core.sql`): `notification` (JSON validado + colunas escalares), `notification_read`, `notification_preferences` (por residente e casa); compare-and-set sobre o estado e o n.º de votos lido: `UPDATE … WHERE id=? AND status=? AND json_array_length(json,'$.responses')=?` (o par só avança: nenhum voto se perde nem se duplica) |
| Lista | `GET …/notifications` (filtros `status`, `scope`, `limit` 1..100), só `NotificationView`; o senhorio só recebe os tipos da allow-list (hoje `info`) |
| Leitura | `POST …/read`: recibo por residente; o estado partilhado só muda nas pessoais |
| Resposta / voto | `POST …/respond` (corpo `NotificationRespondIn`: `action_id` e, com `other`, `target_resident_id`). Confirmações: um voto por inquilino (409 `already_responded` ao repetir ou depois de fechada), fecha segundo `confirmation_outcome` (D-32); alvo inválido 400 `invalid_request`; 409 `notification_expired`. Outros tipos: a primeira resposta vence. `notification.responded` **por voto**, com `outcome`, gravado na mesma transação; se o CAS perde, relê e reaplica a regra |
| Provider do assistente (**IMPLEMENTADO**) | `features/notifications/agent_providers.py`: leitura SQLite sob o lock comum, `query_only`, sem transação de escrita; devolve apenas `confirmation_request` aberto, não expirado e ainda respondível pelo próprio residente (`responder_ids` e votos). Conta todos e inclui até três resumos com aparelho, custo estimado e prazo; sem votos de terceiros. Compõe `ProviderSet` por `dataclasses.replace`, preservando os providers de billing em qualquer ordem de arranque |
| Preferências | `GET|PUT …/notification-preferences` (por casa; `security_alert` não se desliga: 400) |
| Varrimento de expiração | `sweeper.py`: a cada 60 s (`NOTIFICATIONS_EXPIRY_SWEEP_S`, 0 desliga) o lifespan chama `expire_due`; só grava o estado `expired` (a leitura já o deduzia do tempo), sem evento; a tarefa é cancelada no `finally` |
| Consumidores | Nomes permanentes (chave de `processed_event`), subscritos no lifespan (`handlers.CONSUMERS`); todos idempotentes (ids derivados e `processed_event`). Ver a tabela seguinte |

| Consumidor | Evento | Efeito |
|---|---|---|
| `notifications.confirmation_needed` | `billing.confirmation_needed` | `confirmation_request` da casa (votação); deduplicação por pedido aberto (índice único parcial) |
| `notifications.presence_check` | `presence.confirmation_needed` | `presence_check` **pessoal** para `resident_id`, só se for inquilino ativo; ações `in` («Estou em casa») e `out` («Estou fora») de `PRESENCE_CONFIRMATION_ACTIONS`; `expires_at` do pedido; `ref = presence_check`; um pedido aberto de cada vez; saltado se já expirou; texto por `UncertainReason`, sempre pergunta, sem horas nem aparelhos. A resposta volta em `notification.responded` e a presença trata-a (PRES-03) |
| `notifications.safety_alert` | `safety.alert_raised` | Ativo: `window_open_heating` -> `comfort_alert` (pessoal ao inquilino ativo do quarto, se a divisão for um quarto; senão da casa); `smoke` -> `security_alert` crítico da casa com o aviso «não substitui um detetor certificado»; sem botões; id derivado de `alert.id` e destinatário. Resolvido: as notificações abertas com esse `ref` passam a `expired` (CAS, sem evento). O nome da divisão só entra no texto se for zona comum (o de um quarto identifica a pessoa) |
| `notifications.attribution_changed` | `billing.attribution_changed` | Só atribuições `active` de um consumo que a P3 perguntou (existe um `confirmation_request` com esse `ref`); alvo morador -> info pessoal «Registado na tua conta» ao pagador; alvo comum -> info pessoal «Dividido por todos» a cada votante ainda inquilino ativo. Nunca da casa; sem nomes de terceiros (P-18) |
| `notifications.allocation_published` | `billing.allocation_published` | info pessoal «Recibo disponível» (`ref = allocation`) ao inquilino ativo; o valor fica na app |
| `notifications.budget_threshold` | `alerts.threshold_crossed` | `budget_alert` pessoal ao dono do orçamento (ALERT-01) |
| `notifications.appliance_identification` | `energy.identification_needed` | `appliance_identification` **da casa** para os inquilinos ativos (`ResidentDirectory.tenants`), `info`; ações `mine` («É meu»), `household` («É da casa»), `ignore` («Ignorar»); `expires_at` do pedido; `ref = appliance_identification`; id derivado do pedido; saltado se já caducou ou sem inquilinos; texto só com potência arredondada e hora local, sem nomes. A primeira resposta fecha; a energia trata `notification.responded` (ENERGY-04). O senhorio não a vê (allow-list) |
| `notifications.cold_room` | `alerts.cold_room` | `comfort_alert` **pessoal** ao morador do quarto frio (ALERT-06), `info`, sem botões; nunca ao senhorio; não promete valores de plafond; saltado se não for inquilino ativo |
| `notifications.contestation` | `billing.contestation_changed` | Aberta: `info` (`warning`) aos senhorios, sem motivo nem consumo; decidida: `info` pessoal a quem contestou, com a justificação (BILL-06) |
| `notifications.rules_proposal` | `billing.rules_proposal_changed` | HOUSE-04. Aberta: `info` pessoal a cada morador menos quem propôs («Proposta de mudança da regra da sala», com a regra, a data e «pelo menos N de M»; vota-se na página da casa). Aprovada: `info` a todos os moradores e senhorios («A regra da sala muda a …»). Rejeitada/caducada: só a quem propôs. Decidida de qualquer forma: os pedidos de voto abertos passam a `expired`. `ref` = `rules_proposal`; sem etiqueta SIMULADO (é uma decisão da casa) |
| `notifications.agent_action` | `agent.action_proposed` | `agent_action` **pessoal** para `proposed_for_resident_id`, só se for inquilino ativo; `info`; título «Ação por confirmar»; corpo = `rationale` + «Nada é executado sem a tua confirmação.» (+ «(SIMULADO)»); **sem botões** (`actions=[]`); `ref = agent_action` com o id da ação; `expires_at` da proposta; saltado se já expirou; id derivado do evento de origem. Confirmar ou rejeitar é na rota do agente (a UI usa o `ref`); este consumidor nunca executa nada. O senhorio não a vê (allow-list). **Limite:** o chat também emite `agent.action_proposed`; sem `source` no contrato não se distingue a proposta do chat (que o utilizador já vê na resposta) da de um alerta (bloqueado: #157) |
| `notifications.peak_alert` | `alerts.alert_raised` (`kind=peak`) | `peak_alert` da casa, `warning`, sem botões (ALERT-03): «A zona «Sala» está a gastar 2,0 kW há 35 min.»; aparelho só se vier no evento (comum, identificado com confiança); sem zona comum → «Pico de consumo por identificar»; sem potência ou início → nada. `kind=anomaly` (gasto do dia fora do habitual): `peak_alert` da casa, `warning`, «Gasto fora do habitual na zona «Sala»» com o gasto de hoje e o habitual em kWh; sem zona comum ou sem os números → nada. Os outros `kind` ainda não têm produtor e são ignorados |

Todos: membership terminada ou papel que não seja inquilino -> nada; origem simulada -> «(SIMULADO)»; o senhorio continua a ver só `info` (allow-list), e as informações são pessoais, por isso não lhe chegam.

| Adiado (**PLANEADO**) | Porquê |
|---|---|
| WebSocket | não existe rota WebSocket ativa; transporte em tempo real continua PLANEADO |
| Aparelho esquecido e «não bate certo» (`alerts.alert_raised`) | sem produtor (ALERT-04, fase 2); o consumidor `notifications.peak_alert` já subscreve o tipo e ignora estes `kind`, por isso um produtor novo precisa de outro consumidor (nome novo) |
| Botões nos alertas de conforto | **Mudou:** a proposta de desligar a tomada chega como notificação `agent_action` (sem botões) e confirma-se na rota do agente; a execução real depende do executor da P1 (hoje só SIMULADO na casa demo) |
| `notify_landlord` do fumo | sem decisão de audiência; o senhorio continua sem ver `security_alert` |
| Push, aplicação das preferências, dispensar, histórico | sem serviço de push; sem operação de dispensar |
| Acordar consumidores após o commit | `_publish` na rota só acorda consumidores (os eventos já estão na outbox); falta um `bus.wake()` público (pedido à P5) em vez de `publish` |
| Produtores | Já produzem na `main`: `safety.alert_raised`, `presence.confirmation_needed`, `billing.confirmation_needed`, `billing.attribution_changed`, `billing.allocation_published`, `billing.contestation_changed`, `alerts.*`, `energy.identification_needed` e `agent.action_proposed`. Teste ponta a ponta com **billing real** (`app/backend/tests/test_p3_billing_notifications_e2e.py`, SIMULADO): consumo na sala -> voto «É minha» -> «Registado na tua conta» só ao pagador; voto inconclusivo + expiração (`run_expiry`) -> «Dividido por todos» a cada votante; fecho do mês -> «Recibo disponível» só ao dono de cada parcela, sem valores no texto |

## Pedidos pendentes (ver issue a criar)

Estado: **PROPOSTA** (o contrato da `main` não mudou): pedidos da P3 à P4/P5 sobre `contracts/`, por ordem de importância; a abrir como issue. Onde a P3 já aplicou uma regra em código, diz-se (as marcadas «P-03» ligam-se a [decisions.md](../decisions.md)).

1. **Estado de leitura partilhado.** `Notification.status` tem `read` e as notificações de casa são partilhadas: se um morador abre, passa a «lida» para todos. Proposta: recibo de leitura por residente (fora da entidade); `status=read` só nas pessoais. **P3 já aplica:** recibo por residente (`notification_read`); `read` partilhado só nas pessoais.
2. **Expiração sem sinal.** Nada avisa a P4 de que um pedido caducou (o fallback depende disso). Proposta: evento `notification.expired {notification_id, ref}` emitido pelo varrimento da P3.
3. **Retry da resposta.** Com D-32, `respond` devolve `409 already_responded` a qualquer repetição do mesmo residente (um voto por pessoa), mesmo com a mesma ação (reenvio de rede). Pergunta que fica: o reenvio idêntico devia devolver `200` com a vista atual em vez de `409`? Não duplica votos nem cobranças (o evento só sai ao gravar o voto).
4. **`ConfirmationRequest` curto.** APP-03 #96 propõe os campos mínimos de dica (`likely_owner_resident_id`, `match_confidence`) e respetiva regra de exposição, ainda **PROPOSTA a aprovar pela P5** (P-18). Continuam por decidir divisão/localização, evidência e origem; não se adicionam aqui.
5. **Proveniência dos eventos.** `EventBase.provenance` é obrigatória mas `NotificationCreatedData`/`NotificationRespondedData` não têm proveniência e `Notification` só tem `origin`. Proposta: `(n.origin, measured)`, escrita no contrato. **P3 já aplica:** `notification.created` herda a proveniência do evento de origem e `notification.responded` usa `(n.origin, measured)`.
6. **`responder_ids` é um snapshot.** Quem deixa a casa (`ends_on`) continua a poder responder. Proposta: `respond` revalida a membership ativa (via `core/access`) além do snapshot; documentar que o senhorio é filtrado por P3 (nada no contrato o garante). **P3 já aplica:** quem não é membro ativo na data (fuso da casa) recebe 404 e deixa de ver a notificação, mesmo estando em `responder_ids`; o senhorio é filtrado dos `responder_ids` à criação.
7. **`BudgetThreshold` incompleto.** Só tem `budget_id`, `pct`, `spent_cents`, `forecast_cents`. P3 não pode ler `Budget` (uma feature não importa outra), logo não sabe a quem avisar nem o limite. Proposta: `resident_id`, `limit_cents` e `period`.
8. **`AlertRaisedData` incompleto.** **RESOLVIDO para picos (ALERT-03):** campos opcionais `device_id`, `room_id`, `appliance_id`, `power_w` e `since` (compatível com v1); para gasto anormal, `AlertKind.anomaly` com `day`, `energy_wh` e `baseline_wh`. Falta: `AlertKind.mismatch` não tem `NotificationKind` correspondente.
9. **Silêncio noturno.** O contrato impede desligar `security_alert`, mas não diz que ignora as horas de silêncio. **P3 já aplica:** todo o `security_alert` entrega sempre, independentemente da severidade; só afeta *push*, a notificação persiste sempre. Confirmar com a equipa.
10. **WebSocket sem tipos.** `contracts.md` §7 define `notification` com `data: Notification`, que traz `responder_ids` e `correlation_id`; e `notification_update` não tem modelo. Proposta: `data: NotificationView` calculado por destinatário, e modelos tipados para as duas mensagens em `OPENAPI_MODELS`.
11. **Dispensar.** `dismissed` existe, mas não há operação nem regra: quem pode dispensar uma notificação de casa (o estado é partilhado)? Hoje `respond` numa dispensada devolve `already_responded`, o que engana. (Sem operação de dispensar na API da P3.)
12. **Audiência das notificações de casa.** Não há campo que diga quem as vê: `GET` devolve «pessoais + da casa» a T e L. Proposta: regra explícita por `kind` (ou lista de papéis) no contrato. **Parte P3 RESOLVIDA:** o serviço aplica uma allow-list ao senhorio (só `info`; os restantes tipos, da casa ou pessoais, ficam escondidos: derivam de presença, consumo ou hábitos). **Pedido mantido:** o contrato deve tornar a audiência explícita (por `kind` ou papéis) em vez de depender do filtro de P3.
13. **Operador.** `PERMISSIONS[notification]` não inclui `operator`. Confirmar que é intencional (sem alertas técnicos para o operador no MVP).
14. **Idempotência do `notification.created`.** O barramento entrega «pelo menos uma vez» e `EventBase.id` é aleatório por omissão. Proposta: documentar que o id da notificação e o do evento derivam do evento de origem (`stable_id`), para a reentrega não duplicar. **P3 já aplica:** ids `uuid5` derivados do evento de origem e `processed_event` por consumidor.
15. **Alerta resolvido antes do ativo.** O barramento admite chegadas fora de ordem em *retry*; se `resolved` chegar antes do `active`, o aviso nasce sem nunca expirar. Proposta: `SafetyAlert` ativo já resolvido (ou o consumidor consultar o estado) ou um `expires_at` no aviso. Aceite como risco baixo.
16. **Destinatários de «dividido por todos».** Só avisa quem votou; quem não votou (e paga na mesma) fica sem aviso. Proposta: a P4 diz quem é afetado (campo no evento) ou avisar os `responder_ids` ainda ativos.
17. **`notify_landlord`.** Sem decisão de produto sobre o que o senhorio pode saber de um alarme de fumo, o `security_alert` continua escondido (allow-list). Decidir antes de o ligar.

Resolvido pelo contrato da `main` (sem pedido): a regra B como votação (D-32: `Notification.respond`, `confirmation_outcome`, `VotingView`, `notification.responded` por voto com `outcome`; sem evento de expiração: billing divide por todos pelo seu prazo), as regras de resposta, erros e transições são de `Notification.respond`; os limiares de orçamento (50/80/100) são `Budget.thresholds`, da P4, e não preferências da P3.
