from fastapi import APIRouter

from homemind.core.auth import CurrentUser, User

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
def me(user: CurrentUser) -> User:
    return user
