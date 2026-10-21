"""통역 중계 — WS /api/interpret(SPEC-004 §4 · 이전 PoC interpret-ws-contract 그대로).

`cc/back` 에서 복사(import 아님) · 인증만 바꿨다(§4.2): Origin 만으로는 안 된다(앱은 Origin 을 안 보낸다).
- 토큰: 핸드셰이크 헤더 `Authorization: Bearer <ccc 토큰>`(앱) 또는 `?token=`(브라우저 · 접근 로그는 쿼리를 지운다)
- `accept()` 전에 검증 — 실패면 accept 하지 않고 1008 로 닫는다(클라이언트에는 핸드셰이크 거절 403)
- Origin 이 있으면 PROC_INTERPRET_ORIGIN(비면 PROC_FRONT_ORIGIN)과 같아야. 없으면(앱) 토큰만으로
- 역할은 세 역할 모두
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.domain.errors import DomainError
from app.service.interpret.session import InterpretSession

router = APIRouter(prefix="/api", tags=["interpret"])


class StarletteClient:
    def __init__(self, ws: WebSocket):
        self.ws = ws

    async def receive(self):
        try:
            msg = await self.ws.receive()
        except WebSocketDisconnect:
            return "close", None
        if msg["type"] == "websocket.disconnect":
            return "close", None
        if msg.get("bytes") is not None:
            return "bytes", msg["bytes"]
        return "text", msg.get("text")

    async def send_json(self, data: dict) -> None:
        await self.ws.send_json(data)

    async def send_bytes(self, data: bytes) -> None:
        await self.ws.send_bytes(data)

    async def close(self, code: int = 1000) -> None:
        await self.ws.close(code)


def _token(ws: WebSocket) -> str | None:
    header = ws.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:]
    return ws.query_params.get("token")


@router.websocket("/interpret")
async def interpret(ws: WebSocket) -> None:
    c = ws.app.state.container
    s = c.settings
    origin = ws.headers.get("origin")
    if origin and origin != (s.proc_interpret_origin or s.proc_front_origin):
        await ws.close(code=1008)  # 브라우저는 허용 출처만
        return
    try:
        c.auth.verify(_token(ws))
    except DomainError:
        await ws.close(code=1008)  # accept 전 — 토큰 없음 · 틀림 · 만료 · 비활성
        return
    await ws.accept()
    session = InterpretSession(StarletteClient(ws), s.soniox_api_key, c.open_stt, c.open_tts)
    await session.run()
