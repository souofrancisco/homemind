import numpy as np
import pytest

from homemind.contracts.presence import DoorDirection as D
from homemind.features.presence.door import ContadorPorta, Soleira, parse_retangulo, recortar
from homemind.features.presence.tests._fakes import (
    ALTURA,
    FPS,
    LARGURA,
    SOLEIRA,
    juntar,
    pessoa,
    sobrepor,
    trajeto,
)


def correr(roteiro, **kw):
    """Passa o roteiro ao contador (relógio simulado a FPS) e junta todas as passagens."""
    c = ContadorPorta(SOLEIRA, **kw)
    saida = []
    for i, pessoas in enumerate(roteiro):
        saida += c.atualizar(i / FPS, pessoas, LARGURA, ALTURA)
    for i in range(len(roteiro), len(roteiro) + 3 * FPS):  # tempo a passar: confirma pendentes
        saida += c.atualizar(i / FPS, [], LARGURA, ALTURA)
    return saida


def sentidos(passagens):
    return [p.direcao for p in passagens]


def test_entrada_e_saida_tem_o_sentido_certo():
    assert sentidos(correr(juntar(trajeto(1, 0.2, 0.8, 8), pausa=5))) == [D.entered]
    assert sentidos(correr(juntar(trajeto(1, 0.8, 0.2, 8), pausa=5))) == [D.left]


def test_cenario_entradas_saidas_visita_e_cruzamento_reverso():
    roteiro = juntar(
        trajeto(1, 0.2, 0.8, 8),  # morador entra
        trajeto(2, 0.8, 0.2, 8),  # morador sai
        trajeto(3, 0.2, 0.8, 8),  # visita entra...
        trajeto(4, 0.8, 0.2, 8),  # ...e outra pessoa sai
        trajeto(5, 0.2, 0.7, 6) + trajeto(5, 0.7, 0.2, 6),  # chega à linha e volta atrás: nada
        trajeto(6, 0.8, 0.2, 8),  # a visita sai
        pausa=15,
    )
    assert sentidos(correr(roteiro)) == [D.entered, D.left, D.entered, D.left, D.left]


def test_cruzamento_reverso_dentro_da_confirmacao_anula_os_dois():
    ida_e_volta = trajeto(1, 0.3, 0.6, 4) + trajeto(1, 0.6, 0.3, 4)
    assert correr(ida_e_volta) == []


def test_ir_e_voltar_depois_da_confirmacao_conta_as_duas():
    # Mesma pista, mas parada 2 s do outro lado: é uma entrada e uma saída reais.
    roteiro = trajeto(1, 0.3, 0.7, 4) + [[pessoa(1, 0.7)]] * 20 + trajeto(1, 0.7, 0.3, 4)
    assert sentidos(correr(roteiro)) == [D.entered, D.left]


def test_oscilar_sobre_a_linha_nao_conta():
    roteiro = [[pessoa(1, 0.5 + (0.015 if i % 2 else -0.015))] for i in range(30)]
    assert correr(roteiro) == []


def test_oscilar_e_depois_entrar_conta_uma_so_vez():
    roteiro = [[pessoa(1, 0.4)]] * 3
    roteiro += [[pessoa(1, 0.5 + (0.015 if i % 2 else -0.015))] for i in range(20)]
    roteiro += trajeto(1, 0.55, 0.8, 4)
    assert sentidos(correr(roteiro)) == [D.entered]


def test_mesma_pessoa_em_duas_pistas_conta_uma_vez_por_cooldown():
    # A pista 1 cruza; logo a seguir a pista 2 (a mesma pessoa, ID trocado) cruza também.
    a = trajeto(1, 0.3, 0.7, 4)
    b = [[]] * 2 + trajeto(2, 0.3, 0.7, 4)
    assert sentidos(correr(sobrepor(a, b), cooldown_s=2.0)) == [D.entered]


