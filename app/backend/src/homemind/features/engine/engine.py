"""Motor ObjectOS: eventos de visão → regras → Home. Máquina de estados e poupança de energia.

Estados: INATIVO → ATIVO (gesto) → EM_ESPERA (divisão vazia) → SUSPENSO (luz/tomada off, estado
guardado) → INATIVO (após `suspenso_max_s`). O regresso restaura; `desligar_tudo` cancela tudo.
Todas as mudanças passam por `_lock`; os temporizadores são uma única tarefa asyncio cancelável.
Modelos expostos ao frontend: ver frontend-api-contract (v3) §3, §4 e §7.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from homemind.contracts.eventos import Evento, ObjetoLevantado, Presenca
from homemind.contracts.home import Backend, EstadoCasa, Home
from homemind.contracts.regras import Acao, AcaoLampada, AcaoTomada, Rule
from homemind.features.engine.eventlog import EventLog, EventLogItem, Nivel
from homemind.features.engine.rules import RulesStore, descrever_acao

log = logging.getLogger(__name__)


class Estado(StrEnum):
    INATIVO = "inativo"
    ATIVO = "ativo"
    EM_ESPERA = "em_espera"
    SUSPENSO = "suspenso"


@dataclass
class Tempos:
    espera_s: float = 180
    aviso_s: float = 5
    brilho_aviso: int = 20
    suspenso_max_s: float = 30 * 60
    tarifa_eur_kwh: float = 0.16


class HomeState(BaseModel):
    mode: str | None  # id da regra ativa
    mode_name: str | None
    state: Estado
    presence: bool | None  # None = ainda sem dados da visão
    camera_ok: bool
    mcp_ok: bool
    backend: Backend
    waiting_remaining_seconds: float | None
    energy_saved_wh: float  # estimativa desde o arranque do servidor
    energy_saved_eur: float
    updated_at: datetime
    casa: EstadoCasa | None  # None só se Home.estado() falhar


class HomeStateMessage(BaseModel):
    type: Literal["home_state"] = "home_state"
    data: HomeState


class EventMessage(BaseModel):
    type: Literal["event"] = "event"
    data: EventLogItem


class ErrorData(BaseModel):
    code: str
    message: str


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    data: ErrorData


WsMessage = HomeStateMessage | EventMessage | ErrorMessage


class OffDevices(BaseModel):
    lampada: Literal["off", "unknown"]
    tomada: Literal["off", "unknown"]


class OffResult(BaseModel):
    success: bool
    state: Estado
    backend: Backend
    devices: OffDevices
    code: Literal["partial_failure", "mcp_unavailable"] | None = None
    message: str | None = None


_DESLIGAR = [AcaoLampada(ligada=False), AcaoTomada(ligada=False)]


def _relogio() -> datetime:
    return datetime.now(UTC)


class Engine:
    def __init__(
        self,
        home: Home,
        regras: RulesStore,
        registo: EventLog,
        tempos: Tempos,
        relogio: Callable[[], datetime] = _relogio,
    ) -> None:
        self.home = home
        self.regras = regras
        self.registo = registo
        self.tempos = tempos
        self.relogio = relogio
        self.fila: asyncio.Queue[ObjetoLevantado | Presenca] = asyncio.Queue()
        # Atualizado pela visão (Pessoa 1).
        self.camara_ok = False

        self.estado = Estado.INATIVO
        self.modo: Rule | None = None
        self.presenca: bool | None = None
        self.espera_ate: datetime | None = None
        self.suspenso_desde: datetime | None = None
        self._watts_suspensos = 0.0
        self._wh = 0.0
        self._guardado: EstadoCasa | None = None
        self._avisado = False
        self._casa: EstadoCasa | None = None
        self._lock = asyncio.Lock()
        self._timer: asyncio.Task | None = None
        self._ouvintes: set[asyncio.Queue[WsMessage]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        registo.ao_registar = lambda item: self._emitir(EventMessage(data=item))

    # ---- ciclo de vida -------------------------------------------------------------------
    async def iniciar(self) -> None:
        self._loop = asyncio.get_running_loop()
        await self._ler_casa()
        self._log("Motor iniciado")

    async def parar(self) -> None:
        self._cancelar_timer()

    async def consumir(self) -> None:
        """Consome a fila de eventos da visão (uma tarefa durante a vida da app)."""
        while True:
            evento = await self.fila.get()
            try:
                await self.processar(evento)
            except Exception:
                log.exception("erro ao processar evento")
                self._log("Erro interno ao processar evento", "error")

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """Loop do motor (para o `PublicadorEventos` da P2); None antes do arranque."""
        return self._loop

    def publicar_de_thread(self, evento: ObjetoLevantado | Presenca) -> None:
        """Para a thread de visão: entrega o evento ao loop sem bloquear."""
        if self._loop is None:
            raise RuntimeError("motor não iniciado")
        self._loop.call_soon_threadsafe(self.fila.put_nowait, evento)

    # ---- API pública ---------------------------------------------------------------------
    async def processar(self, evento: Evento, simulado: bool = False) -> None:
        async with self._lock:
            prefixo = "[SIMULADO] " if simulado else ""
            if isinstance(evento, ObjetoLevantado):
                await self._objeto(evento, prefixo)
            else:
                await self._presenca(evento, prefixo)
            self._publicar()

    async def desligar_tudo(self) -> OffResult:
        async with self._lock:
            self._cancelar_timer()
            self._fechar_poupanca()
            self._log("Desligar tudo (manual)")
            ok = await self._aplicar(_DESLIGAR)
            self._limpar(Estado.INATIVO)
            self._publicar()
        devices = OffDevices(
            lampada="off" if ok["lampada"] else "unknown",
            tomada="off" if ok["tomada"] else "unknown",
        )
        res = OffResult(
            success=all(ok.values()), state=self.estado, backend=self._backend(), devices=devices
        )
        if not any(ok.values()):
            res.code, res.message = "mcp_unavailable", "Não foi possível contactar o kit"
        elif not all(ok.values()):
            falhou = "a lâmpada" if not ok["lampada"] else "a tomada"
            res.code = "partial_failure"
            res.message = f"Não foi possível confirmar que {falhou} desligou"
        return res

    async def notificar(self) -> None:
        """Publica o estado atual (ex.: depois de mudar regras ou `camara_ok`)."""
        async with self._lock:
            await self._ler_casa()
            self._publicar()

    def home_state(self) -> HomeState:
        wh = self._wh + self._wh_em_curso()
        restante = None
        if self.espera_ate is not None:
            restante = max((self.espera_ate - self.relogio()).total_seconds(), 0.0)
        return HomeState(
            mode=self.modo.id if self.modo else None,
            mode_name=self.modo.nome if self.modo else None,
            state=self.estado,
            presence=self.presenca,
            camera_ok=self.camara_ok,
            mcp_ok=self._casa.mcp_ok if self._casa else False,
            backend=self._backend(),
            waiting_remaining_seconds=restante,
            energy_saved_wh=round(wh, 3),
            energy_saved_eur=round(wh / 1000 * self.tempos.tarifa_eur_kwh, 4),
            updated_at=self.relogio(),
            casa=self._casa,
        )

    def subscrever(self) -> asyncio.Queue[WsMessage]:
        q: asyncio.Queue[WsMessage] = asyncio.Queue(maxsize=200)
        self._ouvintes.add(q)
        return q

    def cancelar_subscricao(self, q: asyncio.Queue[WsMessage]) -> None:
        self._ouvintes.discard(q)

    # ---- transições ----------------------------------------------------------------------
    async def _objeto(self, ev: ObjetoLevantado, prefixo: str) -> None:
        self._log(f"{prefixo}{ev.classe.capitalize()} levantado(a)")
        self.presenca = True  # o gesto implica alguém presente
        regra = self.regras.ativa_para(ev.classe)
        if regra is None:
            self._log(f"Sem regra ativa para {ev.classe}; ignorado")
            return
        if (
            self.modo
            and self.modo.id == regra.id
            and self.estado in (Estado.ATIVO, Estado.EM_ESPERA)
        ):
            self._log(f"«{regra.nome}» já está ativo; nada a fazer")
            return
        self._cancelar_timer()
        self._fechar_poupanca()
        self._guardado, self._avisado, self.espera_ate = None, False, None
        await self._aplicar(regra.acoes)
        self.modo = regra
        self._mudar(Estado.ATIVO, f"«{regra.nome}» ativado")

    async def _presenca(self, ev: Presenca, prefixo: str) -> None:
        if ev.ha_alguem == self.presenca:
            return
        self.presenca = ev.ha_alguem
        self._log(prefixo + ("Entrou alguém na divisão" if ev.ha_alguem else "Divisão vazia"))
        if not ev.ha_alguem:
            if self.estado == Estado.ATIVO:
                self._guardado = await self._ler_casa()
                self._avisado = False
                self.espera_ate = self.relogio() + timedelta(seconds=self.tempos.espera_s)
                self._mudar(Estado.EM_ESPERA, f"Em espera: suspende em {self.tempos.espera_s:g} s")
                self._timer = asyncio.create_task(self._contar())
            return
        if self.estado == Estado.EM_ESPERA:
            self._cancelar_timer()
            if self._avisado and self._guardado:
                await self._repor(self._guardado)
            self._guardado, self._avisado, self.espera_ate = None, False, None
            self._mudar(Estado.ATIVO, "Regresso: modo mantido")
        elif self.estado == Estado.SUSPENSO:
            self._cancelar_timer()
            self._fechar_poupanca()
            if self._guardado:
                await self._repor(self._guardado)
            self._guardado = None
            self._mudar(Estado.ATIVO, "Regresso: estado anterior restaurado")

    async def _contar(self) -> None:
        """EM_ESPERA → aviso (brilho baixo) → SUSPENSO → INATIVO. Cancelada por qualquer mudança."""
        t = self.tempos
        await asyncio.sleep(max(t.espera_s - t.aviso_s, 0))
        async with self._lock:
            if self.estado != Estado.EM_ESPERA:
                return
            if self._guardado and self._guardado.lampada.ligada:
                await self._chamar("lampada", self.home.definir_lampada(True, None, t.brilho_aviso))
                self._avisado = True
                await self._ler_casa()
                self._log(f"Aviso: luz a {t.brilho_aviso}%, suspende em {t.aviso_s:g} s")
            self._publicar()

        await asyncio.sleep(min(t.aviso_s, t.espera_s))
        async with self._lock:
            if self.estado != Estado.EM_ESPERA:
                return
            await self._suspender()
            self._publicar()

        await asyncio.sleep(t.suspenso_max_s)
        async with self._lock:
            if self.estado != Estado.SUSPENSO:
                return
            self._fechar_poupanca()
            self._limpar(Estado.INATIVO, "Suspenso há demasiado tempo: inativo")
            self._publicar()

    async def _suspender(self) -> None:
        watts: float | None = None
        try:
            watts = await self.home.ler_consumo()
        except Exception:
            log.exception("ler_consumo falhou")
        if watts is None:
            self._log("Consumo indisponível: poupança não contabilizada", "warning")
        await self._aplicar(_DESLIGAR)
        self._watts_suspensos = watts or 0.0
        self.suspenso_desde = self.relogio()
        self.espera_ate = None
        consumo = f"{watts:.0f} W" if watts is not None else "consumo desconhecido"
        self._mudar(Estado.SUSPENSO, f"Suspenso: luz e tomada desligadas ({consumo})")

    # ---- auxiliares ----------------------------------------------------------------------
    def _log(self, mensagem: str, level: Nivel = "info") -> None:
        self.registo.registar(mensagem, level)

    def _backend(self) -> Backend:
        return self._casa.backend if self._casa else self.registo.source

    def _mudar(self, novo: Estado, mensagem: str | None = None) -> None:
        self.estado = novo
        if mensagem:
            self._log(mensagem)

    def _limpar(self, estado: Estado, mensagem: str | None = None) -> None:
        self.modo, self._guardado, self._avisado = None, None, False
        self.espera_ate, self.suspenso_desde = None, None
        self._mudar(estado, mensagem)

    def _cancelar_timer(self) -> None:
        if self._timer and self._timer is not asyncio.current_task():
            self._timer.cancel()
        self._timer = None

    def _wh_em_curso(self) -> float:
        if self.suspenso_desde is None:
            return 0.0
        horas = (self.relogio() - self.suspenso_desde).total_seconds() / 3600
        return self._watts_suspensos * max(horas, 0)

    def _fechar_poupanca(self) -> None:
        if self.suspenso_desde is None:
            return
        wh = self._wh_em_curso()
        self._wh += wh
        self.suspenso_desde = None
        eur = wh / 1000 * self.tempos.tarifa_eur_kwh
        self._log(f"Poupança estimada: {wh:.2f} Wh ({eur:.4f} €)")

    async def _aplicar(self, acoes: list[Acao]) -> dict[str, bool]:
        resultado: dict[str, bool] = {}
        for a in acoes:
            if a.dispositivo == "lampada":
                coro = self.home.definir_lampada(a.ligada, a.cor, a.brilho)
            else:
                coro = self.home.definir_tomada(a.ligada)
            resultado[a.dispositivo] = await self._chamar(a.dispositivo, coro)
            if resultado[a.dispositivo]:
                self._log(descrever_acao(a).capitalize())
        await self._ler_casa()
        return resultado

    async def _repor(self, g: EstadoCasa) -> None:
        """Repõe só o que era conhecido (`None` = desconhecido, não se toca)."""
        acoes = []
        if g.lampada.ligada is not None:
            acoes.append(
                AcaoLampada(
                    ligada=g.lampada.ligada,
                    cor=g.lampada.cor,
                    brilho=g.lampada.brilho,
                )
            )
        if g.tomada.ligada is not None:
            acoes.append(AcaoTomada(ligada=g.tomada.ligada))
        if acoes:
            await self._aplicar(acoes)

    async def _chamar(self, dispositivo: str, coro) -> bool:
        try:
            ok = await coro
        except Exception:
            log.exception("escrita em %s falhou", dispositivo)
            ok = False
        if not ok:
            self._log(f"Falha ao atuar em {dispositivo} (não confirmado)", "error")
        return ok

    async def _ler_casa(self) -> EstadoCasa | None:
        try:
            self._casa = await self.home.estado()
            self.registo.source = self._casa.backend
        except Exception:
            log.exception("estado da casa indisponível")
        return self._casa

    def _emitir(self, msg: WsMessage) -> None:
        for q in self._ouvintes:
            if q.full():  # cliente lento: descarta o mais antigo; o próximo home_state repõe
                q.get_nowait()
            q.put_nowait(msg)

    def _publicar(self) -> None:
        self._emitir(HomeStateMessage(data=self.home_state()))
