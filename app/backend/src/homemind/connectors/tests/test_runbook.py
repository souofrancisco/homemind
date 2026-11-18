"""SIMULADO: runbook DEMO-03 contra o FakeKit, relógio virtual fixo, sem rede, kit nem câmara."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from homemind.connectors import runbook
from homemind.connectors.fake_mcp import FakeKit
from homemind.connectors.runbook import (
    Ambiente,
    RelogioSimulado,
    _CapturaSimulada,
    ambiente_simulado,
    atualizar_guia,
    executar,
    higienizar,
    relatorio_json,
    relatorio_markdown,
)
from homemind.core.config import Settings

INICIO = datetime(2026, 11, 17, 12, tzinfo=UTC)
IDS_KIT = (FakeKit.PLUG, FakeKit.BULB, FakeKit.CONTACT, FakeKit.CLIMATE)


@pytest.fixture(autouse=True)
def _sem_esperas(monkeypatch):
    monkeypatch.setattr("homemind.connectors.mcp_home._READBACK_GAP_S", 0)


def _amb(**kwargs) -> Ambiente:
    return ambiente_simulado(inicio=INICIO, amostras_s=kwargs.pop("amostras_s", 90), **kwargs)


def _correr(amb: Ambiente) -> dict[str, runbook.Check]:
    return {c.id: c for c in asyncio.run(executar(amb))}


def _saida(amb: Ambiente, checks: dict[str, runbook.Check]) -> str:
    lista = list(checks.values())
    return relatorio_markdown(lista, amb.modo, INICIO) + relatorio_json(lista, amb.modo, INICIO)


def _autorizar(monkeypatch, respostas):
    resposta = iter(respostas)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(resposta))


def test_caminho_feliz_so_leitura_sem_escritas():
    amb = _amb()
    checks = _correr(amb)
    assert list(checks) == list(runbook.TESTES)
    for cid in ("MCP-01", "MCP-02", "MCP-03", "MCP-06", "MCP-07", "MCP-08", "MCP-09", "VID-04"):
        assert checks[cid].status == "PASS", (cid, checks[cid].evidence)
    for cid in ("MCP-04", "MCP-05"):
        assert checks[cid].status == "BLOQUEADO"
        assert "não autorizado nesta sessão" in checks[cid].evidence
    assert all(c.mode == "SIMULADO" for c in checks.values())
    assert amb.kit.writes() == []  # nunca escreve sem --write
    assert "intervalos: 30,0 s" in checks["MCP-06"].evidence
    assert "P/(V·I) mediana 1,00" in checks["MCP-06"].evidence
    assert "temperatura 20,0 °C" in checks["MCP-09"].evidence
    assert checks["MCP-01"].at == INICIO


def test_escritas_autorizadas_passam_so_com_releitura(monkeypatch):
    _autorizar(monkeypatch, ["AUTORIZO LAMPADA", "AUTORIZO TOMADA"])
    amb = _amb(escritas=("lamp", "plug"))
    checks = _correr(amb)
    assert checks["MCP-04"].status == "PASS"
    assert "alteração confirmada, restauro confirmado" in checks["MCP-04"].evidence
    assert checks["MCP-05"].status == "PASS"
    assert "final=True" in checks["MCP-05"].evidence
    alvos = {args["deviceId"] for _, args in amb.kit.writes()}
    assert alvos == {FakeKit.BULB, FakeKit.PLUG}
    assert amb.kit._caps(FakeKit.PLUG)["power"]["value"] == "on"  # restaurada


def test_operador_recusa_nada_e_escrito(monkeypatch):
    _autorizar(monkeypatch, ["não"])
    amb = _amb(escritas=("lamp",))
    checks = _correr(amb)
    assert checks["MCP-04"].status == "BLOQUEADO"
    assert "nada foi alterado" in checks["MCP-04"].evidence
    assert checks["MCP-05"].status == "BLOQUEADO"
    assert amb.kit.writes() == []


def test_write_ignored_h1_nunca_passa(monkeypatch):
    _autorizar(monkeypatch, ["AUTORIZO LAMPADA"])
    amb = _amb(escritas=("lamp",))
    amb.kit.write_ignored = True
    checks = _correr(amb)
    assert checks["MCP-04"].status == "FAIL"
    assert "NÃO confirmada" in checks["MCP-04"].evidence
    assert "estado final não corresponde" in checks["MCP-04"].evidence


def test_real_exige_confirmacao_fisica_do_operador(monkeypatch):
    _autorizar(monkeypatch, ["AUTORIZO LAMPADA"])
    amb = _amb(escritas=("lamp",))
    amb.simulado = False  # só para exercitar a pergunta; continua a ser o FakeKit
    amb.perguntar = lambda _p: "n"
    check = asyncio.run(runbook.check_escrita(amb, "lamp"))
    assert check.status == "FAIL" and "NÃO observou" in check.evidence


@pytest.mark.parametrize(
    ("falha", "estado", "texto"),
    [
        ("session_down", "FAIL", "ConnectionError"),
        ("oauth_expired", "BLOQUEADO", "make mcp-login"),
    ],
)
def test_sessao_indisponivel_bloqueia_o_resto(falha, estado, texto):
    amb = _amb()
    setattr(amb.kit, falha, True)
    checks = _correr(amb)
    assert checks["MCP-01"].status == estado
    assert texto in checks["MCP-01"].evidence
    assert "SIMULADO:" not in checks["MCP-01"].evidence  # só o tipo, nunca a mensagem
    for cid in ("MCP-02", "MCP-03", "MCP-04", "MCP-05", "MCP-06", "MCP-07", "MCP-08", "MCP-09"):
        assert checks[cid].status == "BLOQUEADO"
    assert "tokens" not in _saida(amb, checks).lower().replace("tokens persistidos", "")


def test_real_sem_configuracao_ou_tokens_bloqueia(tmp_path):
    base = dict(_env_file=None, mcp_token_path=tmp_path / "nao-existe.json")
    sem_env = Settings(**base, mcp_endpoint="", mcp_api_key="")
    assert "MCP_ENDPOINT" in runbook._sem_configuracao(sem_env)
    sem_tokens = Settings(**base, mcp_endpoint="https://mcp.exemplo", mcp_api_key="k" * 12)
    motivo = runbook._sem_configuracao(sem_tokens)
    assert "make mcp-login" in motivo and str(tmp_path) not in motivo
    amb = _amb()
    amb.simulado, amb.settings = False, sem_tokens
    check = asyncio.run(runbook.check_oauth(amb))
    assert check.status == "BLOQUEADO" and amb.kit.opens == 0


def test_consumo_sem_unidade_falha_e_sem_carga_bloqueia():
    amb = _amb()
    amb.settings = amb.settings.model_copy(update={"mcp_instantpower_unit": ""})
    checks = _correr(amb)
    assert checks["MCP-06"].status == "FAIL"
    assert "MCP_INSTANTPOWER_UNIT" in checks["MCP-06"].evidence
    amb = _amb()
    amb.settings = amb.settings.model_copy(update={"mcp_instantpower_unit": ""})
    amb.kit.set_load(0)
    assert _correr(amb)["MCP-06"].status == "BLOQUEADO"


def test_consumo_incoerente_falha():
    amb = _amb()
    amb.settings = amb.settings.model_copy(update={"mcp_instantpower_unit": "dW"})
    amb.kit.set_load(2000)  # 2000 dW = 200 W, mas V·I diz 2000 W: fator 0,1
    check = _correr(amb)["MCP-06"]
    assert check.status == "FAIL" and "incoerente" in check.evidence


def test_contacto_interativo_mede_latencias():
    amb = _amb(interativo=True)
    pedidos = []

    def pedir(acao, _mensagem):
        pedidos.append(acao)
        atraso, mudar = (
            (5.0, amb.kit.open_contact) if acao == "abrir" else (1.0, amb.kit.close_contact)
        )
        amb.relogio.agendar(atraso, mudar)

    amb.pedir_acao = pedir
    check = _correr(amb)["MCP-08"]
    assert pedidos == ["abrir", "fechar"]
    assert check.status == "PASS"
    # amostras a cada 2 s: mudança aos 5 s vista aos 6 s; aos 1 s vista aos 2 s
    assert "latência ao abrir: 6,0 s" in check.evidence
    assert "latência ao fechar: 2,0 s" in check.evidence
    assert "realista" in check.evidence


def test_contacto_interativo_sem_mudanca_falha():
    amb = _amb(interativo=True)
    amb.pedir_acao = lambda _acao, _mensagem: None
    check = _correr(amb)["MCP-08"]
    assert check.status == "FAIL" and "sem mudança em 90 s" in check.evidence


def test_camera_injetada_mede_e_nao_grava(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cv2.imwrite", lambda *a, **k: pytest.fail("nenhum frame pode ser gravado"))
    relogio = RelogioSimulado(INICIO)
    estado, texto = runbook.medir_camera(lambda: _CapturaSimulada(relogio, fps=10), relogio)
    assert estado == "PASS"
    assert "resolução 640x480" in texto and "10,0 FPS" in texto
    assert list(tmp_path.iterdir()) == []


def test_camera_real_bloqueada_e_url_nunca_aparece():
    url = "rtsp://utilizador:segredo@camara.local/stream"
    amb = _amb()
    amb.simulado = False
    amb.settings = amb.settings.model_copy(update={"video_source": ""})
    assert asyncio.run(runbook.check_camera(amb)).status == "BLOQUEADO"
    amb.settings = amb.settings.model_copy(update={"video_source": url})
    amb.abrir_camera = None  # sem --camera
    check = asyncio.run(runbook.check_camera(amb))
    assert check.status == "BLOQUEADO" and "PRIV-02" in check.evidence and check.mode == "REAL"

    def abrir():
        raise RuntimeError(f"não abriu {url}")

    amb.abrir_camera = abrir
    check = asyncio.run(runbook.check_camera(amb))
    assert check.status == "FAIL" and "RuntimeError" in check.evidence
    assert url not in check.evidence and "rtsp://" not in check.evidence


def test_saida_higienizada(monkeypatch):
    _autorizar(monkeypatch, ["AUTORIZO LAMPADA", "AUTORIZO TOMADA"])
    amb = _amb(escritas=("lamp", "plug"), interativo=True)
    saida = _saida(amb, _correr(amb))
    for proibido in (*IDS_KIT, "rtsp://", "cgh_live", "SIMULADO: tomada"):
        assert proibido not in saida
    json.loads(saida[saida.index("{") :])
    assert higienizar("x sim-plug-1 rtsp://a:b@c/d a@b.pt", {"sim-plug-1"}) == (
        "x ‹oculto› ‹url oculto› ‹e-mail oculto›"
    )


GUIA_MINIMO = """# Guia

