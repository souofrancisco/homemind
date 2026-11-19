import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from homemind.contracts import fixtures as fx
from homemind.contracts.common import Origin, ValueKind
from homemind.contracts.domain_events import BillingConfirmationNeeded
from homemind.core.config import Settings
from homemind.core.events import load_events
from homemind.demo.web import _seed_live_catalog
from homemind.features.demo_live.router import DemoLive, enabled

pytest_plugins = ("homemind.features.billing.tests.conftest",)
HOUSE = f"/api/households/{fx.HOUSEHOLD}"
TENANTS = {name: {"x-test-sub": f"sub-{name}"} for name in ("ana", "bruno")}


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def test_tick_emite_leituras_simuladas_e_arranca_o_aquecedor_ao_minuto():
    start = datetime(2026, 11, 18, 12, tzinfo=UTC)
    bus = Bus()
    live = DemoLive(bus, clock=lambda: start, started_at=start)

    asyncio.run(live.tick(start))
    asyncio.run(live.tick(start + timedelta(seconds=5)))
    asyncio.run(live.tick(start + timedelta(seconds=60)))

    assert [event.data.power_w for event in bus.events] == [40, 40, 2080]
    assert all(event.provenance.origin is Origin.simulated for event in bus.events)
    assert all(event.provenance.kind is ValueKind.measured for event in bus.events)


def test_tick_recusa_sessoes_sobrepostas_e_identifica_instantes():
    start = datetime(2026, 11, 18, 12, tzinfo=UTC)
    bus = Bus()
    live = DemoLive(bus, clock=lambda: start, started_at=start)
    asyncio.run(live.start("heater", start))
    with pytest.raises(HTTPException) as error:
        asyncio.run(live.start("kettle", start + timedelta(seconds=1)))
    assert error.value.status_code == 409
    asyncio.run(live.tick(start))
    asyncio.run(live.tick(start))
    assert len(bus.events) == 1
    assert bus.events[0].id == bus.events[0].data.id
    asyncio.run(live.start("kettle", start + timedelta(seconds=181)))
    asyncio.run(live.tick(start + timedelta(seconds=186)))
    # Fim do aquecedor: leitura em falta (fecha o consumo já), depois a chaleira.
    assert [event.data.power_w for event in bus.events[-2:]] == [None, 1860]


def test_guarda_exige_demo_fake_flag_e_casa_demo():
    settings = Settings(profile="demo", home_backend="fake", demo_live=True)
    assert enabled(settings, "demo")
    assert not enabled(Settings(profile="normal", home_backend="fake"), "demo")
    assert not enabled(Settings(profile="demo", home_backend="mcp"), "demo")
    assert not enabled(Settings(profile="demo", home_backend="fake", demo_live=False), "demo")
    assert not enabled(settings, "real")


def test_endpoints_so_operador_na_casa_demo(app, client, monkeypatch):
    from homemind.features.demo_live import router

    start = datetime(2026, 11, 17, 12, tzinfo=UTC)
    app.state.demo_live = DemoLive(Bus(), clock=lambda: start, started_at=start)
    monkeypatch.setattr(
        router, "get_settings", lambda: Settings(profile="demo", home_backend="fake")
    )

    assert (
        client.post("/api/demo/live/heater", headers={"x-test-sub": "sub-bruno"}).status_code == 403
    )
    assert (
        client.post("/api/demo/live/kettle", headers={"x-test-sub": "sub-senhorio"}).status_code
        == 403
    )
    assert (
        client.post("/api/demo/live/heater", headers={"x-test-sub": "sub-operador"}).status_code
        == 200
    )
    assert (
        client.post("/api/demo/live/kettle", headers={"x-test-sub": "sub-operador"}).status_code
        == 409
    )

    monkeypatch.setattr(
        router, "get_settings", lambda: Settings(profile="normal", home_backend="fake")
    )
    assert (
        client.post("/api/demo/live/heater", headers={"x-test-sub": "sub-operador"}).status_code
        == 404
    )
    app.state.db.run_sync(
        lambda c: c.execute(
            "UPDATE household SET source_kind='real' WHERE id=?", (str(fx.HOUSEHOLD),)
        )
    )
    monkeypatch.setattr(
        router, "get_settings", lambda: Settings(profile="demo", home_backend="fake")
    )
    assert (
        client.post("/api/demo/live/heater", headers={"x-test-sub": "sub-operador"}).status_code
        == 404
    )


def test_sessao_automatica_identifica_aquecedor_localiza_e_pergunta(app, client, now, monkeypatch):
    monkeypatch.setattr(
        "homemind.features.billing.attributor.ignore_wh_month", lambda: 0
    )  # a demo mostra a pergunta
    start = now["value"]
    app.state.db.run_sync(lambda c: _seed_live_catalog(c, start - timedelta(minutes=1)))
    live = DemoLive(app.state.bus, clock=lambda: start, started_at=start)
    for second in range(0, 305, 5):  # 1 min até arrancar + 3 min de sessão + fecho: ~5 min
        asyncio.run(live.tick(start + timedelta(seconds=second)))

    def confirmation():
        return app.state.db.run_sync(
            lambda c: load_events(c, types=["billing.confirmation_needed"])
        )

    deadline = time.monotonic() + 5
    events = []
    while time.monotonic() < deadline and not events:
        events = confirmation()
        time.sleep(0.01)
    assert events, "o fecho da sessão deve gerar a confirmação"

    closed = app.state.db.run_sync(lambda c: load_events(c, types=["energy.consumption_closed"]))[
        -1
    ].event.data
    assert closed.match.appliance_id == fx.HEATER
    assert closed.match.confidence >= 0.8
    assert closed.appliance_owner_resident_id == fx.BRUNO
    assert closed.peak_w == 2040
    assert closed.location.value == "common"
    request = events[-1].event
    assert isinstance(request, BillingConfirmationNeeded)
    assert request.data.appliance_name == "Aquecedor do Bruno"

    overview = client.get(f"{HOUSE}/energy/overview", headers=TENANTS["ana"])
    assert overview.status_code == 200
    assert overview.json()["meters"][0]["read_at"]
    last_reading = datetime.fromisoformat(overview.json()["meters"][0]["read_at"])
    assert start <= last_reading <= start + timedelta(seconds=305)

    kettle_live = DemoLive(app.state.bus, clock=lambda: start, started_at=start)
    asyncio.run(kettle_live.start("kettle", start + timedelta(seconds=870)))
    for second in range(865, 1045, 5):  # chaleira: 155 s + fecho
        asyncio.run(kettle_live.tick(start + timedelta(seconds=second)))
    deadline = time.monotonic() + 5
    closed_events = []
    while time.monotonic() < deadline and len(closed_events) < 2:
        closed_events = app.state.db.run_sync(
            lambda c: load_events(c, types=["energy.consumption_closed"])
        )
        time.sleep(0.01)
    kettle_event = closed_events[-1].event.data
    assert kettle_event.match.appliance_id == fx.KETTLE
    assert kettle_event.appliance_owner_resident_id is None
    assert kettle_event.location.value == "common"
    assert len(confirmation()) == 1  # a chaleira comum fica abaixo do limiar da pergunta

    before = app.state.db.run_sync(
        lambda c: c.execute("SELECT count(*) FROM domain_event").fetchone()[0]
    )
    restarted = DemoLive(app.state.bus, clock=lambda: start, started_at=start)
    asyncio.run(restarted.tick(start))  # reinício: mesmo instante, mesmo ID, sem duplicação
    after = app.state.db.run_sync(
        lambda c: c.execute("SELECT count(*) FROM domain_event").fetchone()[0]
    )
    assert before == after
