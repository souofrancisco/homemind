"""O contrato OpenAPI inclui os modelos partilhados sem rotas falsas e sem expor dados privados."""

import json
import re

import pytest

from homemind.contracts.api import OPENAPI_MODELS
from homemind.main import app


@pytest.fixture(scope="module")
def spec():
    return app.openapi()


def test_every_shared_model_is_in_the_contract_exactly_once(spec):
    names = {m.__name__ for m in OPENAPI_MODELS}
    schemas = spec["components"]["schemas"]
    assert names <= set(schemas)
    assert not [n for n in schemas if re.search(r"-(Input|Output)$", n)]  # sem pares ambíguos


def test_no_dangling_refs(spec):
    text = json.dumps(spec)
    schemas = spec["components"]["schemas"]
    for name in set(re.findall(r'#/components/schemas/([^"]+)"', text)):
        assert name in schemas, name


def test_private_models_and_fields_never_reach_the_frontend(spec):
    schemas = spec["components"]["schemas"]
    internal_models = (
        *("Device", "Resident", "Membership", "StoredEvent", "ApplianceSignature"),
        *("PresenceEvent", "Notification", "DoorCrossed", "ConfirmationRequest"),
    )
    for internal in internal_models:
        assert internal not in schemas, internal
    props = {p for s in schemas.values() for p in s.get("properties", {})}
    assert not props & {"external_ref", "auth_subject", "image", "frame", "frames", "token"}
    # ids de terceiros que a app não precisa: a notificação pública não traz quem pode responder
    assert "responder_ids" not in schemas["NotificationView"]["properties"]
    assert "presence_opt_in" not in schemas["MemberView"]["properties"]


def test_no_fake_endpoints_for_shared_models(spec):
    paths = set(spec["paths"])
    for banned in ("/api/contracts", "/api/schemas", "/api/models", "/api/presence", "/api/bills"):
        assert banned not in paths
    # as rotas existentes antes da fundação continuam
    for kept in ("/healthz", "/api/me", "/api/status", "/api/state", "/api/events", "/api/rules"):
        assert kept in paths, kept


def test_response_fields_with_defaults_are_required_and_null_is_explicit(spec):
    consumption = spec["components"]["schemas"]["ConsumptionEvent"]
    for field in ("energy_wh", "ended_at", "cost_estimate", "room_id"):
        assert field in consumption["required"], field  # presente, possivelmente `null`
    assert {"type": "null"} in consumption["properties"]["energy_wh"]["anyOf"]


def test_enums_and_formats_are_precise(spec):
    s = spec["components"]["schemas"]
    assert s["ValueKind"]["enum"] == ["measured", "estimated", "inferred"]
    assert s["Origin"]["enum"] == ["real", "simulated"]
    assert s["PresenceState"]["enum"] == ["in", "out", "uncertain"]
    assert s["NotificationAction"]["properties"]["id"]["pattern"]
    assert s["EnergyReading"]["properties"]["ts"]["format"] == "date-time"
    assert s["EnergyReading"]["properties"]["device_id"]["format"] == "uuid"
    assert s["ElectricityBill"]["properties"]["total_cents"]["type"] == "integer"
