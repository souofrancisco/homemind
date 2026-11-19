"""Integração dos providers reais de billing no assistente (sem LLM)."""

import asyncio
from datetime import datetime, timedelta
from threading import Lock
from types import SimpleNamespace
from uuid import UUID

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.agent_providers import ProviderSet
from homemind.contracts.common import Origin, cost_cents, replace, stable_id
from homemind.contracts.energy import ApplianceMatch, CostEstimate, LocationKind
from homemind.contracts.notification import ConfirmationRequest, Notification, NotificationResponse
from homemind.features.agent.formatting import format_eur
from homemind.features.agent.tests.conftest import GINA
from homemind.features.billing import attributor, budgets
from homemind.features.households.tests.conftest import NOW
from homemind.features.notifications.compose import compose_confirmation
from homemind.features.notifications.sqlite import SqliteNotificationRepository


def _seed_attributed(
    app,
    household=fx.HOUSEHOLD,
    resident=fx.ANA,
    room=fx.ROOM_ANA,
    name="agent",
    appliance=None,
    started_at=None,
):
    if appliance:
        appliance_id, appliance_name = appliance
        app.state.db.run_sync(
            lambda conn: conn.execute(
                "INSERT OR IGNORE INTO appliance (id, household_id, name, category,"
                " registered_by_resident_id, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (
                    str(appliance_id),
                    str(household),
                    appliance_name,
                    "heating",
                    str(resident),
                    "2026-11-01T00:00:00.000000+00:00",
                ),
            )
        )
    event = replace(
        fx.consumption(closed=True),
        id=stable_id("agent-provider", name),
        household_id=household,
        energy_wh=10_000,
        match=ApplianceMatch(appliance_id=appliance[0], confidence=0.95)
        if appliance
        else ApplianceMatch(),
        appliance_owner_resident_id=resident if appliance else None,
        started_at=started_at or NOW - timedelta(days=1),
        ended_at=(started_at or NOW - timedelta(days=1)) + timedelta(hours=1),
        location=LocationKind.room,
        room_id=room,
        cost_estimate=CostEstimate(
            cents=cost_cents(10_000, fx.PRICE_MILLICENTS),
            price_millicents_per_kwh=fx.PRICE_MILLICENTS,
        ),
    )
    stored = de.StoredEvent(
        seq=1,
        event=de.EnergyConsumptionClosed(
            ts=event.ended_at,
            household_id=household,
            provenance=event.provenance,
            data=event,
        ),
    )
    app.state.db.run_sync(lambda conn: attributor.handle(conn, stored))


def test_provider_set_registado_e_post_usa_consumo_de_billing(app, client):
    _seed_attributed(app)
    providers = app.state.agent_providers
    assert isinstance(providers, ProviderSet)
    value = providers.consumption.consumption_summary(fx.HOUSEHOLD, fx.ANA, "2026-11")
    assert value is not None and value.cost_cents == 160 and value.provenance.simulated

    response = client.post(
        f"/api/households/{fx.HOUSEHOLD}/agent/messages",
        json={"text": "Quanto consumi este mês?"},
        headers={"x-test-sub": "sub-ana"},
    )
    assert response.status_code == 200, response.text
    assert "1,60 €" in response.json()["text"]
    assert "SIMULADO" in response.json()["text"]


def test_post_aparelho_devolve_nome_e_custo_vindos_de_billing(app, client):
    _seed_attributed(
        app,
        name="chat-heater",
        appliance=(stable_id("chat", "heater"), "Aquecedor do Bruno"),
    )
    response = client.post(
        f"/api/households/{fx.HOUSEHOLD}/agent/messages",
        json={"text": "Qual foi o aparelho que mais gastou?"},
        headers={"x-test-sub": "sub-ana"},
    )
    assert response.status_code == 200, response.text
    assert "Aquecedor do Bruno" in response.json()["text"]
    assert "0,40 €" in response.json()["text"]


def test_post_compara_mes_atual_com_anterior(app, client):
    _seed_attributed(app, name="november")
    _seed_attributed(
        app,
        name="october",
        started_at=datetime(2026, 10, 10, 12, tzinfo=NOW.tzinfo),
    )
    providers = app.state.agent_providers
    this_month = providers.consumption.consumption_summary(fx.HOUSEHOLD, fx.ANA, "2026-11")
    last_month = providers.consumption.consumption_summary(fx.HOUSEHOLD, fx.ANA, "2026-10")
    assert this_month is not None and last_month is not None
    response = client.post(
        f"/api/households/{fx.HOUSEHOLD}/agent/messages",
        json={"text": "Porque é que o meu valor subiu?"},
        headers={"x-test-sub": "sub-ana"},
    )
    assert response.status_code == 200
    assert format_eur(abs(this_month.cost_cents - last_month.cost_cents)) in response.json()["text"]
    assert "outubro de 2026" in response.json()["text"]


