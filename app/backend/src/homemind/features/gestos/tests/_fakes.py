"""Helpers de teste (dados SIMULADOS) para gestos/presença. Sem hardware nem rede."""

from collections.abc import Iterable, Iterator
from typing import Literal

from homemind.contracts.simulacao import objeto_simulado, pessoa_simulada, sequencia_simulada
from homemind.contracts.visao import KP, ClasseObjeto, FrameDeteccoes, Keypoint, PessoaDetetada

Lado = Literal["esq", "dir"]
Estado = Literal["levantado", "repouso", "beber", "longe"]


def pessoa_levantada(lado: Lado = "dir", *, confianca_pulso: float | None = None) -> PessoaDetetada:
    """Pessoa com o pulso do `lado` acima do cotovelo (o simulador só levanta o direito)."""
    pessoa = pessoa_simulada(pulso_dir_levantado=lado == "dir")
    if lado == "dir" and confianca_pulso is None:
        return pessoa
    i_pulso, i_ombro = (
        (KP.PULSO_ESQ, KP.OMBRO_ESQ) if lado == "esq" else (KP.PULSO_DIR, KP.OMBRO_DIR)
    )
    pontos = list(pessoa.keypoints)
    if lado == "esq":
        y = pessoa.kp(i_ombro).y + 10
        pontos[i_pulso] = pontos[i_pulso].model_copy(update={"y": y})
    if confianca_pulso is not None:
        pontos[i_pulso] = pontos[i_pulso].model_copy(update={"confianca": confianca_pulso})
    return pessoa.model_copy(update={"keypoints": tuple[Keypoint, ...](pontos)})


def segmento(
    duracao_s: float,
    estado: Estado,
    classe: ClasseObjeto = "caneca",
    *,
    fps: float = 10.0,
    t0: float = 0.0,
    indice0: int = 0,
    lado: Lado = "dir",
    confianca_pulso: float | None = None,
) -> list[FrameDeteccoes]:
    """Frames de `duracao_s` a `fps` no `estado`:
    levantado = objeto no pulso levantado; repouso = braços em baixo, objeto pousado longe;
    beber = objeto no pulso mas abaixo do cotovelo; longe = pulso levantado, objeto longe."""
    n = round(duracao_s * fps)
    base = sequencia_simulada(
        n,
        fps=fps,
        classe=classe,
        levantado=estado in ("levantado", "longe"),
        objeto_no_pulso=estado in ("levantado", "beber"),
        t0=t0,
        indice0=indice0,
    )
    if lado == "dir" and confianca_pulso is None:
        return list(base)
    saida = []
    for f in base:
        pessoa = (
            pessoa_levantada(lado, confianca_pulso=confianca_pulso)
            if estado
            in (
                "levantado",
                "longe",
            )
            else pessoa_simulada()
        )
        objetos = f.objetos
        if estado in ("levantado", "beber") and lado == "esq":
            pulso = pessoa.kp(KP.PULSO_ESQ)
            objetos = (objeto_simulado(classe, (pulso.x, pulso.y)),)
        saida.append(f.model_copy(update={"pessoas": (pessoa,), "objetos": objetos}))
    return saida


def encadear(*partes: Iterable[FrameDeteccoes]) -> Iterator[FrameDeteccoes]:
    for p in partes:
        yield from p
