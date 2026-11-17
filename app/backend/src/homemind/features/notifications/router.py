"""Centro de notificações (APP-02): lista, leitura, resposta e preferências, por casa.

IMPLEMENTADO: `GET .../notifications`, `POST .../notifications/{id}/read`, `POST .../respond`,
`GET|PUT .../notification-preferences` e o consumidor de `billing.confirmation_needed`.
PLANEADO: WebSocket, varrimento de expiração, limiares de orçamento/picos e push (ver
`docs/modules/notifications.md`).

Todas as rotas exigem membership na casa do caminho (`require_access`); o `resident_id` vem
sempre da base de dados, nunca do cliente. As respostas são `NotificationView`, nunca a entidade.
"""

import logging
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, ValidationError

from homemind.contracts.common import ContractModel
from homemind.contracts.notification import (
    AlreadyRespondedError,
    NotAllowedToRespondError,
    NotificationExpiredError,
    NotificationKind,
    NotificationPreferences,
    NotificationScope,
    NotificationStatus,
    NotificationView,
    QuietHours,
    UnknownActionError,
)
from homemind.core.access import (
    ClockDep,
    DbDep,
    HouseholdAccess,
    Operation,
    Resource,
    get_clock,
    require_access,
)
from homemind.core.events import append_event
from homemind.features.notifications.directory import SqliteResidentDirectory
from homemind.features.notifications.handlers import (
    CONFIRMATION_CONSUMER,
    CONFIRMATION_EVENT_TYPES,
    make_confirmation_handler,
)
from homemind.features.notifications.service import (
    NotificationNotFoundError,
    NotificationService,
    Outcome,
)
from homemind.features.notifications.sqlite import (
    SqliteNotificationRepository,
    load_preferences,
    save_preferences,
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Um só relógio: o do consumidor é o mesmo que as rotas usam (o override de `get_clock`
    # nos testes também vale aqui; em produção é o relógio real).
    clock = app.dependency_overrides.get(get_clock, get_clock)()
    app.state.bus.subscribe(
        CONFIRMATION_CONSUMER, make_confirmation_handler(clock), CONFIRMATION_EVENT_TYPES
    )
    yield


router = APIRouter(prefix="/api", tags=["notifications"], lifespan=lifespan)

ReadAccess = Annotated[HouseholdAccess, Depends(require_access(Resource.notification))]
WriteAccess = Annotated[
    HouseholdAccess, Depends(require_access(Resource.notification, Operation.write))
]


class RespondIn(ContractModel):
    action_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]


class NotificationPreferencesIn(ContractModel):
    """O `resident_id` nunca vem do cliente: é o de quem pede."""

    quiet_hours: QuietHours | None = None
    disabled_kinds: list[NotificationKind] = []


def _service(conn: sqlite3.Connection, clock: Callable[[], datetime]) -> NotificationService:
    return NotificationService(
        SqliteNotificationRepository(conn), SqliteResidentDirectory(conn), clock
    )


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


async def _publish(request: Request, outcome: Outcome) -> None:
    """Depois do COMMIT: acorda os consumidores. Os eventos já estão gravados (outbox), por isso
    uma falha aqui só atrasa a entrega e nunca falha o pedido."""
    for ev in outcome.events:
        try:
            await request.app.state.bus.publish(ev)
        except Exception as e:  # noqa: BLE001 - só o tipo vai para o log
            log.warning("falha a publicar %s (%s)", ev.type, type(e).__name__)


@router.get("/households/{household_id}/notifications")
async def list_notifications(
    access: ReadAccess,
    db: DbDep,
    clock: ClockDep,
    status: NotificationStatus | None = None,
    scope: NotificationScope | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[NotificationView]:
    """Notificações visíveis a quem pede (as suas e as da casa), a mais recente primeiro.
    O senhorio nunca recebe pedidos de confirmação."""
    return await db.run(
        lambda c: _service(c, clock).list_for(
            access.household_id, access.resident_id, status=status, scope=scope, limit=limit
        )
    )


@router.post("/households/{household_id}/notifications/{notification_id}/read")
async def read_notification(
    notification_id: UUID, access: WriteAccess, db: DbDep, clock: ClockDep
) -> NotificationView:
    """Marca como lida para quem pede (recibo por residente; a da casa não muda para os outros)."""
    try:
        return await db.run(
            lambda c: _service(c, clock).mark_read(
                notification_id, household_id=access.household_id, resident_id=access.resident_id
            )
        )
    except NotificationNotFoundError:
        raise _error(404, "notification_not_found", "Notificação não encontrada") from None


@router.post("/households/{household_id}/notifications/{notification_id}/respond")
async def respond_notification(
    notification_id: UUID, body: RespondIn, access: WriteAccess, db: DbDep, clock: ClockDep,
    request: Request,
) -> NotificationView:  # fmt: skip
    """Primeira resposta válida vence (os restantes recebem 409). A resposta e o evento
    `notification.responded` gravam-se na mesma transação."""

    def work(conn: sqlite3.Connection) -> tuple[NotificationView, Outcome]:
        service = _service(conn, clock)
        out = service.respond(
            notification_id,
            household_id=access.household_id,
            resident_id=access.resident_id,
            action_id=body.action_id,
        )
        for ev in out.events:
            append_event(conn, ev)
        assert out.notification is not None  # só o vencedor chega aqui
        return service.view(out.notification, access.resident_id), out

    try:
        view, out = await db.run(work)
    except NotificationNotFoundError:
        raise _error(404, "notification_not_found", "Notificação não encontrada") from None
    except AlreadyRespondedError:
        raise _error(409, "already_responded", "Esta notificação já foi respondida") from None
    except NotificationExpiredError:
        raise _error(409, "notification_expired", "O pedido já expirou") from None
    except NotAllowedToRespondError:
        raise _error(403, "forbidden_role", "Sem permissão para responder") from None
    except UnknownActionError:
        raise _error(400, "invalid_request", "Ação desconhecida") from None
    await _publish(request, out)
    return view


@router.get("/households/{household_id}/notification-preferences")
async def get_preferences(access: ReadAccess, db: DbDep) -> NotificationPreferences:
    prefs = await db.run(lambda c: load_preferences(c, access.resident_id, access.household_id))
    return prefs or NotificationPreferences(resident_id=access.resident_id)


@router.put("/households/{household_id}/notification-preferences")
async def put_preferences(
    body: NotificationPreferencesIn, access: WriteAccess, db: DbDep
) -> NotificationPreferences:
    """Preferências de quem pede NESTA casa (as horas de silêncio são locais à casa)."""
    try:
        prefs = NotificationPreferences(
            resident_id=access.resident_id,
            quiet_hours=body.quiet_hours,
            disabled_kinds=list(dict.fromkeys(body.disabled_kinds)),
        )
    except ValidationError:  # ex.: desligar `security_alert`; nunca o texto da exceção
        raise _error(400, "invalid_request", "Preferências inválidas") from None
    await db.run(lambda c: save_preferences(c, access.household_id, prefs))
    return prefs
