from homemind.contracts.eventos import ObjetoLevantado, Presenca
from homemind.core.config import Settings
from homemind.features.gestos.parametros import ParametrosGesto, ParametrosPresenca
from homemind.features.gestos.processador import ProcessadorObjectOS
from homemind.features.gestos.tests._fakes import encadear, segmento


def correr(proc: ProcessadorObjectOS, frames) -> list:
    return [e for f in frames for e in proc.processar(f)]


GESTO_RAPIDO = ParametrosGesto(janela_s=0.1, min_frames=1)


def test_presenca_antes_do_gesto_no_mesmo_frame():
    # Ao 2.º frame confirmam-se presença (2 positivos) e gesto (janela 0,1 s): presença primeiro.
    proc = ProcessadorObjectOS(GESTO_RAPIDO)
    assert correr(proc, segmento(0.1, "levantado")) == []
    eventos = proc.processar(segmento(0.2, "levantado")[1])
    assert [type(e) for e in eventos] == [Presenca, ObjetoLevantado]
    assert proc.ha_alguem


def test_gesto_sem_pessoa_presente_ainda():
    # Presença exige 5 frames; o gesto dispara antes: ha_alguem ainda False.
    proc = ProcessadorObjectOS(GESTO_RAPIDO, ParametrosPresenca(frames_regresso=5))
    eventos = correr(proc, segmento(0.2, "levantado"))
    assert [type(e) for e in eventos] == [ObjetoLevantado]
    assert not proc.ha_alguem


def test_frames_repetidos_ou_antigos_ignorados():
    proc = ProcessadorObjectOS()
    frames = segmento(1.5, "levantado")
    eventos = correr(proc, frames)
    assert sum(isinstance(e, ObjetoLevantado) for e in eventos) == 1
    assert correr(proc, frames) == []  # repetição integral
    assert proc.processar(frames[3]) == ()  # antigo


def test_fluxo_completo_um_gesto():
    proc = ProcessadorObjectOS()
    frames = encadear(
        segmento(1.5, "levantado", "livro"), segmento(1.0, "repouso", t0=1.5, indice0=15)
    )
    eventos = correr(proc, frames)
    assert [type(e) for e in eventos] == [Presenca, ObjetoLevantado]
    assert eventos[1].classe == "livro"


def test_de_settings():
    s = Settings(gesto_janela_s=2.0, presenca_frames_regresso=4)
    proc = ProcessadorObjectOS.de_settings(s)
    eventos = correr(proc, segmento(1.5, "levantado"))  # janela 2 s: nunca dispara
    assert not any(isinstance(e, ObjetoLevantado) for e in eventos)
    assert [type(e) for e in eventos] == [Presenca]  # regresso só ao 4.º frame
    assert proc.ha_alguem
