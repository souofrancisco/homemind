"""Afinador offline de gestos (#8): `python -m homemind.features.gestos.afinador --jsonl FICHEIRO`.

Reproduz frames de deteção (JSONL) pelo `ProcessadorObjectOS`, imprime eventos e resumo.
Sem rede, sem dependências novas, nunca grava imagens.
"""

import argparse
import dataclasses
import sys
from collections import Counter
from collections.abc import Iterator
from typing import Any

from homemind.contracts.eventos import ObjetoLevantado, Presenca
from homemind.contracts.visao import FrameDeteccoes
from homemind.core.config import get_settings
from homemind.features.gestos.parametros import ParametrosGesto, ParametrosPresenca
from homemind.features.gestos.processador import ProcessadorObjectOS
from homemind.features.gestos.repeticao import escrever_jsonl, ler_jsonl

CLASSES = ("caneca", "livro", "comando")


class DetetorIndisponivel(RuntimeError):
    pass


def _frames_de_video(caminho: str) -> Iterator[FrameDeteccoes]:
    """Ponto de extensão: frames de deteção de um clip.

    TODO(integração P1): importar o `Detetor` real e a `FonteVideo` de clip, e fazer
    `yield detetor.detetar(frame_video)` por frame (sem guardar a imagem).
    """
    raise DetetorIndisponivel("Detetor real ainda não disponível (P1)")


def _converter(tipo: Any) -> type:
    return int if tipo is int else float


def _adicionar_overrides(parser: argparse.ArgumentParser, prefixo: str, cls: type) -> None:
    for campo in dataclasses.fields(cls):
        flag = f"--{prefixo}-{campo.name.replace('_', '-')}"
        parser.add_argument(
            flag,
            dest=f"{prefixo}_{campo.name}",
            type=_converter(campo.type),
            default=None,
            help=f"override de {cls.__name__}.{campo.name}",
        )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="afinador", description="Afinador offline de gestos e presença (ObjectOS)."
    )
    fonte = p.add_mutually_exclusive_group(required=True)
    fonte.add_argument("--jsonl", help="JSONL de FrameDeteccoes (um por linha)")
    fonte.add_argument("--video", help="clip de vídeo (requer o Detetor real de P1)")
    p.add_argument("--gravar-jsonl", help="com --video: grava as deteções em JSONL")
    p.add_argument(
        "--esperar", help="contagens esperadas, ex. caneca=4,livro=3,comando=3,presenca=2"
    )
    _adicionar_overrides(p, "gesto", ParametrosGesto)
    _adicionar_overrides(p, "presenca", ParametrosPresenca)
    return p


def _overrides(args: argparse.Namespace, prefixo: str, cls: type) -> Any:
    base = cls.de_settings(get_settings())  # type: ignore[attr-defined]
    mudancas = {
        c.name: v
        for c in dataclasses.fields(cls)
        if (v := getattr(args, f"{prefixo}_{c.name}")) is not None
    }
    return dataclasses.replace(base, **mudancas)


def _parse_esperar(texto: str) -> dict[str, int]:
    esperado: dict[str, int] = {}
    for par in texto.split(","):
        chave, _, valor = par.partition("=")
        chave = chave.strip()
        if chave not in (*CLASSES, "presenca") or not valor.strip().isdigit():
            raise ValueError(f"--esperar inválido: {par!r}")
        esperado[chave] = int(valor)
    return esperado


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.gravar_jsonl and not args.video:
        parser.error("--gravar-jsonl só é válido com --video")
    try:
        esperado = _parse_esperar(args.esperar) if args.esperar else None
    except ValueError as e:
        parser.error(str(e))
    pg: ParametrosGesto = _overrides(args, "gesto", ParametrosGesto)
    pp: ParametrosPresenca = _overrides(args, "presenca", ParametrosPresenca)

    try:
        frames = ler_jsonl(args.jsonl) if args.jsonl else _frames_de_video(args.video)
        if args.gravar_jsonl:
            frames = _gravando(frames, args.gravar_jsonl)
        return _correr(frames, ProcessadorObjectOS(pg, pp), pg, pp, esperado)
    except DetetorIndisponivel as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2


def _gravando(frames: Iterator[FrameDeteccoes], saida: str) -> Iterator[FrameDeteccoes]:
    guardados = list(frames)
    escrever_jsonl(guardados, saida)
    return iter(guardados)


def _correr(
    frames: Iterator[FrameDeteccoes],
    proc: ProcessadorObjectOS,
    pg: ParametrosGesto,
    pp: ParametrosPresenca,
    esperado: dict[str, int] | None,
) -> int:
    n = 0
    t_primeiro = t_anterior = 0.0
    intervalo_max = 0.0
    classes: Counter[str] = Counter()
    transicoes = 0
    for frame in frames:
        if n == 0:
            t_primeiro = frame.t
        else:
            intervalo_max = max(intervalo_max, frame.t - t_anterior)
        t_anterior = frame.t
        n += 1
        for ev in proc.processar(frame):
            rel = frame.t - t_primeiro
            if isinstance(ev, ObjetoLevantado):
                classes[ev.classe] += 1
                detalhe = f"classe={ev.classe}"
            elif isinstance(ev, Presenca):
                transicoes += 1
                detalhe = f"ha_alguem={ev.ha_alguem}"
            print(f"t={rel:7.2f}s  hora={ev.hora.isoformat()}  {ev.tipo}  {detalhe}")

    duracao = t_anterior - t_primeiro if n else 0.0
    fps_medio = (n - 1) / duracao if n > 1 and duracao > 0 else 0.0
    fps_min = 1 / intervalo_max if intervalo_max > 0 else 0.0
    print("--- resumo ---")
    print(f"frames: {n}  duração: {duracao:.2f}s")
    print(f"fps médio: {fps_medio:.1f}  fps mínimo (pior intervalo): {fps_min:.1f}")
    print("gestos: " + "  ".join(f"{c}={classes[c]}" for c in CLASSES))
    print(f"transições de presença: {transicoes}")
    print(f"parâmetros gesto: {pg}")
    print(f"parâmetros presença: {pp}")

    if esperado is None:
        return 0
    obtido = {**{c: classes[c] for c in CLASSES}, "presenca": transicoes}
    difs = [f"{k}: esperado {v}, obtido {obtido[k]}" for k, v in esperado.items() if obtido[k] != v]
    if difs:
        print("DIFERENÇAS:\n  " + "\n  ".join(difs))
        return 1
    print("OK: contagens batem com --esperar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
