"""Escolha do dispositivo de inferência (CUDA > MPS > CPU). `torch` só é importado aqui."""


def escolher_device(pedido: str = "auto") -> str:
    """`auto` escolhe o melhor disponível; outro valor (`cpu`, `mps`, `cuda:0`) é respeitado.

    Sem `torch` instalado (extra `visao` ausente) em modo `auto` devolve `cpu`.
    """
    pedido = (pedido or "auto").strip().lower()
    if pedido != "auto":
        return pedido
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda:0"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"
