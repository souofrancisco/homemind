"""Home real Altice. Só permite alterações observadas no schema MCP validado."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any

from homemind.connectors.altice_auth import altice_session
from homemind.contracts.home import (
    CORES,
    Cor,
    EstadoCasa,
    EstadoLampada,
    EstadoTomada,
)
from homemind.core.config import get_settings

log = logging.getLogger(__name__)

_ALLOWED_WRITE_TYPES = {"power", "brightness", "color_rgb"}
_POLL_SECONDS = 5
_IO_TIMEOUT_SECONDS = 5


def _payload(result: Any) -> Any:
    if result.isError:
        raise RuntimeError("MCP tool returned an error")
    return result.structuredContent or [
        item.model_dump(mode="json", exclude_none=True) for item in result.content
    ]


def _capabilities(device: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for cap in device.get("capabilities", []):
        if isinstance(cap, dict) and isinstance(cap.get("type"), str):
            result[cap["type"]] = cap
    return result


def _tool_names(tools: list[Any]) -> tuple[str, str, str]:
    """Resolve operations from the live catalogue and schemas, never fixed tool names."""
    home_devices: str | None = None
    device_details: str | None = None
    update_capabilities: str | None = None
    for tool in tools:
        words = set(re.findall(r"[a-z]+", tool.name.casefold()))
        schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {}
        required = set(schema.get("required", []))
        properties = schema.get("properties", {})
        if "home" in words and "devices" in words and not required:
            home_devices = tool.name
        elif "device" in words and "details" in words and "deviceId" in required:
            device_details = tool.name
        elif "update" in words and "device" in words:
            body = properties.get("body", {})
            variants = body.get("oneOf", []) if isinstance(body, dict) else []
            kinds = {
                kind
                for variant in variants
                for kind in variant.get("properties", {}).get("type", {}).get("enum", [])
            }
            if _ALLOWED_WRITE_TYPES <= kinds:
                update_capabilities = tool.name
    if not home_devices or not device_details or not update_capabilities:
        raise RuntimeError("MCP tool catalog does not provide required device operations")
    return home_devices, device_details, update_capabilities


async def _tools_for_session(session: Any) -> tuple[str, str, str]:
    result = await session.list_tools()
    return _tool_names(result.tools)


def _find_devices(payload: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
        raise RuntimeError("Unexpected home-device-list response")
    lamps: list[dict[str, Any]] = []
    plugs: list[dict[str, Any]] = []
    for device in payload["devices"]:
        if not isinstance(device, dict) or not device.get("id"):
            continue
        caps = _capabilities(device)
        if {"power", "brightness", "color_rgb"} <= caps.keys():
            lamps.append(device)
        if {"power", "instantPower"} <= caps.keys() and "energy" in device.get("categories", []):
            plugs.append(device)
    # Ambiguous inventories remain unknown; never choose an arbitrary device.
    return (lamps[0] if len(lamps) == 1 else None, plugs[0] if len(plugs) == 1 else None)


def _state_map(device: dict[str, Any]) -> dict[str, dict[str, Any]]:
    caps = _capabilities(device)
    power = caps.get("power", {}).get("value")
    return {
        "capabilities": caps,
        "power": power,
        "on": power == "on" if isinstance(power, str) else None,
    }


def _rgb(capability: dict[str, Any] | None) -> tuple[int, int, int] | None:
    if capability is None:
        return None
    values = tuple(capability.get(k) for k in ("redValue", "greenValue", "blueValue"))
    if not all(isinstance(value, int | float) for value in values):
        return None
    return tuple(int(value) for value in values)  # type: ignore[return-value]


def _color_name(rgb: tuple[int, int, int] | None) -> Cor | None:
    if rgb is None:
        return None
    return next((name for name, value in CORES.items() if value == rgb), None)  # type: ignore[return-value]


class McpHome:
    """Adapta a casa MCP ao contrato Home sem expor IDs nem capacidades de segurança."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._mcp_ok = False
        self._lampada = EstadoLampada()
        self._tomada = EstadoTomada()
        self._consumo_w: float | None = None
        self._consumo_raw: int | float | None = None
        self._consumo_unit: str | None = None
        self._consumo_lido_em: datetime | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._unidade_consumo_conhecida = False

    async def iniciar(self) -> None:
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll_consumption())

    async def parar(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

    async def definir_lampada(
        self, ligada: bool, cor: Cor | None = None, brilho: int | None = None
    ) -> bool:
        if not self._settings.enable_physical_writes:
            return False
        if brilho is not None and not 1 <= brilho <= 100:
            return False
        changes: list[dict[str, Any]] = []
        if ligada and cor is not None:
            red, green, blue = CORES[cor]
            changes.append(
                {"type": "color_rgb", "redValue": red, "greenValue": green, "blueValue": blue}
            )
        if ligada and brilho is not None:
            changes.append({"type": "brightness", "value": brilho})
        changes.append({"type": "power", "value": "on" if ligada else "off"})
        return await self._write_and_verify("lamp", changes, ligada, cor, brilho)

    async def definir_tomada(self, ligada: bool) -> bool:
        if not self._settings.enable_physical_writes:
            return False
        return await self._write_and_verify(
            "plug", [{"type": "power", "value": "on" if ligada else "off"}], ligada
        )

    async def ler_consumo(self) -> float | None:
        """Devolve apenas watts confirmados; a capability observada não declara unidade."""
        return self._consumo_w

    async def estado(self) -> EstadoCasa:
        aviso: str | None = None
        async with self._lock:
            try:
                async with asyncio.timeout(_IO_TIMEOUT_SECONDS):
                    async with altice_session() as session:
                        home_tool, details_tool, _ = await _tools_for_session(session)
                        devices = _find_devices(_payload(await session.call_tool(home_tool, {})))
                        lamp_device, plug_device = devices
                        lamp = (
                            await self._details(session, details_tool, lamp_device)
                            if lamp_device
                            else None
                        )
                        plug = (
                            await self._details(session, details_tool, plug_device)
                            if plug_device
                            else None
                        )
                self._lampada = self._lamp_state(lamp) if lamp else EstadoLampada()
                self._tomada = self._plug_state(plug) if plug else EstadoTomada()
                self._mcp_ok = True
                if lamp_device is None or plug_device is None:
                    aviso = "Não foi possível identificar inequivocamente lâmpada RGB e tomada."
                if not self._unidade_consumo_conhecida:
                    aviso = (
                        f"{aviso} " if aviso else ""
                    ) + "A unidade de instantPower não está declarada; consumo em W desconhecido."
            except Exception as exc:
                self._mcp_ok = False
                self._lampada = EstadoLampada()
                self._tomada = EstadoTomada()
                aviso = f"MCP Altice indisponível ({type(exc).__name__})."
                log.warning("leitura MCP indisponível (%s)", type(exc).__name__)
            return EstadoCasa(
                backend="mcp",
                mcp_ok=self._mcp_ok,
                lampada=self._lampada,
                tomada=self._tomada.model_copy(
                    update={
                        "consumo_w": self._consumo_w,
                        "consumo_lido_em": self._consumo_lido_em,
                    }
                ),
                atualizado_em=datetime.now(UTC),
                aviso=aviso,
            )

    async def _details(
        self, session: Any, tool_name: str, device: dict[str, Any]
    ) -> dict[str, Any]:
        response = await session.call_tool(tool_name, {"deviceId": device["id"]})
        result = _payload(response)
        if not isinstance(result, dict) or not isinstance(result.get("capabilities"), list):
            raise RuntimeError("Unexpected device-details response")
        return result

    @staticmethod
    def _lamp_state(device: dict[str, Any]) -> EstadoLampada:
        caps = _state_map(device)["capabilities"]
        rgb = _rgb(caps.get("color_rgb"))
        brightness = caps.get("brightness", {}).get("value")
        if not isinstance(brightness, int | float) or not 1 <= brightness <= 100:
            brightness = None
        return EstadoLampada(
            ligada=_state_map(device)["on"],
            cor=_color_name(rgb),
            rgb=rgb,
            brilho=int(brightness) if brightness is not None else None,
        )

    def _plug_state(self, device: dict[str, Any]) -> EstadoTomada:
        state = _state_map(device)
        instant_power = state["capabilities"].get("instantPower", {})
        unit = instant_power.get("unit") or instant_power.get("unitOfMeasure")
        raw_value = instant_power.get("value")
        self._consumo_raw = raw_value if isinstance(raw_value, int | float) else None
        self._consumo_unit = unit if isinstance(unit, str) else None
        self._unidade_consumo_conhecida = unit in {"W", "w", "mW", "milliwatt"}
        if isinstance(raw_value, int | float) and unit in {"W", "w"}:
            self._consumo_w = float(raw_value)
        elif isinstance(raw_value, int | float) and unit in {"mW", "milliwatt"}:
            self._consumo_w = float(raw_value) / 1000
        else:
            # The observed MCP schema has no unit field; never assume the raw value is watts.
            self._consumo_w = None
        return EstadoTomada(ligada=state["on"])

    async def _poll_consumption(self) -> None:
        while True:
            try:
                async with self._lock:
                    async with asyncio.timeout(_IO_TIMEOUT_SECONDS):
                        async with altice_session() as session:
                            home_tool, details_tool, _ = await _tools_for_session(session)
                            _, plug = _find_devices(
                                _payload(await session.call_tool(home_tool, {}))
                            )
                            if plug is None:
                                raise RuntimeError("Tomada MCP indisponível ou ambígua")
                            details = await self._details(session, details_tool, plug)
                    self._plug_state(details)
                    self._consumo_lido_em = datetime.now(UTC)
                    self._mcp_ok = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._consumo_w = None
                self._consumo_raw = None
                self._consumo_unit = None
                self._consumo_lido_em = None
                self._mcp_ok = False
                log.warning("poll de consumo MCP indisponível (%s)", type(exc).__name__)
            await asyncio.sleep(_POLL_SECONDS)

    async def _write_and_verify(
        self,
        role: str,
        changes: list[dict[str, Any]],
        ligada: bool,
        cor: Cor | None = None,
        brilho: int | None = None,
    ) -> bool:
        if any(change.get("type") not in _ALLOWED_WRITE_TYPES for change in changes):
            return False
        async with self._lock:
            device: dict[str, Any] | None = None
            try:
                async with asyncio.timeout(_IO_TIMEOUT_SECONDS):
                    async with altice_session() as session:
                        home_tool, details_tool, update_tool = await _tools_for_session(session)
                        lamp, plug = _find_devices(_payload(await session.call_tool(home_tool, {})))
                        device = lamp if role == "lamp" else plug
                        if device is None:
                            return False
                        for change in changes:
                            result = await session.call_tool(
                                update_tool,
                                {"deviceId": device["id"], "body": change},
                            )
                            if result.isError:
                                break
            except Exception as exc:
                # A write timeout is ambiguous. Never retry; readback below is read-only.
                log.warning("escrita MCP sem confirmação de transporte (%s)", type(exc).__name__)
            if device is None:
                return False
            try:
                async with asyncio.timeout(_IO_TIMEOUT_SECONDS):
                    async with altice_session() as session:
                        _, details_tool, _ = await _tools_for_session(session)
                        current = await self._details(session, details_tool, device)
                self._mcp_ok = True
                if role == "lamp":
                    self._lampada = self._lamp_state(current)
                    return (
                        self._lampada.ligada is ligada
                        and (cor is None or self._lampada.rgb == CORES[cor])
                        and (brilho is None or self._lampada.brilho == brilho)
                    )
                self._tomada = self._plug_state(current)
                return self._tomada.ligada is ligada
            except Exception as exc:
                self._mcp_ok = False
                log.warning("releitura MCP indisponível (%s)", type(exc).__name__)
                return False
