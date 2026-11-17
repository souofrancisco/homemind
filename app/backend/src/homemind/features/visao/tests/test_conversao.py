import numpy as np

from homemind.contracts.visao import COCO_PARA_CLASSE
from homemind.features.visao.conversao import _np, objetos_de_resultado, pessoas_de_resultado
from homemind.features.visao.tests._fakes import resultado_objetos, resultado_pose


def test_mapeia_classes_e_descarta_outras():
    res = resultado_objetos(
        [[0, 0, 10, 10], [1, 1, 5, 5], [2, 2, 6, 6], [3, 3, 9, 9]],
        [0.9, 0.8, 0.7, 0.6],
        [41, 73, 65, 0],  # 0 = pessoa: fora do mapa
        ids=[1, 2, 3, 4],
    )
    objs = objetos_de_resultado(res, COCO_PARA_CLASSE)
    assert [o.classe for o in objs] == ["caneca", "livro", "comando"]
    assert [o.track_id for o in objs] == [1, 2, 3]
    assert objs[0].confianca == 0.9 and objs[0].caixa.x2 == 10


def test_track_id_none_sem_tracker():
    objs = objetos_de_resultado(resultado_objetos([[0, 0, 4, 4]], [0.5], [41]), COCO_PARA_CLASSE)
    assert objs[0].track_id is None


def test_vazio_e_sem_boxes():
    vazio = resultado_objetos([], [], [])
    assert objetos_de_resultado(vazio, COCO_PARA_CLASSE) == ()
    assert objetos_de_resultado(type("R", (), {"boxes": None})(), COCO_PARA_CLASSE) == ()


def test_confianca_limitada_e_caixa_invertida_normalizada():
    res = resultado_objetos([[10, 8, 2, 1]], [1.0000001], [41])
    o = objetos_de_resultado(res, COCO_PARA_CLASSE)[0]
    assert o.confianca == 1.0
    assert (o.caixa.x1, o.caixa.y1, o.caixa.x2, o.caixa.y2) == (2, 1, 10, 8)


def test_livro_noutra_categoria_coco():
    mapa = {41: "caneca", 39: "livro", 65: "comando"}
    res = resultado_objetos([[0, 0, 4, 4], [0, 0, 4, 4]], [0.9, 0.9], [73, 39])
    assert [o.classe for o in objetos_de_resultado(res, mapa)] == ["livro"]


def _kp(n=1):
    return np.arange(n * 17 * 2, dtype=float).reshape(n, 17, 2)


def test_pessoa_com_17_keypoints():
    conf = np.full((1, 17), 0.8)
    res = resultado_pose([[0, 0, 50, 100]], [0.9], _kp(), conf, ids=[7])
    p = pessoas_de_resultado(res)[0]
    assert len(p.keypoints) == 17 and p.track_id == 7
    assert p.keypoints[9].x == 18 and p.keypoints[9].confianca == 0.8


def test_keypoints_sem_conf_ficam_a_zero():
    res = resultado_pose([[0, 0, 5, 5]], [0.9], _kp(), None)
    assert all(k.confianca == 0 for k in pessoas_de_resultado(res)[0].keypoints)


def test_keypoints_com_forma_errada_descartados():
    xy = np.zeros((1, 15, 2))
    assert pessoas_de_resultado(resultado_pose([[0, 0, 5, 5]], [0.9], xy)) == ()
    assert pessoas_de_resultado(type("R", (), {"boxes": None, "keypoints": None})()) == ()


def test_np_aceita_objeto_tipo_tensor():
    class Tensor:
        def cpu(self):
            return self

        def numpy(self):
            return np.array([1.0, 2.0])

    assert _np(Tensor()).tolist() == [1.0, 2.0]
