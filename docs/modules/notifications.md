# Módulo `notifications` — centro de notificações

**Dono: P3 (RafaelMat0s-Dev).** UI: páginas desenhadas por P5 com P3. **PLANEADO.** Substitui todas as interações que o PDF previa no Telegram (D-01 em [decisions.md](../decisions.md)).

## Responsabilidade

Ser o **único canal de comunicação com o utilizador**: avisos, perguntas interativas e confirmações. Guarda notificações e respostas, aplica preferências e entrega em tempo real.

## Tipos (`Notification.kind`)

| Tipo | Origem | Âmbito | Interativa | Exemplo (PT-PT) |
|---|---|---|---|---|
| `confirmation_request` | `billing.confirmation_needed` | Casa (moradores autorizados) | Sim | «O aquecedor do Bruno está ligado na sala. De quem é esta conta?» [É minha] [É de todos] [Não sei] |
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
| `billing.confirmation_needed`, `alerts.*`, `billing.bill_*`, `automation.proposed`, `agent.action_proposed` | `Notification`, `notification.created` (→ WebSocket) |
| `POST /api/notifications/{id}/respond` | `notification.responded` (→ billing/agente/automações) |
| `PUT /api/me/notification-preferences` | Preferências guardadas e aplicadas |

## Regras

- **Resposta persistida e idempotente:** a primeira resposta válida fixa o estado; repetir devolve `409 already_responded`. Registo: autor, hora, ação.
- **Quem responde:** inquilinos ativos da casa (confirmações); o **senhorio nunca** vê nem responde a pedidos de confirmação de consumo.
- **Expiração:** `expires_at` por tipo (omissão 24 h para confirmações); ao expirar, o produtor aplica o fallback.
- **Deduplicação:** uma notificação por `(kind, ref_type, ref_id, destinatário)` aberta de cada vez.
- **Preferências (P1):** limiares de orçamento (50/80/100 %), silêncio noturno (PDF §6.9), tipos desligáveis. Alertas `critical` de segurança ignoram o silêncio.
- **Privacidade:** o texto nunca contém o endereço de dispositivos, URLs, tokens nem identificadores externos; notificações pessoais só chegam ao destinatário; nada vai para serviços externos.
- **Proveniência:** se o consumo é `simulated`, a notificação indica-o («SIMULADO»).
- **Ações físicas:** uma ação numa notificação («Desliga») só chama `Home` depois de confirmada pelo utilizador e com as protecções existentes (flag + grant). Nada se dá como feito sem releitura confirmada.

## Entrega

| Canal | Estado |
|---|---|
| Centro de notificações na aplicação (lista + contador) | P0 |
| Tempo real por WebSocket (`/api/ws`: mensagens `notification`, `notification_update`) | P0 |
| Histórico com filtros | P1 |
| Push em Android/iOS via Capacitor | P2 (**PROPOSTA**; exige serviço de push; sem acesso a dados pessoais no texto) |

## Ficheiros existentes reutilizáveis

`features/engine/router.py` (gestor de ligações WS, fila de 200 mensagens por cliente, auth na 1.ª mensagem), `frontend/src/app/providers/HomeProvider.tsx`, `components/events/*`, `services/api/client.ts`, `core/errors.py`.

## Ficheiros novos previstos

`features/notifications/{router,service,preferences,tests}`, `contracts/notification.py`; frontend: `pages/NotificationsPage.tsx`, `components/notifications/*`, `hooks/useNotifications.ts`.

## Dependências

P5 (barramento, papéis), P4 (pedidos e alertas), P1 (ações físicas), P2 (alertas de presença).

## Critérios de aceitação

- Fluxo completo com simulador: pedido → notificação no ecrã do inquilino A → resposta «É minha» → `Attribution` atualizada → confirmação mostrada; pedido não chega ao senhorio.
- Responder duas vezes: segunda resposta `409`.
- Expiração sem resposta aciona o fallback (verificado por P4).
- Reconexão do WebSocket recupera as notificações por `GET`.
- Preferências de silêncio aplicadas a alertas não críticos.

## Testes

Serviço com relógio injetado e barramento falso; permissões por papel; idempotência; expiração; preferências. Sem rede.
