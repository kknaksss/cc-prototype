"""푸시 기기 등록(SPEC-004 §5-1.1) — 다섯 역할 모두. 응답 deviceId = 앱이 띄우기 · SSE 에서 자기 기기를 알아보는 id."""

from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import Actor, Ctr
from app.api.docs import INVALID, T_DEVICE, UNAUTHORIZED, errors
from app.schemas.actions import DeviceRequest, DeviceResponse, OkResponse

router = APIRouter(prefix="/api/devices", tags=[T_DEVICE])


@router.post(
    "", response_model=DeviceResponse,
    summary="푸시 기기 등록 — APNs 토큰 · 이름 · 종류",
    description="""
앱이 받은 APNs 기기 토큰을 지금 로그인 계정에 붙인다. 다섯 역할 모두 부를 수 있다. 응답 `deviceId` 는 SSE `?deviceId=` ·
띄우기 요청 · 여권 스캔에서 이 기기를 가리킬 때 쓴다.

- 토큰은 소문자로 바꿔 저장한다. 행을 찾는 순서: ① 같은 `installId` 행(있으면 그 행에 새 토큰 · 계정을 넣어 deviceId 유지 ·
  새 토큰을 가진 다른 행은 지움) → ② 같은 토큰 행(다른 계정 것이어도 지금 계정으로 옮김) → ③ 없으면 새 행.
- `name` · `kind` · `installId` 는 보낸 것만 고친다(생략 = 기존 값). 처음 오는 기기인데 이름이 없으면
  「iPhone」/「iPad」(kind=tablet).
- 그 기기의 `lastSeenAt` = 지금. 반복 호출 = 같은 행을 고친다(같은 deviceId · 멱등).
- KOS 쓰기 · SSE · 푸시 없음.
""",
    responses=errors(INVALID, UNAUTHORIZED),
)
def register(body: DeviceRequest, c: Ctr, actor: Actor) -> DeviceResponse:
    """같은 토큰이 다른 계정에 있으면 지금 계정으로 옮긴다 · 같은 계정이면 이름 · 종류 · 시각만."""
    return DeviceResponse(deviceId=c.devices.register(actor, body.token, body.name, body.kind, body.installId))


@router.delete(
    "/{token}", response_model=OkResponse,
    summary="푸시 기기 지우기 — 로그아웃 때",
    description="""
그 토큰(대소문자 무시)이 **지금 계정의 기기**면 기기 행을 지운다. 남의 계정 토큰 · 없는 토큰은 아무것도 하지 않고 그대로
`{"ok": true}`(멱등). 다섯 역할 모두. KOS 쓰기 · SSE · 푸시 없음.
""",
    responses=errors(UNAUTHORIZED),
)
def unregister(token: Annotated[str, Path(description="APNs 기기 토큰(등록 때 보낸 값 · 대소문자 무시)")],
               c: Ctr, actor: Actor) -> OkResponse:
    """자기 계정의 토큰만 지운다 — 남의 것 · 없는 것은 그냥 ok."""
    c.devices.unregister(actor, token)
    return OkResponse()
