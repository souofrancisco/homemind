# Módulo `notifications` — centro de notificações

**Dono: P3 (RafaelMat0s-Dev).** UI: páginas desenhadas por P5 com P3. **Estado: IMPLEMENTADO (backend parcial)**: persistência SQLite, lista, leitura, votação/resposta, preferências e o consumidor de `billing.confirmation_needed` (ver «Estado de implementação»); UI, WebSocket, limiares/picos, varrimento de expiração e push são **PLANEADO**.

> **REGRA B = VOTAÇÃO (D-32, prevalece):** em `confirmation_request` cada inquilino vota uma vez; um «É minha» fecha; atribuir a outro exige ≥ metade dos elegíveis com o mesmo alvo (fecha antes se o próprio assumir); todos votaram sem decisão ou 24 h → por todos. Fonte única: `confirmation_outcome` em `contracts/notification.py`. **Quem fizer merge (pessoa ou agente) adapta o código de P3/P5/billing a esta regra; não reintroduzir «primeira resposta vence» nas confirmações.** Substitui todas as interações que o PDF previa no Telegram (D-01 em [decisions.md](../decisions.md)).

## Responsabilidade

Ser o **único canal de comunicação com o utilizador**: avisos, perguntas interativas e confirmações. Guarda notificações e respostas, aplica preferências e entrega em tempo real.

## Tipos (`Notification.kind`)

| Tipo | Origem | Âmbito | Interativa | Exemplo (PT-PT) |
|---|---|---|---|---|
| `confirmation_request` | `billing.confirmation_needed` | Casa (moradores autorizados) | Sim | «O aquecedor do Bruno está ligado na sala. De quem é esta conta?» [É minha] [É de todos] [Não sei] [É de outra pessoa → escolher] |
| `budget_alert` | `alerts.threshold_crossed` | Pessoal | Não | «Já gastaste 20 € dos teus 25 € (80 %). Ao ritmo atual chegas aos 31 €.» |
| `peak_alert` | `alerts.alert_raised` | Casa | Opcional | «Pico na sala: 2 kW há 40 min.» |
| `forgotten_appliance` | `alerts.alert_raised` | Pessoal (dono) | Sim | «Saíste há 1 h e o aquecedor continua ligado. Desligo?» [Desliga] [Deixa estar] |
| `security_alert` | `presence` (P2) | Casa | Não | «Entrada com a casa vazia.» |
| `saving_tip` | `alerts`/agente | Pessoal | Não | Recomendação de poupança |
| `automation_proposal` | `automations` | Casa | Sim | Proposta de regra para aprovar |
| `agent_action` | agente | Pessoal | Sim | Ação sugerida com confirmação |
| `info` | qualquer | Ambos | Não | Fatura publicada, atribuição registada |

Um aviso «da casa» é o que o PDF punha no grupo; um aviso «pessoal» é o que punha em privado.

## Recebe / produz

| Recebe | Produz |
|---|---|
| `billing.confirmation_needed` (**IMPLEMENTADO**, consumidor `notifications.confirmation_needed`); `alerts.*`, `billing.bill_*`, `automation.proposed`, `agent.action_proposed` (PLANEADO) | `Notification`, `notification.created` (→ WebSocket, PLANEADO) |
| `POST /api/households/{household_id}/notifications/{id}/respond` (**IMPLEMENTADO**) | `notification.responded` (→ billing/agente/automações) |
| `PUT /api/households/{household_id}/notification-preferences` (**IMPLEMENTADO**) | Preferências guardadas (a aplicação ao push é PLANEADO) |

Rotas por casa (o papel e o `resident_id` vêm de `core/access`): `GET …/notifications?status&scope&limit`, `POST …/notifications/{id}/read`, `POST …/notifications/{id}/respond`, `GET|PUT …/notification-preferences`.

## Regras

- **Confirmações = votação (D-32):** cada inquilino elegível vota uma vez (`409 already_responded` ao repetir); a notificação fica aberta até `confirmation_outcome` decidir e fecha (`actioned`) com o voto decisivo em `response` e todos em `responses`. Persistência: *compare-and-set* sobre o n.º de votos lido (perdeu → reler e reaplicar). Cada voto aceite emite `notification.responded` com `outcome`. A app mostra `NotificationView.voting` (votos, necessários, atribuições por alvo, o meu voto; nunca quem votou).
- **Restantes tipos:** a primeira resposta válida fixa o estado; repetir devolve `409 already_responded`. Registo: autor, hora, ação.
- **Quem responde:** inquilinos ativos da casa (confirmações); o **senhorio nunca** vê nem responde a pedidos de confirmação de consumo.
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
| Tempo real por WebSocket (`/api/ws`: mensagens `notification`, `notification_update`) | P0, **PLANEADO** (o único `/api/ws` é o do ObjectOS, sem hook; a reconexão recupera por `GET`) |
| Histórico com filtros | P1 |
| Push em Android/iOS via Capacitor | P2 (**PROPOSTA**; exige serviço de push; sem acesso a dados pessoais no texto) |

