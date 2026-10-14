"""SSE — GET /api/events. 변경마다 `event: state` `data: {"version": n}` (D-29)."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.deps import Ctr
from app.container import Container

router = APIRouter(prefix="/api", tags=["events"])
HEARTBEAT_SEC = 15.0


def sse(version: int) -> str:
    return f"event: state\ndata: {json.dumps({'version': version})}\n\n"


async def event_stream(c: Container, request: Request | None = None, heartbeat: float = HEARTBEAT_SEC
                       ) -> AsyncIterator[str]:
    q = c.bus.subscribe()
    try:
        yield sse(c.board.version())  # 붙자마자 지금 version 한 번
        while True:
            if request is not None and await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(q.get(), timeout=heartbeat)
                yield sse(msg["version"])
            except TimeoutError:
                yield ": ping\n\n"
    finally:
        c.bus.unsubscribe(q)


@router.get("/events")
async def events(request: Request, c: Ctr) -> StreamingResponse:
    return StreamingResponse(
        event_stream(c, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