def test_duas_pessoas_separadas_no_tempo_contam_as_duas():
    roteiro = juntar(trajeto(1, 0.3, 0.7, 4), trajeto(2, 0.3, 0.7, 4), pausa=20)
    assert sentidos(correr(roteiro)) == [D.entered, D.entered]


def test_pessoas_em_sentidos_opostos_em_simultaneo_nao_se_anulam():
    roteiro = sobrepor(trajeto(1, 0.3, 0.7, 6, x=0.35), trajeto(2, 0.7, 0.3, 6, x=0.65))
    assert sorted(sentidos(correr(roteiro))) == sorted([D.entered, D.left])


def test_sem_track_id_ou_fora_da_soleira_nao_conta():
    sem_id = [[pessoa(None, 0.3 + 0.1 * i)] for i in range(5)]
    assert correr(sem_id) == []
    fora = [[pessoa(1, 0.3 + 0.1 * i, x=0.9)] for i in range(5)]  # x fora da roi (0.2–0.8)
    assert correr(fora) == []


def test_pista_que_aparece_ja_do_outro_lado_nao_conta():
    assert correr([[pessoa(1, 0.8)]] * 10) == []


def test_confianca_e_a_media_do_detetor_e_o_tempo_e_o_do_cruzamento():
    roteiro = [[pessoa(1, y, conf=c)] for y, c in ((0.3, 0.6), (0.4, 0.8), (0.6, 1.0))]
    (p,) = correr(roteiro)
    assert p.confianca == pytest.approx(0.8)
    assert p.t == pytest.approx(2 / FPS)  # cruzou no 3.º frame, não quando foi confirmado


def test_estado_de_pistas_e_esquecido():
    c = ContadorPorta(SOLEIRA, perdida_s=1.0)
    c.atualizar(0.0, [pessoa(7, 0.3)], LARGURA, ALTURA)
    c.atualizar(5.0, [], LARGURA, ALTURA)
    assert c._pistas == {}  # o track_id não fica guardado


def test_recortar_devolve_so_a_soleira_e_a_origem_sem_alterar_o_original():
    img = np.arange(ALTURA * LARGURA * 3, dtype=np.uint8).reshape(ALTURA, LARGURA, 3)
    original = img.copy()
    out, (x0, y0) = recortar(img, (0.2, 0.1, 0.8, 0.9))
    assert (x0, y0) == (20, 10) and out.shape == (80, 60, 3)
    assert (out == original[10:90, 20:80]).all()
    out[:] = 0
    assert (img == original).all()  # é uma cópia


@pytest.mark.parametrize(
    "kw",
    [
        {"roi": (0.5, 0, 0.2, 1)},  # invertida
        {"linha": (0.3, 0.5, 0.3, 0.5)},  # sem comprimento
        {"linha": (0.0, 0.5, 0.8, 0.5)},  # fora da roi
        {"sinal_interior": 0},
    ],
)
def test_soleira_invalida(kw):
    base = {"roi": (0.2, 0.0, 0.8, 1.0), "linha": (0.2, 0.5, 0.8, 0.5)}
    with pytest.raises(ValueError):
        Soleira(**{**base, **kw})


def test_parse_retangulo():
    assert parse_retangulo("") is None
    assert parse_retangulo("0.1, 0.2, 0.9, 1") == (0.1, 0.2, 0.9, 1.0)
    for ruim in ("1,2,3", "a,b,c,d", "0,0,1,2", "nan,0,1,1"):
        with pytest.raises(ValueError):
            parse_retangulo(ruim)


def test_sinal_interior_inverte_os_sentidos():
    inv = Soleira(roi=SOLEIRA.roi, linha=SOLEIRA.linha, sinal_interior=-1)
    c = ContadorPorta(inv)
    saida = []
    for i, ps in enumerate(juntar(trajeto(1, 0.2, 0.8, 8), pausa=15)):
        saida += c.atualizar(i / FPS, ps, LARGURA, ALTURA)
    assert sentidos(saida) == [D.left]
