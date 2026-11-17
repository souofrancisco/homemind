"""Fakes e construtores de teste da feature `notifications` (sem rede nem relógio real)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from homemind.contracts.common import Origin, Provenance, ValueKind
from homemind.contracts.household import MembershipRole
from homemind.contracts.notification import ConfirmationChoice, ConfirmationRequest
from homemind.features.notifications.repository import InMemoryNotificationRepository
from homemind.features.notifications.service import NotificationService

_NS = UUID("00000000-0000-0000-0000-00000000c0de")


def uid(name: str) -> UUID:
    """UUID determinístico a partir de um nome (legibilidade nos testes)."""
    return uuid5(_NS, name)


T0 = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
HOUSE = uid("casa")
OTHER_HOUSE = uid("outra-casa")
LANDLORD = uid("senhorio")
ANA = uid("ana")
BRUNO = uid("bruno")
OUTSIDER = uid("estranho")


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class FakeDirectory:
    """Papéis por (casa, residente); quem não consta não é membro."""

    def __init__(self, roles: dict[tuple[UUID, UUID], MembershipRole] | None = None) -> None:
        self.roles = (
            roles
            if roles is not None
            else {
                (HOUSE, LANDLORD): MembershipRole.landlord,
                (HOUSE, ANA): MembershipRole.tenant,
                (HOUSE, BRUNO): MembershipRole.tenant,
                (OTHER_HOUSE, OUTSIDER): MembershipRole.tenant,
            }
        )

    def role_in(self, household_id: UUID, resident_id: UUID, at: datetime) -> MembershipRole | None:
        return self.roles.get((household_id, resident_id))


def make_service(
    clock: FakeClock | None = None, directory: FakeDirectory | None = None
) -> tuple[NotificationService, InMemoryNotificationRepository, FakeClock]:
    clock = clock or FakeClock()
    repo = InMemoryNotificationRepository()
    return NotificationService(repo, directory or FakeDirectory(), clock), repo, clock


def confirmation_request(
    *,
    consumption: str = "consumo-1",
    eligible: list[UUID] | None = None,
    cost: int | None = 64,
    name: str | None = "aquecedor",
    expires_in: timedelta = timedelta(hours=24),
    now: datetime = T0,
) -> ConfirmationRequest:
    return ConfirmationRequest(
        consumption_event_id=uid(consumption),
        appliance_name=name,
        estimated_cost_cents=cost,
        options=list(ConfirmationChoice),
        eligible_resident_ids=eligible if eligible is not None else [LANDLORD, ANA, BRUNO],
        expires_at=now + expires_in,
    )


def prov(origin: Origin = Origin.real, kind: ValueKind = ValueKind.estimated) -> Provenance:
    return Provenance(origin=origin, kind=kind)
