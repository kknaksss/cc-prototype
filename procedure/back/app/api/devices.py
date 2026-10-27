"""푸시 기기 등록(SPEC-004 §5-1.1) — 다섯 역할 모두. 응답 deviceId = 앱이 띄우기 · SSE 에서 자기 기기를 알아보는 id."""

from fastapi import APIRouter

from app.api.deps import Actor, Ctr
from app.schemas.actions import DeviceRequest, DeviceResponse, OkResponse

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.post("", response_model=DeviceResponse)
def register(body: DeviceRequest, c: Ctr, actor: Actor) -> DeviceResponse:
    """같은 토큰이 다른 계정에 있으면 지금 계정으로 옮긴다 · 같은 계정이면 이름 · 종류 · 시각만."""
    return DeviceResponse(deviceId=c.devices.register(actor, body.token, body.name, body.kind))


@router.delete("/{token}", response_model=OkResponse)
def unregister(token: str, c: Ctr, actor: Actor) -> OkResponse:
    """자기 계정의 토큰만 지운다 — 남의 것 · 없는 것은 그냥 ok."""
    c.devices.unregister(actor, token)
    return OkResponse()
