"""예약 현황 시험 환경 — 가짜 KOS(WP-KOS K1 모양) + 컨테이너 + 시계 · 캐시 시계 고정."""

import asyncio
from datetime import UTC, datetime

from app.container import build_container
from app.domain.clock import Clock
from app.domain.models import Account
from app.kos.client import KosClient
from app.kos.runtime import KosRuntime
from tests.fake_kos import FakeKos, kos_settings

T0 = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)  # KST 수요일 11:00
DAY = "2026-10-21"
DESK = Account(0, "desk1", "coordinator", "코디 1", None, True, True)


def run(coro):
    return asyncio.run(coro)


def make_env(tmp_path, **kw):
    fake = FakeKos()
    clock = Clock()
    clock.set(T0)
    s = kos_settings(tmp_path, **kw)
    c = build_container(s, clock)
    c.kos = KosRuntime(s, c.repo, clock, c.hub.publish, client=KosClient(s, c.repo, clock, transport=fake.transport()))
    mono = [1000.0]
    c.kos.resv.mono = lambda: mono[0]
    run(c.kos.startup())
    return c, fake, mono


def rid_of(c, kos_id: str) -> int:
    with c.repo.tx() as tx:
        return tx.reservation_id_of(kos_id)


def load(c, day: str = DAY):
    """그 날짜 사본을 채운다(캐시 무시)."""
    c.kos.resv.invalidate(day)
    return run(c.resv.board(day))