def test_provider_de_consumo_isola_residente_e_sem_dados(app, client, real_house):
    _seed_attributed(app)
    provider = app.state.agent_providers.consumption
    bruno = provider.consumption_summary(fx.HOUSEHOLD, fx.BRUNO, "2026-11")
    assert bruno is not None and bruno.cost_cents == 0  # nunca o consumo da Ana
    assert provider.consumption_summary(fx.HOUSEHOLD, fx.ANA, "2026-10") is None
    response = client.post(
        f"/api/households/{real_house}/agent/messages",
        json={"text": "Quanto consumi este mês?"},
        headers={"x-test-sub": "sub-gina"},
    )
    assert "Não tenho dados" in response.json()["text"]


def test_casa_real_descarta_proveniencia_simulada(app, client, real_house):
    _seed_attributed(app, real_house, resident=GINA, room=stable_id("room", "c1"), name="real-sim")
    response = client.post(
        f"/api/households/{real_house}/agent/messages",
        json={"text": "Quanto consumi este mês?"},
        headers={"x-test-sub": "sub-gina"},
    )
    assert response.status_code == 200, response.text
    assert "Não tenho dados" in response.json()["text"]
    assert (
        app.state.agent_providers.attribution.explain_attribution(real_house, GINA, "2026-11")
        is None
    )


def test_explicar_atribuicao_provisorio_reconcilia_e_isola_morador(app, client):
    _seed_attributed(app, name="explain", appliance=(stable_id("chat", "heater"), "Aquecedor"))
    provider = app.state.agent_providers.attribution
    value = provider.explain_attribution(fx.HOUSEHOLD, fx.ANA, "2026-11")
    summary = app.state.agent_providers.consumption.consumption_summary(
        fx.HOUSEHOLD, fx.ANA, "2026-11"
    )
    assert value is not None and summary is not None and not value.final
    assert (
        sum(part.amount_cents for part in value.parts)
        == value.total.cost_cents
        == summary.cost_cents
    )
    other = provider.explain_attribution(fx.HOUSEHOLD, fx.BRUNO, "2026-11")
    other_summary = app.state.agent_providers.consumption.consumption_summary(
        fx.HOUSEHOLD, fx.BRUNO, "2026-11"
    )
    assert other is not None and other_summary is not None
    assert other.total.cost_cents == other_summary.cost_cents
    assert all("Aquecedor" not in part.label for part in other.parts)
    response = client.post(
        f"/api/households/{fx.HOUSEHOLD}/agent/messages",
        json={"text": "Porque pago este valor?"},
        headers={"x-test-sub": "sub-ana"},
    )
    assert response.status_code == 200
    assert (
        "provisório" in response.json()["text"] and "estimado · SIMULADO" in response.json()["text"]
    )
    assert "presença" not in response.json()["text"] and "Bruno" not in response.json()["text"]


def test_explicar_atribuicao_final_usa_recibo_e_texto_contestavel(client, app, now):
    now["value"] = NOW.replace(month=12, day=5)
    household_url = f"/api/households/{fx.HOUSEHOLD}"
    landlord = {"x-test-sub": "sub-senhorio"}
    created = client.post(
        f"{household_url}/bills",
        json={
            "period": {"start": "2026-11-01", "end": "2026-11-30"},
            "total_cents": 12_000,
            "fixed_cents": 2_400,
            "total_wh": 600_000,
            "origin": "simulated",
        },
        headers=landlord,
    )
    assert created.status_code == 201, created.text
    closed = client.post(f"{household_url}/bills/{created.json()['id']}/finalize", headers=landlord)
    assert closed.status_code == 200
    total = app.state.agent_providers.consumption.consumption_summary(
        fx.HOUSEHOLD, fx.ANA, "2026-11"
    )
    explained = app.state.agent_providers.attribution.explain_attribution(
        fx.HOUSEHOLD, fx.ANA, "2026-11"
    )
    assert total is not None and explained is not None and explained.final
    assert (
        sum(part.amount_cents for part in explained.parts)
        == explained.total.cost_cents
        == total.cost_cents
    )
    now["value"] = NOW
    response = client.post(
        f"{household_url}/agent/messages",
        json={"text": "Como chegaram a este valor?"},
        headers={"x-test-sub": "sub-ana"},
    )
    assert "contestar no recibo" in response.json()["text"]


