from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import Actor, Ctr, require_real_board
from app.schemas.actions import BoardOrderRequest, BoardOrderResponse
from app.schemas.board import BoardSnapshot

router = APIRouter(prefix="/api/board", tags=["board"])


@router.get("", response_model=BoardSnapshot)
def board(c: Ctr, _: Actor) -> BoardSnapshot:
    return c.snapshot()


@router.put("/order", response_model=BoardOrderResponse, dependencies=[Depends(require_real_board)])
async def board_order(body: BoardOrderRequest, c: Ctr, actor: Actor) -> BoardOrderResponse:
    """카드 드래그 순서 저장(SPEC-003 0.4.0 §7.3) — 세 역할 모두 · 응답 뒤 SSE `board` 1개(§7.5 ①)."""
    return BoardOrderResponse(visitIds=c.actions.board_order(actor.login_id, body.visitIds))


@router.get("/stream")
async def stream(c: Ctr, token: str | None = None, deviceId: int | None = None) -> StreamingResponse:  # noqa: N803
    """SSE(§7.5) — 인증은 `?token=`(EventSource 는 헤더를 못 싣는다). 틀리면 401.

    앱은 `deviceId` 를 붙인다(SPEC-004 §7.1) — 그 계정 기기면 last_seen_at · online · `display` 대상 · 아니면 무시.
    """
    actor = c.auth.verify(token)
    device = c.devices.own(actor, deviceId)
    return StreamingResponse(
        c.hub.frames(account_id=actor.id, device_id=device.id if device else None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
