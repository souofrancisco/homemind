from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from homemind.contracts.eventos import ObjetoLevantado, Presenca, evento_adapter
from homemind.contracts.simulacao import pessoa_simulada, sequencia_simulada
from homemind.contracts.visao import (
    COCO_PARA_CLASSE,
    KP,
    Caixa,
    FrameDeteccoes,
    Keypoint,
    PessoaDetetada,
)

HORA = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def test_eventos_ida_e_volta_json_pelo_discriminador():
    for evento in (
        ObjetoLevantado(classe="caneca", hora=HORA),
        Presenca(ha_alguem=False, hora=HORA),
    ):
        assert evento_adapter.validate_json(evento.model_dump_json()) == evento


def test_evento_rejeita_classe_desconhecida():
    with pytest.raises(ValidationError):
        ObjetoLevantado(classe="chaves", hora=HORA)


def test_classes_coco_do_plano():
    assert COCO_PARA_CLASSE == {41: "caneca", 73: "livro", 65: "comando"}


def test_pessoa_exige_17_keypoints():
    caixa = Caixa(x1=0, y1=0, x2=10, y2=10)
    with pytest.raises(ValidationError):
        PessoaDetetada(confianca=0.9, caixa=caixa, keypoints=(Keypoint(x=0, y=0, confianca=1),))


def test_caixa_invertida_rejeitada():
    with pytest.raises(ValidationError):
        Caixa(x1=10, y1=0, x2=0, y2=10)


def test_pulso_levantado_fica_acima_do_cotovelo_em_coordenadas_de_imagem():
    levantada = pessoa_simulada(pulso_dir_levantado=True)
    assert levantada.kp(KP.PULSO_DIR).y < levantada.kp(KP.COTOVELO_DIR).y
    pousada = pessoa_simulada()
    assert pousada.kp(KP.PULSO_DIR).y > pousada.kp(KP.COTOVELO_DIR).y


def test_pipeline_mock_troca_frames_por_json_sem_camara():
    frames = list(sequencia_simulada(20, fps=10, classe="livro", levantado=True))
    assert [f.indice for f in frames] == list(range(20))
    assert frames[10].t == pytest.approx(1.0)
    for frame in frames:
        assert FrameDeteccoes.model_validate_json(frame.model_dump_json()) == frame
    objeto, pessoa = frames[0].objetos[0], frames[0].pessoas[0]
    pulso = pessoa.kp(KP.PULSO_DIR)
    assert objeto.classe == "livro"
    assert objeto.caixa.centro == (pulso.x, pulso.y)


def test_sequencia_sem_pessoa_nem_objeto():
    frame = next(sequencia_simulada(1, com_pessoa=False))
    assert frame.pessoas == () and frame.objetos == ()


def test_sequencias_encadeiam_com_t0_e_indice0():
    a = list(sequencia_simulada(5, fps=10, indice0=0, t0=0.0))
    b = list(sequencia_simulada(5, fps=5, indice0=5, t0=a[-1].t + 0.1, com_pessoa=False))
    assert [f.indice for f in a + b] == list(range(10))
    assert all(x.t < y.t for x, y in zip(a + b, (a + b)[1:], strict=False))
    assert b[0].pessoas == ()


def test_objeto_no_pulso_independente_do_pulso_levantado():
    (frame,) = sequencia_simulada(1, classe="caneca", levantado=False, objeto_no_pulso=True)
    pessoa = frame.pessoas[0]
    pulso, cotovelo = pessoa.kp(KP.PULSO_DIR), pessoa.kp(KP.COTOVELO_DIR)
    assert pulso.y > cotovelo.y
    assert frame.objetos[0].caixa.centro == (pulso.x, pulso.y)
