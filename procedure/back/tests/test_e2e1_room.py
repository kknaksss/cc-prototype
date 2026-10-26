"""E2E-1 — 호출 전에 카드 방(「방 배정」 작업의 방)을 고른 시술 작업에 넣는다(KOS: 방 없는 작업 호출 = 400 roomId NotFound)."""

from tests.test_kos_sync import env, run  # noqa: F401 — fixture 재사용


def op_states(c):
    with c.repo.tx() as tx:
        return [(o.path.rsplit("/", 1)[-1], o.status, o.attempts) for o in tx.ops()]


def boot(c):
    run(c.kos.startup())
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    return card.visitId, [p.id for p in card.procedures if p.kind == "procedure"]


def writes(fake):
    return [(p.rsplit("/", 1)[-1], b) for p, b in fake.calls if "/schedule/" in p and "/commands/" in p]


def test_room_then_assignees_then_call(env):  # noqa: F811
    c, fake = env  # 가짜 일정 = 실물처럼 시술 작업에 방 없음 · 「방 배정」 ETCETERA 에만 room-1
    vid, (p1, p2) = boot(c)
    c.actions.create_call("t", vid, [p1, p2], "all", None)
    for _ in range(4):
        run(c.kos.flush())
        run(c.kos.tick())
    w = writes(fake)
    assert [n for n, _ in w] == ["change-tasks-room", "change-tasks-assignees", "call-tasks-doctors"]
    assert w[0][1] == {"scheduleId": "sch-1", "sequences": [1, 2], "roomId": "room-1"}
    assert [s for _, s, _ in op_states(c)] == ["confirmed", "confirmed", "confirmed"]
    assert all(t["room"]["id"] == "room-1" for t in fake.schedules[0]["tasks"] if t["type"] == "PROCEDURE")
    assert c.board.snapshot().cards[0].kos.status == "ok"


def test_call_without_room_is_rejected_by_fake():
    from tests.fake_kos import FakeKos

    fake = FakeKos()
    assert fake._reject("call-tasks-doctors", {"scheduleId": "sch-1", "sequences": [1]}) == "roomId NotFound"


def test_same_room_already_is_not_sent(env):  # noqa: F811
    c, fake = env
    fake.rooms_on_procedures()
    vid, (p1, _) = boot(c)
    c.actions.create_call("t", vid, [p1], "all", None)
    assert op_states(c)[0] == ("change-tasks-room", "confirmed", 0)
    run(c.kos.flush())
    run(c.kos.tick())
    assert "change-tasks-room" not in [n for n, _ in writes(fake)]
    assert [n for n, _ in writes(fake)] == ["change-tasks-assignees", "call-tasks-doctors"]


def test_room_failure_blocks_assignees_and_call(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = boot(c)
    fake.fail_paths = {"change-tasks-room": 400}
    c.actions.create_call("t", vid, [p1], "all", None)
    run(c.kos.flush())
    run(c.kos.tick())
    run(c.kos.tick())
    assert op_states(c) == [("change-tasks-room", "failed", 3), ("change-tasks-assignees", "failed", 0),
                            ("call-tasks-doctors", "failed", 0)]
    assert [n for n, _ in writes(fake)] == ["change-tasks-room"] * 3
    assert c.board.snapshot().cards[0].kos.status == "failed"


def test_sync_keeps_local_room_while_pending(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = boot(c)
    fake.apply_writes = False
    c.actions.create_call("t", vid, [p1], "all", None)
    run(c.kos.tick())  # 방 넣기 대기 중 — 조회가 작업 방(없음)으로 덮지 않는다
    with c.repo.tx() as tx:
        assert tx.procedures_of(vid)[1].room_kos_id == "room-1"


def test_etc_items_are_procedures(env):  # noqa: F811
    """① 2026-10-25 — 방 없는 ETCETERA(시트팩)는 일반 시술: 체크 · 호출 · 시작 · 종료 · 전부 완료에 같이 든다.

    KOS 쓰기도 같은 API(change-tasks-room · assignees · call · complete) — type 으로 거르는 곳 없음.
    ③ 「방 배정」(방 붙은 ETCETERA)은 스냅샷에 실리고 isRoomTask · 판정 · 조작에서 빠진다.
    """
    c, fake = env
    fake.schedules[0]["tasks"].append({**fake.schedules[0]["tasks"][0], "type": "ETCETERA", "sequence": 4, "order": 4,
                                       "title": "시트팩", "status": "NOT_STARTED"})
    run(c.kos.startup())
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    vid = card.visitId
    assert [(p.sequence, p.kind, p.isRoomTask) for p in card.procedures] == [
        (1, "procedure", False), (2, "procedure", False), (3, "etc", True), (4, "etc", False)]
    room_row, pack = card.procedures[2], card.procedures[3]
    assert room_row.title == "방 배정" and not (room_row.pickable or room_row.canStart or room_row.canFinish)
    assert pack.state == "wait" and pack.pickable and not pack.canStart  # 담당의 없음 → [시작] 꺼짐(시술과 같은 규칙)
    import pytest

    from app.domain.errors import NotFound

    with pytest.raises(NotFound):
        c.actions.start("t", room_row.id)
    with pytest.raises(NotFound):
        c.actions.create_call("t", vid, [room_row.id], "all", None)
    c.actions.create_call("t", vid, [pack.id], "all", None)
    run(c.kos.flush())
    assert [n for n, b in writes(fake)] == ["change-tasks-room", "change-tasks-assignees", "call-tasks-doctors"]
    assert all(b["sequences"] == [4] for _, b in writes(fake))
    for _ in range(2):
        run(c.kos.flush())
        run(c.kos.tick())
    from tests.helpers import admin

    staff = {s.name: s.id for s in c.repo.world().staff.values()}
    call = c.board.snapshot().calls[0].callId
    c.actions.accept(admin(), call, staff["가 원장"])
    c.actions.start("t", pack.id)
    c.actions.finish("t", pack.id)
    run(c.kos.flush())
    assert writes(fake)[-1] == ("change-tasks-complete", {"scheduleId": "sch-1", "sequences": [4], "complete": True})
    assert not c.board.snapshot().cards[0].canHome  # 시술 1 · 2 가 남음
    for i in (0, 1):
        fake.schedules[0]["tasks"][i]["status"] = "DONE"
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    assert card.canHome and not card.canCall  # 「방 배정」(READY)은 「전부 완료」에서 기다리지 않는다
    fake.schedules[0]["tasks"][2]["status"] = "CANCELED"
    run(c.kos.tick())
    assert sorted(p.sequence for p in c.board.snapshot().cards[0].procedures) == [1, 2, 4]  # CANCELED 는 목록에서 빠진다
