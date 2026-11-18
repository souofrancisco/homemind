"""Assinaturas (ENERGY-01): ver e travar o padrão; desfazer amostras (ENERGY-04).

URLs finais: `/api/households/{household_id}/energy/signatures[...]` e
`.../energy/identifications/{request_id}/revoke` (o prefixo vem do router). Desfazer só revoga
amostras e recalcula a assinatura a partir das restantes: leituras, consumos e eventos ficam
intactos. Escrever exige as mesmas regras do PATCH (dono, ou autor de um aparelho comum).
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from homemind.contracts.appliance_catalog import ApplianceCatalog
from homemind.contracts.common import ContractModel, UtcDatetime, stable_id
from homemind.contracts.devices import SignatureOrigin, SignaturePattern
from homemind.core.access import (
    ClockDep,
    DbDep,
    Grant,
    HouseholdAccess,
    Operation,
    Resource,
    require_access,
)
from homemind.features.energy.learning_consumer import stamp, store_signature

signatures_router = APIRouter()
Read = Annotated[HouseholdAccess, Depends(require_access(Resource.appliance))]
Write = Annotated[HouseholdAccess, Depends(require_access(Resource.appliance, Operation.write))]


class SignaturePatch(ContractModel):
    model_config = ContractModel.model_config | {"extra": "forbid"}
    pattern: SignaturePattern


class SignatureDiagnosticView(ContractModel):
    appliance_id: UUID
    watts_mean: float
    watts_tolerance: float
    duration_typical_s: int | None
    pattern: SignaturePattern
    pattern_locked: bool
    samples: int
    origin: SignatureOrigin
    updated_at: UtcDatetime


class SignatureView(SignatureDiagnosticView):
    typical_hours: list[int] | None


Visible = SignatureView | SignatureDiagnosticView


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _rows(conn: sqlite3.Connection, access: HouseholdAccess) -> list[sqlite3.Row]:
    # Match HOUSE-03 current visibility: diagnostic, common, or caller's ownership.
    return conn.execute(
        "SELECT sig.*,a.registered_by_resident_id,s.scope,s.owner_resident_id,"
        " lock.pattern AS locked_pattern FROM appliance_signature sig"
        " JOIN appliance a ON a.id=sig.appliance_id"
        " JOIN appliance_state s ON s.id=(SELECT latest.id FROM appliance_state latest"
        " WHERE latest.appliance_id=a.id ORDER BY latest.valid_from DESC,latest.id DESC LIMIT 1)"
        " LEFT JOIN energy_signature_lock lock ON lock.signature_id=sig.id"
        " WHERE a.household_id=? AND a.status='active'"
        " AND (? OR s.scope='common' OR s.owner_resident_id=?) ORDER BY a.id,sig.id",
        (str(access.household_id), access.grant is Grant.diagnostic, str(access.resident_id)),
    ).fetchall()


def _view(row: sqlite3.Row, access: HouseholdAccess) -> Visible:
    data = {
        name: row[name]
        for name in SignatureDiagnosticView.model_fields
        if name not in {"pattern_locked", "pattern"}
    }
    data["pattern"] = row["locked_pattern"] or row["pattern"]
    data["pattern_locked"] = row["locked_pattern"] is not None
    if access.grant is Grant.diagnostic:
        return SignatureDiagnosticView(**data)
    return SignatureView(
        **data,
        typical_hours=json.loads(row["typical_hours_json"])
        if row["typical_hours_json"] is not None
        else None,
    )


async def _run(db, fn):
    try:
        return await db.run(fn)
    except sqlite3.IntegrityError:
        raise _error(409, "signature_conflict", "Conflito ao guardar assinatura") from None
    except ValidationError:
        raise _error(422, "invalid_request", "Dados da assinatura inválidos") from None


@signatures_router.get("/signatures")
async def list_signatures(access: Read, db: DbDep) -> list[Visible]:
    return await _run(db, lambda conn: [_view(r, access) for r in _rows(conn, access)])


@signatures_router.patch("/signatures/{appliance_id}")
async def patch_signature(
    appliance_id: UUID,
    body: SignaturePatch,
    access: Write,
    db: DbDep,
    clock: ClockDep,
) -> Visible:
    def operation(conn):
        sid = str(stable_id("energy.signature", str(appliance_id)))
        row = next(
            (
                r
                for r in _rows(conn, access)
                if r["appliance_id"] == str(appliance_id) and r["id"] == sid
            ),
            None,
        )
        if row is None:
            raise _error(404, "signature_not_found", "Assinatura não encontrada")
        if access.grant is not Grant.own or not (
            row["owner_resident_id"] == str(access.resident_id)
            or (
                row["scope"] == "common"
                and row["registered_by_resident_id"] == str(access.resident_id)
            )
        ):
            raise _error(403, "forbidden_role", "Sem permissão para corrigir este aparelho")
        conn.execute(
            "UPDATE appliance_signature SET pattern=? WHERE id=?", (body.pattern.value, sid)
        )
        conn.execute(
            "INSERT INTO energy_signature_lock(signature_id,pattern,locked_at) VALUES (?,?,?)"
            " ON CONFLICT(signature_id) DO UPDATE SET"
            " pattern=excluded.pattern,locked_at=excluded.locked_at",
            (sid, body.pattern.value, clock().astimezone(UTC).isoformat(timespec="microseconds")),
        )
        return _view(next(r for r in _rows(conn, access) if r["id"] == sid), access)

    return await _run(db, operation)


# --- ENERGY-04: histórico de amostras e desfazer -------------------------------------------------


class SignatureSampleView(ContractModel):
    """Uma amostra (uma sessão) que conta ou contou para a assinatura. Só para moradores."""

    id: UUID
    appliance_id: UUID
    power_w: float
    duration_s: float
    pattern: SignaturePattern
    hour_local: int
    origin_kind: Literal["confirmation", "learning"]
    identification_id: UUID | None  # pedido «O que é este aparelho?» que a originou
    created_at: UtcDatetime
    revoked_at: UtcDatetime | None


class SignatureRevocationView(ContractModel):
    appliance_id: UUID
    revoked_samples: int
    signature: SignatureView | None  # None: sem amostras, a assinatura deixou de existir


def _appliance(conn: sqlite3.Connection, access: HouseholdAccess, appliance_id: str):
    """Aparelho ativo visível ao morador (comum ou dele); `None` = 404."""
    return conn.execute(
        "SELECT a.id,a.registered_by_resident_id,s.scope,s.owner_resident_id FROM appliance a"
        " JOIN appliance_state s ON s.id=(SELECT latest.id FROM appliance_state latest"
        " WHERE latest.appliance_id=a.id ORDER BY latest.valid_from DESC,latest.id DESC LIMIT 1)"
        " WHERE a.id=? AND a.household_id=? AND a.status='active'"
        " AND (? OR s.scope='common' OR s.owner_resident_id=?)",
        (
            appliance_id,
            str(access.household_id),
            access.grant is Grant.diagnostic,
            str(access.resident_id),
        ),
    ).fetchone()


def _can_correct(row: sqlite3.Row, access: HouseholdAccess) -> bool:
    """As regras de escrita do PATCH: dono, ou quem registou um aparelho comum."""
    return access.grant is Grant.own and (
        row["owner_resident_id"] == str(access.resident_id)
        or (
            row["scope"] == "common" and row["registered_by_resident_id"] == str(access.resident_id)
        )
    )


def _catalog(request: Request) -> ApplianceCatalog:
    # Publicado por `appliances` em app.state (sem importar a feature).
    catalog = getattr(request.app.state, "appliance_catalog", None)
    if catalog is None:
        raise _error(503, "catalog_unavailable", "Catálogo de aparelhos indisponível")
    return catalog


def _recalculate(
    conn: sqlite3.Connection,
    catalog: ApplianceCatalog,
    access: HouseholdAccess,
    appliance_id: UUID,
    revoked: int,
    now: datetime,
) -> SignatureRevocationView:
    sid = str(stable_id("energy.signature", str(appliance_id)))
    current = conn.execute(
        "SELECT updated_at FROM appliance_signature WHERE id=?", (sid,)
    ).fetchone()
    # `updated_at` sobe sempre: o catálogo só aceita gravar uma versão mais recente.
    at = now.astimezone(UTC)
    if current is not None:
        at = max(at, datetime.fromisoformat(current["updated_at"]) + timedelta(microseconds=1))
    signature = store_signature(conn, catalog, access.household_id, appliance_id, [], updated_at=at)
    row = (
        next((r for r in _rows(conn, access) if r["id"] == sid), None)
        if signature is not None
        else None
    )
    return SignatureRevocationView(
        appliance_id=appliance_id,
        revoked_samples=revoked,
        signature=_view(row, access) if row is not None else None,
    )


@signatures_router.get("/signatures/{appliance_id}/samples")
async def list_signature_samples(
    appliance_id: UUID, access: Read, db: DbDep
) -> list[SignatureSampleView]:
    """Histórico de amostras (com as revogadas). Horas e datas são hábitos: só moradores."""
    if access.grant is not Grant.own:
        raise _error(403, "forbidden_role", "Só para moradores")

    def operation(conn):
        if _appliance(conn, access, str(appliance_id)) is None:
            raise _error(404, "signature_not_found", "Assinatura não encontrada")
        rows = conn.execute(
            "SELECT * FROM energy_signature_sample WHERE appliance_id=? ORDER BY created_at,id",
            (str(appliance_id),),
        ).fetchall()
        return [
            SignatureSampleView(**{name: r[name] for name in SignatureSampleView.model_fields})
            for r in rows
        ]

    return await _run(db, operation)


@signatures_router.post("/signatures/{appliance_id}/samples/{sample_id}/revoke")
async def revoke_signature_sample(
    appliance_id: UUID,
    sample_id: UUID,
    access: Write,
    db: DbDep,
    clock: ClockDep,
    request: Request,
) -> SignatureRevocationView:
    """Desfaz uma amostra: deixa de contar e a assinatura recalcula-se a partir das outras."""
    catalog = _catalog(request)

    def operation(conn):
        row = _appliance(conn, access, str(appliance_id))
        sample = conn.execute(
            "SELECT revoked_at FROM energy_signature_sample WHERE id=? AND appliance_id=?",
            (str(sample_id), str(appliance_id)),
        ).fetchone()
        if row is None or sample is None:
            raise _error(404, "sample_not_found", "Amostra não encontrada")
        if not _can_correct(row, access):
            raise _error(403, "forbidden_role", "Sem permissão para corrigir este aparelho")
        if sample["revoked_at"] is not None:
            raise _error(409, "already_revoked", "Amostra já desfeita")
        now = clock()
        conn.execute(
            "UPDATE energy_signature_sample SET revoked_at=? WHERE id=?",
            (stamp(now), str(sample_id)),
        )
        return _recalculate(conn, catalog, access, appliance_id, 1, now)

    return await _run(db, operation)


@signatures_router.post("/identifications/{request_id}/revoke")
async def revoke_identification(
    request_id: UUID,
    access: Write,
    db: DbDep,
    clock: ClockDep,
    request: Request,
) -> SignatureRevocationView:
    """Desfaz a resposta a «O que é este aparelho?»: revoga as amostras dessa confirmação e
    recalcula. O aparelho criado mantém-se (renomeia-se ou retira-se pela API de aparelhos) e
    o grupo volta a poder perguntar."""
    catalog = _catalog(request)

    def operation(conn):
        req = conn.execute(
            "SELECT * FROM energy_identification_request WHERE id=? AND household_id=?",
            (str(request_id), str(access.household_id)),
        ).fetchone()
        row = (
            _appliance(conn, access, req["appliance_id"])
            if req is not None and req["appliance_id"] is not None
            else None
        )
        if row is None:
            raise _error(404, "identification_not_found", "Identificação não encontrada")
        if not _can_correct(row, access):
            raise _error(403, "forbidden_role", "Sem permissão para corrigir este aparelho")
        if req["status"] != "answered":
            raise _error(409, "already_revoked", "Identificação já desfeita")
        now = clock()
        revoked = conn.execute(
            "UPDATE energy_signature_sample SET revoked_at=?"
            " WHERE identification_id=? AND revoked_at IS NULL",
            (stamp(now), str(request_id)),
        ).rowcount
        conn.execute(
            "UPDATE energy_identification_request SET status='revoked',revoked_at=? WHERE id=?",
            (stamp(now), str(request_id)),
        )
        conn.execute(
            "UPDATE energy_identification_group SET status='open',appliance_id=NULL"
            " WHERE id=? AND appliance_id=?",
            (req["group_id"], req["appliance_id"]),
        )
        return _recalculate(conn, catalog, access, UUID(req["appliance_id"]), revoked, now)

    return await _run(db, operation)
