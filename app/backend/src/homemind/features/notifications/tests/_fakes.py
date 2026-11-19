"""Fakes e construtores de teste da feature `notifications` (sem rede nem relógio real)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from homemind.contracts.common import Origin, Provenance, ValueKind
from homemind.contracts.household import MembershipRole, RoomKind
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

    def __init__(
        self,
        roles: dict[tuple[UUID, UUID], MembershipRole] | None = None,
        rooms: dict[tuple[UUID, UUID], tuple[str, RoomKind]] | None = None,
        room_tenants: dict[tuple[UUID, UUID], list[UUID]] | None = None,
        appliances: dict[tuple[UUID, UUID], str] | None = None,
        resident_names: dict[tuple[UUID, UUID], str] | None = None,
    ) -> None:
        self.rooms = rooms or {}
        self.appliances = appliances or {}
        self.resident_names = resident_names or {}
        self._room_tenants = room_tenants or {}
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

    def room(self, household_id: UUID, room_id: UUID) -> tuple[str, RoomKind] | None:
        return self.rooms.get((household_id, room_id))

    def room_tenants(self, household_id: UUID, room_id: UUID, at: datetime) -> list[UUID]:
        return list(self._room_tenants.get((household_id, room_id), []))

    def appliance_name(self, household_id: UUID, appliance_id: UUID) -> str | None:
        return self.appliances.get((household_id, appliance_id))

    def resident_name(self, household_id: UUID, resident_id: UUID) -> str | None:
        return self.resident_names.get((household_id, resident_id))

    def tenants(self, household_id: UUID, at: datetime) -> list[UUID]:
        found = [r for (h, r), role in self.roles.items() if h == household_id and role == "tenant"]
        return sorted(found, key=str)


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
