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


def test_etc_items_shown_but_not_actionable(env):  # noqa: F811
    """E2E-4 — 「방 배정」(ETCETERA)은 카드 목록에 kind etc 로 보이고 호출 · 시작 · 종료 · 전부 완료에서 빠진다."""
    c, fake = env
    vid, procs = boot(c)
    card = c.board.snapshot().cards[0]
    etc = next(p for p in card.procedures if p.kind == "etc")
    assert etc.state == "wait" and not (etc.pickable or etc.canStart or etc.canFinish) and etc.call is None
    import pytest

    from app.domain.errors import NotFound

    with pytest.raises(NotFound):
        c.actions.start("t", etc.id)
    with pytest.raises(NotFound):
        c.actions.create_call("t", vid, [etc.id], "all", None)
    fake.schedules[0]["tasks"][0]["status"] = "DONE"
    fake.schedules[0]["tasks"][1]["status"] = "DONE"  # 시술 둘 다 완료 · 방 배정은 READY 그대로
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    assert card.canHome and not card.canCall  # etc 는 「전부 완료」 판정에서 빠진다
    fake.schedules[0]["tasks"][2]["status"] = "CANCELED"
    run(c.kos.tick())
    assert [p.kind for p in c.board.snapshot().cards[0].procedures] == ["procedure", "procedure"]  # 취소된 etc 는 목록에서 빠진다
