"""Demo web: a cópia é separada da original, só o comando local liga `sub`s, guardas de marcador."""

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from homemind.contracts import fixtures as fx
from homemind.demo import web
from homemind.demo.cli import FILE_NAME, DemoStore


@pytest.fixture
def roots(tmp_path, monkeypatch):
    demo, copy = tmp_path / "demo", tmp_path / "web"
    DemoStore(demo).prepare()
    monkeypatch.setattr(web, "DEMO_ROOT", demo)
    monkeypatch.setattr(web, "WEB_ROOT", copy)
    return demo, copy


def _subs(path):
    with closing(sqlite3.connect(path)) as c:
        return dict(c.execute("SELECT display_name, auth_subject FROM resident"))


def test_prepare_copia_sem_tocar_na_original(roots):
    demo, copy = roots
    before = hashlib.sha256((demo / FILE_NAME).read_bytes()).hexdigest()
    assert web.prepare() == "criada" and web.prepare() == "existente"
    assert hashlib.sha256((demo / FILE_NAME).read_bytes()).hexdigest() == before
    web.link("ana", "sub-real-ana")
    assert _subs(copy / web.WEB_FILE)["Ana"] == "sub-real-ana"
    assert _subs(demo / FILE_NAME)["Ana"] == "sub-ana"  # original e `demo-reset` intactos
    DemoStore(demo)._guard(existing=True)


def test_copia_web_ancorada_no_relógio_e_com_catálogo_real(roots):
    web.prepare()
    with closing(sqlite3.connect(web.web_path())) as c:
        recent = c.execute(
            "SELECT max(ts) FROM domain_event WHERE type='energy.reading_recorded'"
        ).fetchone()[0]
        assert datetime.now(UTC) - datetime.fromisoformat(recent) < timedelta(minutes=30)
        device = c.execute(
            "SELECT role,room_id,name FROM device WHERE name LIKE '%SIMULADA%'"
        ).fetchone()
        assert device[0] == "room_meter" and "SIMULADA" in device[2]
        assert c.execute("SELECT count(*) FROM appliance").fetchone()[0] == 2
        assert (
            c.execute(
                "SELECT count(*) FROM appliance_signature WHERE origin='simulated'"
            ).fetchone()[0]
            == 2
        )


def test_copia_web_sem_plafond_cada_um_paga_o_seu_quarto(roots):
    web.prepare()
    with closing(sqlite3.connect(web.web_path())) as c:
        quartos = c.execute("SELECT included_wh FROM room WHERE kind = 'bedroom'").fetchall()
        assert quartos and all(wh == 0 for (wh,) in quartos)  # 0 = sem plafond solidário
    # A original (cenário oficial offline, exemplo do PDF) mantém o plafond de 30 kWh.
    with closing(sqlite3.connect(roots[0] / FILE_NAME)) as c:
        assert {
            wh for (wh,) in c.execute("SELECT included_wh FROM room WHERE kind = 'bedroom'")
        } == {30000}


def test_link_recusa_desconhecido_vazio_e_duplicado(roots):
    web.prepare()
    for user, sub in (("eva", "x"), ("ana", ""), ("ana", "a" * 300)):
        with pytest.raises(web.WebDemoError):
            web.link(user, sub)
    web.link("ana", "S1")
    with pytest.raises(web.WebDemoError):
        web.link("bruno", "S1")


def test_recusa_ficheiro_sem_marcador(roots):
    _, copy = roots
    copy.mkdir()
    with closing(sqlite3.connect(copy / web.WEB_FILE)) as c:
        c.execute("CREATE TABLE x (a)")
    for fn in (web.prepare, web.clean, lambda: web.link("ana", "S")):
        with pytest.raises(web.WebDemoError):
            fn()
    assert (copy / web.WEB_FILE).exists()


def test_clean_apaga_so_a_copia(roots):
    demo, copy = roots
    web.prepare()
    web.clean()
    assert not (copy / web.WEB_FILE).exists() and (demo / FILE_NAME).exists()
    assert fx.ANA in web.ACCOUNTS["ana"]