def test_notificacoes_pendentes_so_mostram_pedidos_proprios_e_respeitam_limite(app, client):
    provider = app.state.agent_providers.confirmations
    assert provider.pending_confirmations(fx.HOUSEHOLD, fx.ANA).count == 0

    def insert(conn):
        repo = SqliteNotificationRepository(conn)
        for index in range(7):
            created = NOW - timedelta(days=2) if index == 5 else NOW
            expires = NOW - timedelta(hours=1) if index == 5 else NOW + timedelta(days=2, hours=2)
            event_id = stable_id("pending-test", str(index))
            request = ConfirmationRequest(
                consumption_event_id=stable_id("consumption", str(index)),
                appliance_name=f"Aparelho {index}",
                estimated_cost_cents=64,
                eligible_resident_ids=[fx.ANA, fx.BRUNO],
                expires_at=expires,
            )
            notification = compose_confirmation(
                request,
                household_id=fx.HOUSEHOLD,
                responder_ids=[fx.ANA, fx.BRUNO],
                origin=Origin.simulated,
                correlation_id=stable_id("corr", str(index)),
                source_event_id=event_id,
                now=created,
            )
            if index == 0:
                vote = NotificationResponse(
                    notification_id=notification.id,
                    action_id="unknown",
                    resident_id=fx.ANA,
                    responded_at=NOW,
                )
                notification = notification.model_copy(update={"responses": [vote]})
            if index == 6:
                notification = notification.respond(fx.ANA, "mine", NOW)
            repo.insert(notification)

    app.state.db.run_sync(insert)
    response = client.post(
        f"/api/households/{fx.HOUSEHOLD}/agent/messages",
        json={"text": "Tenho pedidos por responder?"},
        headers={"x-test-sub": "sub-ana"},
    )
    assert response.status_code == 200
    text = response.json()["text"]
    assert "4 pedidos" in text and "Aparelho 0" not in text
    assert text.count("cerca de 0,64 €") == 3 and "19/11" in text
    assert provider.pending_confirmations(fx.HOUSEHOLD, fx.ANA).count == 4

    def close_three(conn):
        rows = conn.execute(
            "SELECT id, json FROM notification WHERE household_id = ?",
            (str(fx.HOUSEHOLD),),
        ).fetchall()
        for row in rows:
            notification = Notification.model_validate_json(row["json"])
            if any(f"Aparelho {index}" in notification.body for index in (2, 3, 4)):
                notification = notification.respond(fx.BRUNO, "mine", NOW)
                conn.execute(
                    "UPDATE notification SET status = ?, json = ? WHERE id = ?",
                    (notification.status.value, notification.model_dump_json(), row["id"]),
                )

    app.state.db.run_sync(close_three)
    assert provider.pending_confirmations(fx.HOUSEHOLD, fx.ANA).count == 1
    landlord = client.post(
        f"/api/households/{fx.HOUSEHOLD}/agent/messages",
        json={"text": "Tenho pedidos por responder?"},
        headers={"x-test-sub": "sub-senhorio"},
    )
    assert landlord.status_code == 403


def test_lifespans_de_billing_e_notifications_compõem_providers_em_qualquer_ordem(monkeypatch):
    from homemind.contracts.agent_providers import ProviderSet
    from homemind.features.billing.router import lifespan as billing_lifespan
    from homemind.features.notifications import router as notification_router

    class Db:
        _lock = Lock()
        _conn = None

        async def run(self, fn):
            return []

    class Bus:
        def subscribe(self, *args):
            pass

        async def publish(self, event):
            pass

    monkeypatch.setattr(
        notification_router,
        "get_notification_settings",
        lambda: SimpleNamespace(notifications_expiry_sweep_s=0),
    )

    async def order(first, second):
        app = SimpleNamespace(state=SimpleNamespace(db=Db(), bus=Bus()), dependency_overrides={})
        async with first(app):
            async with second(app):
                providers = app.state.agent_providers
                assert isinstance(providers, ProviderSet)
                assert providers.attribution is not None
                assert providers.confirmations is not None
                assert providers.consumption is not None

    asyncio.run(order(billing_lifespan, notification_router.lifespan))
    asyncio.run(order(notification_router.lifespan, billing_lifespan))


