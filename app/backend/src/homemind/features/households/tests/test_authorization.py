"""Isolamento por casa e papel, no backend, com várias casas e papéis."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from homemind.contracts import fixtures as fx
from homemind.contracts.household import MembershipRole
from homemind.core import access as access_module
from homemind.core.access import (
    PERMISSIONS,
    Grant,
    HouseholdAccess,
    Operation,
    Resource,
    get_clock,
    grant_for,
    require_access,
)
from homemind.core.errors import register_errors
from homemind.core.lifespan import core_lifespan
from homemind.features.auth.service import User, current_user
from homemind.features.households.tests.conftest import (
    HOUSE_B,
    M_BRUNO_B,
    M_EVA,
    NOW,
    ROOM_B1,
    as_,
    seed_two_houses,
)

A = str(fx.HOUSEHOLD)
B = str(HOUSE_B)
ANA, BRUNO, CARLA = "sub-ana", "sub-bruno", "sub-carla"
LANDLORD, OPERATOR = "sub-senhorio", "sub-operador"
EVA, HUGO, FRED = "sub-eva", "sub-hugo", "sub-fred"


def err(r):
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    return r.status_code, body["error"]["code"]


# --- a matriz, aplicada por uma rota de teste por (recurso, operação) -----------------------------


@pytest.fixture
def matrix_client(monkeypatch):
    """App mínima com a MESMA guarda real; uma rota por recurso e operação. Sem rotas falsas
    na app real."""
    monkeypatch.setenv("DB_PATH", ":memory:")
    app = FastAPI(lifespan=core_lifespan)
    register_errors(app)
    router = APIRouter()
    for res in Resource:
        for op in Operation:

            def make(res=res, op=op):
                async def view(
                    access: Annotated[HouseholdAccess, Depends(require_access(res, op))],
                ):
                    return {"grant": access.grant.value, "role": access.role.value}

                return view

            router.add_api_route(
                f"/t/{{household_id}}/{res.value}/{op.value}", make(), methods=["GET"]
            )
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: User(sub=as_current["sub"])
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    with TestClient(app) as c:
        app.state.db.run_sync(seed_two_houses)
        yield c


as_current = {"sub": ""}
ROLE_SUB = {
    MembershipRole.landlord: LANDLORD,
    MembershipRole.tenant: ANA,
    MembershipRole.operator: OPERATOR,
}


def test_matrix_is_enforced_for_every_resource_operation_and_role(matrix_client):
    for res in Resource:
        for op in Operation:
            for role, sub in ROLE_SUB.items():
                as_current["sub"] = sub
                r = matrix_client.get(f"/t/{A}/{res.value}/{op.value}")
                expected = grant_for(role, res, op)
                if expected is Grant.none:
                    assert err(r) == (403, "forbidden_role"), (res, op, role)
                else:
                    assert r.status_code == 200 and r.json()["grant"] == expected.value, (
                        res,
                        op,
                        role,
                    )


def test_matrix_covers_every_resource_and_only_known_ones():
    assert set(PERMISSIONS) == set(Resource)
    for ops in PERMISSIONS.values():
        assert set(ops) <= set(Operation)


def test_privacy_invariants_of_the_matrix():
    L, T, O_ = MembershipRole.landlord, MembershipRole.tenant, MembershipRole.operator
    never_landlord = (
        *(Resource.presence, Resource.appliance, Resource.device, Resource.camera_status),
        *(Resource.attribution, Resource.consumption, Resource.agent, Resource.automation),
    )
    never_operator = (Resource.presence, Resource.member, Resource.bill, Resource.receipt,
                      Resource.budget, Resource.attribution, Resource.agent, Resource.notification,
                      Resource.energy, Resource.automation)  # fmt: skip
    for op in Operation:
        for res in never_landlord:
            assert grant_for(L, res, op) is Grant.none, (res, op)  # o senhorio nunca
        for res in never_operator:
            if (res, op) != (Resource.energy, Operation.read):  # diagnóstico de leituras
                assert grant_for(O_, res, op) is Grant.none, (res, op)  # operador não vê pessoas
    assert grant_for(L, Resource.energy, Operation.read) is Grant.aggregate  # só totais
    assert grant_for(L, Resource.receipt, Operation.read) is Grant.aggregate
    assert grant_for(T, Resource.presence, Operation.read) is Grant.own


def test_landlord_cannot_reach_presence_even_in_own_house(matrix_client):
    as_current["sub"] = LANDLORD
    r = matrix_client.get(f"/t/{A}/presence/read")
    assert err(r) == (403, "forbidden_role")


def test_non_member_gets_404_and_cannot_tell_whether_the_house_exists(matrix_client):
    as_current["sub"] = ANA  # inquilina da casa A
    other = matrix_client.get(f"/t/{B}/presence/read")  # casa B existe mas ela não é membro
    ghost = matrix_client.get(f"/t/{UUID(int=1)}/presence/read")  # casa inexistente
    assert err(other) == err(ghost) == (404, "household_not_found")
    assert other.json() == ghost.json()


def test_expired_and_future_memberships_grant_nothing(matrix_client):
    as_current["sub"] = FRED  # membership terminada em 2026-10-01
    assert err(matrix_client.get(f"/t/{B}/household/read")) == (404, "household_not_found")


# --- rotas reais ----------------------------------------------------------------------------


def test_invalid_or_missing_token_is_refused(monkeypatch):
    from homemind.main import app

    with TestClient(app) as c:
        assert c.get(f"/api/households/{A}").status_code == 401
        r = c.get(f"/api/households/{A}", headers={"Authorization": "Bearer lixo"})
        assert err(r) == (401, "http_401")
        assert c.get("/api/me/context", headers={"Authorization": "Bearer lixo"}).status_code == 401


def test_tenant_reads_own_house_but_not_the_other(client):
    assert client.get(f"/api/households/{A}", headers=as_(ANA)).status_code == 200
    assert err(client.get(f"/api/households/{B}", headers=as_(ANA))) == (404, "household_not_found")
    assert err(client.get(f"/api/households/{A}", headers=as_(EVA))) == (404, "household_not_found")
    for path in ("rooms", "members"):
        assert err(client.get(f"/api/households/{B}/{path}", headers=as_(ANA)))[0] == 404
        assert err(client.get(f"/api/households/{A}/{path}", headers=as_(EVA)))[0] == 404


def test_household_response_has_no_internal_fields(client):
    body = client.get(f"/api/households/{A}", headers=as_(ANA)).json()
    assert set(body) == {"id", "name", "timezone", "source_kind", "policy"}
    assert body["policy"]["common_area_rule"] == "ask" and body["source_kind"] == "demo"


def test_members_dto_hides_private_fields_and_differs_by_role(client):
    tenant = client.get(f"/api/households/{A}/members", headers=as_(ANA))
    landlord = client.get(f"/api/households/{A}/members", headers=as_(LANDLORD))
    assert tenant.status_code == landlord.status_code == 200
    for m in tenant.json() + landlord.json():
        assert "presence_opt_in" not in m and "auth_subject" not in m and "sub" not in str(m)
    assert {m["display_name"] for m in tenant.json()} >= {"Ana", "Bruno", "Carla", "Diogo"}
    assert (
        err(client.get(f"/api/households/{A}/members", headers=as_(OPERATOR)))[1]
        == "forbidden_role"
    )


def test_tenant_sees_only_active_members_landlord_sees_history(client):
    # Fred (casa B) terminou: Eva não o vê, Hugo vê-o
    eva = {
        m["display_name"]
        for m in client.get(f"/api/households/{B}/members", headers=as_(EVA)).json()
    }
    hugo = {
        m["display_name"]
        for m in client.get(f"/api/households/{B}/members", headers=as_(HUGO)).json()
    }
    assert "Fred" not in eva and "Fred" in hugo


def test_operator_is_limited_to_diagnostic_resources(client):
    assert client.get(f"/api/households/{A}", headers=as_(OPERATOR)).status_code == 200
    assert client.get(f"/api/households/{A}/rooms", headers=as_(OPERATOR)).status_code == 200
    assert err(client.get(f"/api/households/{A}/members", headers=as_(OPERATOR))) == (
        403,
        "forbidden_role",
    )
    assert err(client.get(f"/api/households/{B}", headers=as_(OPERATOR))) == (
        404,
        "household_not_found",
    )


def test_mcp_tools_are_only_available_to_an_operator(client, monkeypatch):
    from homemind.connectors import altice

    async def tools():
        return [{"name": "get_home_devices"}]

    monkeypatch.setattr(altice, "list_tools", tools)
    for sub in (ANA, LANDLORD, "sub-sem-membership"):
        assert err(client.get("/api/mcp/tools", headers=as_(sub))) == (403, "forbidden_role")
    response = client.get("/api/mcp/tools", headers=as_(OPERATOR))
    assert response.status_code == 200
    assert response.json() == [{"name": "get_home_devices"}]


def test_tenant_patches_only_own_membership(client, app):
    mine = str(fx.memberships()[0].id)  # Ana
    theirs = str(fx.memberships()[1].id)  # Bruno
    url = lambda m, h=A: f"/api/households/{h}/memberships/{m}"  # noqa: E731
    ok = client.patch(url(mine), json={"presence_opt_in": True}, headers=as_(ANA))
    assert ok.status_code == 200 and ok.json()["presence_opt_in"] is True
    row = app.state.db.run_sync(
        lambda c: c.execute("SELECT presence_opt_in FROM membership WHERE id=?", (mine,)).fetchone()
    )
    assert row[0] == 1
    assert err(client.patch(url(theirs), json={"presence_opt_in": True}, headers=as_(ANA))) == (
        403,
        "forbidden_role",
    )
    row = app.state.db.run_sync(
        lambda c: c.execute(
            "SELECT presence_opt_in FROM membership WHERE id=?", (theirs,)
        ).fetchone()
    )
    assert row[0] == 0  # intocada
    # membership de OUTRA casa, com o contexto desta: não existe aqui
    assert (
        err(client.patch(url(str(M_EVA)), json={"presence_opt_in": True}, headers=as_(ANA)))[0]
        == 404
    )
    # id da própria pessoa mas de outra casa no caminho certo: 404 (Bruno tem membership em B)
    assert (
        err(client.patch(url(str(M_BRUNO_B)), json={"presence_opt_in": True}, headers=as_(BRUNO)))[
            0
        ]
        == 404
    )


def test_patch_rechecks_membership_in_the_write_transaction(client, app, monkeypatch):
    """A revoke between FastAPI authorization and PATCH must cancel the write."""
    membership_id = str(fx.memberships()[0].id)
    original = access_module.resolve_access

    async def revoke_after_access(db, sub, household_id, resource, op, now):
        access = await original(db, sub, household_id, resource, op, now)
        await db.run(
            lambda conn: conn.execute(
                "UPDATE membership SET status='ended', ends_on=? WHERE id=?",
                (NOW.date().isoformat(), membership_id),
            )
        )
        return access

    monkeypatch.setattr(access_module, "resolve_access", revoke_after_access)
    response = client.patch(
        f"/api/households/{A}/memberships/{membership_id}",
        json={"presence_opt_in": True},
        headers=as_(ANA),
    )
    assert err(response) == (404, "household_not_found")
    stored = app.state.db.run_sync(
        lambda conn: conn.execute(
            "SELECT presence_opt_in FROM membership WHERE id=?", (membership_id,)
        ).fetchone()[0]
    )
    assert stored == 0


def test_landlord_and_operator_cannot_change_consent(client):
    m = str(fx.memberships()[0].id)
    for sub in (LANDLORD, OPERATOR):
        r = client.patch(
            f"/api/households/{A}/memberships/{m}", json={"presence_opt_in": True}, headers=as_(sub)
        )
        assert err(r) == (403, "forbidden_role")


def test_patch_rejects_unknown_and_identity_fields(client):
    mine = str(fx.memberships()[0].id)
    url = f"/api/households/{A}/memberships/{mine}"
    for body in ({"presence_opt_in": True, "role": "landlord"},
                 {"presence_opt_in": True, "resident_id": str(fx.BRUNO)},
                 {"presence_opt_in": "yes"}, {}):  # fmt: skip
        r = client.patch(url, json=body, headers=as_(ANA))
        assert err(r) == (400, "invalid_request"), body


def test_identity_comes_from_the_token_never_from_client_fields(client):
    # `resident_id` no query string não muda quem somos
    r = client.get(f"/api/me/context?resident_id={fx.BRUNO}", headers=as_(ANA))
    assert r.json()["resident"]["id"] == str(fx.ANA)


def test_me_context_lists_active_memberships_across_houses(client):
    ctx = client.get("/api/me/context", headers=as_(BRUNO)).json()  # inquilino em A e em B
    assert ctx["resident"] == {"id": str(fx.BRUNO), "display_name": "Bruno"}
    assert {m["household_id"] for m in ctx["memberships"]} == {A, B}
    assert all(m["role"] == "tenant" for m in ctx["memberships"])
    fred = client.get("/api/me/context", headers=as_(FRED)).json()
    assert fred["memberships"] == []  # terminada: sem contexto
    ghost = client.get("/api/me/context", headers=as_("sub-desconhecido")).json()
    assert ghost == {"resident": None, "memberships": []}


def test_membership_expiry_follows_the_household_clock(client, now):
    assert client.get(f"/api/households/{B}", headers=as_(EVA)).status_code == 200
    # Hugo (senhorio) continua; Eva continua; no dia seguinte ao fim de Fred nada muda para ele
    now["value"] = datetime(2027, 1, 1, tzinfo=UTC)
    assert client.get(f"/api/households/{B}", headers=as_(EVA)).status_code == 200


def test_access_expires_at_midnight_in_household_timezone(client, app, now):
    app.state.db.run_sync(
        lambda conn: (
            conn.execute("UPDATE household SET timezone='America/Los_Angeles' WHERE id=?", (B,)),
            conn.execute("UPDATE membership SET ends_on='2026-11-17' WHERE id=?", (str(M_EVA),)),
        )
    )
    now["value"] = datetime(2026, 11, 18, 7, 59, 59, tzinfo=UTC)
    assert client.get(f"/api/households/{B}", headers=as_(EVA)).status_code == 200
    now["value"] = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
    assert err(client.get(f"/api/households/{B}", headers=as_(EVA))) == (
        404,
        "household_not_found",
    )


def test_same_person_has_different_roles_per_house(matrix_client):
    # Bruno: inquilino em A (presença sim) e inquilino em B; Hugo: senhorio só em B
    as_current["sub"] = HUGO
    assert matrix_client.get(f"/t/{B}/bill/read").json()["grant"] == "aggregate"
    assert err(matrix_client.get(f"/t/{A}/bill/read"))[0] == 404


def test_ended_membership_via_repo_removes_access(client, app):
    from homemind.features.households.repo import end_membership

    assert client.get(f"/api/households/{A}", headers=as_(DIOGO := "sub-diogo")).status_code == 200
    app.state.db.run_sync(
        lambda c: end_membership(c, fx.memberships()[3].id, NOW.date().replace(day=10))
    )
    assert err(client.get(f"/api/households/{A}", headers=as_(DIOGO))) == (
        404,
        "household_not_found",
    )


def test_room_of_another_house_cannot_be_assigned(app):
    from homemind.contracts import household as hh
    from homemind.features.households.repo import insert_membership

    bad = hh.Membership(
        id=fx.stable_id("m", "bad"), household_id=fx.HOUSEHOLD,
        resident_id=fx.stable_id("resident", "eva"), role=hh.MembershipRole.tenant,
        room_id=ROOM_B1, starts_on=NOW.date(), status=hh.MembershipStatus.invited,
    )  # fmt: skip
    with pytest.raises(ValueError, match="outra casa"):
        app.state.db.run_sync(lambda c: insert_membership(c, bad))
