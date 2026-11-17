"""HOUSE-02: convites, associação OIDC e revogação na mesma transação SQLite."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from homemind.contracts.household import (
    Membership,
    MembershipRole,
    MembershipSelfView,
    MembershipStatus,
    MemberView,
    Resident,
    Room,
    RoomKind,
    RoomView,
)
from homemind.core.access import find_membership
from homemind.features.auth.service import User
from homemind.features.households import repo

INVITE_TTL = timedelta(hours=72)


class FlowError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)


def _fail(status: int, code: str, message: str) -> None:
    raise FlowError(status, code, message)


def _landlord(conn: sqlite3.Connection, user: User, house: UUID, now: datetime) -> str:
    # Revalidar dentro da transação: autorização e escrita não têm uma race.
    row = find_membership(conn, user.sub, house, now)
    if row is None:
        _fail(404, "household_not_found", "Casa não encontrada")
    if row["role"] != MembershipRole.landlord.value:
        _fail(403, "forbidden_role", "Sem permissão")
    return str(row["id"])


def create_room(conn: sqlite3.Connection, user: User, house: UUID, body: object,
                now: datetime) -> RoomView:
    _landlord(conn, user, house, now)
    room = Room(
        id=uuid4(), household_id=house, name=body.name, kind=body.kind,
        included_wh=body.included_wh,
    )
    repo.insert_room(conn, room)
    return RoomView(id=room.id, name=room.name, kind=room.kind)


def issue_invitation(conn: sqlite3.Connection, user: User, house: UUID, body: object,
                     now: datetime) -> dict:
    inviter = _landlord(conn, user, house, now)
    room = repo.get_room(conn, body.room_id)
    if room is None or room.household_id != house or room.kind is not RoomKind.bedroom:
        _fail(404, "room_not_found", "Quarto não encontrado")
    if body.ends_on is not None and body.ends_on < body.starts_on:
        _fail(400, "invalid_request", "Datas contratuais inválidas")
    email = body.email.strip().casefold()
    if not email or len(email) > 254:
        _fail(400, "invalid_request", "Email inválido")

    resident_id, membership_id, invitation_id = uuid4(), uuid4(), uuid4()
    repo.insert_resident(
        conn, Resident(id=resident_id, display_name=body.display_name), created_at=now
    )
    repo.insert_membership(
        conn, Membership(
            id=membership_id, household_id=house, resident_id=resident_id,
            role=MembershipRole.tenant, room_id=body.room_id, starts_on=body.starts_on,
            ends_on=body.ends_on, status=MembershipStatus.invited,
        ),
    )
    token = secrets.token_urlsafe(32)
    expires_at = now.astimezone(UTC) + INVITE_TTL
    conn.execute(
        "INSERT INTO membership_invitation "
        "(id, membership_id, token_sha256, target_email, created_by_membership_id,"
        " created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
        (str(invitation_id), str(membership_id), hashlib.sha256(token.encode()).hexdigest(),
         email, inviter, now.astimezone(UTC).isoformat(), expires_at.isoformat()),
    )
    # Apenas a resposta desta criação contém o segredo. Nunca é persistido em claro.
    return {"invitation_id": invitation_id, "token": token, "expires_at": expires_at}


def accept_invitation(conn: sqlite3.Connection, user: User, token: str,
                      now: datetime) -> MembershipSelfView:
    if user.email_verified is not True or not user.email:
        _fail(403, "verified_email_required", "Email verificado obrigatório")
    row = conn.execute(
        "SELECT i.id AS invitation_id, i.target_email, i.expires_at, i.redeemed_at,"
        " i.revoked_at, m.id AS membership_id, m.household_id, m.resident_id,"
        " m.status, m.ends_on, r.auth_subject AS reserved_subject, h.timezone"
        " FROM membership_invitation i JOIN membership m ON m.id=i.membership_id"
        " JOIN resident r ON r.id=m.resident_id"
        " JOIN household h ON h.id=m.household_id WHERE i.token_sha256=?",
        (hashlib.sha256(token.encode()).hexdigest(),),
    ).fetchone()
    if row is None or row["revoked_at"] is not None:
        _fail(404, "invitation_not_found", "Convite indisponível")
    if row["redeemed_at"] is not None:
        _fail(409, "invitation_used", "Convite já utilizado")
    if datetime.fromisoformat(row["expires_at"]) <= now.astimezone(UTC):
        _fail(404, "invitation_not_found", "Convite indisponível")
    if row["target_email"] != user.email.strip().casefold():
        _fail(404, "invitation_not_found", "Convite indisponível")
    if row["reserved_subject"] not in (None, user.sub):
        _fail(404, "invitation_not_found", "Convite indisponível")
    if row["status"] != MembershipStatus.invited.value:
        _fail(409, "membership_conflict", "Contrato indisponível")
    today = now.astimezone(ZoneInfo(row["timezone"])).date().isoformat()
    if row["ends_on"] is not None and row["ends_on"] < today:
        _fail(409, "membership_conflict", "Contrato já terminou")

    reserved_id = row["resident_id"]
    existing = conn.execute(
        "SELECT id FROM resident WHERE auth_subject=?", (user.sub,)
    ).fetchone()
    if existing is not None and existing["id"] != reserved_id:
        resident_id = existing["id"]
        conn.execute(
            "UPDATE membership SET resident_id=? WHERE id=? AND status='invited'",
            (resident_id, row["membership_id"]),
        )
        # A reserva ainda sem contratos não é historial contratual.
        conn.execute(
            "DELETE FROM resident WHERE id=? AND auth_subject IS NULL"
            " AND NOT EXISTS (SELECT 1 FROM membership WHERE resident_id=?)",
            (reserved_id, reserved_id),
        )
    else:
        resident_id = reserved_id
        if existing is None:
            conn.execute(
                "UPDATE resident SET auth_subject=? WHERE id=? AND auth_subject IS NULL",
                (user.sub, resident_id),
            )
    changed = conn.execute(
        "UPDATE membership SET status='active' WHERE id=? AND status='invited'",
        (row["membership_id"],),
    )
    if changed.rowcount != 1:
        _fail(409, "membership_conflict", "Contrato indisponível")
    changed = conn.execute(
        "UPDATE membership_invitation SET redeemed_at=?, redeemed_by_resident_id=?"
        " WHERE id=? AND redeemed_at IS NULL AND revoked_at IS NULL",
        (now.astimezone(UTC).isoformat(), resident_id, row["invitation_id"]),
    )
    if changed.rowcount != 1:
        _fail(409, "invitation_used", "Convite já utilizado")
    saved = conn.execute(
        "SELECT id, household_id, role, room_id, starts_on, ends_on, status,"
        " presence_opt_in FROM membership WHERE id=?", (row["membership_id"],)
    ).fetchone()
    return MembershipSelfView(
        **{**dict(saved), "presence_opt_in": bool(saved["presence_opt_in"])}
    )


def revoke_membership(conn: sqlite3.Connection, user: User, house: UUID,
                      membership_id: UUID, now: datetime) -> MemberView:
    actor = _landlord(conn, user, house, now)
    row = conn.execute(
        "SELECT m.*, r.display_name FROM membership m"
        " JOIN resident r ON r.id=m.resident_id"
        " WHERE m.id=? AND m.household_id=?",
        (str(membership_id), str(house)),
    ).fetchone()
    if row is None:
        _fail(404, "household_not_found", "Não encontrado")
    if row["role"] != MembershipRole.tenant.value or row["id"] == actor:
        _fail(403, "forbidden_role", "Sem permissão")
    if row["status"] == MembershipStatus.ended.value:
        _fail(409, "membership_conflict", "Contrato já terminado")
    timezone = conn.execute(
        "SELECT timezone FROM household WHERE id=?", (str(house),)
    ).fetchone()["timezone"]
    today = now.astimezone(ZoneInfo(timezone)).date().isoformat()
    end = max(row["starts_on"], today)
    if row["ends_on"] is not None:
        end = min(end, row["ends_on"])
    repo.end_membership(conn, membership_id, date.fromisoformat(end))
    conn.execute(
        "UPDATE membership_invitation SET revoked_at=? WHERE membership_id=?"
        " AND redeemed_at IS NULL AND revoked_at IS NULL",
        (now.astimezone(UTC).isoformat(), str(membership_id)),
    )
    saved = conn.execute(
        "SELECT m.id AS membership_id, m.resident_id, r.display_name, m.role,"
        " m.room_id, m.starts_on, m.ends_on, m.status FROM membership m"
        " JOIN resident r ON r.id=m.resident_id WHERE m.id=?", (str(membership_id),)
    ).fetchone()
    return MemberView(**dict(saved))
