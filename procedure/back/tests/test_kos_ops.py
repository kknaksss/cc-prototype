"""WP4 — KOS 반영: 같은 visit 순서 · $SYSTEM · 확인 · 재전송 · 3회 실패 · kos_failed · 상태 바뀔 때 SSE."""

import asyncio

from app.kos.ops import expect_met
from tests.fake_kos import SYSTEM
from tests.helpers import admin
from tests.test_kos_sync import env, run  # noqa: F401 — fixture 재사용


def boot(c, fake=None):
    if fake is not None:
        fake.rooms_on_procedures()  # 이 파일은 담당자 → 호출 대기열을 본다 — 방 넣기는 test_e2e1_room
    run(c.kos.startup())
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    return card.visitId, [p.id for p in card.procedures if p.kind == "procedure"]


def op_states(c):
    """방 넣기 op(이미 같은 방 → confirmed · 안 보냄)은 빼고 본다."""
    with c.repo.tx() as tx:
        return [(o.path.rsplit("/", 1)[-1], o.status, o.attempts) for o in tx.ops() if not o.path.endswith("change-tasks-room")]


def test_full_write_flow_in_order(env):  # noqa: F811
    c, fake = env
    vid, (p1, p2) = boot(c, fake)
    doc_a = next(d.id for d in c.board.snapshot().doctors if d.name == "가 원장")
    call = c.actions.create_call("t", vid, [p1], "all", None)
    run(c.kos.flush())  # 조작 직후 — 앞 op 이 2xx 면 이어서 바로(E2E-6): assignees → call 한 번에
    assert fake.paths()[-2:] == ["change-tasks-assignees", "call-tasks-doctors"]
    assert fake.calls[-2][1] == {"scheduleId": "sch-1", "sequences": [1], "assigneeIds": [SYSTEM]}
    assert [s for _, s, _ in op_states(c)] == ["sent", "sent"]
    c.actions.accept(admin(), call, doc_a)  # 확인 조회 전에 수락 — 호출(WAITING)이 수락(READY)에 덮여도 재전송하지 않는다
    run(c.kos.flush())
    run(c.kos.tick())
    assert [s for _, s, _ in op_states(c)] == ["confirmed", "confirmed", "confirmed"]
    c.actions.start("t", p1)
    run(c.kos.flush())
    c.actions.finish("t", p1)
    for _ in range(3):
        run(c.kos.tick())
    assert op_states(c) == [("change-tasks-assignees", "confirmed", 0), ("call-tasks-doctors", "confirmed", 0),
                            ("change-tasks-doctors", "confirmed", 0), ("change-flow-step", "confirmed", 0),
                            ("change-tasks-complete", "confirmed", 0)]
    writes = [p for p in fake.paths() if not p.startswith("get-")]
    assert writes == ["exchange-token", "sign-in", "change-tasks-assignees", "call-tasks-doctors", "change-tasks-doctors",
                      "change-flow-step", "change-tasks-complete"]
    assert fake.schedules[0]["flowStep"] == "PROCEDURE"
    card = c.board.snapshot().cards[0]
    assert card.kos.status == "ok" and card.state == "doing"
    assert {p.id: p.state for p in card.procedures if p.kind == "procedure"} == {p1: "done", p2: "wait"}
    # 공개 change-flow-step 은 Bearer 없이 공개 호스트로
    assert any(p == "/schedule/open/v1/commands/change-flow-step" for p, _ in fake.calls)


