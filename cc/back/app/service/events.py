"""SSE 알림 — 변경마다 {"version": n} 을 구독자 모두에게(D-29). 어느 스레드에서 불러도 된다."""

import asyncio
import threading


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [(lp, x) for lp, x in self._subs if x is not q]

    def publish(self, version: int) -> None:
        payload = {"version": version}
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, payload)
            except RuntimeError:  # 닫힌 루프
                self.unsubscribe(q)

    @property
    def count(self) -> int:
        return len(self._subs)