def test_orcamento_e_recibo_usam_valores_da_fatura_finalizada(client, app, now):
    now["value"] = NOW.replace(month=12, day=5)
    household_url = f"/api/households/{fx.HOUSEHOLD}"
    landlord = {"x-test-sub": "sub-senhorio"}
    created = client.post(
        f"{household_url}/bills",
        json={
            "period": {"start": "2026-11-01", "end": "2026-11-30"},
            "total_cents": 12_000,
            "fixed_cents": 2_400,
            "total_wh": 600_000,
            "origin": "simulated",
        },
        headers=landlord,
    )
    assert created.status_code == 201, created.text
    bill_id = created.json()["id"]
    closed = client.post(f"{household_url}/bills/{bill_id}/finalize", headers=landlord)
    assert closed.status_code == 200, closed.text

    app.state.db.run_sync(
        lambda conn: budgets.set_personal(
            conn, fx.HOUSEHOLD, fx.ANA, "2026-11", 10_000, [50, 80, 100], now["value"]
        )
    )
    providers = app.state.agent_providers
    latest = providers.receipt.latest_bill(fx.HOUSEHOLD, fx.ANA)
    assert latest == (UUID(bill_id), "2026-11")
    receipt = providers.receipt.receipt(fx.HOUSEHOLD, fx.ANA, latest[0])
    budget = providers.budget.budget_status(fx.HOUSEHOLD, fx.ANA, "2026-11")
    assert receipt is not None and receipt.cost_cents is not None
    assert budget is not None and budget.cost_cents == receipt.cost_cents
    assert budget.limit_cents == 10_000 and budget.provenance.simulated
    appliances = providers.appliances.top_appliances(fx.HOUSEHOLD, fx.ANA, "2026-11")
    assert appliances is not None
    assert sum(row.cost_cents for row in appliances[1]) == receipt.cost_cents


def test_consumo_inclui_a_parte_comum_e_coincide_com_o_orcamento(app):
    # Sem identificação nem dono e abaixo do limiar de perguntar (0,50 €): divide-se por igual.
    event = replace(
        fx.consumption(closed=True),
        id=stable_id("agent-provider", "comum"),
        match=ApplianceMatch(),
        appliance_owner_resident_id=None,
        energy_wh=2_000,
        started_at=NOW - timedelta(days=1),
        ended_at=NOW - timedelta(hours=23),
        location=LocationKind.common,
        cost_estimate=CostEstimate(
            cents=cost_cents(2_000, fx.PRICE_MILLICENTS),
            price_millicents_per_kwh=fx.PRICE_MILLICENTS,
        ),
    )
    stored = de.StoredEvent(
        seq=1,
        event=de.EnergyConsumptionClosed(
            ts=event.ended_at,
            household_id=fx.HOUSEHOLD,
            provenance=event.provenance,
            data=event,
        ),
    )
    app.state.db.run_sync(lambda conn: attributor.handle(conn, stored))
    providers = app.state.agent_providers
    consumo = providers.consumption.consumption_summary(fx.HOUSEHOLD, fx.ANA, "2026-11")
    orcamento = providers.budget.budget_status(fx.HOUSEHOLD, fx.ANA, "2026-11")
    assert consumo is not None and orcamento is not None
    # 0,32 € a dividir por 4 = 0,08 €: a parte comum conta e coincide com o orçamento.
    assert consumo.cost_cents == orcamento.cost_cents == 8


def test_aparelhos_reconciliam_com_consumo_e_isolam_morador(app):
    heater = stable_id("agent-provider", "heater")
    _seed_attributed(app, name="heater", appliance=(heater, "Aquecedor da Ana"))
    provider = app.state.agent_providers.appliances
    top = provider.top_appliances(fx.HOUSEHOLD, fx.ANA, "2026-11")
    summary = app.state.agent_providers.consumption.consumption_summary(
        fx.HOUSEHOLD, fx.ANA, "2026-11"
    )
    assert top is not None and summary is not None
    assert sum(row.cost_cents for row in top[1]) == summary.cost_cents == top[0].cost_cents
    assert any(row.label == "Aquecedor da Ana" for row in top[1])
    other = provider.top_appliances(fx.HOUSEHOLD, fx.BRUNO, "2026-11")
    other_total = app.state.agent_providers.consumption.consumption_summary(
        fx.HOUSEHOLD, fx.BRUNO, "2026-11"
    )
    assert other is not None and other_total is not None
    assert sum(row.cost_cents for row in other[1]) == other_total.cost_cents


def test_aparelhos_sem_dados_devolvem_none(app):
    assert (
        app.state.agent_providers.appliances.top_appliances(fx.HOUSEHOLD, fx.ANA, "2026-10") is None
    )
