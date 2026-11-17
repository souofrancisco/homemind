"""Home real Altice. Só usa as 3 ferramentas e as capabilities observadas e validadas.

- Whitelist exata de ferramentas e de capabilities por dispositivo (independente da autorização).
- Escritas exigem `ENABLE_PHYSICAL_WRITES=true` **e** um grant temporário (ver `write_grant`).
- O polling (5 s) é o único leitor periódico; `estado()` e `ler_consumo()` só leem o cache.
- Escrita e releitura na mesma sessão MCP; nunca há retry de uma escrita de resultado incerto.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from datetime import UTC, datetime
from typing import Any

from homemind.connectors.altice_auth import altice_session, needs_login
from homemind.connectors.write_grant import read_grant
from homemind.contracts.home import (
    CORES,
    Cor,
    EstadoCasa,
    EstadoLampada,
    EstadoTomada,
)
from homemind.core.config import Settings, get_settings

log = logging.getLogger(__name__)

TOOL_HOME_DEVICES = "get_home_devices"
TOOL_DEVICE_DETAILS = "get_device_details"
TOOL_UPDATE = "update_device_capabilities"

# Capabilities que o ObjectOS pode alterar, por tipo de dispositivo. Nada mais.
_WRITABLE = {"lamp": {"power", "brightness", "color_rgb"}, "plug": {"power"}}
_POLL_SECONDS = 5
_READ_TIMEOUT_S = 8
_OPEN_TIMEOUT_S = 10
_WRITE_TIMEOUT_S = 14
_READBACK_RETRIES = 5
_READBACK_GAP_S = 0.5
_INVENTORY_EVERY_POLLS = 12  # volta a descobrir dispositivos de ~60 s a ~60 s
_STALE_S = 30  # leitura de consumo mais antiga que isto deixa de ser devolvida
_POWER = {"on": True, "off": False}  # qualquer outro valor = desconhecido
_RGB_TOL = 3  # arredondamentos do brilho; o RGB devolvido vem escalado por ele
_UNIT_FACTOR = {"W": 1.0, "w": 1.0, "mW": 0.001, "milliwatt": 0.001}

SessionFactory = Callable[[], AbstractAsyncContextManager[Any]]
EstadoOuvinte = Callable[[EstadoCasa, bool], None]


def _payload(result: Any) -> Any:
    if result.isError:
        raise RuntimeError("MCP tool returned an error")
    return result.structuredContent or [
        item.model_dump(mode="json", exclude_none=True) for item in result.content
    ]


def _capabilities(device: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        cap["type"]: cap
        for cap in device.get("capabilities", [])
        if isinstance(cap, dict) and isinstance(cap.get("type"), str)
    }


def _validate_tools(tools: list[Any]) -> None:
    """Exige as 3 ferramentas exatas com schemas compatíveis; qualquer desvio bloqueia tudo."""
    by_name = {t.name: t.inputSchema if isinstance(t.inputSchema, dict) else {} for t in tools}
    for name in (TOOL_HOME_DEVICES, TOOL_DEVICE_DETAILS, TOOL_UPDATE):
        if name not in by_name:
            raise RuntimeError(f"MCP sem a ferramenta esperada {name}")
    if by_name[TOOL_HOME_DEVICES].get("required"):
        raise RuntimeError(f"Schema inesperado em {TOOL_HOME_DEVICES}")
    details = by_name[TOOL_DEVICE_DETAILS]
    if "deviceId" not in details.get("required", []) or "deviceId" not in details.get(
        "properties", {}
    ):
        raise RuntimeError(f"Schema inesperado em {TOOL_DEVICE_DETAILS}")
    props = by_name[TOOL_UPDATE].get("properties", {})
    body = props.get("body", {})
    variants = body.get("oneOf", []) if isinstance(body, dict) else []
    kinds = {k for v in variants for k in v.get("properties", {}).get("type", {}).get("enum", [])}
    if "deviceId" not in props or not set().union(*_WRITABLE.values()) <= kinds:
        raise RuntimeError(f"Schema inesperado em {TOOL_UPDATE}")


def _choose(candidates: list[dict[str, Any]], pin: str) -> dict[str, Any] | None:
    """Pin explícito (env) ou candidato único; nunca um dispositivo arbitrário."""
    if pin:
        return next((c for c in candidates if c["id"] == pin), None)
    return candidates[0] if len(candidates) == 1 else None


def _find_devices(
    payload: Any, lamp_pin: str = "", plug_pin: str = ""
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
        raise RuntimeError("Unexpected home-device-list response")
    lamps: list[dict[str, Any]] = []
    plugs: list[dict[str, Any]] = []
    for device in payload["devices"]:
        if not isinstance(device, dict) or not device.get("id"):
            continue
        caps = _capabilities(device)
        categories = set(device.get("categories", []))
        if "security" in categories:
            continue
        if device.get("type") == "bulb" and {"power", "brightness", "color_rgb"} <= caps.keys():
            lamps.append(device)
        if (
            device.get("type") == "plug"
            and {"power", "instantPower"} <= caps.keys()
            and "energy" in categories
        ):
            plugs.append(device)
    lamp, plug = _choose(lamps, lamp_pin), _choose(plugs, plug_pin)
    aviso = None
    if lamp is None or plug is None:
        aviso = (
            f"Não foi possível identificar inequivocamente lâmpada RGB ({len(lamps)} candidatos) "
            f"e tomada ({len(plugs)} candidatos); defina MCP_LAMP_ID/MCP_PLUG_ID se necessário."
        )
    return lamp, plug, aviso


def _power(device: dict[str, Any]) -> bool | None:
    value = _capabilities(device).get("power", {}).get("value")
    return _POWER.get(value) if isinstance(value, str) else None


def _rgb(capability: dict[str, Any] | None) -> tuple[int, int, int] | None:
    if capability is None:
        return None
    values = tuple(capability.get(k) for k in ("redValue", "greenValue", "blueValue"))
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in values):
        return None
    return tuple(int(v) for v in values)  # type: ignore[return-value]


def _color_name(rgb: tuple[int, int, int] | None) -> Cor | None:
    if rgb is None:
        return None
    return next(
        (
            n
            for n, v in CORES.items()
            if all(abs(a - b) <= _RGB_TOL for a, b in zip(v, rgb, strict=True))
        ),
        None,
    )  # type: ignore[return-value]


def _brilho(device: dict[str, Any]) -> int | None:
    value = _capabilities(device).get("brightness", {}).get("value")
    if isinstance(value, bool) or not isinstance(value, int | float) or not 1 <= value <= 100:
        return None
    return int(value)


def _normalizar(rgb: tuple[int, int, int] | None, brilho: int | None):
    """A lâmpada real devolve `color_rgb` já escalado pelo brilho (RGB × brilho/100)."""
    if rgb is None or brilho is None:
        return rgb
    return tuple(min(255, round(c * 100 / brilho)) for c in rgb)


def _rgb_confere(device: dict[str, Any], esperado: tuple[int, int, int]) -> bool:
    """Compara com o valor efetivamente devolvido, escalado pelo brilho devolvido."""
    raw, brilho = _rgb(_capabilities(device).get("color_rgb")), _brilho(device)
    if raw is None or brilho is None:
        return False
    return all(abs(r - e * brilho / 100) <= _RGB_TOL for r, e in zip(raw, esperado, strict=True))


def _lamp_state(device: dict[str, Any]) -> EstadoLampada:
    brilho = _brilho(device)
    rgb = _normalizar(_rgb(_capabilities(device).get("color_rgb")), brilho)
    return EstadoLampada(ligada=_power(device), cor=_color_name(rgb), rgb=rgb, brilho=brilho)


def _plug_consumption(device: dict[str, Any]) -> float | None:
    """Watts só com unidade declarada pelo MCP; a capability observada não a declara."""
    cap = _capabilities(device).get("instantPower", {})
    raw = cap.get("value")
    factor = _UNIT_FACTOR.get(cap.get("unit") or cap.get("unitOfMeasure"))
    if isinstance(raw, int | float) and not isinstance(raw, bool) and factor is not None:
        return float(raw) * factor
    return None


async def _nada() -> None:
    return None


def _valid_change(role: str, change: dict[str, Any]) -> bool:
    kind = change.get("type")
    if kind not in _WRITABLE[role]:
        return False
    if kind == "power":
        return set(change) == {"type", "value"} and change["value"] in _POWER
    if kind == "brightness":
        v = change.get("value")
        return set(change) == {"type", "value"} and type(v) is int and 1 <= v <= 100
    channels = [change.get(k) for k in ("redValue", "greenValue", "blueValue")]
    return set(change) == {"type", "redValue", "greenValue", "blueValue"} and all(
        type(c) is int and 0 <= c <= 255 for c in channels
    )


class _Conexao:
    """Sessão MCP persistente, dona de uma só tarefa (o anyio exige abrir/fechar na mesma tarefa).

    A 1.ª chamada de cada sessão custa ~2 s no servidor real, por isso reutilizamos a sessão
    entre pedidos. Qualquer erro fecha-a; o pedido seguinte reabre (e revalida o catálogo).
    """

    def __init__(self, factory: SessionFactory, ao_abrir: Callable[[], None]) -> None:
        self._factory = factory
        self._ao_abrir = ao_abrir
        self._fila: asyncio.Queue[tuple[Callable[[Any], Any], asyncio.Future[Any], float]] = (
            asyncio.Queue()
        )
        self._task: asyncio.Task[None] | None = None

    async def executar(self, fn: Callable[[Any], Any], timeout: float) -> Any:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._correr())
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._fila.put_nowait((fn, fut, timeout))
        return await asyncio.wait_for(fut, timeout + _OPEN_TIMEOUT_S + 1)

    async def fechar(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _correr(self) -> None:
        stack = AsyncExitStack()
        erro: BaseException = ConnectionError("sessão MCP fechada")
        try:
            async with asyncio.timeout(_OPEN_TIMEOUT_S):
                session = await stack.enter_async_context(self._factory())
            self._ao_abrir()
            while True:
                fn, fut, timeout = await self._fila.get()
                try:
                    async with asyncio.timeout(timeout):
                        resultado = await fn(session)
                except Exception as exc:
                    erro = exc
                    if not fut.done():
                        fut.set_exception(exc)
                    return
                if not fut.done():
                    fut.set_result(resultado)
        except Exception as exc:
            erro = exc
        finally:
            while not self._fila.empty():  # pedidos que ficaram para trás (ex.: falha ao abrir)
                _, fut, _ = self._fila.get_nowait()
                if not fut.done():
                    fut.set_exception(erro)
            try:
                await stack.aclose()
            except BaseException:  # noqa: BLE001 — fechar nunca deve esconder o erro original
                pass


class McpHome:
    """Adapta a casa MCP ao contrato Home sem expor IDs nem capacidades de segurança."""

    def __init__(
        self,
        settings: Settings | None = None,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._con = _Conexao(session_factory or altice_session, self._reabriu)
        # Definido pelo motor: ao_estado(casa, mudou). Chamado sem locks; `mudou` só em
        # alterações relevantes (estado, consumo, disponibilidade), não por timestamps.
        self.ao_estado: EstadoOuvinte | None = None
        self.ultima_falha: str | None = None  # motivo (sem segredos) da última escrita recusada
        self.tempos_ms: dict[str, float] = {}  # duração da última operação de cada tipo
        self._mcp_ok = False
        self._aviso: str | None = "Ainda sem leitura MCP."
        self._lampada = EstadoLampada()
        self._tomada = EstadoTomada()
        self._consumo_w: float | None = None
        self._lido_em: datetime | None = None  # última leitura MCP bem-sucedida (qualquer)
        self._consumo_em: datetime | None = None  # última leitura da tomada
        self._ids: dict[str, str] | None = None  # {"lamp": id, "plug": id} da última descoberta
        self._tools_ok = False
        self._polls = 0
        self._fp: tuple | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # ---- ciclo de vida -------------------------------------------------------------------
    async def iniciar(self) -> None:
        if self._poll_task is None:
            await self._refrescar()  # primeira leitura limitada por timeout
            self._poll_task = asyncio.create_task(self._poll())

    async def parar(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        await self._con.fechar()

    # ---- Home ----------------------------------------------------------------------------
    async def definir_lampada(
        self, ligada: bool, cor: Cor | None = None, brilho: int | None = None
    ) -> bool:
        if not ligada:
            cor = brilho = None  # ignorados ao desligar, também na verificação
        if (cor is not None and cor not in CORES) or (
            brilho is not None and not (type(brilho) is int and 1 <= brilho <= 100)
        ):
            return self._recusar("argumentos inválidos")
        changes: list[dict[str, Any]] = []
        # Só omite o "power on" se a cache fresca já o confirma; "off" é sempre enviado.
        if not (ligada and self._lampada.ligada is True and self._fresco()):
            changes.append({"type": "power", "value": "on" if ligada else "off"})
        if cor is not None:
            r, g, b = CORES[cor]
            changes.append({"type": "color_rgb", "redValue": r, "greenValue": g, "blueValue": b})
        if brilho is not None:
            changes.append({"type": "brightness", "value": brilho})

        def confirmado(d: dict[str, Any]) -> bool:
            casa = _lamp_state(d)
            return (
                casa.ligada is ligada
                and (cor is None or _rgb_confere(d, CORES[cor]))
                and (brilho is None or casa.brilho == brilho)
            )

        return await self._escrever("lamp", changes, confirmado)

    async def definir_tomada(self, ligada: bool) -> bool:
        return await self._escrever(
            "plug",
            [{"type": "power", "value": "on" if ligada else "off"}],
            lambda d: _power(d) is ligada,
        )

    async def listar_ferramentas(self) -> list[dict[str, Any]]:
        """`tools/list` pela sessão partilhada (só leitura), para o endpoint de descoberta."""
        async with self._lock:
            res = await self._con.executar(lambda s: s.list_tools(), _READ_TIMEOUT_S)
        return [t.model_dump(mode="json", exclude_none=True) for t in res.tools]

    async def ler_consumo(self) -> float | None:
        """Watts confirmados do cache; None se desconhecidos, sem unidade ou antigos."""
        return self._consumo_atual()[0]

    async def estado(self) -> EstadoCasa:
        """Só cache (sem I/O): o polling e as escritas mantêm-no atualizado."""
        return self._casa()

    # ---- cache e notificação -------------------------------------------------------------
    def _fresco(self, limite_s: float = _POLL_SECONDS * 2) -> bool:
        return (
            self._mcp_ok
            and self._lido_em is not None
            and ((datetime.now(UTC) - self._lido_em).total_seconds() <= limite_s)
        )

    def _consumo_atual(self) -> tuple[float | None, datetime | None]:
        agora = datetime.now(UTC)
        if (
            self._mcp_ok
            and self._consumo_w is not None
            and self._consumo_em is not None
            and (agora - self._consumo_em).total_seconds() <= _STALE_S
        ):
            return self._consumo_w, self._consumo_em
        return None, None

    def _casa(self) -> EstadoCasa:
        w, lido_em = self._consumo_atual()
        return EstadoCasa(
            backend="mcp",
            mcp_ok=self._mcp_ok,
            lampada=self._lampada,
            tomada=self._tomada.model_copy(update={"consumo_w": w, "consumo_lido_em": lido_em}),
            atualizado_em=datetime.now(UTC),
            aviso=self._aviso,
        )

    def _emitir(self) -> None:
        """Chamar sempre fora do lock. Notifica o motor; `mudou` ignora só timestamps."""
        casa = self._casa()
        fp = (
            casa.mcp_ok,
            casa.lampada,
            casa.tomada.ligada,
            casa.tomada.consumo_w,
            casa.aviso,
        )
        mudou, self._fp = fp != self._fp, fp
        if self.ao_estado is not None:
            try:
                self.ao_estado(casa, mudou)
            except Exception:
                log.exception("ouvinte do estado MCP falhou")

    def _falha(self, exc: BaseException) -> None:
        """Leitura falhou: nada de estados/consumo inventados; caches invalidados."""
        self._mcp_ok = False
        self._lampada, self._tomada = EstadoLampada(), EstadoTomada()
        self._consumo_w = self._lido_em = self._consumo_em = None
        self._ids, self._tools_ok = None, False
        if needs_login(exc):
            self._aviso = "Sessão OAuth MCP expirada; execute make mcp-login no host."
        else:
            self._aviso = f"MCP Altice indisponível ({type(exc).__name__})."
        log.warning("MCP indisponível (%s)", type(exc).__name__)

    # ---- polling ---------------------------------------------------------------------------
    async def _poll(self) -> None:
        while True:
            inicio = time.monotonic()
            await self._refrescar()
            await asyncio.sleep(max(_POLL_SECONDS - (time.monotonic() - inicio), 0))

    def _reabriu(self) -> None:
        """Nova sessão: revalida o catálogo e redescobre os dispositivos."""
        self._tools_ok, self._ids = False, None

    async def _refrescar(self) -> None:
        async with self._lock:
            inicio = time.monotonic()
            try:
                await self._con.executar(self._ler_job, _READ_TIMEOUT_S)
                self._mcp_ok = True
            except Exception as exc:
                self._falha(exc)
            self.tempos_ms["poll"] = round((time.monotonic() - inicio) * 1000)
        self._emitir()

    async def _ler_job(self, session: Any) -> None:
        await self._garantir_ferramentas(session)
        await self._ler(session)

    async def _garantir_ferramentas(self, session: Any) -> None:
        if not self._tools_ok:
            _validate_tools((await session.list_tools()).tools)
            self._tools_ok = True

    async def _detalhes(self, session: Any, device_id: str) -> dict[str, Any]:
        result = _payload(await session.call_tool(TOOL_DEVICE_DETAILS, {"deviceId": device_id}))
        if not isinstance(result, dict) or not isinstance(result.get("capabilities"), list):
            raise RuntimeError("Unexpected device-details response")
        return result

    async def _descobrir(self, session: Any) -> None:
        s = self._settings
        lamp, plug, aviso = _find_devices(
            _payload(await session.call_tool(TOOL_HOME_DEVICES, {})), s.mcp_lamp_id, s.mcp_plug_id
        )
        self._ids = {role: d["id"] for role, d in (("lamp", lamp), ("plug", plug)) if d is not None}
        self._aviso = aviso

    async def _ler(self, session: Any) -> None:
        self._polls += 1
        if self._ids is None or self._polls % _INVENTORY_EVERY_POLLS == 0:
            await self._descobrir(session)
        assert self._ids is not None
        # Leituras independentes e idempotentes: pedidos em paralelo na mesma sessão.
        lamp, plug = await asyncio.gather(
            *(
                self._detalhes(session, self._ids[r]) if r in self._ids else _nada()
                for r in ("lamp", "plug")
            )
        )
        self._aplicar_leitura(lamp, plug)

    def _aplicar_leitura(self, lamp: dict | None, plug: dict | None) -> None:
        if lamp is not None:
            self._lampada = _lamp_state(lamp)
        if plug is not None:
            self._tomada = EstadoTomada(ligada=_power(plug))
            self._consumo_w = _plug_consumption(plug)
            self._consumo_em = datetime.now(UTC)
            if self._consumo_w is None and self._aviso is None:
                self._aviso = "Unidade de instantPower não declarada; consumo em W desconhecido."
        self._lido_em = datetime.now(UTC)

    # ---- escritas --------------------------------------------------------------------------
    def _recusar(self, motivo: str) -> bool:
        self.ultima_falha = motivo
        log.warning("escrita MCP recusada: %s", motivo)
        return False

    def _autorizacao(self, role: str) -> str | None:
        s = self._settings
        if not s.enable_physical_writes:
            return "escritas físicas desativadas (ENABLE_PHYSICAL_WRITES=false)"
        grant = read_grant(s.mcp_write_grant_path, s.mcp_write_max_minutes)
        if grant is None:
            return "sem sessão de escritas autorizada (make mcp-writes-on)"
        if role not in grant.roles:
            return "dispositivo fora da autorização"
        return None

    async def _escrever(
        self,
        role: str,
        changes: list[dict[str, Any]],
        confirmado: Callable[[dict[str, Any]], bool],
    ) -> bool:
        if motivo := self._autorizacao(role):
            return self._recusar(motivo)
        if not all(_valid_change(role, c) for c in changes):
            return self._recusar("alteração fora da whitelist")
        inicio = time.monotonic()
        erro: str | None = None
        enviado = False
        device_id: str | None = None
        atual: dict[str, Any] | None = None

        async def job(session: Any) -> dict[str, Any] | None:
            nonlocal enviado, device_id, erro
            await self._garantir_ferramentas(session)
            if self._ids is None:
                await self._descobrir(session)
            device_id = (self._ids or {}).get(role)
            if device_id is None:
                return None
            for change in changes:
                enviado = True
                res = await session.call_tool(TOOL_UPDATE, {"deviceId": device_id, "body": change})
                if res.isError:
                    erro = "MCP recusou a alteração"
                    break
            # Releitura na mesma sessão. O estado pode demorar a refletir-se na cloud: só se
            # repetem LEITURAS (nunca a escrita) até confirmar ou esgotar as tentativas.
            leitura = await self._detalhes(session, device_id)
            for _ in range(_READBACK_RETRIES):
                if erro or confirmado(leitura):
                    break
                await asyncio.sleep(_READBACK_GAP_S)
                leitura = await self._detalhes(session, device_id)
            return leitura

        async with self._lock:
            try:
                atual = await self._con.executar(job, _WRITE_TIMEOUT_S)
            except Exception as exc:
                # Resultado incerto: nunca repetir a escrita; só reler.
                erro = erro or f"escrita sem confirmação de transporte ({type(exc).__name__})"
                if needs_login(exc):
                    erro = "sessão OAuth MCP expirada"
            if device_id is None and not enviado and erro is None:
                return self._recusar("dispositivo não identificado inequivocamente")
            if atual is None and enviado and device_id is not None:
                atual = await self._reler(device_id)
            ok = False
            if atual is not None:
                self._mcp_ok = True
                self._aplicar_leitura(
                    atual if role == "lamp" else None, atual if role == "plug" else None
                )
                ok = erro is None and confirmado(atual)
                if erro is None and not ok:
                    erro = "estado final não corresponde ao pedido"
            elif enviado:
                self._mcp_ok = False
            self.tempos_ms[f"escrita_{role}"] = round((time.monotonic() - inicio) * 1000)
        self.ultima_falha = None if ok else (erro or "sem confirmação")
        log.info(
            "escrita MCP %s: %s em %d ms",
            role,
            "ok" if ok else self.ultima_falha,
            self.tempos_ms[f"escrita_{role}"],
        )
        self._emitir()
        return ok

    async def _reler(self, device_id: str) -> dict[str, Any] | None:
        try:
            return await self._con.executar(
                lambda session: self._detalhes(session, device_id), _READ_TIMEOUT_S
            )
        except Exception as exc:
            log.warning("releitura MCP indisponível (%s)", type(exc).__name__)
            return None
