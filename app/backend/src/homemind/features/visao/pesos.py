"""Descarrega os pesos YOLO11 para `VISAO_PASTA_MODELOS` (único sítio com download).

    python -m homemind.features.visao.pesos [--variante s|n]

Nunca é chamado no arranque do servidor nem no CI. Requer o extra `visao` e rede.
"""

import argparse
import shutil
from pathlib import Path

from homemind.core.config import get_settings


def nomes_pesos(variante: str) -> tuple[str, str]:
    return f"yolo11{variante}.pt", f"yolo11{variante}-pose.pt"


def main(argv: list[str] | None = None) -> int:
    cfg = get_settings()
    ap = argparse.ArgumentParser(prog="python -m homemind.features.visao.pesos")
    ap.add_argument("--variante", choices=["s", "n"], default=cfg.visao_variante)
    args = ap.parse_args(argv)

    from ultralytics.utils.downloads import attempt_download_asset

    pasta = Path(cfg.visao_pasta_modelos)
    pasta.mkdir(parents=True, exist_ok=True)
    for nome in nomes_pesos(args.variante):
        destino = pasta / nome
        if destino.exists():
            print(f"já existe: {destino}")
            continue
        obtido = Path(attempt_download_asset(str(destino)))
        if obtido.exists() and obtido.resolve() != destino.resolve():
            shutil.move(str(obtido), destino)
        if not destino.exists():
            print(f"falhou: {nome}")
            return 1
        print(f"ok: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
