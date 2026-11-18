"""Socket evidence only; declared appliance rooms are never inputs."""

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.appliance_catalog import DeviceLocation
from homemind.contracts.devices import DeviceRole
from homemind.contracts.energy import LocationKind
from homemind.contracts.household import RoomKind
from homemind.features.energy.locate import locate


@pytest.mark.parametrize(
    "device,expected",
    [
        (
            DeviceLocation(DeviceRole.room_meter, fx.ROOM_BRUNO, RoomKind.bedroom),
            (LocationKind.room, fx.ROOM_BRUNO),
        ),
        (
            DeviceLocation(DeviceRole.none, fx.ROOM_SALA, RoomKind.common),
            (LocationKind.common, fx.ROOM_SALA),
        ),
        (
            DeviceLocation(DeviceRole.room_meter, fx.ROOM_SALA, RoomKind.common),
            (LocationKind.common, fx.ROOM_SALA),
        ),
        (DeviceLocation(DeviceRole.main_meter, fx.ROOM_BRUNO, RoomKind.bedroom), None),
        (DeviceLocation(DeviceRole.main_meter, fx.ROOM_SALA, RoomKind.common), None),
        (DeviceLocation(DeviceRole.none, fx.ROOM_BRUNO, RoomKind.bedroom), None),
        (DeviceLocation(DeviceRole.room_meter, None, RoomKind.bedroom), None),
        (DeviceLocation(DeviceRole.room_meter, fx.ROOM_BRUNO, None), None),
        (None, None),
    ],
)
def test_locate(device, expected):
    assert locate(device) == (expected or (LocationKind.unknown, None))
