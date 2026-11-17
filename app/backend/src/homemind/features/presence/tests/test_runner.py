import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np

from homemind.contracts.common import Origin
from homemind.contracts.domain_events import PresenceDoorCrossed
from homemind.contracts.fixtures import HOUSEHOLD
from homemind.contracts.presence import DoorDirection as D
from homemind.contracts.video import FrameVideo
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus
from homemind.features.households.repo import seed_demo
from homemind.features.presence.door import ContadorPorta, Soleira
from homemind.features.presence.runner import (
    ProcessadorPorta,
    ThreadPorta,
    carregar_detetor_pessoas,
)
from homemind.features.presence.tests._fakes import (
    ALTURA,
    FPS,
    LARGURA,
    SOLEIRA,
    DetetorRoteirizado,
    juntar,
    trajeto,
)
from homemind.features.presence.yolo import (
    DetetorYoloPessoas,
    pasta_modelos,
    pessoas_de_resultado,
)

CASA = HOUSEHOLD
AGORA = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
ROTEIRO = juntar(
    trajeto(1, 0.2, 0.8, 8),  # entra
    trajeto(2, 0.8, 0.2, 8),  # sai
    trajeto(3, 0.2, 0.8, 8),  # visita entra
    trajeto(4, 0.2, 0.7, 5) + trajeto(4, 0.7, 0.2, 5),  # reverso: nada
    pausa=15,
)
ESPERADO = [D.entered, D.left, D.entered]


def processador(publicar, roteiro=ROTEIRO, origin=Origin.simulated):
    t = {"v": 0.0}
    det = DetetorRoteirizado(roteiro)
    p = ProcessadorPorta(
        SOLEIRA,
        det,
        ContadorPorta(SOLEIRA),
        publicar,
        CASA,
        origin,
        relogio=lambda: t["v"],
        agora=lambda: AGORA,
    )
    return p, det, t


def frames(n, cor=200):
    for i in range(n):
        yield FrameVideo(
            imagem=np.full((ALTURA, LARGURA, 3), cor, np.uint8), indice=i + 1, t=i / FPS
        )


def correr(p, t, n):
    eventos = []
    for f in frames(n):
        t["v"] = f.t
        eventos += p.processar(f)
    return eventos


def test_cenario_gera_n_eventos_com_o_sentido_certo_e_so_metadados():
    publicados = []
    p, det, t = processador(publicados.append)
    eventos = correr(p, t, len(ROTEIRO) + 40)
    assert [e.data.direction for e in eventos] == ESPERADO == [e.data.direction for e in publicados]
    for e in eventos:
        assert isinstance(e, PresenceDoorCrossed) and e.type == "presence.door_crossed"
        assert e.provenance.origin is Origin.simulated and e.data.provenance == e.provenance
        dump = e.model_dump_json()
        assert "track" not in dump and "image" not in dump and "frame" not in dump
        assert e.ts <= AGORA


def test_o_detetor_so_ve_o_recorte_da_soleira_e_as_caixas_voltam_ao_frame_inteiro():
    """Soleira com origem fora de (0, 0): o detetor recebe só o recorte e devolve coordenadas
    do recorte; o resultado tem de ser o mesmo que se tivesse visto o frame inteiro."""
    soleira = Soleira(roi=(0.2, 0.2, 0.8, 0.9), linha=(0.2, 0.5, 0.8, 0.5), sinal_interior=1)
    x0, y0 = 20, 20  # píxeis da origem do recorte (frame 100x100)

    class DetetorDoRecorte(DetetorRoteirizado):
        def detetar(self, imagem):
            return [
                replace(p, x1=p.x1 - x0, x2=p.x2 - x0, y1=p.y1 - y0, y2=p.y2 - y0)
                for p in super().detetar(imagem)
            ]

    roteiro = juntar(trajeto(1, 0.3, 0.8, 8), trajeto(2, 0.8, 0.3, 8), pausa=15)
    det = DetetorDoRecorte(roteiro)
    t = {"v": 0.0}
    p = ProcessadorPorta(
        soleira, det, ContadorPorta(soleira), lambda e: None, CASA, Origin.simulated,
        relogio=lambda: t["v"], agora=lambda: AGORA,
    )  # fmt: skip
    eventos = correr(p, t, len(roteiro) + 40)
    assert [e.data.direction for e in eventos] == [D.entered, D.left]
    assert all(i.shape == (70, 60, 3) and (i == 200).all() for i in det.imagens_vistas)


def test_zero_imagens_persistidas(tmp_path, monkeypatch):
    """Corre o cenário até à base de dados (bus real) e varre o diretório de dados."""
    monkeypatch.chdir(tmp_path)  # qualquer escrita relativa ao cwd cai aqui
    db = Database(str(tmp_path / "data" / "porta.sqlite3"), 5000)
    (tmp_path / "data").mkdir()
    db.open()
    try:
        migrate(db)
        db.run_sync(seed_demo)
        bus = EventBus(db)
        p, _, t = processador(bus.publish_threadsafe)
        eventos = correr(p, t, len(ROTEIRO) + 40)
        assert len(eventos) == len(ESPERADO)
        rows = db.run_sync(
            lambda c: c.execute("SELECT type, payload_json FROM domain_event").fetchall()
        )
        assert [r["type"] for r in rows] == ["presence.door_crossed"] * len(ESPERADO)
        for r in rows:
            assert "track" not in r["payload_json"] and "frame" not in r["payload_json"]
    finally:
        db.close()
    ficheiros = [f for _, _, fs in os.walk(tmp_path) for f in fs]
    assert ficheiros, "o varrimento tem de ver, pelo menos, a base de dados"
    imagens = (b"\xff\xd8\xff", b"\x89PNG", b"RIFF", b"GIF8", b"\x00\x00\x00\x18ftyp")
    for raiz, _, fs in os.walk(tmp_path):
        for f in fs:
            caminho = os.path.join(raiz, f)
            assert not f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".mp4", ".avi", ".npy"))
            if f.endswith("-wal") or f.endswith("-shm"):
                continue
            with open(caminho, "rb") as fh:
                assert not fh.read(8).startswith(imagens), f


