"""Measured socket location, independent of appliance identification."""

from uuid import UUID

from homemind.contracts.appliance_catalog import DeviceLocation
from homemind.contracts.devices import DeviceRole
from homemind.contracts.energy import LocationKind
from homemind.contracts.household import RoomKind


def locate(device: DeviceLocation | None) -> tuple[LocationKind, UUID | None]:
    """Return evidence from the session's socket, never an appliance's usual room.

    A main_meter is aggregated and always unknown, even when configured in a room.
    A bedroom requires both room_meter and a known bedroom room_id. A configured
    common area yields common with its room_id (except for an aggregated meter).
    Missing devices, missing rooms and unknown room kinds always yield unknown.
    Identification and declared appliance ownership cannot strengthen this proof.
    """
    if device is not None and device.role is not DeviceRole.main_meter and device.room_id:
        if device.room_kind is RoomKind.common:
            return LocationKind.common, device.room_id
        if device.role is DeviceRole.room_meter and device.room_kind is RoomKind.bedroom:
            return LocationKind.room, device.room_id
    return LocationKind.unknown, None
