"""WP3 — KOS 조회: 토큰 2종 · upsert · 카드 조건 · 덮어쓰기 보호 · 조회 시간 · 원장 목록 제외."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.container import build_container
from app.domain.clock import Clock
from app.kos.runtime import KosRuntime
from tests.fake_kos import SYSTEM, FakeKos, kos_settings, schedule, task

IN = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)  # KST 11:00
OUT = datetime(2026, 10, 21, 12, 30, tzinfo=UTC)  # KST 21:30


@pytest.fixture
def env(tmp_path):
    fake = FakeKos()
    clock = Clock()
    clock.set(IN)
    s = kos_settings(tmp_path)
    c = build_container(s, clock)
    from app.kos.client import KosClient

    c.kos = KosRuntime(s, c.repo, clock, c.hub.publish, client=KosClient(s, c.repo, clock, transport=fake.transport()))
    return c, fake


def run(coro):
    return asyncio.run(coro)


def test_startup_tokens_master_and_doctor_list(env):
    c, fake = env
    run(c.kos.startup())
    assert c.kos_tokens() == (True, True)
    assert c.kos.client.system_kos_id() == SYSTEM
    names = sorted(d.name for d in c.board.snapshot().doctors)
    assert names == ["가 원장", "나 원장"]  # 시스템 · 마취용(env 제외) · 간호사 빠짐
    # 시스템 계정 id = get-user-account(sign-in 의 사용자 id 아님)
    assert fake.paths()[:5] == ["exchange-token", "sign-in", "get-user-account", "get-accounts", "get-rooms"]
    # 공개 요청은 Bearer 없음 · 내부는 Bearer + /tenants/{id}/
    assert fake.calls[3][0] == "/account/open/v1/queries/get-accounts"
    assert fake.calls[4][0].startswith("/tenants/tenant-x/schedule/zone/room/")


def test_schedule_upsert_card_and_body(env):
    c, fake = env
    fake.schedules.append(schedule(2, room=False))  # 라운지 — 안 나옴
    fake.schedules.append(schedule(3, flow="CONSULTATION"))
    run(c.kos.startup())
    assert run(c.kos.tick())["schedules"] == 3
    body = next(b for p, b in fake.calls if p.endswith("get-schedules-grouped-by-zone"))
    assert body == {"zoneIds": ["zone-4"], "startDateTimeUtc": "2026-10-20T15:00:00.000Z",
                    "endDateTimeUtc": "2026-10-21T15:00:00.000Z"}
    snap = c.board.snapshot()
    assert len(snap.cards) == 1
    card = snap.cards[0]
    assert card.room.title == "A-룸1" and card.inAt == "2026-10-21T10:00:00+09:00"
    # 작업은 type 무관 전부 실린다 — 「방 배정」(방 붙은 ETCETERA)도 싣고 isRoomTask(front 가 숨김 · 2026-10-25)
    assert [(p.sequence, p.kind, p.isRoomTask) for p in card.procedures] == [
        (1, "procedure", False), (2, "procedure", False), (3, "etc", True)]
    room_row = card.procedures[2]
    assert room_row.title == "방 배정" and room_row.kosStatus == "READY" and card.procedures[0].kosStatus == "NOT_STARTED"
    assert room_row.state == "wait" and not (room_row.pickable or room_row.canStart or room_row.canFinish)
    assert card.customer.name == "고객1" and card.orderMemo == "메모"
    assert snap.sync.lastOkAt and snap.sync.inWindow


def test_overwrite_and_removed_tasks(env):
    c, fake = env
    run(c.kos.startup())
    run(c.kos.tick())
    sch = fake.schedules[0]
    sch["orderMemo"] = "고친 메모"
    sch["tasks"][0].update(status="READY", doctors=[{"id": "doc-a", "name": ""}], paymentRequired=True)
    del sch["tasks"][1]  # 작업 2 빠짐
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    assert card.orderMemo == "고친 메모" and card.paymentRequired
    assert [(p.sequence, p.kind) for p in card.procedures] == [(1, "procedure"), (3, "etc")]
    assert card.procedures[0].doctor.name == "가 원장"
    # 일정이 사라지면 카드도
    fake.schedules.clear()
    run(c.kos.tick())
    assert c.board.snapshot().cards == []


def test_guard_pending_ops(env):
    c, fake = env
    run(c.kos.startup())
    run(c.kos.tick())
    fake.fail_paths = {"change-tasks-assignees": 500, "change-flow-step": 500}  # 반영이 안 돼 대기 중으로 남는다
    card = c.board.snapshot().cards[0]
    p1, p2 = (p.id for p in card.procedures if p.kind == "procedure")
    with c.repo.tx() as tx:
        tx.update_procedure(p2, doctor_staff_ids=[tx.staff_by_kos()["doc-a"].id])
    c.actions.create_call("t", card.visitId, [p1], "all", None)
    c.actions.start("t", p2)
    run(c.kos.tick())  # KOS 는 그대로(NOT_STARTED · PROCEDURE_WAITING · 의사 없음)
    card = c.board.snapshot().cards[0]
    assert card.state == "doing"  # flow-step 대기 중 → 안 덮음
    procs = {p.id: p for p in card.procedures}
    assert procs[p1].call is not None and not procs[p1].canStart
    with c.repo.tx() as tx:
        assert tx.procedures_of(card.visitId)[1].kos_status == "WAITING"  # 호출 대기 중 → 상태 안 덮음
    assert procs[p2].state == "doing"  # started_at 은 ccc 열 — 조회가 안 건드림
    assert card.kos.status == "pending"


def test_out_of_window_no_queries(env):
    c, fake = env
    c.clock.set(OUT)
    run(c.kos.startup())  # 서버 시작 직원 · 방 1회는 시간과 상관없이(W8)
    assert fake.paths()[:5] == ["exchange-token", "sign-in", "get-user-account", "get-accounts", "get-rooms"]
    # 뒤이어 예약 목록(SPEC-005 §4.2 — 조회 시간 무관): 구역 · 그룹 · 다른 구역 방 · 유입 · 기타 작업
    assert fake.paths()[5:] == ["get-zones", "get-reservation-groups", "get-rooms", "get-codes", "get-etcetera-tasks"]
    assert len(c.board.snapshot().doctors) == 2
    run(c.kos.master_once())  # 시작 뒤 1시간 루프는 조회 시간 안에서만
    assert fake.paths().count("get-accounts") == 1
    assert run(c.kos.tick()) is None
    assert "get-schedules-grouped-by-zone" not in fake.paths()
    assert c.board.snapshot().sync.inWindow is False


def test_token_401_refresh_once(env):
    c, fake = env
    run(c.kos.startup())
    fake.expire_once = {"internal", "open"}
    run(c.kos.tick())
    run(c.kos.master_once())
    assert fake.tokens_issued == {"open": 2, "internal": 2}
    assert c.board.snapshot().sync.lastError is None


def test_sync_failure_keeps_last_values(env):
    c, fake = env
    run(c.kos.startup())
    run(c.kos.tick())
    fake.fail_paths = {"get-schedules-grouped-by-zone": 503}
    run(c.kos.tick())
    snap = c.board.snapshot()
    assert len(snap.cards) == 1 and snap.sync.lastError == "HTTP 503 FakeError" and snap.sync.lastOkAt


def test_room_latest_assigned(env):
    c, fake = env
    sch = fake.schedules[0]
    sch["tasks"].append(task(9, "ETCETERA", "READY", room={"id": "room-2", "zoneId": "zone-4", "title": "A-룸2", "order": 2},
                             roomAssignedDateTimeUtc="2026-10-21T01:30:00Z"))
    run(c.kos.startup())
    run(c.kos.tick())
    assert c.board.snapshot().cards[0].room.title == "A-룸2"


def test_tick_publishes(env):
    c, _ = env
    run(c.kos.startup())
    v = c.hub.version
    run(c.kos.tick())
    assert c.hub.version > v


# ---- 방 판정(2026-10-25) — 카드 방 = type 무관 room 있는 작업 중 가장 늦은 배정
def room(n):
    return {"id": f"room-{n}", "zoneId": "zone-4", "title": f"A-룸{n}", "order": n}


def test_room_on_procedure_only_makes_card(env):
    """① 「방 배정」 없이 시술 작업에만 방 → 카드 방 · 입실 시각 = 그 작업 값."""
    c, fake = env
    sch = schedule(1, room=False, procs=2)
    sch["tasks"][0].update(room=room(4), roomAssignedDateTimeUtc="2026-10-21T01:10:00Z")
    sch["tasks"][1].update(room=room(4), roomAssignedDateTimeUtc="2026-10-21T01:05:00Z")
    fake.schedules = [sch]
    run(c.kos.startup())
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    assert card.room.title == "A-룸4" and card.inAt == "2026-10-21T10:10:00+09:00"
    assert [(p.sequence, p.kind) for p in card.procedures] == [(1, "procedure"), (2, "procedure")]


def test_room_latest_across_types(env):
    """② ETCETERA 방 + PROCEDURE 방 → 배정이 가장 늦은 작업(type 무관)."""
    c, fake = env
    sch = fake.schedules[0]  # 「방 배정」 ETCETERA 3 = room-1 · 01:00
    sch["tasks"][0].update(room=room(2), roomAssignedDateTimeUtc="2026-10-21T01:20:00Z")
    run(c.kos.startup())
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    assert card.room.title == "A-룸2" and card.inAt == "2026-10-21T10:20:00+09:00"
    sch["tasks"][2]["roomAssignedDateTimeUtc"] = "2026-10-21T01:30:00Z"  # 「방 배정」이 더 늦어지면 그 방
    run(c.kos.tick())
    assert c.board.snapshot().cards[0].room.title == "A-룸1"


def test_room_tie_prefers_etcetera(env):
    """배정 시각이 없거나 같으면(기본값) ETCETERA 먼저."""
    c, fake = env
    sch = fake.schedules[0]
    sch["tasks"][2]["roomAssignedDateTimeUtc"] = None
    sch["tasks"][0].update(room=room(2))
    run(c.kos.startup())
    run(c.kos.tick())
    assert c.board.snapshot().cards[0].room.title == "A-룸1"


def test_no_room_anywhere_no_card(env):
    """③ 어느 작업에도 방 없음 → 카드 없음(라운지)."""
    c, fake = env
    fake.schedules = [schedule(1, room=False, procs=2)]
    run(c.kos.startup())
    run(c.kos.tick())
    assert c.board.snapshot().cards == []


def test_room_task_row_shown_but_excluded(env):
    """④ 「방 배정」 줄은 실리되 isRoomTask · 판정에서 빠짐 — 시술 작업에 방이 붙어도 시술 줄은 isRoomTask 아님."""
    c, fake = env
    fake.rooms_on_procedures()
    run(c.kos.startup())
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    assert card.room.title == "A-룸1"
    assert [(p.sequence, p.isRoomTask, p.pickable) for p in card.procedures] == [(1, False, True), (2, False, True),
                                                                                (3, True, False)]
