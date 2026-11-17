"""Afinador offline de gestos (#8): `python -m homemind.features.gestos.afinador --jsonl FICHEIRO`.

Reproduz frames de deteção (JSONL) pelo `ProcessadorObjectOS`, imprime eventos e resumo.
Sem rede, sem dependências novas, nunca grava imagens.
"""

import argparse
import dataclasses
import importlib
import os
import sys
import time
from collections import Counter
from collections.abc import Iterator
from typing import Any

from homemind.contracts.eventos import ObjetoLevantado, Presenca
from homemind.contracts.visao import FrameDeteccoes
from homemind.core.config import get_settings
from homemind.features.gestos.parametros import ParametrosGesto, ParametrosPresenca
from homemind.features.gestos.processador import ProcessadorObjectOS
from homemind.features.gestos.repeticao import ler_jsonl

CLASSES = ("caneca", "livro", "comando")


class DetetorIndisponivel(RuntimeError):
    pass


MSG_DETETOR = "Detetor real ainda não disponível (P1, issue #4): passa --detetor modulo:Classe"


@dataclasses.dataclass
class MedidasVideo:
    """Preenchido por `_frames_de_video` enquanto o clip é lido (modo --video)."""

    fps_clip: float = 0.0
    frames: int = 0
    tempo_detetar_s: float = 0.0

    @property
    def ms_por_frame(self) -> float:
        return 1000 * self.tempo_detetar_s / self.frames if self.frames else 0.0


def _carregar_detetor(especificacao: str | None) -> Any:
    """`modulo:Classe` -> instância sem argumentos com método `detetar`."""
    if not especificacao:
        raise DetetorIndisponivel(MSG_DETETOR)
    modulo, sep, nome = especificacao.partition(":")
    if not sep or not modulo or not nome:
        raise DetetorIndisponivel(f"--detetor inválido ({especificacao!r}); formato modulo:Classe")
    try:
        cls = getattr(importlib.import_module(modulo), nome)
    except (ImportError, AttributeError) as e:
        raise DetetorIndisponivel(f"{MSG_DETETOR} ({type(e).__name__}: {e})") from e
    detetor = cls()
    if not callable(getattr(detetor, "detetar", None)):
        raise DetetorIndisponivel(f"{especificacao} não tem o método detetar(FrameVideo)")
    return detetor


def _frames_de_video(
    caminho: str, detetor: Any, medidas: MedidasVideo | None = None
) -> Iterator[FrameDeteccoes]:
    """Lê o clip sequencialmente (todos os frames) e devolve `detetor.detetar(frame)` por frame.

    `t` = tempo do clip (estritamente crescente). A imagem vive só durante a iteração:
    nunca é guardada nem escrita.
    """
    from homemind.contracts.video import FrameVideo
    from homemind.features.video.fonte import FPS_CLIP_OMISSAO, abrir_clip

    medidas = medidas if medidas is not None else MedidasVideo()
    if not os.path.isfile(caminho):
        raise OSError(f"clip não encontrado: {caminho}")
    import cv2

    captura = abrir_clip(caminho)
    try:
        if hasattr(captura, "isOpened") and not captura.isOpened():
            raise OSError(f"clip ilegível: {caminho}")
        fps = captura.get(cv2.CAP_PROP_FPS)
        fps = fps if fps and fps > 0 else FPS_CLIP_OMISSAO
        medidas.fps_clip = fps
        t_ant = -1.0
        indice = 0
        while True:
            ok, imagem = captura.read()
            if not ok:
                break
            t = captura.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if indice == 0 and not t > 0:
                t = 0.0
            elif not t > t_ant:
                t = t_ant + 1 / fps
            t_ant = t
            inicio = time.perf_counter()
            resultado = detetor.detetar(FrameVideo(imagem=imagem, indice=indice, t=t))
            medidas.tempo_detetar_s += time.perf_counter() - inicio
            indice += 1
            medidas.frames = indice
            del imagem
            yield resultado
        if indice == 0:
            raise OSError(f"clip sem frames legíveis: {caminho}")
    finally:
        captura.release()


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
    fonte.add_argument("--video", help="clip de vídeo (requer --detetor)")
    p.add_argument("--detetor", help="com --video: Detetor injetado, formato modulo:Classe")
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
    if args.detetor and not args.video:
        parser.error("--detetor só é válido com --video")
    try:
        esperado = _parse_esperar(args.esperar) if args.esperar else None
    except ValueError as e:
        parser.error(str(e))
    pg: ParametrosGesto = _overrides(args, "gesto", ParametrosGesto)
    pp: ParametrosPresenca = _overrides(args, "presenca", ParametrosPresenca)

    medidas: MedidasVideo | None = None
    try:
        if args.jsonl:
            frames = ler_jsonl(args.jsonl)
        else:
            detetor = _carregar_detetor(args.detetor)
            medidas = MedidasVideo()
            frames = _frames_de_video(args.video, detetor, medidas)
        if args.gravar_jsonl:
            frames = _gravando(frames, args.gravar_jsonl)
        return _correr(frames, ProcessadorObjectOS(pg, pp), pg, pp, esperado, medidas)
    except (DetetorIndisponivel, ValueError, OSError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2


def _gravando(frames: Iterator[FrameDeteccoes], saida: str) -> Iterator[FrameDeteccoes]:
    """Grava em streaming (uma linha por frame) enquanto o frame passa ao processador."""
    with open(saida, "w", encoding="utf-8") as f:
        for frame in frames:
            f.write(frame.model_dump_json() + "\n")
            yield frame


def _correr(
    frames: Iterator[FrameDeteccoes],
    proc: ProcessadorObjectOS,
    pg: ParametrosGesto,
    pp: ParametrosPresenca,
    esperado: dict[str, int] | None,
    medidas: MedidasVideo | None = None,
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
    if medidas is not None:
        print(f"clip: {medidas.fps_clip:.1f} fps  detetar: {medidas.ms_por_frame:.1f} ms/frame")
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
