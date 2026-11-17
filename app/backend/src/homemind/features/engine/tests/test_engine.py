"""Máquina de estados com FakeHome, tempos curtos e relógio controlado (sem rede/hardware)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from homemind.connectors.fake_home import FakeHome
from homemind.contracts.eventos import ObjetoLevantado, Presenca
from homemind.features.engine.engine import Engine, Estado, Tempos
from homemind.features.engine.eventlog import EventLog
from homemind.features.engine.rules import RulesStore

ESPERA, AVISO, MAX = 0.3, 0.15, 0.4


class Relogio:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 17, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def avancar(self, **kw) -> None:
        self.t += timedelta(**kw)


class HomeContada(FakeHome):
    def __init__(self) -> None:
        super().__init__(watts_tomada=60)
        self.escritas = 0

    async def definir_lampada(self, ligada, cor=None, brilho=None):
        self.escritas += 1
        return await super().definir_lampada(ligada, cor, brilho)

    async def definir_tomada(self, ligada):
        self.escritas += 1
        return await super().definir_tomada(ligada)


def montar(tmp_path, **tempos):
    regras = RulesStore(tmp_path / "rules.json")
    regras.carregar()
    home, relogio = HomeContada(), Relogio()
    t = Tempos(espera_s=ESPERA, aviso_s=AVISO, suspenso_max_s=MAX, tarifa_eur_kwh=0.2)
    for k, v in tempos.items():
        setattr(t, k, v)
    engine = Engine(home, regras, EventLog(tmp_path / "events.jsonl"), t, relogio)
    return engine, home, relogio


def correr(coro):
    return asyncio.run(coro)


def presenca(ha_alguem):
    return Presenca(ha_alguem=ha_alguem, hora=datetime.now(UTC))


def levantar(classe):
    return ObjetoLevantado(classe=classe, hora=datetime.now(UTC))


def test_gesto_ativa_modo(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("caneca"))
        assert e.estado == Estado.ATIVO and e.modo.id == "pausa"
        assert home.lampada.ligada and home.lampada.cor == "branco_quente"
        assert home.lampada.brilho == 30

    correr(cenario())


def test_repeticao_ignorada_e_registada(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("livro"))
        escritas = home.escritas
        await e.processar(levantar("livro"))
        assert home.escritas == escritas
        assert "já está ativo" in e.registo.recentes()[-1].message

    correr(cenario())


def test_outro_objeto_troca_modo(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("livro"))
        await e.processar(levantar("comando"))
        assert e.modo.id == "cinema" and home.lampada.cor == "azul" and home.lampada.brilho == 10

    correr(cenario())


def test_objeto_sem_regra_ativa(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        await e.iniciar()
        e.regras.definir_ativa("pausa", False)
        await e.processar(levantar("caneca"))
        assert e.estado == Estado.INATIVO and home.escritas == 0

    correr(cenario())


def test_ausencia_aviso_e_suspensao(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("livro"))
        await e.processar(presenca(False))
        assert e.estado == Estado.EM_ESPERA and e.espera_ate is not None
        await asyncio.sleep(ESPERA - AVISO + 0.05)
        assert e.estado == Estado.EM_ESPERA and home.lampada.brilho == 20
        await asyncio.sleep(AVISO)
        assert e.estado == Estado.SUSPENSO
        assert not home.lampada.ligada and not home.tomada.ligada

    correr(cenario())


def test_regresso_em_espera_restaura_brilho(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("livro"))
        await e.processar(presenca(False))
        await asyncio.sleep(ESPERA - AVISO + 0.05)  # já avisou (20%)
        await e.processar(presenca(True))
        assert e.estado == Estado.ATIVO and home.lampada.brilho == 40
        await asyncio.sleep(ESPERA)
        assert e.estado == Estado.ATIVO  # temporizador cancelado

    correr(cenario())


def test_regresso_apos_suspensao_restaura_e_poupa(tmp_path):
    async def cenario():
        e, home, relogio = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("livro"))  # tomada ligada: 60 W
        await e.processar(presenca(False))
        await asyncio.sleep(ESPERA + 0.05)
        assert e.estado == Estado.SUSPENSO
        relogio.avancar(minutes=30)
        assert e.home_state().energy_saved_wh == 30  # contagem em curso
        await e.processar(presenca(True))
        assert e.estado == Estado.ATIVO and e.modo.id == "leitura"
        assert home.lampada.ligada and home.lampada.brilho == 40 and home.tomada.ligada
        s = e.home_state()
        assert s.energy_saved_wh == 30 and s.energy_saved_eur == 0.006

    correr(cenario())


def test_suspenso_demasiado_tempo_fica_inativo(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("caneca"))
        await e.processar(presenca(False))
        await asyncio.sleep(ESPERA + MAX + 0.1)
        assert e.estado == Estado.INATIVO and e.modo is None
        await e.processar(presenca(True))
        assert e.estado == Estado.INATIVO and not home.lampada.ligada

    correr(cenario())


def test_off_cancela_temporizadores(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("livro"))
        await e.processar(presenca(False))
        await e.desligar_tudo()
        assert e.estado == Estado.INATIVO
        assert not home.lampada.ligada and not home.tomada.ligada
        escritas = home.escritas
        await asyncio.sleep(ESPERA + 0.1)
        assert e.estado == Estado.INATIVO and home.escritas == escritas

    correr(cenario())


def test_presenca_sem_transicao_nao_faz_nada(tmp_path):
    async def cenario():
        e, _, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(presenca(True))
        n = len(e.registo.recentes())
        await e.processar(presenca(True))
        assert len(e.registo.recentes()) == n

    correr(cenario())


def test_falha_da_casa_nao_rebenta_o_motor(tmp_path):
    class HomeAvariada(FakeHome):
        async def definir_lampada(self, *a, **k):
            raise TimeoutError

    async def cenario():
        e, _, _ = montar(tmp_path)
        e.home = HomeAvariada()
        await e.iniciar()
        await e.processar(levantar("caneca"))
        assert e.registo.recentes()[-2].level == "error"

    correr(cenario())


def test_fila_de_thread(tmp_path):
    async def cenario():
        e, _, _ = montar(tmp_path)
        await e.iniciar()
        consumidor = asyncio.create_task(e.consumir())
        await asyncio.to_thread(e.publicar_de_thread, levantar("comando"))
        await asyncio.sleep(0.05)
        consumidor.cancel()
        assert e.modo.id == "cinema"

    correr(cenario())


def test_registo_em_jsonl_sem_imagens(tmp_path):
    async def cenario():
        e, _, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("caneca"))

    correr(cenario())
    linhas = (tmp_path / "events.jsonl").read_text().splitlines()
    assert linhas and all(
        set(json.loads(x)) == {"id", "timestamp", "level", "message", "source"} for x in linhas
    )


def test_vigiar_camara_publica_so_mudancas(tmp_path):
    async def cenario():
        e, _, _ = montar(tmp_path)
        await e.iniciar()
        sinal = {"ok": False}
        fila = e.subscrever()
        tarefa = asyncio.create_task(e.vigiar_camara(lambda: sinal["ok"], intervalo_s=0.01))
        await asyncio.sleep(0.05)
        assert fila.empty()  # sem mudança, nada publicado
        sinal["ok"] = True
        await asyncio.sleep(0.05)
        tarefa.cancel()
        assert e.camara_ok and e.home_state().camera_ok
        msgs = [fila.get_nowait() for _ in range(fila.qsize())]
        assert [m.type for m in msgs] == ["event", "home_state"]

    correr(cenario())


def test_gesto_do_mesmo_modo_em_espera_cancela_suspensao(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("livro"))
        await e.processar(presenca(False))  # presença falhou com a pessoa ainda lá
        await asyncio.sleep(ESPERA - AVISO + 0.05)  # já em aviso (20%)
        await e.processar(levantar("livro"))
        assert e.estado == Estado.ATIVO and e.presenca is True and home.lampada.brilho == 40
        await asyncio.sleep(ESPERA + 0.1)
        assert e.estado == Estado.ATIVO and home.lampada.ligada  # não suspendeu

    correr(cenario())


def test_gesto_com_casa_suspensa_repoe_e_mantem_modo(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        await e.iniciar()
        await e.processar(levantar("livro"))
        await e.processar(presenca(False))
        await asyncio.sleep(ESPERA + 0.05)
        assert e.estado == Estado.SUSPENSO
        await e.processar(levantar("livro"))
        assert e.estado == Estado.ATIVO and e.modo.id == "leitura" and home.tomada.ligada

    correr(cenario())


class HomeFalha(HomeContada):
    ultima_falha = "sem sessão de escritas autorizada"

    async def definir_lampada(self, ligada, cor=None, brilho=None):
        return False

    async def definir_tomada(self, ligada):
        return False


def test_falha_fisica_nao_ativa_modo_nem_poupanca(tmp_path):
    async def cenario():
        e, _, _ = montar(tmp_path)
        e.home = HomeFalha()
        await e.iniciar()
        await e.processar(levantar("caneca"))
        assert e.modo is None and e.estado == Estado.INATIVO
        assert any(
            i.level == "error" and "falha física" in i.message for i in e.registo.recentes(10)
        )
        res = await e.desligar_tudo()
        assert res.code == "mcp_unavailable" and "autorizada" in res.message
        assert res.devices.lampada == "unknown"
        assert e.home_state().energy_saved_wh == 0

    correr(cenario())


def test_polling_do_home_empurra_estado_para_o_ws(tmp_path):
    async def cenario():
        e, home, _ = montar(tmp_path)
        home.ao_estado = None  # FakeHome não tem polling; simula o McpHome
        e.home.ao_estado = e._casa_atualizada
        await e.iniciar()
        fila = e.subscrever()
        casa = (await home.estado()).model_copy(update={"mcp_ok": True})
        e.home.ao_estado(casa, True)
        msg = fila.get_nowait()
        assert msg.type == "home_state" and msg.data.mcp_ok is True
        assert e.home_state().mcp_ok is True

    correr(cenario())
