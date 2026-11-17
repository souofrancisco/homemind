# `features/notifications` — centro de notificações (APP-02, parcial)

Dono: P3. Documento do módulo: [`docs/modules/notifications.md`](../../../../../../docs/modules/notifications.md).
Refs #95 (APP-02) e #96 (APP-03); não as fecha (faltam UI, WebSocket e os produtores da P4).

## IMPLEMENTADO

| Ficheiro | Papel |
|---|---|
| `router.py` | Rotas por casa (abaixo) e `lifespan` que subscreve o consumidor no barramento. |
| `service.py` | `NotificationService` síncrono: criar (com deduplicação), responder, ler, listar e expirar. Devolve os eventos de domínio a gravar (`Outcome.events`). |
| `compose.py` | Pedido de confirmação e aviso de orçamento -> `Notification`; ids determinísticos (uuid5). |
| `repository.py` | Protocolo `NotificationRepository` + versão em memória (referência e testes). |
| `sqlite.py` | `SqliteNotificationRepository` (compare-and-set real), recibos de leitura e preferências. |
| `directory.py` | `SqliteResidentDirectory`: papel de um residente numa casa e data (cópia de `core.access.find_membership`, por `resident_id`; pedir à P5 um helper). |
| `handlers.py` | `CONFIRMATION_CONSUMER = "notifications.confirmation_needed"` e `make_confirmation_handler`. |
| `preferences.py` | `delivery_for`: `now`/`deferred`/`suppressed` (só afeta o push, ainda inexistente). |
| `core/migrations/0300_notifications_core.sql` | Tabelas `notification`, `notification_read`, `notification_preferences` (por residente e casa; dono P3; nunca editar depois do merge: `0301_...`). |

Rotas (todas com `require_access(Resource.notification)`; o `resident_id` vem da base de dados):

| Método e caminho | Resposta |
|---|---|
| `GET /api/households/{household_id}/notifications?status&scope&limit` | `list[NotificationView]` (limit 1..100, omissão 50) |
| `POST …/notifications/{notification_id}/read` | `NotificationView` |
| `POST …/notifications/{notification_id}/respond` (`{"action_id"}`) | `NotificationView` |
| `GET` e `PUT …/notification-preferences` | `NotificationPreferences` |

Erros: `notification_not_found` 404 (inexistente, de outra casa ou invisível: indistinguíveis),
`already_responded` 409, `notification_expired` 409, `forbidden_role` 403, `invalid_request` 400.

Regras que os testes garantem:

- Allow-list de audiência: o senhorio só vê `info` (`_SENHORIO_PODE_VER`), da casa ou pessoal; nunca
  vê nem responde a pedidos de confirmação (404 como se não existissem) e é filtrado dos
  `responder_ids`. Tipos novos ficam escondidos ao senhorio até serem permitidos.
- Preferências por `(residente, casa)`: o silêncio noturno é a hora local de cada casa.
- Primeira resposta válida vence (compare-and-set); só o vencedor emite `notification.responded`,
  gravado na mesma transação da resposta. Repetir, mesmo o mesmo inquilino, é 409.
- Idempotência: ids da notificação e dos eventos derivados do evento de origem (uuid5); o
  barramento regista `processed_event` por consumidor.
- Deduplicação: um pedido de confirmação aberto por `(casa, tipo, referência, destinatário)`
  (índice único parcial); um pedido vencido por tempo passa a `expired` antes de entrar o novo.
- Um `billing.confirmation_needed` repetido para o mesmo consumo, com o primeiro ainda aberto,
  devolve a notificação existente sem prolongar o prazo (a P4 não deve contar com a reemissão).
- Pedidos já caducados não geram notificação. Origem simulada => texto «(SIMULADO)».
- Respostas só com `NotificationView` (nunca ids de pessoas nem `responder_ids`).

## PLANEADO (não existe)

- WebSocket (`notification`, `notification_update`): o único `/api/ws` é o do ObjectOS, sem hook.
- `bus.wake()` público (pedido à P5): `_publish` no router só acorda consumidores depois do
  commit (os eventos já estão na outbox), por isso usa `publish`.
- Varrimento de expiração periódico (`expire_due` existe no serviço, ninguém o chama) e o evento
  `notification.expired` para a P4.
- Subscrição de `alerts.threshold_crossed` e `alerts.alert_raised` (faltam destinatário/limite e
  potência/duração nos contratos; subscrever agora perderia eventos).
- Aplicação das preferências (push, silêncio noturno), dispensar, histórico com filtros, produtor
  de demonstração (`seed_demo` só existe em testes).

Testes: `uv run pytest -q src/homemind/features/notifications` (sem rede; relógio injetado;
`tests/conftest.py` tem a app com duas casas, cópia da dos households).
