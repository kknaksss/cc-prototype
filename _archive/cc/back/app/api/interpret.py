"""통역 중계 — WS /api/interpret (SPEC-001 §7 · interpret-ws-contract)."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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


@router.websocket("/interpret")
async def interpret(ws: WebSocket) -> None:
    c = ws.app.state.container
    origin = ws.headers.get("origin")
    if origin and origin != c.settings.cc_front_origin:
        await ws.close(code=1008)  # CORS 와 같은 규칙 — front 주소만
        return
    await ws.accept()
    session = InterpretSession(StarletteClient(ws), c.settings.soniox_api_key, c.open_stt, c.open_tts)
    await session.run()
