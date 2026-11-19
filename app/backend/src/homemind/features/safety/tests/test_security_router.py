"""`/api/households/{id}/security`: papel × rota (PRIV-01), outra casa, casa real e fluxo ponta a
ponta. O painel é SIMULADO: nenhuma rota chama MCP nem hardware."""

import json

import pytest

from homemind.contracts import fixtures as fx
from homemind.contracts.presence import HouseOccupancy, OccupancyState
from homemind.core.events import load_events
from homemind.features.safety.tests.conftest import HOUSE_B, HOUSE_REAL, as_

A = fx.HOUSEHOLD
ANA, BRUNO = "sub-ana", "sub-bruno"
LANDLORD, OPERATOR, EVA, RITA, NOBODY = (
    "sub-senhorio", "sub-operador", "sub-eva", "sub-rita", "sub-ninguem",
)  # fmt: skip
URL = f"/api/households/{A}/security"
RANDOM = "00000000-0000-0000-0000-0000000000aa"
ROUTES = [
    ("get", URL, None),
    ("post", f"{URL}/proposals", {"kind": "arm"}),
    ("post", f"{URL}/proposals/{RANDOM}/confirm", None),
    ("post", f"{URL}/proposals/{RANDOM}/cancel", None),
]


def err(r):
    b = r.json()
    assert set(b) == {"error"} and set(b["error"]) == {"code", "message"}
    return r.status_code, b["error"]["code"]


def call(client, method, url, sub, payload=None):
    return getattr(client, method)(url, headers=as_(sub), **({"json": payload} if payload else {}))


@pytest.mark.parametrize("method,url,payload", ROUTES)
@pytest.mark.parametrize("sub", [LANDLORD, OPERATOR])
def test_senhorio_e_operador_nao_tem_acesso_a_nenhuma_rota(client, method, url, payload, sub):
    assert err(call(client, method, url, sub, payload)) == (403, "forbidden_role")


@pytest.mark.parametrize("method,url,payload", ROUTES)
def test_quem_nao_e_membro_recebe_404_e_sem_token_401(client, method, url, payload):
    assert err(call(client, method, url, EVA, payload)) == (404, "household_not_found")
    assert err(call(client, method, url, NOBODY, payload)) == (404, "household_not_found")
    r = getattr(client, method)(url, **({"json": payload} if payload else {}))
    assert r.status_code == 401


def test_inquilino_de_outra_casa_nao_toca_na_proposta_desta(client):
    pid = call(client, "post", f"{URL}/proposals", ANA, {"kind": "arm"}).json()["pending"]["id"]
    other = f"/api/households/{HOUSE_B}/security/proposals/{pid}/confirm"
    assert err(call(client, "post", other, EVA)) == (404, "proposal_not_found")
    assert call(client, "get", URL, ANA).json()["panel_status"] == "unknown"


def test_fluxo_armar_confirmar_desarmar(client, app):
    v = call(client, "get", URL, ANA).json()
    assert v["panel_status"] == "unknown" and v["available"] and v["origin"] == "simulated"
    assert v["assessment"] == "no_signal" and "SIMULADO" in v["notice"]

    r = call(client, "post", f"{URL}/proposals", ANA, {"kind": "arm"})
    assert r.status_code == 201
    v = r.json()
    assert v["pending"]["status"] == "proposed" and v["panel_status"] == "unknown"
    assert v["pending"]["executed"] is False

    # um segundo morador confirma (basta um); a resposta é rotulada SIMULADO
    r = call(client, "post", f"{URL}/proposals/{v['pending']['id']}/confirm", BRUNO)
    assert r.status_code == 200
    v = r.json()
    assert v["panel_status"] == "armed" and v["pending"] is None
    assert v["last_result"].startswith("SIMULADO")

    r = call(client, "post", f"{URL}/proposals", ANA, {"kind": "arm"})
    assert err(r) == (409, "action_not_applicable")
    pid = call(client, "post", f"{URL}/proposals", ANA, {"kind": "disarm"}).json()["pending"]["id"]
    v = call(client, "post", f"{URL}/proposals/{pid}/confirm", ANA).json()
    assert v["panel_status"] == "disarmed"

    # só dados anónimos na API; eventos simulados e nunca executados
    stored = app.state.db.run_sync(lambda c: load_events(c, types=["safety.security_action"]))
    assert all(s.event.data.executed is False and s.event.provenance.simulated for s in stored)
    assert {"decided_by"} & set(json.loads(call(client, "get", URL, ANA).text)) == set()


def test_confirmar_duas_vezes_e_cancelar(client):
    pid = call(client, "post", f"{URL}/proposals", ANA, {"kind": "arm"}).json()["pending"]["id"]
    assert call(client, "post", f"{URL}/proposals/{pid}/cancel", ANA).json()["pending"] is None
    assert err(call(client, "post", f"{URL}/proposals/{pid}/confirm", ANA)) == (
        409,
        "proposal_not_pending",
    )
    assert call(client, "get", URL, ANA).json()["panel_status"] == "unknown"


def test_proposta_caduca_com_o_relogio(client, now):
    from datetime import timedelta

    pid = call(client, "post", f"{URL}/proposals", ANA, {"kind": "arm"}).json()["pending"]["id"]
    now["value"] += timedelta(minutes=11)
    assert err(call(client, "post", f"{URL}/proposals/{pid}/confirm", ANA)) == (
        409,
        "proposal_expired",
    )
    v = call(client, "get", URL, ANA).json()
    assert v["pending"] is None and v["panel_status"] == "unknown"


