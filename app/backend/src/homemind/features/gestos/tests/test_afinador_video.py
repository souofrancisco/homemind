"""Afinador `--video` com detetor SIMULADO sobre um clip sintético (sem hardware nem rede)."""

import cv2
import numpy as np
import pytest

from homemind.features.gestos.afinador import main
from homemind.features.gestos.repeticao import ler_jsonl

DETETOR = "homemind.features.gestos.tests._fakes:DetetorDeClip"
FRAMES = 80


@pytest.fixture
def clip(tmp_path):
    caminho = tmp_path / "clip.avi"
    w = cv2.VideoWriter(str(caminho), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48))
    if not w.isOpened():
        pytest.skip("codec MJPG indisponível no OpenCV deste ambiente")
    for i in range(FRAMES):
        w.write(np.full((48, 64, 3), i * 3 % 256, dtype=np.uint8))
    w.release()
    return caminho


def _ficheiros(pasta):
    return sorted(p.name for p in pasta.iterdir())


def test_video_gera_eventos_esperados(clip, capsys):
    assert main(["--video", str(clip), "--detetor", DETETOR, "--esperar", "caneca=1"]) == 0
    saida = capsys.readouterr().out
    assert "classe=caneca" in saida
    assert "clip: 10.0 fps" in saida
    assert f"frames: {FRAMES}" in saida


def test_gravar_jsonl_sem_imagens_e_reproduz(clip, tmp_path, capsys):
    jsonl = tmp_path / "saida.jsonl"
    args = ["--video", str(clip), "--detetor", DETETOR, "--gravar-jsonl", str(jsonl)]
    assert main([*args, "--esperar", "caneca=1,presenca=1"]) == 0
    frames = list(ler_jsonl(jsonl))
    assert len(frames) == FRAMES
    ts = [f.t for f in frames]
    assert all(b > a for a, b in zip(ts, ts[1:], strict=False))
    assert [f.indice for f in frames] == list(range(FRAMES))
    assert "imagem" not in jsonl.read_text()
    capsys.readouterr()
    assert main(["--jsonl", str(jsonl), "--esperar", "caneca=1,presenca=1"]) == 0
    assert _ficheiros(tmp_path) == ["clip.avi", "saida.jsonl"]


def test_sem_detetor_sai_com_2(clip, capsys):
    assert main(["--video", str(clip)]) == 2
    assert "passa --detetor modulo:Classe" in capsys.readouterr().err


def test_detetor_inexistente_sai_com_2(clip, capsys):
    assert main(["--video", str(clip), "--detetor", "nao.existe:X"]) == 2
    assert "Detetor real ainda não disponível" in capsys.readouterr().err


def test_detetor_sem_metodo_sai_com_2(clip):
    assert main(["--video", str(clip), "--detetor", "collections:OrderedDict"]) == 2


def test_clip_inexistente_sai_com_2(tmp_path, capsys):
    assert main(["--video", str(tmp_path / "nao.avi"), "--detetor", DETETOR]) == 2
    assert "clip" in capsys.readouterr().err
    assert _ficheiros(tmp_path) == []


def test_clip_ilegivel_sai_com_2(tmp_path):
    lixo = tmp_path / "lixo.avi"
    lixo.write_bytes(b"nao e video")
    assert main(["--video", str(lixo), "--detetor", DETETOR]) == 2
    assert _ficheiros(tmp_path) == ["lixo.avi"]
