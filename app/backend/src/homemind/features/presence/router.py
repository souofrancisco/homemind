"""Presença (P2). IMPLEMENTADO: estado da câmara (PRES-01). PLANEADO: o resto (PRES-02…06)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from homemind.contracts.household import MembershipRole
from homemind.contracts.presence import CameraStatus
from homemind.core.access import ClockDep, DbDep, find_membership
from homemind.core.config import get_settings
from homemind.features.auth.service import CurrentUser
from homemind.features.presence.camera import CameraProbe, resolve_kind
from homemind.features.video import service as video

router = APIRouter(prefix="/api/presence", tags=["presence"])

_probe = CameraProbe()


async def require_operator(user: CurrentUser, db: DbDep, clock: ClockDep) -> None:
    """A rota não tem casa no caminho: exige papel `operator` numa membership ativa. Senhorio,
    inquilino ou sem membership recebem 403 (nunca se revela o que existe)."""
    now = clock()

    def query(conn) -> bool:
        casas = conn.execute(
            "SELECT DISTINCT m.household_id FROM membership m JOIN resident r"
            " ON r.id = m.resident_id WHERE r.auth_subject = ? AND m.role = ?",
            (user.sub, MembershipRole.operator.value),
        ).fetchall()
        for (casa,) in casas:
            row = find_membership(conn, user.sub, UUID(casa), now)
            if row is not None and row["role"] == MembershipRole.operator.value:
                return True
        return False

    if not await db.run(query):
        raise HTTPException(403, {"code": "forbidden_role", "message": "Sem permissão"})


@router.get("/camera/status", dependencies=[Depends(require_operator)])
async def camera_status() -> CameraStatus:
    """Diagnóstico da câmara da porta: fonte, origem (real/simulada), vida e FPS. Sem imagem
    nem URL. Fonte em falha ou ausente: `camera_ok=false`, nunca «casa vazia»."""
    return _probe.status(video.fonte_atual(), resolve_kind(get_settings()))
