"""원장 호출 푸시 기기 등록(SPEC-004 §5-1.1) — 세 역할 모두. 발송 대상은 의사 · 관리자(§5-1.2)."""

from fastapi import APIRouter

from app.api.deps import Actor, Ctr
from app.schemas.actions import DeviceRequest, OkResponse

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.post("", response_model=OkResponse)
def register(body: DeviceRequest, c: Ctr, actor: Actor) -> OkResponse:
    """같은 토큰이 다른 계정에 있으면 지금 계정으로 옮긴다 · 같은 계정이면 updated_at 만."""
    with c.repo.tx() as tx:
        tx.put_device(actor.id, body.token.lower(), c.clock.now())
    return OkResponse()


@router.delete("/{token}", response_model=OkResponse)
def unregister(token: str, c: Ctr, actor: Actor) -> OkResponse:
    """자기 계정의 토큰만 지운다 — 남의 것 · 없는 것은 그냥 ok."""
    with c.repo.tx() as tx:
        tx.delete_device(token.lower(), actor.id)
    return OkResponse()
