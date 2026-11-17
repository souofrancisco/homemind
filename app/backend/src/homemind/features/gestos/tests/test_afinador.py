import pytest

from homemind.contracts.visao import ClasseObjeto, FrameDeteccoes
from homemind.features.gestos.afinador import main
from homemind.features.gestos.repeticao import escrever_jsonl, ler_jsonl
from homemind.features.gestos.tests._fakes import segmento, segmento_presenca

LEVANTAMENTOS: tuple[ClasseObjeto, ...] = (
    ("caneca", "livro", "comando") * 3 + ("caneca",)  # 4 + 3 + 3
)


def clip_sintetico(fps: float = 10.0, duracao_levantar: float = 1.5) -> list[FrameDeteccoes]:
    """10 levantamentos + 3 «beber» + saída (4 s) e regresso. Dados SIMULADOS."""
    frames: list[FrameDeteccoes] = []
    t, i = 0.0, 0

    def juntar(seg: list[FrameDeteccoes]) -> None:
        nonlocal t, i
        frames.extend(seg)
        t += len(seg) / fps
        i += len(seg)

    for classe in LEVANTAMENTOS:
        juntar(segmento(duracao_levantar, "levantado", classe, fps=fps, t0=t, indice0=i))
        juntar(segmento(3.0, "repouso", classe, fps=fps, t0=t, indice0=i))
    for classe in ("caneca", "caneca", "caneca"):
        juntar(segmento(2.0, "beber", classe, fps=fps, t0=t, indice0=i))
        juntar(segmento(3.0, "repouso", classe, fps=fps, t0=t, indice0=i))
    juntar(segmento_presenca(4.0, False, fps=fps, t0=t, indice0=i))  # saída
    juntar(segmento_presenca(1.0, True, fps=fps, t0=t, indice0=i))  # regresso
    return frames


@pytest.fixture
def jsonl(tmp_path):
    caminho = tmp_path / "clip.jsonl"
    escrever_jsonl(clip_sintetico(), caminho)
    return caminho


def test_esperar_certo_devolve_0_e_imprime_resumo(jsonl, capsys):
    codigo = main(["--jsonl", str(jsonl), "--esperar", "caneca=4,livro=3,comando=3,presenca=3"])
    saida = capsys.readouterr().out
    assert codigo == 0
    assert "--- resumo ---" in saida
    assert "caneca=4  livro=3  comando=3" in saida
    assert "transições de presença: 3" in saida
    assert "fps médio: 10.0" in saida
    assert "objeto_levantado  classe=caneca" in saida
    assert "presenca  ha_alguem=False" in saida
    assert "ParametrosGesto" in saida


def test_esperar_errado_devolve_1_com_diferenca(jsonl, capsys):
    codigo = main(["--jsonl", str(jsonl), "--esperar", "caneca=5,livro=3"])
    saida = capsys.readouterr().out
    assert codigo == 1
    assert "caneca: esperado 5, obtido 4" in saida
    assert "livro" not in saida.split("DIFERENÇAS")[1]


def test_sem_esperar_devolve_0(jsonl):
    assert main(["--jsonl", str(jsonl)]) == 0


def test_override_de_limiar_muda_o_resultado(jsonl, capsys):
    # janela 2 s > levantamentos de 1,5 s: nenhum gesto.
    codigo = main(["--jsonl", str(jsonl), "--gesto-janela-s", "2.0", "--esperar", "caneca=0"])
    saida = capsys.readouterr().out
    assert codigo == 0
    assert "caneca=0  livro=0  comando=0" in saida
    assert "janela_s=2.0" in saida


def test_override_de_presenca(jsonl, capsys):
    # ausência de 5 s > saída de 4 s: sem transição para False; só 1 transição (entrada).
    codigo = main(["--jsonl", str(jsonl), "--presenca-ausencia-s", "5", "--esperar", "presenca=1"])
    assert codigo == 0


def test_video_sem_detetor_real_devolve_2(capsys):
    assert main(["--video", "clip.mp4"]) == 2
    assert "Detetor real ainda não disponível (P1)" in capsys.readouterr().err


def test_fontes_mutuamente_exclusivas(jsonl):
    with pytest.raises(SystemExit) as e:
        main(["--jsonl", str(jsonl), "--video", "x.mp4"])
    assert e.value.code == 2


def test_gravar_jsonl_so_com_video(jsonl, tmp_path):
    with pytest.raises(SystemExit) as e:
        main(["--jsonl", str(jsonl), "--gravar-jsonl", str(tmp_path / "s.jsonl")])
    assert e.value.code == 2


def test_esperar_invalido(jsonl):
    with pytest.raises(SystemExit) as e:
        main(["--jsonl", str(jsonl), "--esperar", "garrafa=1"])
    assert e.value.code == 2


def test_linha_invalida_erro_claro(tmp_path, capsys):
    caminho = tmp_path / "mau.jsonl"
    escrever_jsonl(clip_sintetico()[:2], caminho)
    with open(caminho, "a", encoding="utf-8") as f:
        f.write("\n")  # linha vazia ignorada
        f.write('{"indice": -1}\n')
    assert main(["--jsonl", str(caminho)]) == 2
    assert "linha 4 inválida" in capsys.readouterr().err


def test_jsonl_ida_e_volta_sem_imagens(tmp_path):
    frames = clip_sintetico()[:30]
    caminho = tmp_path / "rt.jsonl"
    assert escrever_jsonl(frames, caminho) == 30
    assert list(ler_jsonl(caminho)) == frames
    texto = caminho.read_text(encoding="utf-8")
    assert "imagem" not in texto
    assert texto.count("\n") == 30


def test_fps_variavel_no_resumo(tmp_path, capsys):
    caminho = tmp_path / "var.jsonl"
    frames = segmento(1.5, "levantado", fps=30.0) + segmento(
        2.0, "repouso", fps=5.0, t0=1.5, indice0=45
    )
    escrever_jsonl(frames, caminho)
    assert main(["--jsonl", str(caminho), "--esperar", "caneca=1"]) == 0
    saida = capsys.readouterr().out
    assert "fps mínimo (pior intervalo): 5.0" in saida
    assert "fps médio: 1" in saida or "fps médio: 2" in saida  # entre 5 e 30