## Ficheiros existentes reutilizáveis

`features/engine/router.py` (gestor de ligações WS, fila de 200 mensagens por cliente, auth na 1.ª mensagem), `frontend/src/app/providers/HomeProvider.tsx`, `components/events/*`, `services/api/client.ts`, `core/errors.py`.

## Ficheiros (backend IMPLEMENTADO; frontend PLANEADO)

`features/notifications/` (`router`, `service`, `sqlite`, `handlers`, `directory`, `compose`, `preferences`, `tests`) e `core/migrations/0300_notifications_core.sql` já existem; falta o frontend: `pages/NotificationsPage.tsx`, `components/notifications/*`, `hooks/useNotifications.ts`.

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

Serviço com relógio injetado e barramento falso; permissões por papel; idempotência; expiração; preferências. Sem rede.

## Estado de implementação (backend parcial)

Refs #95 (APP-02) e #96 (APP-03); não as fecham (faltam UI, WebSocket e os produtores da P4). Detalhe e ficheiros em [`features/notifications/README.md`](../../app/backend/src/homemind/features/notifications/README.md).

| Feito (**IMPLEMENTADO**) | Como |
|---|---|
| Persistência | SQLite (`0300_notifications_core.sql`): `notification` (JSON validado + colunas escalares), `notification_read`, `notification_preferences` (por residente e casa); compare-and-set `UPDATE … WHERE status IN ('unread','read')` |
| Lista | `GET …/notifications` (filtros `status`, `scope`, `limit` 1..100), só `NotificationView`; o senhorio só recebe os tipos da allow-list (hoje `info`) |
| Leitura | `POST …/read`: recibo por residente; o estado partilhado só muda nas pessoais |
| Resposta | `POST …/respond`: um só vencedor (409 `already_responded` aos restantes), `notification.responded` gravado na mesma transação, 409 `notification_expired` |
| Preferências | `GET|PUT …/notification-preferences` (por casa; `security_alert` não se desliga: 400) |
| Consumidor | `notifications.confirmation_needed` (nome permanente) sobre `billing.confirmation_needed`; idempotente por evento; deduplicação por pedido aberto (índice único parcial) |

| Adiado (**PLANEADO**) | Porquê |
|---|---|
| WebSocket | só existe o `/api/ws` do ObjectOS, sem hook para notificações |
| Limiar de orçamento (`alerts.threshold_crossed`) | `BudgetThreshold` sem destinatário nem limite; subscrever marcaria eventos como processados e perdê-los-ia |
| Picos e aparelho esquecido (`alerts.alert_raised`) | `AlertRaisedData` sem potência, duração nem divisão |
| Varrimento de expiração | `expire_due` existe no serviço mas nada o agenda; o estado expirado deduz-se do tempo na leitura |
| Push, aplicação das preferências, dispensar, histórico | sem serviço de push; sem operação de dispensar |
| Acordar consumidores após o commit | `_publish` na rota só acorda consumidores (os eventos já estão na outbox); falta um `bus.wake()` público (pedido à P5) em vez de `publish` |
| Produtor/seed de demonstração | `seed_demo` só existe em testes; nada produz `billing.confirmation_needed` em runtime (P4) |

## Pedidos pendentes (ver issue a criar)

Estado: **PROPOSTA** (o contrato da `main` não mudou): pedidos da P3 à P4/P5 sobre `contracts/`, por ordem de importância; a abrir como issue. Onde a P3 já aplicou uma regra em código, diz-se (as marcadas «P-03» ligam-se a [decisions.md](../decisions.md)).

