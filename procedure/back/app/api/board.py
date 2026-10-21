from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import Actor, Ctr
from app.schemas.board import BoardSnapshot

router = APIRouter(prefix="/api/board", tags=["board"])


@router.get("", response_model=BoardSnapshot)
def board(c: Ctr, _: Actor) -> BoardSnapshot:
    return c.snapshot()


@router.get("/stream")
async def stream(c: Ctr, token: str | None = None) -> StreamingResponse:
    """SSE(§7.5) — 인증은 `?token=`(EventSource 는 헤더를 못 싣는다). 틀리면 401."""
    c.auth.verify(token)
    return StreamingResponse(
        c.hub.frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
