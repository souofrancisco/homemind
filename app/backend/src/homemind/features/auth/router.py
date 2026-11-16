from fastapi import APIRouter

from homemind.features.auth.service import CurrentUser, User

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/me")
def me(user: CurrentUser) -> User:
    return user
