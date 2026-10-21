"""E2E-3 — [귀가 대기] = ① cancel-flow-tasks(남은 비시술 작업 — 「방 배정」 등) → ② change-flow-step PROCEDURE_DONE.

카드는 KOS 가 COMPLETED(데스크 귀가)가 되면 조회에서 빠진다.
"""

from app.domain.kos_ops import PATH_CANCEL, PATH_FLOW_STEP
from tests.test_kos_sync import env, run  # noqa: F401 — fixture 재사용


def writes(fake):
    return [(p.rsplit("/", 1)[-1], b) for p, b in fake.calls if "/schedule/" in p and "/commands/" in p]


def finish_all(c, fake):
    """원장 배정(가짜 KOS · ccc 둘 다) → 시술 전부 [시작] · [종료]."""
    fake.rooms_on_procedures()
    for t in fake.schedules[0]["tasks"]:
        if t["type"] == "PROCEDURE":
            t["doctors"] = [{"id": "doc-a", "name": ""}]
    run(c.kos.startup())
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    for p in (q for q in card.procedures if q.kind == "procedure"):
        c.actions.start("t", p.id)
        c.actions.finish("t", p.id)
    return card.visitId


def ops(c, vid):
    with c.repo.tx() as tx:
        return [o for o in tx.ops() if o.visit_id == vid]


def test_home_cancels_open_tasks_then_flow_step(env):  # noqa: F811
    c, fake = env  # 가짜 일정: 시술 1 · 2 + 「방 배정」 ETCETERA 3(READY)
    vid = finish_all(c, fake)
    c.actions.home("t", vid)  # 시술 완료 반영이 아직 대기 중이어도 시술은 취소 대상이 아니다
    cancel, flow = ops(c, vid)[-2:]
    assert cancel.path == PATH_CANCEL and cancel.body == {"scheduleId": "sch-1", "sequences": [3], "reason": "CANCEL"}
    assert cancel.expect == {"tasks": [3], "status": "CANCELED"}
    assert flow.path == PATH_FLOW_STEP and flow.body == {"scheduleId": "sch-1", "step": "PROCEDURE_DONE"}
    for _ in range(3):
        run(c.kos.flush())
        run(c.kos.tick())
    names = [n for n, _ in writes(fake)]
    assert names[-2:] == ["cancel-flow-tasks", "change-flow-step"]  # ① → ② 순서
    assert all(o.status == "confirmed" for o in ops(c, vid))
    tasks = {t["sequence"]: t["status"] for t in fake.schedules[0]["tasks"]}
    assert tasks == {1: "DONE", 2: "DONE", 3: "CANCELED"} and fake.schedules[0]["flowStep"] == "PROCEDURE_DONE"
    card = c.board.snapshot().cards[0]
    assert card.state == "home" and card.room.title == "A-룸1" and card.kos.status == "ok"  # ccc 카드 · 방은 그대로


def test_home_without_open_tasks_skips_cancel(env):  # noqa: F811
    c, fake = env
    for t in fake.schedules[0]["tasks"]:
        if t["type"] == "ETCETERA":
            t["status"] = "DONE"
    vid = finish_all(c, fake)
    c.actions.home("t", vid)
    assert [o.path for o in ops(c, vid)][-1] == PATH_FLOW_STEP
    assert PATH_CANCEL not in [o.path for o in ops(c, vid)]


def test_card_leaves_when_kos_completed(env):  # noqa: F811
    c, fake = env
    vid = finish_all(c, fake)
    c.actions.home("t", vid)
    run(c.kos.flush())
    run(c.kos.tick())
    assert [x.visitId for x in c.board.snapshot().cards] == [vid]
    fake.schedules[0]["flowStep"] = "COMPLETED"  # 데스크가 KOS 에서 귀가
    run(c.kos.tick())
    assert c.board.snapshot().cards == []
