"""Runbook de verificação do kit Altice (DEMO-03, #122): mede e regista PASS/FAIL/BLOQUEADO.

    uv run --env-file ../.env python -m homemind.connectors.runbook    # kit REAL, só leitura
    uv run python -m homemind.connectors.runbook --simulated           # FakeKit (SIMULADO)

Só leitura por omissão. As escritas físicas (MCP-04 lâmpada, MCP-05 tomada) só correm com
`--write lamp|plug`, uma a uma, com o grant privado de 2 min e a confirmação «AUTORIZO …» do
`mcp_verify`. A câmara real só abre com `--camera` (PRIV-02): frames lidos em memória durante
poucos segundos e descartados. A saída nunca tem IDs, nomes de dispositivos, URL RTSP, tokens nem
a MCP_API_KEY; o relatório só vai para `--out` (ou stdout), nunca para o repositório sozinho.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import statistics
import sys
import tempfile
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from homemind.connectors import mcp_verify
from homemind.connectors.altice_auth import JsonTokenStorage, needs_login
from homemind.connectors.fake_mcp import FakeKit
from homemind.connectors.mcp_energy import observed_at_from_device
from homemind.connectors.mcp_home import (
    _UNIT_FACTOR,
    TOOL_DEVICE_DETAILS,
    TOOL_HOME_DEVICES,
    McpHome,
    SessionFactory,
    _capabilities,
    _find_devices,
    _payload,
    _validate_tools,
)
from homemind.connectors.mcp_sensors import sensor_readings_from_device
from homemind.connectors.write_grant import write_grant
from homemind.contracts.common import Origin
from homemind.contracts.sensors import ContactState, SensorKind, SensorStatus
from homemind.core.config import Settings, get_settings

if TYPE_CHECKING:
    from homemind.features.video.fonte import Captura

Modo = Literal["REAL", "SIMULADO"]
Estado = Literal["PASS", "FAIL", "BLOQUEADO"]

GUIA = Path(__file__).resolve().parents[5] / "docs" / "development" / "guia-validacao-manual.md"

_TIMEOUT_S = 20  # cada operação MCP do runbook (abrir sessão + chamada)
_AMOSTRA_S = 5.0  # MCP-06: intervalo entre amostras
_CONTACTO_AMOSTRA_S = 2.0  # MCP-08 interativo
_CONTACTO_TIMEOUT_S = 90.0
_CAMERA_S = 5.0  # VID-04: leitura em memória
_P_MIN_W = 20.0  # abaixo disto o fator P/(V·I) não é significativo
_FATOR_MIN, _FATOR_MAX = 0.3, 1.05
_META_LATENCIA_S = 10.0  # meta «janela → corte < 10 s»
_TIPO_CONTACTO = "contactSensor"
_TIPO_CLIMA = "temperatureSensor"

# (título no relatório, issue). A ordem é a da tabela.
TESTES: dict[str, tuple[str, str]] = {
    "MCP-01": ("OAuth: sessão MCP", "#10"),
    "MCP-02": ("Ferramentas (tools/list)", "#10"),
    "MCP-03": ("Inventário de dispositivos", "#122"),
    "MCP-04": ("⚠️ Lâmpada RGB (escrita)", "#11"),
    "MCP-05": ("⚠️ Tomada (escrita)", "#11"),
    "MCP-06": ("Consumo: unidade e cadência", "#12"),
    "MCP-07": ("⚠️ Falhas e reconexão", "#11, #12"),
    "MCP-08": ("Contacto: estado e latência", "#122"),
    "MCP-09": ("Clima: temperatura e humidade", "#122"),
    "VID-04": ("Câmara: abertura e FPS (runbook)", "#122"),
}
# Linhas da Folha de resultados que o runbook preenche. MCP-03 fica de fora: no guia é «Leitura
# acompanha a realidade» (teste manual com a app oficial), não o inventário. MCP-07 só é medido
# no simulador; no kit real segue os passos manuais do guia.
LINHAS_GUIA = ("MCP-01", "MCP-02", "MCP-04", "MCP-05", "MCP-06", "MCP-08", "MCP-09", "VID-04")


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    mode: Modo
    status: Estado
    evidence: str
    at: datetime

    def as_json(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "mode": self.mode,
            "status": self.status,
            "evidence": self.evidence,
            "at_utc": self.at.astimezone(UTC).isoformat(timespec="seconds"),
            "at_local": self.at.astimezone().isoformat(timespec="seconds"),
        }


# ---- relógios ---------------------------------------------------------------------------------
class RelogioReal:
    def agora(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    def esperar(self, segundos: float) -> None:  # síncrono (thread da câmara)
        time.sleep(max(segundos, 0))

    async def dormir(self, segundos: float) -> None:
        await asyncio.sleep(max(segundos, 0))


class RelogioSimulado:
    """Tempo virtual: `dormir` avança logo; ações agendadas correm quando o tempo lá chega."""

    def __init__(self, inicio: datetime) -> None:
        self._inicio = inicio
        self._t = 0.0
        self._agendado: list[tuple[float, Callable[[], None]]] = []

    def agora(self) -> datetime:
        return self._inicio + timedelta(seconds=self._t)

    def monotonic(self) -> float:
        return self._t

    def agendar(self, atraso_s: float, acao: Callable[[], None]) -> None:
        self._agendado.append((self._t + atraso_s, acao))

    def avancar(self, segundos: float) -> None:
        alvo = self._t + max(segundos, 0)
        while True:
            devidos = sorted((a for a in self._agendado if a[0] <= alvo), key=lambda a: a[0])
            if not devidos:
                break
            quando, acao = devidos[0]
            self._agendado.remove(devidos[0])
            self._t = max(self._t, quando)
            acao()
        self._t = alvo

    def esperar(self, segundos: float) -> None:
        self.avancar(segundos)

    async def dormir(self, segundos: float) -> None:
        self.avancar(segundos)
        await asyncio.sleep(0)


class _CapturaSimulada:
    """Câmara SIMULADA: frames sem píxeis (só a forma), ao ritmo do relógio virtual."""

    def __init__(self, relogio: RelogioSimulado, fps: float = 15.0) -> None:
        self._relogio, self._fps = relogio, fps

    def read(self) -> tuple[bool, Any]:
        self._relogio.avancar(1 / self._fps)
        return True, SimpleNamespace(shape=(480, 640, 3))

    def get(self, propriedade: int) -> float:
        return self._fps

    def release(self) -> None:
        return None


# ---- ambiente ---------------------------------------------------------------------------------
@dataclass
class Ambiente:
    settings: Settings
    simulado: bool
    session_factory: SessionFactory
    relogio: Any  # RelogioReal | RelogioSimulado
    # Pede ao operador uma ação física no contacto ("abrir" | "fechar") e espera pelo Enter.
    pedir_acao: Callable[[str, str], None]
    perguntar: Callable[[str], str] = input
    abrir_camera: Callable[[], Captura] | None = None
    kit: FakeKit | None = None
    interativo: bool = False
    escritas: tuple[str, ...] = ()
    amostras_s: float = 90.0
    segredos: set[str] = field(default_factory=set)
    _ids: dict[str, str] = field(default_factory=dict)  # papel -> ID (nunca impresso)

    @property
    def modo(self) -> Modo:
        return "SIMULADO" if self.simulado else "REAL"

    def check(self, cid: str, status: Estado, evidencia: str, modo: Modo | None = None) -> Check:
        return Check(
            cid,
            TESTES[cid][0],
            modo or self.modo,
            status,
            higienizar(evidencia, self.segredos),
            self.relogio.agora(),
        )

    def guardar_segredos(self, devices: list[Any]) -> None:
        """IDs, nomes e divisões vistos nesta execução: nunca podem aparecer na saída."""
        for d in devices:
            if not isinstance(d, dict):
                continue
            for chave, valor in d.items():
                k = chave.lower()
                if isinstance(valor, str) and (
                    k in ("id", "name", "deviceid") or "room" in k or "division" in k
                ):
                    self.segredos.add(valor)

    @asynccontextmanager
    async def sessao(self) -> AsyncIterator[Any]:
        async with asyncio.timeout(_TIMEOUT_S):
            async with self.session_factory() as session:
                yield session


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)


def higienizar(texto: str, segredos: set[str]) -> str:
    """Retira segredos conhecidos, URLs (incl. rtsp://) e e-mails; a saída é sempre segura."""
    for segredo in sorted((s for s in segredos if len(s) >= 3), key=len, reverse=True):
        texto = texto.replace(segredo, "‹oculto›")
    texto = _URL.sub("‹url oculto›", texto)
    return _EMAIL.sub("‹e-mail oculto›", texto)


def _n(valor: float, casas: int = 1) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


def _erro(exc: BaseException) -> str:
    return type(exc).__name__  # nunca a mensagem: pode trazer URLs, cabeçalhos ou tokens


def _devices(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
        raise RuntimeError("resposta inesperada de get_home_devices")
    return [d for d in payload["devices"] if isinstance(d, dict)]


async def _ler_casa(amb: Ambiente) -> list[dict[str, Any]]:
    async with amb.sessao() as s:
        devices = _devices(_payload(await s.call_tool(TOOL_HOME_DEVICES, {})))
    amb.guardar_segredos(devices)
    return devices


async def _ler_dispositivo(amb: Ambiente, device_id: str) -> dict[str, Any]:
    async with amb.sessao() as s:
        device = _payload(await s.call_tool(TOOL_DEVICE_DETAILS, {"deviceId": device_id}))
    if not isinstance(device, dict) or not isinstance(device.get("capabilities"), list):
        raise RuntimeError("resposta inesperada de get_device_details")
    return device


def _idade(device: dict[str, Any], agora: datetime) -> str:
    visto = observed_at_from_device(device, agora)
    if visto is None:
        return "último contacto desconhecido"
    segundos = (agora - visto).total_seconds()
    if segundos < 120:
        return f"último contacto há {round(segundos)} s"
    return f"último contacto há {round(segundos / 60)} min"


# ---- MCP-01 … MCP-03 ----------------------------------------------------------------------------
def _sem_configuracao(settings: Settings) -> str | None:
    """Pré-condições do kit real, sem expor caminhos, endpoint nem tokens."""
    if not settings.mcp_endpoint or not settings.mcp_api_key:
        return "MCP_ENDPOINT/MCP_API_KEY não configurados em app/.env"
    try:
        tokens = JsonTokenStorage(settings.mcp_token_path).tokens
    except RuntimeError:
        return "sessão OAuth inválida; execute make mcp-login"
    if tokens is None:
        return "sem sessão OAuth; execute make mcp-login"
    return None


async def check_oauth(amb: Ambiente) -> Check:
    if not amb.simulado and (motivo := _sem_configuracao(amb.settings)):
        return amb.check("MCP-01", "BLOQUEADO", motivo)
    inicio = amb.relogio.monotonic()
    try:
        async with amb.sessao():
            pass
    except Exception as exc:
        if needs_login(exc):
            return amb.check("MCP-01", "BLOQUEADO", "sessão OAuth expirada; execute make mcp-login")
        return amb.check("MCP-01", "FAIL", f"sessão MCP não abriu ({_erro(exc)})")
    ms = round((amb.relogio.monotonic() - inicio) * 1000)
    origem = "do simulador" if amb.simulado else "com os tokens persistidos, sem login"
    return amb.check("MCP-01", "PASS", f"sessão aberta {origem} ({ms} ms)")


async def check_ferramentas(amb: Ambiente) -> Check:
    try:
        async with amb.sessao() as s:
            tools = (await s.list_tools()).tools
        nomes = sorted(
            t.name for t in tools if isinstance(t.name, str) and re.fullmatch(r"\w{1,64}", t.name)
        )
        _validate_tools(tools)
    except RuntimeError as exc:  # mensagens de `_validate_tools`: só nomes de ferramentas
        return amb.check("MCP-02", "FAIL", f"catálogo incompatível: {exc}")
    except Exception as exc:
        return amb.check("MCP-02", "FAIL", f"tools/list falhou ({_erro(exc)})")
    return amb.check(
        "MCP-02",
        "PASS",
        f"{len(nomes)} ferramentas ({', '.join(nomes)}); as 3 usadas têm schema compatível",
    )


async def check_inventario(amb: Ambiente) -> Check:
    try:
        devices = await _ler_casa(amb)
        s = amb.settings
        lamp, plug, aviso = _find_devices({"devices": devices}, s.mcp_lamp_id, s.mcp_plug_id)
    except Exception as exc:
        return amb.check("MCP-03", "FAIL", f"get_home_devices falhou ({_erro(exc)})")
    for papel, device in (("lamp", lamp), ("plug", plug)):
        if device is not None:
            amb._ids[papel] = device["id"]
    tipos = Counter(
        d["type"]
        if isinstance(d.get("type"), str) and re.fullmatch(r"\w{1,40}", d["type"])
        # tipo estranho não sai na evidência
        else "outro"
        for d in devices
    )
    contacto, clima = tipos[_TIPO_CONTACTO], tipos[_TIPO_CLIMA]
    texto = (
        f"{len(devices)} dispositivos ("
        + ", ".join(f"{t}×{n}" for t, n in sorted(tipos.items()))
        + f"); lâmpada RGB: {'identificada' if lamp else 'NÃO identificada'}; "
        f"tomada: {'identificada' if plug else 'NÃO identificada'}; "
        f"contacto: {contacto}; clima: {clima}"
    )
    if aviso:
        texto += f". {aviso}"
    ok = lamp is not None and plug is not None and contacto >= 1 and clima >= 1
    return amb.check("MCP-03", "PASS" if ok else "FAIL", texto)


# ---- MCP-06 consumo -----------------------------------------------------------------------------
def _numero(cap: dict[str, Any] | None) -> float | None:
    v = (cap or {}).get("value")
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


async def check_consumo(amb: Ambiente) -> Check:
    plug_id = amb._ids.get("plug")
    if plug_id is None:
        return amb.check("MCP-06", "BLOQUEADO", "tomada não identificada (ver MCP-03)")
    n = max(int(amb.amostras_s // _AMOSTRA_S), 1)
    amostras: list[dict[str, Any]] = []
    erros: Counter[str] = Counter()
    inicio = amb.relogio.monotonic()
    for i in range(n):
        try:
            device = await _ler_dispositivo(amb, plug_id)
            caps = _capabilities(device)
            ip = caps.get("instantPower", {})
            amostras.append(
                {
                    "p": _numero(ip),
                    "v": _numero(caps.get("instantVoltage")),
                    "i": _numero(caps.get("instantCurrent")),
                    "unidade": ip.get("unit") or ip.get("unitOfMeasure") or "",
                    "lct": device.get("lastCommunicationTime"),
                }
            )
        except Exception as exc:
            erros[_erro(exc)] += 1
        if i < n - 1:
            await amb.relogio.dormir(inicio + (i + 1) * _AMOSTRA_S - amb.relogio.monotonic())
    if not amostras:
        detalhe = ", ".join(f"{k}×{v}" for k, v in erros.items())
        return amb.check("MCP-06", "FAIL", f"nenhuma amostra lida ({detalhe})")

    def faixa(chave: str, casas: int = 0) -> str:
        vals = [a[chave] for a in amostras if a[chave] is not None]
        return f"{_n(min(vals), casas)}–{_n(max(vals), casas)}" if vals else "ausente"

    declarada = next((a["unidade"] for a in amostras if a["unidade"]), "")
    configurada = amb.settings.mcp_instantpower_unit
    fator_unidade = _UNIT_FACTOR.get(declarada or configurada)
    lcts = [a["lct"] for a in amostras if isinstance(a["lct"], int | float)]
    mudancas = [b for a, b in zip(lcts, lcts[1:], strict=False) if b != a]
    pontos = sorted(set(lcts))
    intervalos = [(b - a) / 1000 for a, b in zip(pontos, pontos[1:], strict=False)]
    cadencia = (
        ", ".join(f"{_n(x)} s" for x in intervalos) if intervalos else "sem mudanças observadas"
    )
    texto = (
        f"{len(amostras)}/{n} amostras em {_n(amb.relogio.monotonic() - inicio, 0)} s; "
        f"instantPower bruto {faixa('p')}; V {faixa('v')}; I {faixa('i')} mA; "
        f"unidade declarada: {declarada or 'ausente'}; "
        f"MCP_INSTANTPOWER_UNIT: {configurada or 'vazia'}; "
        f"lastCommunicationTime mudou {len(mudancas)}× (intervalos: {cadencia})"
    )
    if erros:
        texto += "; falhas de leitura: " + ", ".join(f"{k}×{v}" for k, v in erros.items())
    if max((a["p"] or 0) for a in amostras) <= 0:
        return amb.check(
            "MCP-06", "BLOQUEADO", f"{texto}; sem carga (P = 0): ligue uma carga > 20 W"
        )
    if fator_unidade is None:
        return amb.check(
            "MCP-06", "FAIL", f"{texto}; unidade desconhecida: defina MCP_INSTANTPOWER_UNIT"
        )
    fatores = [
        a["p"] * fator_unidade / (a["v"] * a["i"] / 1000)
        for a in amostras
        if a["p"] is not None
        and a["p"] * fator_unidade > _P_MIN_W
        and (a["v"] or 0) > 0
        and (a["i"] or 0) > 0
    ]
    if not fatores:
        return amb.check(
            "MCP-06",
            "BLOQUEADO",
            f"{texto}; carga ≤ 20 W ou sem V/I: fator P/(V·I) não verificável",
        )
    texto += (
        f"; P/(V·I) mediana {_n(statistics.median(fatores), 2)} "
        f"(mín. {_n(min(fatores), 2)}, máx. {_n(max(fatores), 2)})"
    )
    coerente = all(_FATOR_MIN <= f <= _FATOR_MAX for f in fatores)
    if not coerente:
        texto += f"; fora de [{_n(_FATOR_MIN, 2)}; {_n(_FATOR_MAX, 2)}]: unidade incoerente"
    return amb.check("MCP-06", "PASS" if coerente else "FAIL", texto)


# ---- MCP-08 / MCP-09 sensores -------------------------------------------------------------------
_NOME_CONTACTO = {ContactState.open: "aberto", ContactState.closed: "fechado"}


def _unico(devices: list[dict[str, Any]], tipo: str) -> tuple[dict[str, Any] | None, int]:
    candidatos = [d for d in devices if d.get("type") == tipo and d.get("id")]
    return (candidatos[0] if len(candidatos) == 1 else None), len(candidatos)


def _leituras(amb: Ambiente, device: dict[str, Any]) -> dict[SensorKind, Any]:
    origem = Origin.simulated if amb.simulado else Origin.real
    leituras = sensor_readings_from_device(
        device, device_id=UUID(int=0), now=amb.relogio.agora(), origin=origem
    )
    return {r.kind: r for r in leituras}


async def _estado_contacto(amb: Ambiente, device_id: str) -> ContactState | None:
    leitura = _leituras(amb, await _ler_dispositivo(amb, device_id))[SensorKind.contact]
    return leitura.contact if leitura.status is SensorStatus.ok else None


async def _latencia(amb: Ambiente, device_id: str, acao: str, alvo: ContactState) -> float | None:
    """Do Enter do operador até a leitura mudar; None se não mudar em 90 s."""
    amb.pedir_acao(acao, f"Carregue Enter e, logo a seguir, {acao.upper()} o sensor de contacto.")
    inicio = amb.relogio.monotonic()
    while (decorrido := amb.relogio.monotonic() - inicio) <= _CONTACTO_TIMEOUT_S:
        t = amb.relogio.monotonic()
        try:
            if await _estado_contacto(amb, device_id) is alvo:
                return decorrido
        except Exception:
            pass  # uma leitura falhada não decide; tenta de novo até ao timeout
        await amb.relogio.dormir(t + _CONTACTO_AMOSTRA_S - amb.relogio.monotonic())
    return None


async def check_contacto(amb: Ambiente) -> Check:
    try:
        device, n = _unico(await _ler_casa(amb), _TIPO_CONTACTO)
    except Exception as exc:
        return amb.check("MCP-08", "FAIL", f"get_home_devices falhou ({_erro(exc)})")
    if device is None:
        estado: Estado = "FAIL" if n == 0 else "BLOQUEADO"
        return amb.check("MCP-08", estado, f"{n} sensores de contacto; é preciso exatamente 1")
    leitura = _leituras(amb, device)[SensorKind.contact]
    idade = _idade(device, amb.relogio.agora())
    if leitura.status is SensorStatus.stale:
        return amb.check(
            "MCP-08", "BLOQUEADO", f"leitura antiga ({idade}); repita com --interactive"
        )
    if leitura.contact is None:
        return amb.check("MCP-08", "FAIL", f"estado desconhecido ({idade})")
    texto = f"estado: {_NOME_CONTACTO[leitura.contact]}; {idade}"
    if not amb.interativo:
        return amb.check("MCP-08", "PASS", f"{texto}; latência não medida (sem --interactive)")
    passos = [("abrir", ContactState.open), ("fechar", ContactState.closed)]
    if leitura.contact is ContactState.open:
        passos.reverse()
    latencias: dict[str, float | None] = {}
    for acao, alvo in passos:
        latencias[acao] = await _latencia(amb, device["id"], acao, alvo)
    partes = [
        f"latência ao {acao}: " + (f"{_n(v)} s" if v is not None else "sem mudança em 90 s")
        for acao, v in latencias.items()
    ]
    texto += "; " + "; ".join(partes) + f" (amostragem {_n(_CONTACTO_AMOSTRA_S, 0)} s)"
    if any(v is None for v in latencias.values()):
        return amb.check("MCP-08", "FAIL", texto)
    pior = max(v for v in latencias.values() if v is not None)
    texto += (
        f"; meta < {_n(_META_LATENCIA_S, 0)} s "
        + ("realista" if pior < _META_LATENCIA_S else "NÃO realista")
        + " só pela leitura do sensor"
    )
    return amb.check("MCP-08", "PASS", texto)


async def check_clima(amb: Ambiente) -> Check:
    try:
        device, n = _unico(await _ler_casa(amb), _TIPO_CLIMA)
    except Exception as exc:
        return amb.check("MCP-09", "FAIL", f"get_home_devices falhou ({_erro(exc)})")
    if device is None:
        estado: Estado = "FAIL" if n == 0 else "BLOQUEADO"
        return amb.check("MCP-09", estado, f"{n} sensores de clima; é preciso exatamente 1")
    leituras = _leituras(amb, device)
    t, h = leituras[SensorKind.temperature], leituras[SensorKind.humidity]
    idade = _idade(device, amb.relogio.agora())
    if SensorStatus.stale in (t.status, h.status):
        return amb.check("MCP-09", "BLOQUEADO", f"leitura antiga ({idade})")
    if t.temperature_c is None or h.humidity_pct is None:
        return amb.check("MCP-09", "FAIL", f"temperatura/humidade desconhecida ({idade})")
    return amb.check(
        "MCP-09",
        "PASS",
        f"temperatura {_n(t.temperature_c)} °C; humidade {_n(h.humidity_pct, 0)} %; {idade}",
    )


# ---- MCP-07 falhas (só simulado) ----------------------------------------------------------------
@asynccontextmanager
async def _home_com_grant(
    amb: Ambiente, papeis: tuple[str, ...], factory: SessionFactory | None = None
) -> AsyncIterator[McpHome]:
    """McpHome com o grant privado e curto do `mcp_verify` (2 min, só os papéis pedidos)."""
    with tempfile.TemporaryDirectory() as tmp:  # fora do repositório; apagado no fim
        settings = amb.settings.model_copy(
            update={
                "enable_physical_writes": bool(papeis),
                "mcp_write_grant_path": Path(tmp) / "grant.json",
            }
        )
        if papeis:
            write_grant(settings.mcp_write_grant_path, 2, papeis, settings.mcp_write_max_minutes)
        home = McpHome(settings, factory or amb.session_factory, simulated=amb.simulado)
        try:
            yield home
        finally:
            await home.parar()


async def check_falhas(amb: Ambiente) -> Check:
    if not amb.simulado:
        return amb.check(
            "MCP-07",
            "BLOQUEADO",
            "não se provocam falhas no kit real; seguir os passos manuais de MCP-07 no guia",
        )
    kit = FakeKit(amb.relogio.agora)  # kit à parte: não mexe no estado das outras verificações
    resultados: list[tuple[str, bool]] = []
    async with _home_com_grant(amb, (), kit.session_factory) as home:
        await home._refrescar()
        recusou = not await home.definir_tomada(False)
        resultados.append(("sem grant, escrita recusada", recusou and not kit.writes()))
    async with _home_com_grant(amb, ("lamp",), kit.session_factory) as home:
        await home._refrescar()
        recusou = not await home.definir_tomada(False)
        fora = recusou and "fora da autorização" in (home.ultima_falha or "") and not kit.writes()
        resultados.append(("tomada fora do grant recusada", fora))
        kit.session_down = True
        await home._refrescar()
        desconhecido = not home._mcp_ok and (await home.estado()).lampada.ligada is None
        kit.session_down = False
        await home._refrescar()
        resultados.append(("queda → estado desconhecido e recupera", desconhecido and home._mcp_ok))
    async with _home_com_grant(amb, ("plug",), kit.session_factory) as home:
        await home._refrescar()
        kit.die_after_write = True
        await home.definir_tomada(False)
        kit.die_after_write = False
        incerto = home.ultimo_resultado is not None and home.ultimo_resultado.outcome == "unknown"
        resultados.append(("escrita incerta não repetida", incerto and len(kit.writes()) == 1))
    texto = "; ".join(f"{nome}: {'ok' if ok else 'FALHOU'}" for nome, ok in resultados)
    return amb.check("MCP-07", "PASS" if all(ok for _, ok in resultados) else "FAIL", texto)


# ---- VID-04 câmara ------------------------------------------------------------------------------
def medir_camera(
    abrir: Callable[[], Captura], relogio: Any, duracao_s: float = _CAMERA_S, sem_frame_s=3.0
) -> tuple[Estado, str]:
    """Lê frames em memória durante `duracao_s` e descarta-os logo; devolve só métricas."""
    t0 = relogio.monotonic()
    captura: Captura | None = None
    frames, resolucao, erro = 0, None, None
    aberta_s = primeiro_s = None
    t_primeiro = t_ultimo = 0.0
    try:
        captura = abrir()
        aberta_s = relogio.monotonic() - t0
        inicio = ultimo_ok = relogio.monotonic()
        while relogio.monotonic() - inicio < duracao_s:
            ok, frame = captura.read()
            if ok and frame is not None:
                agora = relogio.monotonic()
                frames += 1
                if primeiro_s is None:
                    primeiro_s, t_primeiro = agora - t0, agora
                t_ultimo = ultimo_ok = agora
                altura, largura = frame.shape[:2]
                resolucao = f"{largura}x{altura}"
            elif relogio.monotonic() - ultimo_ok >= sem_frame_s:
                break
            else:
                relogio.esperar(0.05)
            del frame  # nada fica guardado: só a forma foi lida
    except Exception as exc:
        erro = _erro(exc)  # nunca a mensagem: pode trazer o URL com credenciais
    finally:
        if captura is not None:
            captura.release()
    if frames == 0:
        return "FAIL", "sem frames" + (f" ({erro})" if erro else f" em {_n(duracao_s, 0)} s")
    fps = (frames - 1) / (t_ultimo - t_primeiro) if t_ultimo > t_primeiro else 0.0
    return "PASS", (
        f"resolução {resolucao}; {_n(fps)} FPS ({frames} frames em {_n(t_ultimo - t_primeiro)} s); "
        f"abertura {round((aberta_s or 0) * 1000)} ms; "
        f"primeiro frame {round((primeiro_s or 0) * 1000)} ms; frames descartados, nada gravado"
    )


async def check_camera(amb: Ambiente) -> Check:
    s = amb.settings
    if amb.simulado:
        modo: Modo = "SIMULADO"
    else:
        if not s.video_source:
            return amb.check("VID-04", "BLOQUEADO", "VIDEO_SOURCE não definido")
        kind = s.video_source_kind or ("rtsp" if "://" in s.video_source else "clip")
        modo = "REAL" if kind in ("kit", "rtsp") else "SIMULADO"
        if amb.abrir_camera is None:
            return amb.check(
                "VID-04", "BLOQUEADO", "PRIV-02: câmara só com --camera e autorização", modo
            )
    assert amb.abrir_camera is not None
    status, texto = await asyncio.to_thread(medir_camera, amb.abrir_camera, amb.relogio)
    return amb.check("VID-04", status, texto, modo)


# ---- MCP-04 / MCP-05 escritas -------------------------------------------------------------------
def _confirmou_fisicamente(amb: Ambiente, pergunta: str) -> bool:
    """No kit real a releitura não chega (H1): o operador confirma o que viu."""
    if amb.simulado:
        return True
    return amb.perguntar(f"{pergunta} [s/N] ").strip().lower() in ("s", "sim")


async def check_escrita(amb: Ambiente, papel: str) -> Check:
    cid = "MCP-04" if papel == "lamp" else "MCP-05"
    if papel not in amb.escritas:
        return amb.check(cid, "BLOQUEADO", "não autorizado nesta sessão (sem --write)")
    if papel == "plug":
        print(
            "\nATENÇÃO: o corte desliga a extensão INTEIRA ligada à tomada. Deixe só uma carga "
            "segura (ex.: candeeiro), nada que não possa perder energia."
        )
    try:
        async with _home_com_grant(amb, (papel,)) as home:
            verificar = mcp_verify.verify_lamp if papel == "lamp" else mcp_verify.verify_plug
            r = await verificar(home)
            tempo = home.tempos_ms.get(f"escrita_{papel}")
    except SystemExit as exc:  # recusa do operador ou dispositivo não identificado
        motivo = str(exc.code)
        estado: Estado = "BLOQUEADO" if motivo.startswith("Não autorizado") else "FAIL"
        return amb.check(cid, estado, motivo)
    except Exception as exc:
        return amb.check(cid, "FAIL", f"verificação falhou ({_erro(exc)})")
    aplicado, restaurado = r.get("applied_confirmed") is True, r.get("restored_confirmed") is True
    texto = (
        f"releitura: alteração {'confirmada' if aplicado else 'NÃO confirmada'}, "
        f"restauro {'confirmado' if restaurado else 'NÃO confirmado'}"
    )
    if r.get("failure_reason"):
        texto += f"; motivo: {r['failure_reason']}"
    if papel == "lamp":
        final = r.get("final") or {}
        texto += f"; estado final: ligada={final.get('ligada')}, brilho={final.get('brilho')}"
        if r.get("restored_color_verified") is False:
            texto += "; cor do restauro não verificável pela leitura (brilho baixo): só o olho"
    else:
        texto += f"; ligada inicial={r.get('initial_on')}, final={r.get('final_on')}"
        restaurado = restaurado and r.get("final_on") == r.get("initial_on")
    if tempo is not None:
        texto += f"; última escrita {tempo} ms"
    if not (aplicado and restaurado):
        return amb.check(cid, "FAIL", texto)
    pergunta = (
        "Viu a lâmpada ficar vermelha e voltar ao estado inicial?"
        if papel == "lamp"
        else "Viu a carga desligar e voltar a ligar?"
    )
    if not _confirmou_fisicamente(amb, pergunta):
        return amb.check(cid, "FAIL", f"{texto}; operador NÃO observou a mudança física")
    if not amb.simulado:
        texto += "; mudança física observada pelo operador"
    return amb.check(cid, "PASS", texto)


# ---- orquestração e relatório -------------------------------------------------------------------
async def executar(amb: Ambiente) -> list[Check]:
    """Leituras primeiro; escritas no fim, uma a uma. Sem sessão, o resto fica BLOQUEADO."""
    checks = [await check_oauth(amb)]
    if checks[0].status == "PASS":
        for fn in (check_ferramentas, check_inventario, check_consumo, check_contacto, check_clima):
            checks.append(await fn(amb))
        checks.append(await check_falhas(amb))
        for papel in ("lamp", "plug"):
            checks.append(await check_escrita(amb, papel))
    else:
        for cid in ("MCP-02", "MCP-03", "MCP-06", "MCP-08", "MCP-09", "MCP-07", "MCP-04", "MCP-05"):
            checks.append(amb.check(cid, "BLOQUEADO", "depende de MCP-01 (sessão MCP)"))
    checks.append(await check_camera(amb))
    ordem = list(TESTES)
    return sorted(checks, key=lambda c: ordem.index(c.id))


def _hora(at: datetime) -> str:
    return f"{at.astimezone(UTC):%Y-%m-%d %H:%M:%S} UTC ({at.astimezone():%H:%M:%S} local)"


def _celula(texto: str) -> str:
    return texto.replace("|", "\\|").replace("\n", " ")


def linha_tabela(c: Check, teste: str | None = None, issue: str | None = None) -> str:
    return (
        f"| {c.id} | {_celula(teste or c.title)} | {c.mode} | {c.status} | "
        f"{_celula(f'{_hora(c.at)} · {c.evidence}')} | {issue or TESTES[c.id][1]} |"
    )


def relatorio_markdown(checks: list[Check], modo: Modo, inicio: datetime) -> str:
    linhas = [
        f"Runbook DEMO-03 · modo {modo} · início {_hora(inicio)}",
        "",
        "| ID | Teste | REAL / SIM | PASS / FAIL | Evidência / valor medido | Issue |",
        "|---|---|---|---|---|---|",
        *(linha_tabela(c) for c in checks),
    ]
    return "\n".join(linhas) + "\n"


def relatorio_json(checks: list[Check], modo: Modo, inicio: datetime) -> str:
    dados = {
        "runbook": "DEMO-03",
        "mode": modo,
        "started_utc": inicio.astimezone(UTC).isoformat(timespec="seconds"),
        "started_local": inicio.astimezone().isoformat(timespec="seconds"),
        "checks": [c.as_json() for c in checks],
    }
    return json.dumps(dados, indent=2, ensure_ascii=False) + "\n"


_PIPE = re.compile(r"(?<!\\)\|")


def atualizar_guia(caminho: Path, checks: list[Check]) -> list[str]:
    """Preenche, por ID, as linhas da Folha de resultados; o resto do ficheiro fica intacto.

    Só toca nas colunas REAL / SIM, PASS / FAIL e Evidência. Um BLOQUEADO nunca apaga um
    resultado já registado. Devolve os IDs atualizados.
    """
    por_id = {c.id: c for c in checks if c.id in LINHAS_GUIA}
    texto = caminho.read_text(encoding="utf-8")
    linhas = texto.splitlines(keepends=True)
    folha = next(
        (i for i, li in enumerate(linhas) if li.startswith("## Folha de resultados")), None
    )
    if folha is None:
        raise ValueError("guia sem a secção «Folha de resultados»")
    atualizados: list[str] = []
    for i in range(folha, len(linhas)):
        bruto = linhas[i].rstrip("\r\n")
        fim = linhas[i][len(bruto) :]
        if not bruto.startswith("| "):
            continue
        celulas = [c.strip() for c in _PIPE.split(bruto.strip())[1:-1]]
        if len(celulas) != 6 or celulas[0] not in por_id:
            continue
        c = por_id[celulas[0]]
        if c.status == "BLOQUEADO" and celulas[3]:
            continue
        linhas[i] = linha_tabela(c, teste=celulas[1], issue=celulas[5]) + fim
        atualizados.append(c.id)
    caminho.write_text("".join(linhas), encoding="utf-8", newline="")
    return atualizados


# ---- CLI ----------------------------------------------------------------------------------------
def ambiente_simulado(
    *,
    interativo: bool = False,
    escritas: tuple[str, ...] = (),
    amostras_s: float = 90.0,
    inicio: datetime | None = None,
) -> Ambiente:
    """FakeKit com carga de 60 W, relógio virtual e câmara SIMULADA (sem rede nem ficheiros)."""
    relogio = RelogioSimulado(inicio or datetime.now(UTC).replace(microsecond=0))
    kit = FakeKit(relogio.agora)
    kit.set_load(60)
    settings = Settings(
        _env_file=None,
        mcp_endpoint="",
        mcp_api_key="",
        mcp_lamp_id="",
        mcp_plug_id="",
        mcp_instantpower_unit="W",
        enable_physical_writes=False,
        mcp_write_max_minutes=60,
        video_source="",
    )

    def pedir_acao(acao: str, mensagem: str) -> None:
        print(f"[SIMULADO] {mensagem} (o simulador vai {acao} o sensor 3 s depois)")
        relogio.agendar(3.0, kit.open_contact if acao == "abrir" else kit.close_contact)

    return Ambiente(
        settings=settings,
        simulado=True,
        session_factory=kit.session_factory,
        relogio=relogio,
        pedir_acao=pedir_acao,
        abrir_camera=lambda: (relogio.avancar(0.8), _CapturaSimulada(relogio))[1],
        kit=kit,
        interativo=interativo,
        escritas=escritas,
        amostras_s=amostras_s,
    )


def ambiente_real(
    *, interativo: bool, escritas: tuple[str, ...], amostras_s: float, camera: bool
) -> Ambiente:
    from homemind.connectors.altice_auth import altice_session

    settings = get_settings()
    abrir = None
    if camera and settings.video_source:
        from homemind.features.video.fonte import abrir_rtsp

        def abrir() -> Captura:
            return abrir_rtsp(
                settings.video_source,
                timeout_abrir_ms=settings.video_timeout_abrir_ms,
                timeout_ler_ms=int(settings.video_sem_frame_s * 1000),
            )

    amb = Ambiente(
        settings=settings,
        simulado=False,
        session_factory=altice_session,
        relogio=RelogioReal(),
        pedir_acao=lambda _acao, mensagem: input(f"{mensagem} ") and None,
        abrir_camera=abrir,
        interativo=interativo,
        escritas=escritas,
        amostras_s=amostras_s,
    )
    amb.segredos |= {
        v
        for v in (
            settings.mcp_api_key,
            settings.mcp_endpoint,
            settings.video_source,
            settings.mcp_lamp_id,
            settings.mcp_plug_id,
        )
        if v
    }
    return amb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Runbook de verificação do kit (DEMO-03)")
    parser.add_argument("--simulated", action="store_true", help="FakeKit, tudo SIMULADO")
    parser.add_argument("--samples-s", type=float, default=90.0, help="duração de MCP-06 (s)")
    parser.add_argument("--interactive", action="store_true", help="mede a latência do contacto")
    parser.add_argument("--write", nargs="+", action="extend", choices=("lamp", "plug"), default=[])
    parser.add_argument("--camera", action="store_true", help="abre VIDEO_SOURCE (PRIV-02)")
    parser.add_argument("--out", type=Path, help="ficheiro JSON do relatório (omissão: stdout)")
    parser.add_argument(
        "--update-guide", action="store_true", help="preenche a Folha de resultados"
    )
    parser.add_argument("--guide", type=Path, help="guia a atualizar (omissão: o do repositório)")
    args = parser.parse_args(argv)
    if args.samples_s <= 0:
        parser.error("--samples-s tem de ser > 0")
    if args.update_guide and args.simulated and args.guide is None:
        parser.error("um ensaio SIMULADO só atualiza um guia indicado com --guide")
    # No ensaio SIMULADO os avisos do McpHome vêm das falhas provocadas de propósito (MCP-07).
    nivel = logging.ERROR if args.simulated else logging.WARNING
    logging.basicConfig(level=nivel, format="%(levelname)s %(message)s")
    escritas = tuple(dict.fromkeys(args.write))
    if args.simulated:
        amb = ambiente_simulado(
            interativo=args.interactive, escritas=escritas, amostras_s=args.samples_s
        )
    else:
        amb = ambiente_real(
            interativo=args.interactive,
            escritas=escritas,
            amostras_s=args.samples_s,
            camera=args.camera,
        )
    inicio = amb.relogio.agora()
    try:
        checks = asyncio.run(executar(amb))
    except KeyboardInterrupt:
        print("Runbook interrompido; nada foi registado.")
        return 130
    markdown = relatorio_markdown(checks, amb.modo, inicio)
    dados = relatorio_json(checks, amb.modo, inicio)
    sys.stdout.write("\n" + markdown)
    if args.out is not None:
        args.out.write_text(dados, encoding="utf-8")
        print(f"\nRelatório JSON escrito em {args.out}")
    else:
        sys.stdout.write("\n" + dados)
    if args.update_guide:
        ids = atualizar_guia(args.guide or GUIA, checks)
        print(f"Folha de resultados atualizada: {', '.join(ids) or 'nenhuma linha'}")
    return 1 if any(c.status == "FAIL" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
