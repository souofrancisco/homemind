"""Repetição offline: frames de deteção em JSONL (#8). Uma `FrameDeteccoes` por linha.

Só metadados (caixas, keypoints, tempos): nunca imagens.
"""

from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import ValidationError

from homemind.contracts.visao import FrameDeteccoes


def ler_jsonl(caminho: str | Path) -> Iterator[FrameDeteccoes]:
    """Ignora linhas vazias; linha inválida -> `ValueError` com o nº da linha."""
    with open(caminho, encoding="utf-8") as f:
        for n, linha in enumerate(f, start=1):
            if not linha.strip():
                continue
            try:
                yield FrameDeteccoes.model_validate_json(linha)
            except ValidationError as e:
                raise ValueError(f"{caminho}: linha {n} inválida: {e.error_count()} erro(s)") from e


def escrever_jsonl(frames: Iterable[FrameDeteccoes], caminho: str | Path) -> int:
    """Devolve o nº de frames escritos."""
    n = 0
    with open(caminho, "w", encoding="utf-8") as f:
        for frame in frames:
            f.write(frame.model_dump_json() + "\n")
            n += 1
    return n
