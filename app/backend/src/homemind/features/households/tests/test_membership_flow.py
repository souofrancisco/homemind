"""HOUSE-02: convites, papéis e isolamento usando a app e as dependências reais."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from homemind.contracts import fixtures as fx
from homemind.core.access import Operation, Resource, resolve_access
from homemind.features.auth import service as auth
from homemind.features.households.tests.conftest import HOUSE_B, NOW, as_

HOUSE_A = fx.HOUSEHOLD


def error(response):
    assert set(response.json()) == {"error"}
    return response.status_code, response.json()["error"]["code"]


def verified(sub="sub-guest", email="guest@example.test"):
    return {**as_(sub), "x-test-email": email, "x-test-verified": "true"}


def create_room(client, household_id=HOUSE_A, landlord="sub-senhorio", name="Suite nova"):
    response = client.post(
        f"/api/households/{household_id}/rooms",
        json={"name": name, "kind": "bedroom"},
        headers=as_(landlord),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def invite(
    client,
    room_id,
    household_id=HOUSE_A,
    landlord="sub-senhorio",
    email="guest@example.test",
    starts="2026-11-01",
    ends=None,
    **extra,
):
    payload = {
        "display_name": "Novo morador",
        "email": email,
        "room_id": room_id,
        "starts_on": starts,
        **extra,
    }
    if ends:
        payload["ends_on"] = ends
    return client.post(
        f"/api/households/{household_id}/invitations",
        json=payload,
        headers=as_(landlord),
    )


def accept(client, token, headers=None):
    return client.post(
        "/api/invitations/accept",
        json={"code": token},
        headers=headers or verified(),
    )


def test_landlords_can_provision_rooms_only_in_their_own_house(client):
    assert create_room(client, name="Quarto novo A")
    assert create_room(client, HOUSE_B, "sub-hugo", "Quarto novo B")
    body = {"name": "Intrusão", "kind": "bedroom"}
    assert error(
        client.post(f"/api/households/{HOUSE_A}/rooms", json=body, headers=as_("sub-hugo"))
    ) == (404, "household_not_found")
    assert error(
        client.post(f"/api/households/{HOUSE_A}/rooms", json=body, headers=as_("sub-ana"))
    ) == (403, "forbidden_role")
    assert error(
        client.post(
            f"/api/households/{HOUSE_A}/rooms",
            json={**body, "household_id": str(HOUSE_B)},
            headers=as_("sub-senhorio"),
        )
    ) == (400, "invalid_request")


def test_invitation_is_one_use_and_restores_context(client, app):
    room = create_room(client)
    issued = invite(client, room)
    assert issued.status_code == 201, issued.text
    data = issued.json()
    assert set(data) == {"invitation_id", "code", "expires_at"}
    assert len(data["code"]) >= 40
    assert (
        app.state.db.run_sync(
            lambda c: c.execute(
                "SELECT token_sha256 FROM membership_invitation WHERE id=?",
                (data["invitation_id"],),
            ).fetchone()[0]
        )
        == hashlib.sha256(data["code"].encode()).hexdigest()
    )
    # Convite pendente não autoriza nada, e os inquilinos não o veem na lista.
    assert client.get("/api/me/context", headers=verified()).json()["resident"] is None
    assert error(client.get(f"/api/households/{HOUSE_A}", headers=verified())) == (
        404,
        "household_not_found",
    )
    members = client.get(f"/api/households/{HOUSE_A}/members", headers=as_("sub-ana")).json()
    assert all(m["room_id"] != room for m in members)
    accepted = accept(client, data["code"])
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["role"] == "tenant"
    assert accepted.json()["room_id"] == room
    assert accepted.json()["status"] == "active"
    assert error(accept(client, data["code"])) == (409, "invitation_used")
    assert client.get(f"/api/households/{HOUSE_A}", headers=verified()).status_code == 200
    ctx = client.get("/api/me/context", headers=verified()).json()
    assert ctx["resident"]["display_name"] == "Novo morador"
    assert len(ctx["memberships"]) == 1
    assert "auth_subject" not in str(accepted.json()) + str(ctx)
    assert "token" not in str(accepted.json()) + str(ctx)


def test_invalid_expired_unverified_and_wrong_account(client, now):
    room = create_room(client)
    issued = invite(client, room)
    token = issued.json()["code"]
    assert error(accept(client, "x" * 45)) == (404, "invitation_not_found")
    assert error(accept(client, token, as_("sub-guest"))) == (403, "verified_email_required")
    assert error(accept(client, token, verified(email="wrong@example.test"))) == (
        404,
        "invitation_not_found",
    )
    attacker = verified(sub="sub-attacker", email="wrong@example.test")
    assert error(accept(client, token, attacker)) == (404, "invitation_not_found")
    # Tentativas com email incorreto não consomem o código de convite.
    assert accept(client, token, verified(email="guest@example.test")).status_code == 200
    next_room = create_room(client, name="Outra suite")
    future = invite(client, next_room)
    now["value"] = NOW + timedelta(hours=73)
    assert error(accept(client, future.json()["code"])) == (404, "invitation_not_found")


def test_invite_rejects_role_escalation_and_cross_house_room(client):
    room = create_room(client)
    for role in ("landlord", "operator", "tenant"):
        assert error(invite(client, room, role=role)) == (400, "invalid_request")
    assert error(invite(client, room, household_id=HOUSE_B, landlord="sub-hugo")) == (
        404,
        "room_not_found",
    )
    assert error(invite(client, room, landlord="sub-ana")) == (403, "forbidden_role")
    assert error(invite(client, room, landlord="sub-hugo")) == (404, "household_not_found")
    assert error(invite(client, room, starts="2026-12-01", ends="2026-11-01")) == (
        400,
        "invalid_request",
    )


def test_revoke_immediately_denies_and_preserves_history(client, app):
    room = create_room(client)
    token = invite(client, room).json()["code"]
    membership_id = accept(client, token).json()["id"]
    resp = client.post(
        f"/api/households/{HOUSE_A}/memberships/{membership_id}/revoke",
        headers=as_("sub-senhorio"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ended"
    assert resp.json()["ends_on"] == NOW.date().isoformat()
    assert error(client.get(f"/api/households/{HOUSE_A}", headers=verified())) == (
        404,
        "household_not_found",
    )
    assert client.get("/api/me/context", headers=verified()).json()["memberships"] == []
    stored = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT status, ends_on FROM membership WHERE id=?", (membership_id,)
        ).fetchone()
    )
    assert tuple(stored) == ("ended", NOW.date().isoformat())
    assert error(
        client.post(
            f"/api/households/{HOUSE_A}/memberships/{membership_id}/revoke",
            headers=as_("sub-senhorio"),
        )
    ) == (409, "membership_conflict")
    assert error(
        client.post(
            f"/api/households/{HOUSE_A}/memberships/{membership_id}/revoke",
            headers=verified(),
        )
    ) == (404, "household_not_found")


def test_revoke_invite_prevents_accept_and_house_swap_keeps_history(client, app):
    old = str(fx.memberships()[0].id)  # Ana
    path = f"/api/households/{HOUSE_A}/memberships/{old}/revoke"
    assert client.post(path, headers=as_("sub-senhorio")).status_code == 200
    issued = invite(client, str(fx.ROOM_ANA))
    assert issued.status_code == 201
    new_id = accept(client, issued.json()["code"]).json()["id"]
    assert new_id != old
    rows = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT id, status FROM membership WHERE room_id=? ORDER BY id",
            (str(fx.ROOM_ANA),),
        ).fetchall()
    )
    assert {tuple(x) for x in rows} == {(old, "ended"), (new_id, "active")}
    assert error(client.get(f"/api/households/{HOUSE_A}", headers=as_("sub-ana"))) == (
        404,
        "household_not_found",
    )
    new_room = create_room(client, name="Quarto por anular")
    invite_pending = invite(client, new_room)
    pending_id = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT membership_id FROM membership_invitation WHERE id=?",
            (invite_pending.json()["invitation_id"],),
        ).fetchone()[0]
    )
    assert (
        client.post(
            f"/api/households/{HOUSE_A}/memberships/{pending_id}/revoke",
            headers=as_("sub-senhorio"),
        ).status_code
        == 200
    )
    assert error(accept(client, invite_pending.json()["code"])) == (404, "invitation_not_found")


def test_future_contract_and_tenant_list_use_household_local_date(client, now):
    room = create_room(client)
    created = invite(client, room, starts="2026-12-01", ends="2027-01-01")
    assert accept(client, created.json()["code"]).status_code == 200
    assert error(client.get(f"/api/households/{HOUSE_A}", headers=verified())) == (
        404,
        "household_not_found",
    )
    assert client.get("/api/me/context", headers=verified()).json()["memberships"] == []
    now["value"] = datetime(2026, 12, 2, tzinfo=UTC)
    assert client.get(f"/api/households/{HOUSE_A}", headers=verified()).status_code == 200
    now["value"] = datetime(2027, 1, 2, tzinfo=UTC)
    assert error(client.get(f"/api/households/{HOUSE_A}", headers=verified())) == (
        404,
        "household_not_found",
    )
    assert client.get("/api/me/context", headers=verified()).json()["memberships"] == []


def test_existing_resident_reused_across_houses(client):
    room = create_room(client)
    issued = invite(client, room, email="eva@example.test")
    accepted = accept(client, issued.json()["code"], verified("sub-eva", "eva@example.test"))
    assert accepted.status_code == 200, accepted.text
    context = client.get("/api/me/context", headers=as_("sub-eva")).json()
    assert context["resident"]["id"] == str(UUID(str(context["resident"]["id"])))
    assert {m["household_id"] for m in context["memberships"]} == {str(HOUSE_A), str(HOUSE_B)}
    assert client.get(f"/api/households/{HOUSE_B}", headers=as_("sub-eva")).status_code == 200


def test_401_and_privileged_contracts_cannot_be_self_assigned(client):
    room = create_room(client)
    assert client.post("/api/invitations/accept", json={"code": "x" * 45}).status_code == 401
    response = invite(client, room, email="malformed")
    assert error(response) == (400, "invalid_request")
    current = str(fx.memberships()[0].id)
    assert error(
        client.patch(
            f"/api/households/{HOUSE_A}/memberships/{current}",
            json={"presence_opt_in": True, "role": "landlord"},
            headers=as_("sub-ana"),
        )
    ) == (400, "invalid_request")
    assert error(
        client.post(
            f"/api/households/{HOUSE_A}/memberships/{current}/revoke",
            headers=as_("sub-ana"),
        )
    ) == (403, "forbidden_role")


def test_same_verified_oidc_identity_used_by_http_and_future_ws(client, app, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = SimpleNamespace(oidc_issuer="https://issuer.invalid/app/", oidc_client_id="homemind")

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=key.public_key())

    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "_jwks", lambda: Keys())
    token = jwt.encode(
        {
            "sub": "sub-ana",
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_client_id,
            "exp": int(datetime.now(UTC).timestamp()) + 3600,
            "email": "ana@example.test",
            "email_verified": True,
        },
        key,
        algorithm="RS256",
    )
    principal = auth.validate_access_token(token)
    assert principal.sub == "sub-ana" and principal.email_verified
    access = asyncio.run(
        resolve_access(app.state.db, principal.sub, HOUSE_A, Resource.member, Operation.read, NOW)
    )
    assert access.resident_id == fx.ANA
    assert client.get("/api/me/context", headers=as_("sub-ana")).json()["resident"]["id"] == (
        str(access.resident_id)
    )
