"""HOUSE-02 × HOUSE-03: convite real → membership → aparelho → revogação, sem hardware."""

from datetime import timedelta
from uuid import UUID

from homemind.contracts import fixtures as fx
from homemind.features.appliances import repo
from homemind.features.appliances.tests.test_catalog import A, appliance_url
from homemind.features.households.tests.conftest import NOW, as_
from homemind.features.households.tests.test_membership_flow import (
    accept,
    create_room,
    invite,
    verified,
)

pytest_plugins = ("homemind.features.households.tests.conftest",)


def test_invited_tenant_owns_appliance_and_history_survives_revocation(client, app, now):
    room = create_room(client)
    code = invite(client, room).json()["code"]
    membership = accept(client, code).json()
    guest = verified()

    created = client.post(
        f"/api/households/{A}/appliances",
        json={"name": "Aquecedor", "category": "heating", "scope": "personal",
              "home_room_id": room, "typical_watts": 1500},
        headers=guest,
    )  # fmt: skip
    assert created.status_code == 201, created.text
    aid = UUID(created.json()["id"])
    owner = UUID(created.json()["ownership"]["owner_resident_id"])
    # outra casa não vê o aparelho
    assert client.get(appliance_url(aid), headers=as_("sub-eva")).status_code == 404

    earlier = NOW + timedelta(seconds=1)
    now["value"] = NOW + timedelta(minutes=5)
    revoked = client.post(
        f"/api/households/{A}/memberships/{membership['id']}/revoke", headers=as_("sub-senhorio")
    )
    assert revoked.status_code == 200, revoked.text
    assert client.get(appliance_url(aid), headers=guest).status_code == 404  # acesso atual cortado
    # histórico preservado e consumo antigo não é reatribuído
    assert (
        app.state.db.run_sync(
            lambda c: repo.ownership_at(c, fx.HOUSEHOLD, aid, earlier)
        ).owner_resident_id
        == owner
    )