1. **Estado de leitura partilhado.** `Notification.status` tem `read` e as notificações de casa são partilhadas: se um morador abre, passa a «lida» para todos. Proposta: recibo de leitura por residente (fora da entidade); `status=read` só nas pessoais. **P3 já aplica:** recibo por residente (`notification_read`); `read` partilhado só nas pessoais.
2. **Expiração sem sinal.** Nada avisa a P4 de que um pedido caducou (o fallback depende disso). Proposta: evento `notification.expired {notification_id, ref}` emitido pelo varrimento da P3.
3. **Retry da resposta (P-03).** `respond` devolve `409 already_responded` a qualquer repetição, mesmo do mesmo residente com a mesma ação (reenvio de rede). Proposta: decidir se esse caso devolve `200` com a vista atual ou `409`; APP-03 exige que o retry não duplique cobranças.
4. **`ConfirmationRequest` curto.** Só tem `appliance_name`: faltam divisão/localização, evidência e confiança, e origem (APP-03 pede evidência). «O aquecedor do Bruno» expõe o dono de um aparelho (P-18). Proposta: campos opcionais (`room_name`, `evidence`, `confidence`, `origin`) e regra sobre nomes de terceiros.
5. **Proveniência dos eventos.** `EventBase.provenance` é obrigatória mas `NotificationCreatedData`/`NotificationRespondedData` não têm proveniência e `Notification` só tem `origin`. Proposta: `(n.origin, measured)`, escrita no contrato. **P3 já aplica:** `notification.created` herda a proveniência do evento de origem e `notification.responded` usa `(n.origin, measured)`.
6. **`responder_ids` é um snapshot.** Quem deixa a casa (`ends_on`) continua a poder responder. Proposta: `respond` revalida a membership ativa (via `core/access`) além do snapshot; documentar que o senhorio é filtrado por P3 (nada no contrato o garante). **P3 já aplica:** quem não é membro ativo na data (fuso da casa) recebe 404 e deixa de ver a notificação, mesmo estando em `responder_ids`; o senhorio é filtrado dos `responder_ids` à criação.
7. **`BudgetThreshold` incompleto.** Só tem `budget_id`, `pct`, `spent_cents`, `forecast_cents`. P3 não pode ler `Budget` (uma feature não importa outra), logo não sabe a quem avisar nem o limite. Proposta: `resident_id`, `limit_cents` e `period`.
8. **`AlertRaisedData` incompleto.** Sem potência, duração nem divisão, o texto do pico e do aparelho esquecido não se escreve sem inventar. `AlertKind.mismatch` não tem `NotificationKind` correspondente.
9. **Silêncio noturno.** O contrato impede desligar `security_alert`, mas não diz que ignora as horas de silêncio. **P3 já aplica:** todo o `security_alert` entrega sempre, independentemente da severidade; só afeta *push*, a notificação persiste sempre. Confirmar com a equipa.
10. **WebSocket sem tipos.** `contracts.md` §7 define `notification` com `data: Notification`, que traz `responder_ids` e `correlation_id`; e `notification_update` não tem modelo. Proposta: `data: NotificationView` calculado por destinatário, e modelos tipados para as duas mensagens em `OPENAPI_MODELS`.
11. **Dispensar.** `dismissed` existe, mas não há operação nem regra: quem pode dispensar uma notificação de casa (o estado é partilhado)? Hoje `respond` numa dispensada devolve `already_responded`, o que engana. (Sem operação de dispensar na API da P3.)
12. **Audiência das notificações de casa.** Não há campo que diga quem as vê: `GET` devolve «pessoais + da casa» a T e L. Proposta: regra explícita por `kind` (ou lista de papéis) no contrato. **Parte P3 RESOLVIDA:** o serviço aplica uma allow-list ao senhorio (só `info`; os restantes tipos, da casa ou pessoais, ficam escondidos: derivam de presença, consumo ou hábitos). **Pedido mantido:** o contrato deve tornar a audiência explícita (por `kind` ou papéis) em vez de depender do filtro de P3.
13. **Operador.** `PERMISSIONS[notification]` não inclui `operator`. Confirmar que é intencional (sem alertas técnicos para o operador no MVP).
14. **Idempotência do `notification.created`.** O barramento entrega «pelo menos uma vez» e `EventBase.id` é aleatório por omissão. Proposta: documentar que o id da notificação e o do evento derivam do evento de origem (`stable_id`), para a reentrega não duplicar. **P3 já aplica:** ids `uuid5` derivados do evento de origem e `processed_event` por consumidor.

Resolvido pelo contrato da `main` (sem pedido): as regras de resposta, erros e transições são de `Notification.respond`; os limiares de orçamento (50/80/100) são `Budget.thresholds`, da P4, e não preferências da P3.
