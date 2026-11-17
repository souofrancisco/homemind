import asyncio
from datetime import UTC, datetime, timedelta

from homemind.contracts.video import FrameVideo
from homemind.features.gestos.processador import ProcessadorObjectOS
from homemind.features.gestos.tests._fakes import DetetorDeClip
from homemind.features.visao.medir_latencia import latencias, medir, resumo
from homemind.features.visao.tests.test_visao import FonteSimulada


class DetetorAgora(DetetorDeClip):
    """Como o detetor real: `hora` do frame = relógio de parede no momento da deteção."""

    def detetar(self, frame: FrameVideo):
        return super().detetar(frame).model_copy(update={"hora": datetime.now(UTC)})


def test_latencias_emparelha_e_ignora_gestos_sem_luz():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    gestos = [t0, t0 + timedelta(seconds=10), t0 + timedelta(seconds=20)]
    ligacoes = [t0 + timedelta(seconds=1), t0 + timedelta(seconds=12)]
    assert latencias(gestos, ligacoes) == [1.0, 2.0]


def test_resumo():
    assert "nada medido" in resumo([])
    assert "2/3 abaixo de 4 s" in resumo([1.0, 2.0, 5.0])


def test_medir_com_fakes(tmp_path):
    valores = asyncio.run(
        medir(
            FonteSimulada(60),
            DetetorAgora(),
            ProcessadorObjectOS(),
            duracao_s=5,
            gestos_max=1,
            dados=tmp_path,
        )
    )
    assert len(valores) == 1
    assert 0 <= valores[0] < 4
