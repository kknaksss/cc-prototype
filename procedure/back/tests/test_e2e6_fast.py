"""E2E-6 — 조작 직후 바로 보내고 · 앞 op 이 2xx 면 이어서 · 보낸 뒤 곧바로 확인 조회 1회."""

import asyncio
import time

from app.domain.models import KosOp
from app.kos import runtime as rt
from app.kos.ops import superseded
from tests.test_kos_sync import env, run  # noqa: F401 — fixture 재사용


def boot(c):
    run(c.kos.startup())
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    return card.visitId, [p.id for p in card.procedures if p.kind == "procedure"]


def states(c):
    with c.repo.tx() as tx:
        return [(o.path.rsplit("/", 1)[-1], o.status) for o in tx.ops()]


def test_click_to_kos_and_confirm_fast(env, monkeypatch):  # noqa: F811
    c, fake = env
    vid, (p1, _) = boot(c)
    monkeypatch.setattr(rt, "QUICK_SYNC_SEC", 0.05)
    c.kos._kick = asyncio.Event()
    published = []
    c.kos.on_change = lambda: published.append(time.monotonic())

    async def go():
        loop = asyncio.create_task(c.kos._sender_loop())
        t0 = time.monotonic()
        c.actions.create_call("t", vid, [p1], "all", None)  # on_change → kick
        c.kos.kick()
        while fake.schedules[0]["tasks"][0]["status"] != "WAITING":
            await asyncio.sleep(0.005)
        reflected = time.monotonic() - t0
        while not all(s == "confirmed" for _, s in states(c)):
            await asyncio.sleep(0.01)
        confirmed = time.monotonic() - t0
        loop.cancel()
        return reflected, confirmed

    reflected, confirmed = run(go())
    # 방 → 담당자 → 호출 3개가 조회 주기(10초)를 기다리지 않고 한 번에 KOS 에 닿고, 확인도 QUICK_SYNC_SEC 뒤 바로
    assert reflected < 0.5 and confirmed < 1.0
    assert [n for n, _ in states(c)] == ["change-tasks-room", "change-tasks-assignees", "call-tasks-doctors"]
    assert published  # 확인 뒤 SSE 발행


def test_error_stops_chain_in_visit(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = boot(c)
    fake.fail_paths = {"change-tasks-room": 500}
    c.actions.create_call("t", vid, [p1], "all", None)
    run(c.kos.flush())
    assert states(c) == [("change-tasks-room", "pending"), ("change-tasks-assignees", "pending"),
                         ("call-tasks-doctors", "pending")]
    assert "change-tasks-assignees" not in fake.paths()


def op(seq, status, expect):
    return KosOp(seq, None, 1, seq, "internal", "p", {}, expect, status, 0, 0, None)


def test_superseded_rule():
    flow1 = op(1, "sent", {"flowStep": "PROCEDURE"})
    flow2 = op(2, "sent", {"flowStep": "PROCEDURE_DONE"})
    call = op(3, "sent", {"tasks": [1, 2], "status": "WAITING"})
    accept_other = op(4, "sent", {"tasks": [3], "status": "READY"})
    accept_same = op(5, "pending", {"tasks": [2], "status": "READY"})
    assert superseded(flow1, [flow1, flow2])
    assert not superseded(flow2, [flow1, flow2])
    assert not superseded(call, [call, accept_other])  # 다른 작업
    assert not superseded(call, [call, accept_same])  # 아직 안 보냄
    accept_same.status = "sent"
    assert superseded(call, [call, accept_same])