def test_thread_processa_frames_novos_e_para():
    publicados = []
    p, _, t = processador(publicados.append)

    class Fonte:
        def __init__(self):
            self.i = 0

        def ultimo_frame(self):
            self.i += 1
            t["v"] = self.i / FPS
            return FrameVideo(np.zeros((ALTURA, LARGURA, 3), np.uint8), self.i, self.i / FPS)

    th = ThreadPorta(Fonte(), p, espera_s=0.0)
    th.iniciar()
    fim = time.monotonic() + 5
    while len(publicados) < len(ESPERADO) and time.monotonic() < fim:
        time.sleep(0.01)
    th.parar()
    assert [e.data.direction for e in publicados[: len(ESPERADO)]] == ESPERADO


def test_thread_sem_frames_nao_publica_nada():
    publicados = []
    p, _, _ = processador(publicados.append)
    fonte = SimpleNamespace(ultimo_frame=lambda: None)
    th = ThreadPorta(fonte, p, espera_s=0.001)
    th.iniciar()
    time.sleep(0.1)
    th.parar()
    assert publicados == [] and th.frames == 0  # sem câmara não há eventos nem «casa vazia»


def test_detetor_que_falha_ao_preparar_desliga_so_a_porta():
    class Mau(DetetorRoteirizado):
        def preparar(self):
            raise FileNotFoundError("pesos")

    p, _, _ = processador(lambda e: None)
    p.detetor = Mau([])
    th = ThreadPorta(SimpleNamespace(ultimo_frame=lambda: None), p)
    th.iniciar()
    th._thread.join(2)
    assert not th._thread.is_alive()


def test_carregar_detetor_pessoas_valida_a_especificacao():
    import pytest

    for ruim in (
        "",
        "sem_dois_pontos",
        "modulo.inexistente:X",
        "homemind.features.presence.door:Nada",
    ):
        with pytest.raises(ValueError):
            carregar_detetor_pessoas(ruim)


def test_yolo_filtra_a_classe_pessoa_e_ignora_pistas_por_confirmar():
    res = SimpleNamespace(
        boxes=SimpleNamespace(
            xyxy=np.array([[10, 20, 30, 80], [1, 1, 5, 5]], float),
            conf=np.array([0.9, 0.8]),
            cls=np.array([0.0, 41.0]),  # pessoa e caneca
            id=None,
        )
    )
    (p,) = pessoas_de_resultado(res)
    assert (p.track_id, p.confianca, p.y2) == (None, 0.9, 80.0)
    res.boxes.id = np.array([4.0, 5.0])
    assert pessoas_de_resultado(res)[0].track_id == 4
    assert pessoas_de_resultado(SimpleNamespace(boxes=None)) == ()


def test_detetor_yolo_pede_so_pessoas_com_bytetrack():
    chamadas = []

    class Modelo:
        def track(self, imagem, **kw):
            chamadas.append(kw)
            return [SimpleNamespace(boxes=None)]

    d = DetetorYoloPessoas(modelo=Modelo())
    assert d.detetar(np.zeros((8, 8, 3), np.uint8)) == ()
    assert chamadas[0]["classes"] == [0]
    assert chamadas[0]["persist"] is True and chamadas[0]["tracker"] == "bytetrack.yaml"


def test_pasta_de_modelos_relativa_resolve_a_partir_de_app_backend(tmp_path, monkeypatch):
    from homemind.core.config import Settings

    monkeypatch.chdir(tmp_path)  # arrancar noutro diretório não muda onde estão os pesos
    pasta = pasta_modelos(Settings(visao_pasta_modelos="data/modelos"))
    assert pasta.is_absolute() and pasta.parts[-2:] == ("data", "modelos")
    assert pasta.parent.parent.joinpath("pyproject.toml").is_file()
    assert pasta_modelos(Settings(visao_pasta_modelos=str(tmp_path))) == tmp_path


def test_preparar_procura_os_pesos_na_pasta_resolvida(tmp_path, monkeypatch):
    import pytest

    from homemind.core.config import Settings

    monkeypatch.chdir(tmp_path)
    d = DetetorYoloPessoas(Settings(visao_pasta_modelos=str(tmp_path / "vazia")))
    with pytest.raises(FileNotFoundError, match="pesos YOLO em falta"):
        d.preparar()
    (tmp_path / "vazia").mkdir()
    (tmp_path / "vazia" / "yolo11s.pt").write_bytes(b"x")  # existe: segue para o import (extra)
    try:
        d.preparar()
    except FileNotFoundError:
        raise AssertionError("os pesos existem na pasta resolvida") from None
    except Exception:
        pass  # sem o extra `visao` ou pesos falsos: só interessa que passou a verificação