def test_resend_after_two_misses_then_fail(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = boot(c, fake)
    fake.apply_writes = False  # 200 은 주지만 값이 안 바뀐다
    c.actions.create_call("t", vid, [p1], "all", None)
    run(c.kos.flush())
    sent = fake.paths().count("change-tasks-assignees")
    assert fake.paths().count("call-tasks-doctors") == 1  # 2xx 라 이어서 보냄
    run(c.kos.tick())  # 1번 안 맞음
    run(c.kos.tick())  # 2번 → 재전송 대기(attempts 1) → 같은 tick 에 다시 보냄
    assert fake.paths().count("change-tasks-assignees") == sent + 1
    assert op_states(c)[0] == ("change-tasks-assignees", "sent", 1)
    for _ in range(4):
        run(c.kos.tick())
    states = op_states(c)
    assert states[0] == ("change-tasks-assignees", "failed", 3)
    assert states[1][:2] == ("call-tasks-doctors", "failed")  # 이미 보낸 호출도 확인이 안 맞아 실패
    with c.repo.tx() as tx:
        failed = tx.events("kos_failed")
    assert failed[0]["payload"]["path"].endswith("change-tasks-assignees")
    card = c.board.snapshot().cards[0]
    assert card.kos.status == "failed" and card.kos.failed[0].op == "change-tasks-assignees"
    assert card.procedures[0].call is not None  # ccc 상태는 되돌리지 않는다


def test_http_error_retries_on_tick_and_fails_at_three(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = boot(c, fake)
    fake.fail_paths = {"change-tasks-assignees": 500}
    c.actions.create_call("t", vid, [p1], "all", None)
    run(c.kos.flush())
    assert op_states(c)[0] == ("change-tasks-assignees", "pending", 1)
    run(c.kos.flush())  # 깨우기는 새 op 만 — 실패한 것은 다음 조회 주기에
    assert op_states(c)[0][2] == 1
    run(c.kos.tick())
    run(c.kos.tick())
    assert op_states(c)[0] == ("change-tasks-assignees", "failed", 3)
    with c.repo.tx() as tx:
        assert tx.events("kos_failed")[0]["payload"]["error"] == "HTTP 500 FakeError"


def test_visits_are_independent(env):  # noqa: F811
    c, fake = env
    from tests.fake_kos import schedule

    fake.schedules.append(schedule(2))
    fake.rooms_on_procedures()
    run(c.kos.startup())
    run(c.kos.tick())
    cards = c.board.snapshot().cards
    for card in cards:
        c.actions.create_call("t", card.visitId, [card.procedures[0].id], "all", None)
    run(c.kos.flush())
    assert fake.paths().count("change-tasks-assignees") == 2  # visit 마다 맨 앞 하나씩


def test_status_change_publishes(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = boot(c, fake)
    c.actions.create_call("t", vid, [p1], "all", None)
    v = c.hub.version
    run(c.kos.flush())
    assert c.hub.version == v + 1


def test_kick_wakes_sender_loop(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = boot(c, fake)

    async def go():
        task = asyncio.create_task(c.kos._sender_loop())
        c.actions.create_call("t", vid, [p1], "all", None)  # on_change → kick
        c.kos.kick()
        for _ in range(50):
            await asyncio.sleep(0.01)
            if "change-tasks-assignees" in fake.paths():
                break
        task.cancel()

    c.kos._kick = asyncio.Event()
    run(go())
    assert "change-tasks-assignees" in fake.paths()


def test_expect_met():
    sch = {"flowStep": "PROCEDURE", "tasks": [{"sequence": 1, "status": "READY", "doctors": [{"id": "d"}], "assignees": []}]}
    assert expect_met({"flowStep": "PROCEDURE"}, sch)
    assert expect_met({"tasks": [1], "doctorsContain": "d", "status": "READY"}, sch)
    assert not expect_met({"tasks": [1], "assigneesContain": "s"}, sch)
    assert not expect_met({"tasks": [2], "status": "READY"}, sch)
    assert not expect_met({"flowStep": "PROCEDURE"}, None)


def test_expect_met_status_not():
    """[종료] 되돌리기 확인 = 그 작업 status 가 DONE 이 아님(§8)."""
    sch = {"tasks": [{"sequence": 1, "status": "READY"}, {"sequence": 2, "status": "DONE"}]}
    assert expect_met({"tasks": [1], "statusNot": "DONE"}, sch)
    assert not expect_met({"tasks": [2], "statusNot": "DONE"}, sch)
    assert not expect_met({"tasks": [3], "statusNot": "DONE"}, sch)


def test_superseded_status_and_status_not_same_field():
    """[종료](status DONE) ↔ 되돌리기(statusNot DONE)는 같은 작업 status 필드 — 뒤 op 이 sent · confirmed 면 앞 op 은 대체."""
    from app.domain.models import KosOp
    from app.kos.ops import superseded

    def op(seq, status, expect):
        return KosOp(seq, None, 1, seq, "internal", "p", {}, expect, status, 0, 0, None)

    finish = op(1, "sent", {"tasks": [1], "status": "DONE"})
    undo = op(2, "pending", {"tasks": [1], "statusNot": "DONE"})
    again = op(3, "pending", {"tasks": [1], "status": "DONE"})
    other = op(4, "sent", {"tasks": [2], "statusNot": "DONE"})
    assert not superseded(finish, [finish, undo])  # 되돌리기 아직 안 보냄
    assert not superseded(finish, [finish, other])  # 다른 작업
    undo.status = "sent"
    assert superseded(finish, [finish, undo])
    assert not superseded(undo, [finish, undo, again])
    again.status = "confirmed"
    assert superseded(undo, [finish, undo, again])  # 되돌린 뒤 다시 [종료] → 앞 되돌리기 op 대체
