from fastapi import APIRouter

from app.api.deps import Actor, Ctr
from app.schemas.actions import Account, LoginRequest, LoginResponse, MeResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/accounts", response_model=list[Account])
def accounts(c: Ctr) -> list[Account]:
    """로그인 화면의 계정 카드(로그인 전 · 인증 없음)."""
    return [Account(**a) for a in c.auth.accounts()]


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, c: Ctr) -> LoginResponse:
    token, expires_at, a = c.auth.login(body.id)
    return LoginResponse(token=token, expiresAt=expires_at, id=a.login_id, role=a.role, name=a.name, staffId=a.staff_id)


@router.get("/me", response_model=MeResponse)
def me(actor: Actor) -> MeResponse:
    return MeResponse(id=actor.login_id, role=actor.role, name=actor.name, staffId=actor.staff_id)