def test_pedido_invalido_e_proposta_dupla(client):
    assert call(client, "post", f"{URL}/proposals", ANA, {"kind": "explode"}).status_code == 400
    assert call(client, "post", f"{URL}/proposals", ANA, {"kind": "arm"}).status_code == 201
    assert err(call(client, "post", f"{URL}/proposals", ANA, {"kind": "disarm"})) == (
        409,
        "proposal_pending",
    )


def test_casa_real_nao_tem_painel_simulado(client):
    url = f"/api/households/{HOUSE_REAL}/security"
    v = call(client, "get", url, RITA).json()
    assert v["available"] is False and v["can_arm"] is False
    assert err(call(client, "post", f"{url}/proposals", RITA, {"kind": "arm"})) == (
        409,
        "panel_unavailable",
    )


def _occupancy(app, state, house=A):
    from homemind.contracts import domain_events as de

    kw = {
        OccupancyState.likely_empty: dict(people_inside=0, visitors=0, residents_home=0),
        OccupancyState.occupied: dict(people_inside=2, visitors=0, residents_home=2),
        OccupancyState.uncertain: dict(people_inside=None, visitors=None, residents_home=0),
    }[state]
    ts = fx.T0
    app.state.safety.engine.on_event(
        de.PresenceOccupancyChanged(
            ts=ts, household_id=house, provenance=fx.SIM_INFERRED,
            data=HouseOccupancy(ts=ts, state=state, provenance=fx.SIM_INFERRED, **kw),
        )
    )  # fmt: skip


def test_painel_corrobora_ou_contradiz_o_away_sem_o_decidir(client, app):
    assert call(client, "get", URL, ANA).json()["away_status"] == "unknown"
    _occupancy(app, OccupancyState.likely_empty)
    v = call(client, "get", URL, ANA).json()
    assert v["away_status"] == "away" and v["assessment"] == "no_signal"  # painel sem leitura
    pid = call(client, "post", f"{URL}/proposals", ANA, {"kind": "arm"}).json()["pending"]["id"]
    v = call(client, "post", f"{URL}/proposals/{pid}/confirm", ANA).json()
    assert v["assessment"] == "consistent"
    _occupancy(app, OccupancyState.occupied)
    assert call(client, "get", URL, ANA).json()["assessment"] == "armed_with_people"
    _occupancy(app, OccupancyState.uncertain)  # falha de sinais: volta a não se inferir nada
    v = call(client, "get", URL, ANA).json()
    assert v["away_status"] == "unknown" and v["assessment"] == "no_signal"


def test_casa_real_le_o_alarme_real_so_de_leitura_e_alimenta_o_assess(client, app, now):
    """Leitura REAL (mock, formato assumido): rotulada REAL, só leitura, nunca decide o AWAY."""
    from homemind.features.safety.panel_reader import SecurityPanelCache

    url = f"/api/households/{HOUSE_REAL}/security"
    gw = {
        "type": "gateway",
        "categories": ["security"],
        "capabilities": [{"type": "alarmState", "value": "armed"}],
    }  # formato assumido
    cache = SecurityPanelCache(HOUSE_REAL, clock=lambda: now["value"])
    app.state.security_panel = cache
    try:
        v = call(client, "get", url, RITA).json()  # sem leitura ainda
        assert v["origin"] == "real" and v["panel_status"] == "unknown" and v["panel_since"] is None
        cache.ingest([gw])
        v = call(client, "get", url, RITA).json()
        assert v["origin"] == "real" and v["panel_status"] == "armed" and v["available"] is False
        assert v["can_arm"] is False and v["can_disarm"] is False and v["pending"] is None
        assert v["assessment"] == "no_signal" and "REAL" in v["notice"]  # presença sem sinal
        assert "simulado" not in v["assessment_text"].lower()
        _occupancy(app, OccupancyState.occupied, HOUSE_REAL)
        assert call(client, "get", url, RITA).json()["assessment"] == "armed_with_people"
        _occupancy(app, OccupancyState.likely_empty, HOUSE_REAL)
        assert call(client, "get", url, RITA).json()["assessment"] == "consistent"
        assert err(call(client, "post", f"{url}/proposals", RITA, {"kind": "arm"})) == (
            409,
            "panel_unavailable",
        )  # sem escrita real
        cache.ingest("lixo")  # resposta malformada do MCP: volta a não haver leitura
        v = call(client, "get", url, RITA).json()
        assert v["panel_status"] == "unknown" and v["assessment"] == "no_signal"
        # a leitura real de uma casa nunca aparece noutra, nem na demo (sempre SIMULADA)
        cache.ingest([gw])
        assert call(client, "get", URL, ANA).json()["origin"] == "simulated"
        assert call(client, "get", URL, ANA).json()["panel_status"] == "unknown"
    finally:
        app.state.security_panel = None


def test_demo_ignora_uma_leitura_real_mesmo_com_a_mesma_casa(client, app, now):
    from homemind.features.safety.panel_reader import SecurityPanelCache

    cache = SecurityPanelCache(A, clock=lambda: now["value"])
    cache.ingest(
        [
            {
                "type": "gateway",
                "categories": ["security"],
                "capabilities": [{"type": "alarmState", "value": "armed"}],
            }
        ]
    )
    app.state.security_panel = cache
    try:
        v = call(client, "get", URL, ANA).json()
        assert v["origin"] == "simulated" and v["panel_status"] == "unknown" and v["available"]
    finally:
        app.state.security_panel = None