| MCP-01 | fora da folha | | | | #10 |

## Folha de resultados

| ID | Teste | REAL / SIM | PASS / FAIL | Evidência / valor medido | Issue |
|---|---|---|---|---|---|
| INS-01 | Arranque FakeHome | | | | #28 |
| MCP-01 | OAuth | | | | #10 |
| MCP-03 | Leitura acompanha a realidade | | | | #11 |
| MCP-04 | ⚠️ Lâmpada RGB | REAL | PASS | registado antes | #11 |
| MCP-06 | Consumo | | | valor bruto: ____ | #12 |
| MCP-07 | ⚠️ Falhas e reconexão | | | | #11, #12 |
| VID-04 | Câmara | | | | #122 |
"""


def test_update_guide_so_atualiza_as_linhas_certas(tmp_path):
    guia = tmp_path / "guia.md"
    guia.write_text(GUIA_MINIMO, encoding="utf-8")
    checks = asyncio.run(executar(_amb()))
    ids = atualizar_guia(guia, checks)
    assert ids == ["MCP-01", "MCP-06", "VID-04"]
    antes, depois = GUIA_MINIMO.splitlines(), guia.read_text(encoding="utf-8").splitlines()
    assert len(antes) == len(depois)
    mudou = {a.split("|")[1].strip() for a, d in zip(antes, depois, strict=True) if a != d}
    assert mudou == {"MCP-01", "MCP-06", "VID-04"}
    linha = next(d for d in depois if d.startswith("| MCP-06 |"))
    assert linha.startswith("| MCP-06 | Consumo | SIMULADO | PASS | 2026-11-17 ")
    assert linha.endswith("| #12 |")
    assert "| MCP-01 | fora da folha | | | | #10 |" in depois  # fora da Folha: intacta
    # BLOQUEADO (MCP-04 sem --write) não apaga o PASS registado; MCP-03/07 nunca são escritas.
    assert "| MCP-04 | ⚠️ Lâmpada RGB | REAL | PASS | registado antes | #11 |" in depois
    assert "| MCP-03 | Leitura acompanha a realidade | | | | #11 |" in depois


def test_guia_do_repositorio_tem_as_linhas_do_runbook():
    texto = runbook.GUIA.read_text(encoding="utf-8")
    folha = texto[texto.index("## Folha de resultados") :]
    for cid in runbook.LINHAS_GUIA:
        assert f"| {cid} |" in folha


def test_cli_simulado(tmp_path, capsys):
    out = tmp_path / "relatorio.json"
    assert runbook.main(["--simulated", "--samples-s", "10", "--out", str(out)]) == 0
    dados = json.loads(out.read_text(encoding="utf-8"))
    assert dados["mode"] == "SIMULADO" and len(dados["checks"]) == len(runbook.TESTES)
    assert "| MCP-01 |" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        runbook.main(["--simulated", "--update-guide"])  # nunca o guia oficial em SIMULADO


def test_cli_codigo_de_saida_com_fail(tmp_path, monkeypatch):
    original = runbook.ambiente_simulado

    def sem_unidade(**kwargs):
        amb = original(**kwargs)
        amb.settings = amb.settings.model_copy(update={"mcp_instantpower_unit": ""})
        return amb

    monkeypatch.setattr(runbook, "ambiente_simulado", sem_unidade)
    assert runbook.main(["--simulated", "--samples-s", "5", "--out", str(tmp_path / "r.json")]) == 1


def test_guia_path_existe():
    assert isinstance(runbook.GUIA, Path) and runbook.GUIA.is_file()
