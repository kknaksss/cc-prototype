"""SSE — `board` 이벤트 하나 · 본문 = 전체 스냅샷 + version(SPEC-003 §7.5). 연결 목록은 메모리(프로세스 1개)."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable

from app.schemas.board import BoardEvent, BoardSnapshot

RETRY_MS = 3000
PING_SEC = 15.0


def _frame(version: int, data: str) -> str:
    return f"event: board\nid: {version}\ndata: {data}\n\n"


class StreamHub:
    def __init__(self, build: Callable[[], BoardSnapshot]):
        self._build = build
        self.version = 0
        self.last_publish = time.monotonic()
        self._queues: set[asyncio.Queue[str]] = set()

    @property
    def connections(self) -> int:
        return len(self._queues)

    def event(self) -> BoardEvent:
        return BoardEvent(**self._build().model_dump(), version=self.version)

    def publish(self) -> int:
        """지금 상태를 모든 연결에 보낸다. 연결이 없어도 version 은 는다."""
        self.version += 1
        self.last_publish = time.monotonic()
        if self._queues:
            frame = _frame(self.version, self.event().model_dump_json())
            for q in self._queues:
                q.put_nowait(frame)
        return self.version

    async def frames(self, ping_sec: float = PING_SEC) -> AsyncIterator[str]:
        """연결 하나의 흐름 — 첫 프레임은 retry + 지금 전체 스냅샷, 그 뒤 발행마다 1개 · 유휴면 `: ping`."""
        q: asyncio.Queue[str] = asyncio.Queue()
        self._queues.add(q)
        try:
            ev = self.event()
            yield f"retry: {RETRY_MS}\n" + _frame(ev.version, ev.model_dump_json())
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=ping_sec)
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            self._queues.discard(q)
