from fastapi import APIRouter

from app.api.deps import Actor, Ctr
from app.schemas.actions import LoginRequest, LoginResponse, MeResponse, OkResponse, UnlockRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, c: Ctr) -> LoginResponse:
    token, expires_at, a = c.auth.login(body.id, body.password)
    return LoginResponse(token=token, expiresAt=expires_at, id=a.login_id, role=a.role, name=a.name, staffId=a.staff_id)


@router.get("/me", response_model=MeResponse)
def me(actor: Actor) -> MeResponse:
    return MeResponse(id=actor.login_id, role=actor.role, name=actor.name, staffId=actor.staff_id)


@router.post("/unlock", response_model=OkResponse)
def unlock(body: UnlockRequest, c: Ctr, actor: Actor) -> OkResponse:
    """문진 잠금 나가기(SPEC-004 §3.3 · §6.15) — 남의 계정 · 없는 deviceId = 404 device_not_found 먼저."""
    device = c.devices.check(actor, body.deviceId)
    c.auth.unlock(actor, body.password, device.id if device else None)
    return OkResponse()
