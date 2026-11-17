import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from homemind.contracts.video import FrameVideo
from homemind.core.config import Settings
from homemind.features.visao.detetor import DetetorYolo
from homemind.features.visao.tests._fakes import ModeloFalso, resultado_objetos, resultado_pose


def _detetor(**cfg):
    obj = ModeloFalso(
        resultado_objetos(
            [[0, 0, 10, 10]],
            [0.9],
            [
                41,
            ][:1],
            ids=[3],
        )
    )
    pose = ModeloFalso(
        resultado_pose([[0, 0, 50, 100]], [0.8], np.zeros((1, 17, 2)), np.full((1, 17), 0.9))
    )
    settings = Settings(visao_device="cpu", **cfg)
    return DetetorYolo(settings, modelo_objetos=obj, modelo_pose=pose), obj, pose


def _frame(t=0.0, indice=5):
    return FrameVideo(imagem=np.zeros((48, 64, 3), dtype=np.uint8), indice=indice, t=t)


def test_args_do_track_e_resultado():
    import time

    det, obj, pose = _detetor()
    frame = _frame(t=time.monotonic() - 2.0, indice=9)
    out = det.detetar(frame)
    assert (out.indice, out.t, out.largura, out.altura) == (9, frame.t, 64, 48)
    assert out.objetos[0].classe == "caneca" and out.objetos[0].track_id == 3
    assert len(out.pessoas) == 1 and len(out.pessoas[0].keypoints) == 17
    delta = (datetime.now(UTC) - out.hora).total_seconds()
    assert 1.8 < delta < 2.5  # hora = instante de captura, não de processamento
    co = obj.chamadas[0]
    assert co["persist"] is True and co["verbose"] is False and co["conf"] == 0.4
    assert sorted(co["classes"]) == [41, 65, 73] and co["tracker"] == "bytetrack.yaml"
    assert co["device"] == "cpu" and co["imgsz"] == 640
    cp = pose.chamadas[0]
    assert cp["persist"] is True and cp["classes"] == [0] and cp["conf"] == 0.4


def test_livro_e_conf_configuraveis():
    det, obj, _ = _detetor(visao_livro_coco=39, visao_conf_objetos=0.25)
    det.detetar(_frame())
    assert sorted(obj.chamadas[0]["classes"]) == [39, 41, 65]
    assert obj.chamadas[0]["conf"] == 0.25


def test_resultado_sem_imagem():
    det, _, _ = _detetor()
    out = det.detetar(_frame())
    assert "imagem" not in out.model_dump()


def test_preparar_idempotente_com_modelos_injetados():
    det, obj, _ = _detetor()
    det.preparar()
    det.preparar()
    assert obj.chamadas == []  # nem aquecimento: modelos já injetados


def test_construir_nao_carrega_e_falta_de_pesos_da_erro_claro(tmp_path):
    det = DetetorYolo(Settings(visao_pasta_modelos=str(tmp_path)))
    with pytest.raises(FileNotFoundError, match="visao.pesos"):
        det.preparar()


def test_importar_modulos_nao_importa_ultralytics_nem_torch():
    codigo = (
        "import sys; import homemind.features.visao.detetor, homemind.features.visao.conversao;"
        "assert 'ultralytics' not in sys.modules and 'torch' not in sys.modules"
    )
    src = Path(__file__).resolve().parents[4]
    r = subprocess.run([sys.executable, "-c", codigo], cwd=src, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
