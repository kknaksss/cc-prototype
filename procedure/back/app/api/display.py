"""띄우기 요청(SPEC-004 §5-3) — 다섯 역할 모두. pending · claim 은 부른 기기 · 계정 것만(남의 기기 = 404 device_not_found)."""

from fastapi import APIRouter

from app.api.deps import Actor, Ctr
from app.schemas.actions import (
    ClaimDisplayRequest,
    CloseDisplayRequest,
    CreateDisplayRequest,
    CreateDisplayResponse,
    DisplayPending,
    DisplayRequestItem,
    DisplayTarget,
    OkResponse,
)

router = APIRouter(prefix="/api", tags=["display"])


@router.get("/devices/targets", response_model=list[DisplayTarget])
def targets(c: Ctr, _: Actor) -> list[DisplayTarget]:
    """코디 계정 기기 중 last_seen_at 24시간 안 · 최근 순 · online = 지금 SSE 열림."""
    return [DisplayTarget.model_validate(x) for x in c.display.targets()]


@router.post("/display-requests", response_model=CreateDisplayResponse)
async def create(body: CreateDisplayRequest, c: Ctr, actor: Actor) -> CreateDisplayResponse:
    """async — 띄우기 푸시를 이벤트 루프에 태스크로 띄운다(sync 면 스레드라 루프가 없어 건너뜀 · 리뷰 r1 FAIL-1)."""
    return CreateDisplayResponse.model_validate(c.display.create(actor, body.reservationId, body.kind, body.deviceId))


@router.get("/display-requests/pending", response_model=DisplayPending)
def pending(c: Ctr, actor: Actor, deviceId: int | None = None) -> DisplayPending:  # noqa: N803 — 계약 이름
    """deviceId 필수(없으면 400) — 그 기기 pending(+ 열린 것) · 돌려주며 opened."""
    return DisplayPending.model_validate({"items": c.display.pending(actor, deviceId)})


@router.post("/display-requests/claim", response_model=DisplayRequestItem)
def claim(body: ClaimDisplayRequest, c: Ctr, actor: Actor) -> DisplayRequestItem:
    """QR(ccc://display?t=) — 1회 · 유효 10분 · deviceId 가 있으면 그 기기 요청으로 묶음."""
    return DisplayRequestItem.model_validate(c.display.claim(actor, body.qrToken, body.deviceId))


@router.post("/display-requests/{request_id}/close", response_model=OkResponse)
def close(request_id: int, body: CloseDisplayRequest, c: Ctr, actor: Actor) -> OkResponse:
    c.display.close(actor, request_id, body.status)
    return OkResponse()
