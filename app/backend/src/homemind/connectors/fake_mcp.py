"""Kit Altice SIMULADO à fronteira da sessão MCP, sem rede nem hardware.

Os valores iniciais são cenários inventados, não medições reais. Ao ligar collectors,
usar explicitamente origin=Origin.simulated. Os erros booleanos podem ser desligados;
device_offline(id, False) e declare_unit(None) desfazem os outros controlos.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from homemind.connectors.altice_auth import OAuthReauthRequired


def _cap(kind: str, value: Any, **metadata: Any) -> dict[str, Any]:
    return {"type": kind, "value": value, **metadata}


def _result(data: Any = None, *, error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(isError=error, structuredContent=data, content=[])


def _multi_power(state: str) -> list[dict[str, Any]]:
    """Formato real do `multiPower` da tomada do kit (um só interruptor)."""
    return [
        {
            "id": "1",
            "name": "switch_1",
            "order": 1,
            "partnerType": "switch_1",
            "type": "multiplugSwitch",
            "value": state,
        }
    ]


class FakeKit:
    """Estado SIMULADO. Batimentos ancorados na criação, sem ruído ou latência artificial.

    reset() restaura também erros, chamadas e o instante inicial da criação: não depende
    do tempo decorrido. todayConsumption é um valor de cenário, sem integração inventada.
    multiPower.value tem o formato observado no kit real (17/11/2026): uma lista com um
    interruptor `switch_1` (`type` "multiplugSwitch"), aqui sincronizado com `power`.
    """

    PLUG = "sim-plug-1"
    BULB = "sim-bulb-1"
    CONTACT = "sim-contact-1"
    CLIMATE = "sim-climate-1"

    def __init__(
        self,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        *,
        power_factor: float = 1.0,
    ) -> None:
        if not math.isfinite(power_factor) or not 0 < power_factor <= 1:
            raise ValueError("power_factor must be in (0, 1]")
        self._clock = clock
        self._power_factor = power_factor
        self._initial_ms = self._now_ms()
        self.reset()

    def _now_ms(self) -> int:
        return int(self._clock().timestamp() * 1000)

    def reset(self) -> None:
        self.session_down = False
        self.oauth_expired = False
        self.write_rejected = False
        self.write_ignored = False
        self.die_after_write = False
        self._offline: set[str] = set()
        self._load = 0
        self._base_rgb = (255, 255, 255)
        self._beat_ms = self._initial_ms
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.opens = self.list_calls = 0
        self.dev = {
            self.PLUG: self._device(
                self.PLUG,
                "plug",
                "SIMULADO: tomada",
                [
                    _cap("power", "on", availableValues=["on", "off"]),
                    _cap("instantPower", 0, min=0, max=50000),
                    _cap("instantVoltage", 230),
                    _cap("instantCurrent", 0),
                    _cap("multiPower", _multi_power("on")),
                    _cap("todayConsumption", 0),
                ],
                categories=["energy"],
            ),
            self.BULB: self._device(
                self.BULB,
                "bulb",
                "SIMULADO: lâmpada",
                [
                    _cap("power", "off", availableValues=["on", "off"]),
                    _cap(
                        "workMode", "colour", availableValues=["colour", "music", "white", "scene"]
                    ),
                    _cap("brightness", 100, min=1, max=100),
                    _cap("color_rgb", "255,255,255", redValue=255, greenValue=255, blueValue=255),
                ],
            ),
            self.CONTACT: self._device(
                self.CONTACT,
                "contactSensor",
                "SIMULADO: contacto",
                [
                    _cap("sensorState", "normal", availableValues=["normal", "alarm"]),
                    _cap("tamperState", "normal"),
                    _cap("batteryStatus", "high", availableValues=["low", "medium", "high"]),
                ],
                categories=["security"],
            ),
            self.CLIMATE: self._device(
                self.CLIMATE,
                "temperatureSensor",
                "SIMULADO: clima",
                [
                    _cap("temperatureValue", 20.0, min=-50, max=60),
                    _cap("humidityValue", 50.0, min=0, max=100),
                    _cap("batteryLevel", 100, min=0, max=100),
                ],
            ),
        }

    def _device(self, device_id, kind, name, capabilities, **metadata) -> dict[str, Any]:
        return {
            "id": device_id,
            "name": name,
            "type": kind,
            "lastCommunicationTime": self._initial_ms,
            "capabilities": capabilities,
            **metadata,
        }

    def _caps(self, device: str) -> dict[str, dict[str, Any]]:
        return {c["type"]: c for c in self.dev[device]["capabilities"]}

    def _touch(self, device: str) -> None:
        self.dev[device]["lastCommunicationTime"] = self._now_ms()

    def _heartbeat(self) -> None:
        now = self._now_ms()
        beats = (now - self._beat_ms) // 30_000
        if beats > 0:
            self._beat_ms += beats * 30_000
            if self.PLUG not in self._offline:
                self._report_load()
                self.dev[self.PLUG]["lastCommunicationTime"] = max(
                    self.dev[self.PLUG]["lastCommunicationTime"], self._beat_ms
                )

    def _report_load(self) -> None:
        caps = self._caps(self.PLUG)
        power = self._load if caps["power"]["value"] == "on" else 0
        caps["instantPower"]["value"] = power
        caps["instantCurrent"]["value"] = round(power / 230 * 1000 / self._power_factor)
        caps["multiPower"]["value"] = _multi_power(caps["power"]["value"])

    def set_load(self, watts: int) -> None:
        if type(watts) is not int or not 0 <= watts <= 50000:
            raise ValueError("watts must be an integer in [0, 50000]")
        if watts != self._load:
            self._load = watts
            if self.PLUG not in self._offline:
                self._report_load()
                self._touch(self.PLUG)

    def _contact(self, state: str) -> None:
        cap = self._caps(self.CONTACT)["sensorState"]
        if self.CONTACT not in self._offline and cap["value"] != state:
            cap["value"] = state
            self._touch(self.CONTACT)

    def open_contact(self) -> None:
        self._contact("alarm")

    def close_contact(self) -> None:
        self._contact("normal")

    def set_climate(self, temp_c: float, humidity_pct: float) -> None:
        if not (
            math.isfinite(temp_c)
            and -50 <= temp_c <= 60
            and math.isfinite(humidity_pct)
            and 0 <= humidity_pct <= 100
        ):
            raise ValueError("climate outside capability limits")
        caps = self._caps(self.CLIMATE)
        if self.CLIMATE not in self._offline and (
            caps["temperatureValue"]["value"],
            caps["humidityValue"]["value"],
        ) != (temp_c, humidity_pct):
            caps["temperatureValue"]["value"] = temp_c
            caps["humidityValue"]["value"] = humidity_pct
            self._touch(self.CLIMATE)

    def device_offline(self, device: str, enabled: bool = True) -> None:
        if device not in self.dev:
            raise ValueError("unknown simulated device")
        self._heartbeat()
        if enabled:
            self._offline.add(device)
        else:
            self._offline.discard(device)

    def declare_unit(self, unit: str | None) -> None:
        cap = self._caps(self.PLUG)["instantPower"]
        if unit is None:
            cap.pop("unit", None)
        else:
            cap["unit"] = unit

    def writes(self) -> list[tuple[str, dict[str, Any]]]:
        return [c for c in self.calls if c[0] == "update_device_capabilities"]

    def _check(self) -> None:
        if self.session_down:
            raise ConnectionError("SIMULADO: sessão indisponível")
        if self.oauth_expired:
            raise OAuthReauthRequired("SIMULADO: OAuth expirado")

    @asynccontextmanager
    async def session_factory(self) -> AsyncIterator[_Session]:
        self._check()
        self.opens += 1
        yield _Session(self)


class _Tool(SimpleNamespace):
    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return vars(self).copy()


class _Session:
    def __init__(self, kit: FakeKit) -> None:
        self.kit = kit
        self._dead = False

    def _check(self) -> None:
        self.kit._check()
        if self._dead:
            raise ConnectionError("SIMULADO: transporte caiu após escrita")

    async def list_tools(self) -> SimpleNamespace:
        self._check()
        self.kit.list_calls += 1
        body = {
            "oneOf": [
                {"properties": {"type": {"enum": [kind]}}}
                for kind in ("power", "brightness", "color_rgb", "temperature")
            ]
        }
        return SimpleNamespace(
            tools=[
                _Tool(name="get_home_devices", inputSchema={}),
                _Tool(
                    name="get_device_details",
                    inputSchema={
                        "required": ["deviceId"],
                        "properties": {"deviceId": {"type": "string"}},
                    },
                ),
                _Tool(
                    name="update_device_capabilities",
                    inputSchema={
                        "required": ["body"],
                        "properties": {"deviceId": {"type": "string"}, "body": body},
                    },
                ),
            ]
        )

    async def call_tool(self, name: str, args: dict[str, Any]) -> SimpleNamespace:
        self._check()
        kit = self.kit
        kit.calls.append((name, deepcopy(args)))
        kit._heartbeat()
        if name == "get_home_devices":
            return _result({"devices": deepcopy(list(kit.dev.values()))})
        if name == "get_device_details":
            device = kit.dev.get(args.get("deviceId"))
            return _result(deepcopy(device), error=device is None)
        if name != "update_device_capabilities":
            return _result(error=True)
        device_id = args.get("deviceId")
        body = args.get("body", {})
        if kit.write_rejected or not self._valid_write(device_id, body):
            return _result(error=True)
        if not kit.write_ignored and device_id not in kit._offline:
            caps = kit._caps(device_id)
            kind = body["type"]
            before = deepcopy(kit.dev[device_id])
            if kind == "color_rgb":
                kit._base_rgb = tuple(body[k] for k in ("redValue", "greenValue", "blueValue"))
            else:
                caps[kind]["value"] = body["value"]
            if device_id == kit.PLUG:
                kit._report_load()
            else:
                rgb = [round(c * caps["brightness"]["value"] / 100) for c in kit._base_rgb]
                caps["color_rgb"].update(
                    zip(("redValue", "greenValue", "blueValue"), rgb, strict=True)
                )
                caps["color_rgb"]["value"] = ",".join(map(str, rgb))
            if before != kit.dev[device_id]:
                kit._touch(device_id)
        if kit.die_after_write:
            self._dead = True
            raise ConnectionError("SIMULADO: resposta de escrita perdida")
        return _result({"message": "device updated"})

    def _valid_write(self, device: str, body: Any) -> bool:
        if device not in (self.kit.PLUG, self.kit.BULB) or not isinstance(body, dict):
            return False
        kind = body.get("type")
        if kind == "power":
            return set(body) == {"type", "value"} and body["value"] in ("on", "off")
        if device != self.kit.BULB:
            return False
        if kind == "brightness":
            value = body.get("value")
            return set(body) == {"type", "value"} and type(value) is int and 1 <= value <= 100
        channels = ("redValue", "greenValue", "blueValue")
        return (
            kind == "color_rgb"
            and set(body) == {"type", *channels}
            and all(type(body[c]) is int and 0 <= body[c] <= 255 for c in channels)
        )
