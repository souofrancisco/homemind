"""HOUSE-02: convites, papéis e isolamento usando a app e as dependências reais."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

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
    assert len(base64.urlsafe_b64decode(data["code"] + "=" * (-len(data["code"]) % 4))) == 32
    stored_invitation = app.state.db.run_sync(
        lambda c: dict(
            c.execute(
                "SELECT * FROM membership_invitation WHERE id=?", (data["invitation_id"],)
            ).fetchone()
        )
    )
    assert stored_invitation["token_sha256"] == hashlib.sha256(data["code"].encode()).hexdigest()
    assert data["code"] not in stored_invitation.values()
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
    landlord_members = client.get(
        f"/api/households/{HOUSE_A}/members", headers=as_("sub-senhorio")
    ).json()
    public_data = str(accepted.json()) + str(ctx) + str(landlord_members)
    assert all(
        field not in public_data for field in ("auth_subject", "target_email", "token_sha256")
    )
    assert data["code"] not in public_data


def test_simultaneous_acceptance_redeems_invitation_once(client):
    room = create_room(client)
    token = invite(client, room).json()["code"]
    barrier = Barrier(2)

    def accept_at_once(_):
        barrier.wait()
        return accept(client, token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(accept_at_once, range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert error(conflict) == (409, "invitation_used")


def test_simultaneous_invites_reserve_a_room_once(client):
    room = create_room(client)
    barrier = Barrier(2)

    def issue_at_once(email):
        barrier.wait()
        return invite(client, room, email=email)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(issue_at_once, ("one@example.test", "two@example.test")))
    assert sorted(response.status_code for response in responses) == [201, 409]


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
    now["value"] = NOW + timedelta(hours=72)
    assert error(accept(client, future.json()["code"])) == (404, "invitation_not_found")
    assert invite(client, next_room, email="new-guest@example.test").status_code == 201


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


def test_acceptance_never_activates_a_privileged_membership(client, app):
    room = create_room(client)
    issued = invite(client, room)
    membership_id = app.state.db.run_sync(
        lambda conn: conn.execute(
            "SELECT membership_id FROM membership_invitation WHERE id=?",
            (issued.json()["invitation_id"],),
        ).fetchone()[0]
    )
    # Simula uma associação administrativa incorreta; o fluxo público não deve ativá-la.
    app.state.db.run_sync(
        lambda conn: conn.execute(
            "UPDATE membership SET role='landlord', room_id=NULL WHERE id=?", (membership_id,)
        )
    )
    assert error(accept(client, issued.json()["code"])) == (404, "invitation_not_found")


def test_invitation_rejects_occupied_rooms_and_existing_pending_invites(client):
    assert error(invite(client, str(fx.ROOM_ANA))) == (409, "membership_conflict")
    room = create_room(client, name="Quarto reservado")
    assert invite(client, room).status_code == 201
    assert error(invite(client, room, email="another@example.test")) == (
        409,
        "membership_conflict",
    )


def test_fake_authentik_access_token_is_distinguished_from_id_token(client, app, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = SimpleNamespace(oidc_issuer="https://issuer.invalid/app/", oidc_client_id="homemind")

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=key.public_key())

    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "_jwks", lambda: Keys())
    access_claims = {
        "sub": "sub-ana",
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_client_id,
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
        "email": "ana@example.test",
        "email_verified": True,
        # Authentik 2026.8.5 adds these fields only to access tokens.
        "azp": settings.oidc_client_id,
        "uid": "access-token-id",
        "scope": "openid profile email",
    }
    token = jwt.encode(
        access_claims,
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

    id_token = jwt.encode(
        {
            **{k: v for k, v in access_claims.items() if k not in {"uid", "scope", "azp"}},
            "nonce": "oidc-login-nonce",
        },
        key,
        algorithm="RS256",
    )
    with pytest.raises(HTTPException) as error:
        auth.validate_access_token(id_token)
    assert error.value.status_code == 401

    malformed_claims = jwt.encode({**access_claims, "groups": "not-a-list"}, key, algorithm="RS256")
    with pytest.raises(HTTPException) as error:
        auth.validate_access_token(malformed_claims)
    assert error.value.status_code == 401
