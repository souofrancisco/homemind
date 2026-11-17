import pytest

from homemind.contracts.eventos import ObjetoLevantado
from homemind.contracts.simulacao import pessoa_simulada, sequencia_simulada
from homemind.contracts.visao import ClasseObjeto, FrameDeteccoes
from homemind.core.config import Settings
from homemind.features.gestos.gesto import DetetorGesto
from homemind.features.gestos.parametros import ParametrosGesto, ParametrosPresenca
from homemind.features.gestos.tests._fakes import Estado, pessoa_levantada, segmento


def correr(frames, params: ParametrosGesto | None = None) -> list[tuple[float, ObjetoLevantado]]:
    det = DetetorGesto(params)
    saida = []
    for f in frames:
        for e in det.processar(f):
            saida.append((f.t, e))
    return saida


def _plano(passos: list[tuple[float, Estado, ClasseObjeto]], fps: float = 10.0):
    """Encadeia segmentos (duracao, estado, classe) continuando t e índice."""
    frames: list[FrameDeteccoes] = []
    t0, i0 = 0.0, 0
    for dur, estado, classe in passos:
        seg = segmento(dur, estado, classe, fps=fps, t0=t0, indice0=i0)
        frames += seg
        t0 += len(seg) / fps
        i0 += len(seg)
    return frames


@pytest.mark.parametrize("classe", ["caneca", "livro", "comando"])
def test_gesto_verdadeiro_por_classe(classe):
    frames = segmento(1.5, "levantado", classe) + segmento(
        1.0, "repouso", classe, t0=1.5, indice0=15
    )
    eventos = correr(frames)
    assert len(eventos) == 1
    t, ev = eventos[0]
    assert ev.classe == classe
    # hora = a do frame que confirmou o gesto
    assert ev.hora == next(f.hora for f in frames if f.t == t)


def test_segurar_10s_um_evento():
    assert len(correr(segmento(10.0, "levantado"))) == 1


def test_repeticao_apos_cooldown_dois_eventos():
    eventos = correr(
        _plano(
            [(1.5, "levantado", "caneca"), (3.0, "repouso", "caneca"), (1.5, "levantado", "caneca")]
        )
    )
    assert len(eventos) == 2


def test_repeticao_dentro_do_cooldown_um_evento():
    eventos = correr(
        _plano(
            [
                (1.5, "levantado", "caneca"),
                (1.0, "repouso", "caneca"),
                (1.5, "levantado", "caneca"),
                (2.0, "repouso", "caneca"),
            ]
        )
    )
    assert len(eventos) == 1


def test_troca_de_classe_dois_eventos():
    eventos = correr(
        _plano(
            [
                (1.5, "levantado", "caneca"),
                (0.2, "repouso", "caneca"),
                (1.5, "levantado", "livro"),
                (1.0, "repouso", "livro"),
            ]
        )
    )
    assert [e.classe for _, e in eventos] == ["caneca", "livro"]


def test_lado_esquerdo():
    frames = segmento(1.5, "levantado", "livro", lado="esq")
    assert [e.classe for _, e in correr(frames)] == ["livro"]


def test_pessoa_levantada_esq_tem_pulso_esq_acima_do_cotovelo():
    from homemind.contracts.visao import KP

    p = pessoa_levantada("esq")
    assert p.kp(KP.PULSO_ESQ).y < p.kp(KP.COTOVELO_ESQ).y
    assert p.kp(KP.PULSO_DIR).y > p.kp(KP.COTOVELO_DIR).y


@pytest.mark.parametrize("dur", [0.5, 0.79])
def test_levantamento_curto_nao_dispara(dur):
    frames = _plano([(dur, "levantado", "caneca"), (3.0, "repouso", "caneca")])
    assert correr(frames) == []


def test_beber_nao_dispara():
    frames = _plano(
        [(0.5, "repouso", "caneca"), (5.0, "beber", "caneca"), (1.0, "repouso", "caneca")]
    )
    assert correr(frames) == []


def test_objeto_longe_com_pulso_levantado():
    assert correr(segmento(3.0, "longe", "caneca")) == []


def test_confianca_exatamente_no_limiar_nao_dispara():
    assert correr(segmento(3.0, "levantado", confianca_pulso=0.5)) == []
    assert len(correr(segmento(3.0, "levantado", confianca_pulso=0.51))) == 1


def test_sem_objeto_ou_sem_pessoa():
    sem_obj = sequencia_simulada(30, levantado=True)
    sem_pessoa = sequencia_simulada(30, com_pessoa=False, classe="caneca")
    assert correr(sem_obj) == [] and correr(sem_pessoa) == []


