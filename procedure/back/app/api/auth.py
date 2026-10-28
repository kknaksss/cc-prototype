from fastapi import APIRouter

from app.api.deps import Actor, Ctr
from app.schemas.actions import LoginRequest, LoginResponse, MeResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, c: Ctr) -> LoginResponse:
    token, expires_at, a = c.auth.login(body.id, body.password)
    return LoginResponse(token=token, expiresAt=expires_at, id=a.login_id, role=a.role, name=a.name, staffId=a.staff_id)


@router.get("/me", response_model=MeResponse)
def me(actor: Actor) -> MeResponse:
    return MeResponse(id=actor.login_id, role=actor.role, name=actor.name, staffId=actor.staff_id)

