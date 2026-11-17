import pytest

from homemind.contracts.eventos import Presenca
from homemind.contracts.visao import FrameDeteccoes
from homemind.core.config import Settings
from homemind.features.gestos.parametros import ParametrosPresenca
from homemind.features.gestos.presenca import DetetorPresenca
from homemind.features.gestos.tests._fakes import plano_presenca, segmento_presenca


def correr(
    frames: list[FrameDeteccoes], params: ParametrosPresenca | None = None
) -> list[tuple[float, Presenca]]:
    det = DetetorPresenca(params)
    saida = []
    for f in frames:
        for e in det.processar(f):
            saida.append((f.t, e))
    return saida


def valores(eventos: list[tuple[float, Presenca]]) -> list[bool]:
    return [e.ha_alguem for _, e in eventos]


def test_inicial_false_sem_eventos():
    det = DetetorPresenca()
    assert det.ha_alguem is False
    assert correr(segmento_presenca(10.0, False)) == []


def test_um_frame_nao_chega_dois_confirmam():
    assert correr(segmento_presenca(0.1, True)) == []
    eventos = correr(segmento_presenca(0.2, True))  # arranque com pessoa
    assert valores(eventos) == [True]
    assert eventos[0][0] == pytest.approx(0.1)


def test_propriedade_ha_alguem_acompanha():
    det = DetetorPresenca()
    f1, f2 = segmento_presenca(0.2, True)
    det.processar(f1)
    assert det.ha_alguem is False
    det.processar(f2)
    assert det.ha_alguem is True


def test_saida_so_apos_3s():
    # Pessoa 1 s, depois vazio: 2,9 s (30 frames a 10 fps = t 0,1..3,0 desde último positivo)
    base = plano_presenca([(1.0, True), (2.9, False)])
    assert valores(correr(base)) == [True]
    # primeiro vazio em t=1,0; 3,0 s depois = t=4,0 (último frame de 3,1 s de vazio)
    completo = plano_presenca([(1.0, True), (3.1, False)])
    eventos = correr(completo)
    assert valores(eventos) == [True, False]
    assert eventos[1][0] == pytest.approx(4.0)


def test_regresso_em_dois_frames():
    frames = plano_presenca([(1.0, True), (4.0, False), (0.2, True)])
    eventos = correr(frames)
    assert valores(eventos) == [True, False, True]
    assert eventos[2][0] == pytest.approx(5.1)


def test_alternancia_frame_a_frame_sem_transicoes_extra():
    frames = plano_presenca([(1.0, True)])
    t, i = len(frames) / 10, len(frames)
    for k in range(40):
        frames += segmento_presenca(0.1, k % 2 == 0, t0=t, indice0=i)
        t += 0.1
        i += 1
    assert valores(correr(frames)) == [True]


def test_vazios_curtos_repetidos_nao_desligam():
    frames = plano_presenca([(1.0, True), (2.9, False), (0.1, True)] * 3)
    assert valores(correr(frames)) == [True]


def test_perda_breve_de_frames_nao_desliga():
    frames = plano_presenca([(1.0, True), (1.5, None), (1.0, True)])
    assert valores(correr(frames)) == [True]


def test_buraco_longo_seguido_de_um_vazio_nao_gera_evento():
    frames = plano_presenca([(1.0, True), (10.0, None), (0.1, False)])
    assert valores(correr(frames)) == [True]


def test_buraco_longo_e_vazio_continuo_confirma_so_com_frames_reais():
    frames = plano_presenca([(1.0, True), (10.0, None), (3.1, False)])
    eventos = correr(frames)
    assert valores(eventos) == [True, False]
    assert eventos[1][0] == pytest.approx(14.0)  # 3 s depois do 1.º vazio (t=11,0)


def test_buraco_reinicia_regresso():
    # 1 frame positivo, buraco, 1 frame positivo: não são "2 consecutivos"
    frames = plano_presenca([(0.1, True), (2.0, None), (0.1, True)])
    assert correr(frames) == []


@pytest.mark.parametrize("fps", [5.0, 10.0, 30.0])
def test_fps_variavel_mesmos_resultados(fps):
    frames = plano_presenca([(1.0, True), (4.0, False), (1.0, True)], fps=fps)
    eventos = correr(frames)
    assert valores(eventos) == [True, False, True]
    assert eventos[1][0] - 1.0 == pytest.approx(3.0, abs=1e-6)  # ausência a 3,0 s do 1.º vazio


def test_parametros_alterados_mudam_comportamento():
    frames = plano_presenca([(1.0, True), (2.0, False), (1.0, True)])
    assert valores(correr(frames)) == [True]
    curto = ParametrosPresenca(ausencia_s=1.5)
    assert valores(correr(frames, curto)) == [True, False, True]
    exigente = ParametrosPresenca(frames_regresso=5)
    assert valores(correr(plano_presenca([(0.4, True)]), exigente)) == []
    assert valores(correr(plano_presenca([(0.5, True)]), exigente)) == [True]


def test_hora_e_a_do_frame_que_confirmou():
    frames = plano_presenca([(1.0, True), (3.5, False)])
    det = DetetorPresenca()
    por_frame = [(f, det.processar(f)) for f in frames]
    confirmados = [(f, e) for f, es in por_frame for e in es]
    assert len(confirmados) == 2
    for f, e in confirmados:
        assert e.hora == f.hora


def test_so_transicoes():
    assert valores(correr(plano_presenca([(30.0, True)]))) == [True]
    assert valores(correr(plano_presenca([(1.0, True), (30.0, False)]))) == [True, False]


def test_parametros_de_settings():
    p = ParametrosPresenca.de_settings(Settings())
    assert (p.ausencia_s, p.frames_regresso, p.intervalo_max_s) == (3.0, 2, 1.0)
