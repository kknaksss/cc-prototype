"""KOS 루프 — 서버 시작: 토큰 2종 → 직원 · 방 1회 → 조회 루프 · 반영 루프(SPEC-003 §2.2).

- 일정 루프(KOS_POLL_SCHEDULE_SEC): 조회 시간 안이면 일정 조회 · 확인 → 그 뒤 시간과 상관없이 대기 op 보내기(재전송 포함)
- 직원 · 방 루프(KOS_POLL_MASTER_SEC)
- 반영 루프: 조작 직후 `kick()` 으로 깨어 새 op 을 바로 보낸다
- 바뀐 뒤마다 `on_change()`(SSE 발행)
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable

from app.config import Settings
from app.domain.clock import Clock
from app.kos.client import KosClient, KosError
from app.kos.ops import OpSender
from app.kos.reservation_sync import ReservationSync
from app.kos.sync import KosSync
from app.repository.repo import Repository

log = logging.getLogger("procedure.kos")

QUICK_SYNC_SEC = 1.5  # 보낸 뒤 확인용 일정 조회까지


class KosRuntime:
    def __init__(self, settings: Settings, repo: Repository, clock: Clock, on_change: Callable[[], None],
                 client: KosClient | None = None):
        self.s = settings
        self.client = client or KosClient(settings, repo, clock)
        self.sync = KosSync(settings, repo, self.client, clock)
        self.sender = OpSender(repo, self.client, clock)
        self.resv = ReservationSync(settings, repo, self.client, clock)  # 예약 현황(SPEC-005 §4.2)
        self.on_change = on_change
        self.on_staff: Callable[[], None] = lambda: None  # 직원 · 방 조회 뒤 — 계정(doctor) 맞추기(SPEC-004 §3.1)
        self._kick = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self._quick: asyncio.Task | None = None

    def kick(self) -> None:
        self._kick.set()

    async def startup(self) -> None:
        for name, get in (("open", self.client.open_token), ("internal", self.client.internal_token)):
            try:
                await get()
            except Exception as e:
                log.warning("KOS %s 토큰 실패: %s", name, e if isinstance(e, KosError) else type(e).__name__)
        await self.master_once(force=True)  # 서버 시작 1회는 조회 시간과 상관없이(리뷰 W8)

    async def master_once(self, force: bool = False) -> None:
        async with self._lock:
            if await self.sync.sync_master(force=force):
                self.on_staff()
                self.on_change()
        # 예약 목록(구역 · 그룹 · 다른 구역 방 · 유입 · 기타 작업) — 조회 시간과 상관없이 같은 주기(SPEC-005 §4.2)
        try:
            await self.resv.master()
        except Exception as e:
            log.error("KOS 예약 목록 오류: %s", type(e).__name__)

    async def tick(self) -> dict | None:
        """일정 조회 1번 + 대기 op 보내기 1번."""
        async with self._lock:
            result = await self.sync.sync_schedules()
            sent = await self.sender.send_heads()
        if result is not None or any(sent.values()):
            self.on_change()
        return result

    async def flush(self) -> None:
        """조작 직후 — 새 op 을 바로 보내고, 보낸 게 있으면 QUICK_SYNC_SEC 뒤 일정 조회 1회로 확인을 빨리 찍는다(E2E-6)."""
        async with self._lock:
            sent = await self.sender.send_heads(fresh_only=True)
        if any(sent.values()):
            self.on_change()
        if sent["sent"] and (self._quick is None or self._quick.done()):
            self._quick = asyncio.create_task(self._quick_sync())
            self._tasks.append(self._quick)

    async def _quick_sync(self) -> None:
        await asyncio.sleep(QUICK_SYNC_SEC)
        try:
            await self.tick()
        except Exception as e:
            log.error("KOS 빠른 확인 오류: %s", type(e).__name__)

    async def _every(self, sec: float, fn: Callable) -> None:
        while True:
            try:
                await fn()
            except Exception as e:  # 루프는 죽지 않는다 · 로그는 클래스만(본문 · 토큰 X)
                log.error("KOS 루프 오류: %s", type(e).__name__)
            await asyncio.sleep(sec)

    async def _sender_loop(self) -> None:
        while True:
            await self._kick.wait()
            self._kick.clear()
            try:
                await self.flush()
            except Exception as e:
                log.error("KOS 반영 루프 오류: %s", type(e).__name__)

    async def _master_loop(self) -> None:
        await asyncio.sleep(self.s.kos_poll_master_sec)
        await self._every(self.s.kos_poll_master_sec, self.master_once)

    def start(self) -> None:
        async def boot() -> None:
            try:
                await self.startup()
            except Exception as e:
                log.error("KOS 시작 오류: %s", type(e).__name__)
            self._tasks.append(asyncio.create_task(self._every(self.s.kos_poll_schedule_sec, self.tick)))
            self._tasks.append(asyncio.create_task(self._master_loop()))
            self._tasks.append(asyncio.create_task(self._sender_loop()))

        self._tasks.append(asyncio.create_task(boot()))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        await self.client.aclose()
