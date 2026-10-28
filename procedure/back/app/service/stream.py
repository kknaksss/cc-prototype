"""SSE — `board` 이벤트(본문 = 전체 스냅샷 + version · SPEC-003 §7.5) + 앱 다음 판의 `notification` · `display`(SPEC-004 §7.1).

허브는 연결마다 (계정 id, 기기 id?) 를 붙여 둔다(r2). `board` = 모든 연결 · `notification` = 그 계정 연결만 ·
`display` = 그 기기 연결만. 새 두 이벤트엔 `id:` 줄이 없고 version 을 올리지 않는다. 연결 목록은 메모리(프로세스 1개).
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from app.schemas.board import BoardEvent, BoardSnapshot

RETRY_MS = 3000
PING_SEC = 15.0


def _frame(version: int, data: str) -> str:
    return f"event: board\nid: {version}\ndata: {data}\n\n"


def _plain(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass(eq=False)
class _Conn:
    account_id: int | None
    device_id: int | None
    q: asyncio.Queue[str] = field(default_factory=asyncio.Queue)


class StreamHub:
    def __init__(self, build: Callable[[], BoardSnapshot]):
        self._build = build
        self.version = 0
        self.last_publish = time.monotonic()
        self._conns: set[_Conn] = set()

    @property
    def connections(self) -> int:
        return len(self._conns)

    def event(self) -> BoardEvent:
        return BoardEvent(**self._build().model_dump(), version=self.version)

    def publish(self) -> int:
        """지금 상태를 모든 연결에 보낸다. 연결이 없어도 version 은 는다."""
        self.version += 1
        self.last_publish = time.monotonic()
        if self._conns:
            frame = _frame(self.version, self.event().model_dump_json())
            for c in self._conns:
                c.q.put_nowait(frame)
        return self.version

    def send_to_account(self, account_id: int, event: str, data: dict[str, Any]) -> int:
        """그 계정 연결에만(`notification`) — version 그대로. 보낸 연결 수."""
        return self._send([c for c in self._conns if c.account_id == account_id], event, data)

    def send_to_device(self, device_id: int, event: str, data: dict[str, Any]) -> int:
        """그 기기로 연 연결에만(`display`) — 같은 계정 다른 기기 · 웹 연결은 받지 않는다."""
        return self._send([c for c in self._conns if c.device_id == device_id], event, data)

    def online(self, device_id: int) -> bool:
        return any(c.device_id == device_id for c in self._conns)

    @staticmethod
    def _send(conns: list[_Conn], event: str, data: dict[str, Any]) -> int:
        frame = _plain(event, data)
        for c in conns:
            c.q.put_nowait(frame)
        return len(conns)

    async def frames(self, ping_sec: float = PING_SEC, *, account_id: int | None = None,
                     device_id: int | None = None) -> AsyncIterator[str]:
        """연결 하나의 흐름 — 첫 프레임은 retry + 지금 전체 스냅샷, 그 뒤 발행마다 1개 · 유휴면 `: ping`."""
        conn = _Conn(account_id, device_id)
        self._conns.add(conn)
        try:
            ev = self.event()
            yield f"retry: {RETRY_MS}\n" + _frame(ev.version, ev.model_dump_json())
            while True:
                try:
                    yield await asyncio.wait_for(conn.q.get(), timeout=ping_sec)
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            self._conns.discard(conn)