def _com_invalidos(invalidos: set[int], n_total: int = 20):
    bons = segmento(n_total / 10, "levantado")
    maus = segmento(n_total / 10, "repouso")
    return [maus[i] if i in invalidos else bons[i] for i in range(n_total)]


def test_fracao_80_por_cento():
    # 1 inválido em cada 10 (90 %): dispara; 3 em cada 10 (70 %): não.
    assert len(correr(_com_invalidos({5, 15}))) == 1
    assert correr(_com_invalidos({2, 5, 8, 12, 15, 18})) == []


@pytest.mark.parametrize("fps", [5.0, 10.0, 30.0])
def test_fps_diferentes_mesmos_eventos(fps):
    frames = _plano(
        [
            (0.5, "repouso", "livro"),
            (1.5, "levantado", "livro"),
            (1.0, "repouso", "livro"),
            (0.6, "levantado", "livro"),
            (3.0, "repouso", "livro"),
        ],
        fps=fps,
    )
    assert len(correr(frames)) == 1


def test_fps_misto():
    frames = (
        segmento(1.0, "repouso", fps=5.0)
        + segmento(2.0, "levantado", fps=30.0, t0=1.0, indice0=5)
        + segmento(1.0, "repouso", fps=7.0, t0=3.0, indice0=65)
    )
    assert len(correr(frames)) == 1


def test_jitter_de_tempo():
    frames = segmento(2.0, "levantado")
    jit = [
        f.model_copy(update={"t": f.t + (0.02 if i % 2 else -0.02) * 0.5})
        for i, f in enumerate(frames)
    ]
    assert len(correr(jit)) == 1


def test_parametros_alterados_mudam_comportamento():
    frames = segmento(1.5, "levantado") + segmento(1.0, "repouso", t0=1.5, indice0=15)
    assert len(correr(frames)) == 1
    assert correr(frames, ParametrosGesto(janela_s=2.0)) == []
    assert len(correr(frames, ParametrosGesto(janela_s=0.5))) == 1
    longe = segmento(2.0, "longe")
    assert correr(longe) == []
    # com distância máxima enorme o objeto «longe» já conta
    assert len(correr(longe, ParametrosGesto(distancia_max_ombros=10.0))) == 1
    assert correr(frames, ParametrosGesto(min_frames=100)) == []


def test_buraco_de_frames_limpa_janela():
    # 0,6 s levantado, buraco de 5 s sem frames, 0,6 s levantado: nunca há 1 s contínuo
    a = segmento(0.6, "levantado")
    b = segmento(0.6, "levantado", t0=5.6, indice0=6)
    assert correr(a + b) == []
    # a mesma sequência sem buraco (contínua) dispararia
    assert len(correr(segmento(1.2, "levantado"))) == 1


def test_dez_levantamentos_encadeados():
    frames = _plano(
        [(0.5, "repouso", "caneca")]
        + [
            p
            for i in range(10)
            for p in (
                (1.5, "levantado", ("caneca", "livro", "comando")[i % 3]),
                (3.0, "repouso", "caneca"),
            )
        ]
    )
    assert len(correr(frames)) == 10


def test_beber_encadeado_com_gestos_nao_acrescenta_eventos():
    frames = _plano(
        [
            (1.5, "levantado", "caneca"),
            (3.0, "repouso", "caneca"),
            (4.0, "beber", "caneca"),
            (0.7, "levantado", "caneca"),
            (3.0, "repouso", "caneca"),
        ]
    )
    assert len(correr(frames)) == 1


def test_varias_pessoas_serve_qualquer_pulso():
    repouso = pessoa_simulada(x=100.0, track_id=2)
    frames = [
        f.model_copy(update={"pessoas": (repouso, *f.pessoas)}) for f in segmento(1.5, "levantado")
    ]
    assert len(correr(frames)) == 1


def test_de_settings_valores_por_omissao():
    s = Settings()
    assert ParametrosGesto.de_settings(s) == ParametrosGesto(
        distancia_max_ombros=0.6,
        confianca_min=0.5,
        janela_s=1.0,
        fracao_min=0.8,
        min_frames=3,
        cooldown_s=3.0,
        intervalo_max_s=1.0,
    )
    assert ParametrosPresenca.de_settings(s) == ParametrosPresenca(
        ausencia_s=3.0, frames_regresso=2, intervalo_max_s=1.0
    )
