import sys
from types import SimpleNamespace

import pytest

from homemind.features.visao.dispositivo import escolher_device


def _torch(cuda: bool, mps: bool):
    return SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
    )


@pytest.mark.parametrize(
    ("cuda", "mps", "esperado"),
    [(True, True, "cuda:0"), (False, True, "mps"), (False, False, "cpu")],
)
def test_auto_prefere_cuda_depois_mps_depois_cpu(monkeypatch, cuda, mps, esperado):
    monkeypatch.setitem(sys.modules, "torch", _torch(cuda, mps))
    assert escolher_device("auto") == esperado


def test_pedido_explicito_respeitado_sem_importar_torch(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)  # import falharia
    assert escolher_device("cpu") == "cpu"
    assert escolher_device("cuda:1") == "cuda:1"


def test_auto_sem_torch_devolve_cpu(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    assert escolher_device("auto") == "cpu"
