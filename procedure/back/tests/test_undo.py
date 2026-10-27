"""WORK-006 WP-BE — [시작] · [종료] 되돌리기(SPEC-003 0.5.1 §5.13 · §7.3 · §8 · §9 「0.5.0 더함」)."""

import pytest
from fastapi.testclient import TestClient

from app.domain.errors import Conflict, NotFound
from app.domain.kos_ops import PATH_COMPLETE, PATH_FLOW_STEP
from app.main import create_app
from tests.conftest import ADMIN, make_settings
from tests.helpers import admin, seed_staff, seed_visit
from tests.test_kos_sync import env, run  # noqa: F401 — fixture 재사용


def card(ctr, vid):
    return next(c for c in ctr.board.snapshot().cards if c.visitId == vid)


def row(ctr, vid, pid):
    return next(p for p in card(ctr, vid).procedures if p.id == pid)


def ops(ctr, vid):
    with ctr.repo.tx() as tx:
        return [o for o in tx.ops() if o.visit_id == vid]


def events(ctr, type_):
    with ctr.repo.tx() as tx:
        return tx.events(type_)


@pytest.fixture
def two(ctr):
    """원장 A 가 담당의인 시술 2개 카드."""
    s = seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, procs=2, doctors={1: [s["A"]], 2: [s["A"]]})
    return s, v["visit"], v["procs"]


def code(r):
    return r.status_code, r.json().get("error", {}).get("code")


# ------------------------------------------------------------------ undo-start
def test_undo_start_back_to_waiting_with_flow_step(client, auth, ctr, two):
    s, vid, (p1, _) = two
    ctr.actions.start("t", p1)
    assert card(ctr, vid).state == "doing" and row(ctr, vid, p1).canUndoStart
    before = len(ops(ctr, vid))
    r = client.post(f"/api/procedures/{p1}/undo-start", headers=auth)
    assert r.status_code == 200 and r.json() == {"ok": True, "flowStepChanged": True}
    p = row(ctr, vid, p1)
    assert p.state == "wait" and p.startedAt is None and p.canStart and p.doctor.id == s["A"]  # 담당의 그대로 · [시작] 다시 켜짐
    assert not (p.canUndoStart or p.canUndoFinish)
    assert card(ctr, vid).state == "waiting"
    new = ops(ctr, vid)[before:]
    assert [(o.path, o.body["step"]) for o in new] == [(PATH_FLOW_STEP, "PROCEDURE_WAITING")]  # 항상 1줄
    ev = events(ctr, "proc_undo_start")
    start_ev = events(ctr, "proc_start")[-1]
    assert len(ev) == 1 and ev[0]["actor"] == ADMIN["id"] and ev[0]["visit_id"] == vid
    assert ev[0]["payload"] == {"procedureId": p1, "startedAt": "2026-10-21T11:00:00+09:00", "startedEventId": start_ev["id"],
                                "flowStepChanged": True}
    assert len(events(ctr, "proc_start")) == 1  # 앞 줄은 고치지 · 지우지 않는다
    ctr.actions.start("t", p1)  # 다시 [시작] 된다
    assert row(ctr, vid, p1).state == "doing"


def test_undo_start_keeps_call_and_accept(ctr, two):
    s, vid, (p1, _) = two
    call = ctr.actions.create_call("t", vid, [p1], "all", None)
    ctr.actions.accept(admin(), call, s["B"])
    ctr.actions.start("t", p1)
    ctr.actions.undo_start("t", p1)
    p = row(ctr, vid, p1)
    assert p.state == "wait" and p.call.id == call and p.call.acceptedBy == s["B"] and p.doctor.id == s["B"] and p.canStart


def test_undo_start_other_doing_or_done_keeps_customer(ctr, two):
    _, vid, (p1, p2) = two
    ctr.actions.start("t", p1)
    ctr.actions.start("t", p2)
    n = len(ops(ctr, vid))
    assert ctr.actions.undo_start("t", p2) is False  # p1 진행 중 → 고객 그대로 · op 0
    assert card(ctr, vid).state == "doing" and len(ops(ctr, vid)) == n
    ctr.actions.finish("t", p1)
    ctr.actions.start("t", p2)
    assert ctr.actions.undo_start("t", p2) is False  # p1 완료 → 고객 그대로
    assert card(ctr, vid).state == "doing" and len(ops(ctr, vid)) == n + 1  # [종료] op 만


# ------------------------------------------------------------------ undo-finish
def test_undo_finish(client, auth, ctr, two):
    _, vid, (p1, p2) = two
    ctr.actions.start("t", p1)
    ctr.actions.finish("t", p1)
    ctr.actions.start("t", p2)
    ctr.actions.finish("t", p2)
    assert card(ctr, vid).canHome and row(ctr, vid, p1).canUndoFinish
    n = len(ops(ctr, vid))
    r = client.post(f"/api/procedures/{p1}/undo-finish", headers=auth)
    assert r.status_code == 200 and r.json() == {"ok": True}
    p = row(ctr, vid, p1)
    assert p.state == "doing" and p.completedAt is None and p.kosStatus == "READY" and p.canFinish
    assert p.startedAt == "2026-10-21T11:00:00+09:00" and p.canUndoStart and not p.canUndoFinish  # 옛 [시작] 시각 그대로
    c = card(ctr, vid)
    assert c.state == "doing" and not c.canHome  # 고객 그대로 · 「전부 완료」 풀림
    new = ops(ctr, vid)[n:]
    assert len(new) == 1 and new[0].path == PATH_COMPLETE
    assert new[0].body == {"scheduleId": "sch-1", "sequences": [1], "complete": False}
    assert new[0].expect == {"tasks": [1], "statusNot": "DONE"}
    ev = events(ctr, "proc_undo_finish")
    assert len(ev) == 1 and ev[0]["payload"] == {"procedureId": p1, "completedAt": "2026-10-21T11:00:00+09:00"}
    with ctr.repo.tx() as tx:
        assert tx.procedures_of(vid)[1].completed_at is None


# ------------------------------------------------------------------ 409 · 404 · 403 · 401
def test_conflicts(client, auth, ctr, two):
    _, vid, (p1, p2) = two
    assert code(client.post(f"/api/procedures/{p1}/undo-start", headers=auth)) == (409, "procedure_not_doing")
    assert code(client.post(f"/api/procedures/{p1}/undo-finish", headers=auth)) == (409, "procedure_not_done")
    ctr.actions.start("t", p1)
    assert code(client.post(f"/api/procedures/{p1}/undo-finish", headers=auth)) == (409, "procedure_not_done")
    with ctr.repo.tx() as tx:  # KOS 에서만 완료(ccc [시작] 없음)
        tx.update_procedure(p2, kos_status="DONE")
    assert not row(ctr, vid, p2).canUndoFinish
    r = client.post(f"/api/procedures/{p2}/undo-finish", headers=auth)
    assert code(r) == (409, "procedure_not_started")
    ctr.actions.finish("t", p1)
    assert code(client.post(f"/api/procedures/{p1}/undo-start", headers=auth)) == (409, "procedure_not_doing")
    ctr.actions.home("t", vid)  # 귀가 대기 → 둘 다 visit_home 먼저
    assert not row(ctr, vid, p1).canUndoFinish
    assert code(client.post(f"/api/procedures/{p1}/undo-finish", headers=auth)) == (409, "visit_home")
    assert code(client.post(f"/api/procedures/{p1}/undo-start", headers=auth)) == (409, "visit_home")
    assert r.json()["error"]["message"] == "시작하지 않은 시술이에요"
    assert events(ctr, "proc_undo_start") == events(ctr, "proc_undo_finish") == []


def test_messages(client, auth, ctr, two):
    _, _, (p1, _) = two
    assert client.post(f"/api/procedures/{p1}/undo-start", headers=auth).json()["error"]["message"] == "진행 중인 시술이 아니에요"
    assert client.post(f"/api/procedures/{p1}/undo-finish", headers=auth).json()["error"]["message"] == "완료된 시술이 아니에요"


def test_room_task_and_unknown_404(client, auth, ctr, two):
    _, vid, _ = two
    with ctr.repo.tx() as tx:
        room_task = tx.upsert_procedure(vid, 9, {"kos_order": 9, "title": "방 배정", "kos_status": "DONE", "kind": "etc",
                                                 "room_kos_id": "room-1"})
    p = row(ctr, vid, room_task)
    assert p.isRoomTask and not (p.canUndoStart or p.canUndoFinish)
    for path in ("undo-start", "undo-finish"):
        assert code(client.post(f"/api/procedures/{room_task}/{path}", headers=auth)) == (404, "not_found")
        assert code(client.post(f"/api/procedures/9999/{path}", headers=auth)) == (404, "not_found")
    with pytest.raises(NotFound):
        ctr.actions.undo_start("t", room_task)


def test_requires_login_and_fake_board(tmp_path, client, ctr, two):
    _, _, (p1, _) = two
    for path in ("undo-start", "undo-finish"):
        assert code(client.post(f"/api/procedures/{p1}/{path}")) == (401, "unauthorized")
    with TestClient(create_app(make_settings(tmp_path / "fake", proc_fake_board=True))) as fc:
        tok = fc.post("/api/auth/login", json=ADMIN).json()["token"]
        for path in ("undo-start", "undo-finish"):
            r = fc.post(f"/api/procedures/1021/{path}", headers={"Authorization": f"Bearer {tok}"})
            assert code(r) == (403, "fake_board")


def test_one_event_one_publish(ctr, two):
    _, vid, (p1, _) = two
    ctr.actions.start("t", p1)
    v = ctr.hub.version
    ctr.actions.undo_start("t", p1)
    assert ctr.hub.version == v + 1 and len(events(ctr, "proc_undo_start")) == 1
    ctr.actions.start("t", p1)
    ctr.actions.finish("t", p1)
    v = ctr.hub.version
    ctr.actions.undo_finish("t", p1)
    assert ctr.hub.version == v + 1 and len(events(ctr, "proc_undo_finish")) == 1
    v = ctr.hub.version
    with pytest.raises(Conflict):
        ctr.actions.undo_finish("t", p1)  # 거절은 발행 없음
    assert ctr.hub.version == v


def test_snapshot_flags(ctr, two):
    _, vid, (p1, p2) = two
    assert not any(p.canUndoStart or p.canUndoFinish for p in card(ctr, vid).procedures)  # 대기 줄 = 없음
    ctr.actions.start("t", p1)
    ctr.actions.start("t", p2)
    ctr.actions.finish("t", p2)
    f = {p.id: (p.canUndoStart, p.canUndoFinish) for p in card(ctr, vid).procedures}
    assert f == {p1: (True, False), p2: (False, True)}


# ------------------------------------------------------------------ KOS 반영(가짜 KOS)
def kos_boot(c, fake):
    fake.rooms_on_procedures()
    for t in fake.schedules[0]["tasks"]:
        if t["type"] == "PROCEDURE":
            t["doctors"] = [{"id": "doc-a", "name": ""}]
    run(c.kos.startup())
    run(c.kos.tick())
    card_ = c.board.snapshot().cards[0]
    return card_.visitId, [p.id for p in card_.procedures if not p.isRoomTask]


def kos_ops(c):
    with c.repo.tx() as tx:
        return [(o.path.rsplit("/", 1)[-1], o.body.get("complete", o.body.get("step")), o.status, o.attempts) for o in tx.ops()]


def sent(fake, name):
    return [b for p, b in fake.calls if p.endswith(name)]


def test_kos_undo_finish_confirmed_by_status_not(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = kos_boot(c, fake)
    c.actions.start("t", p1)
    c.actions.finish("t", p1)
    run(c.kos.flush())
    run(c.kos.tick())
    assert fake.schedules[0]["tasks"][0]["status"] == "DONE"
    c.actions.undo_finish("t", p1)
    run(c.kos.flush())
    run(c.kos.tick())
    assert fake.schedules[0]["tasks"][0]["status"] == "READY"
    assert all(s == "confirmed" for _, _, s, _ in kos_ops(c))
    assert c.board.snapshot().cards[0].procedures[0].state == "doing"  # 확인 뒤 KOS 값(READY)으로 덮여도 진행


def test_kos_finish_undo_finish_no_resend(env):  # noqa: F811
    """[종료] → 되돌리기 → [종료] — 확인 조회 전에 이어 보내도 앞 op 재전송 0(superseded — status · statusNot 같은 필드)."""
    c, fake = env
    vid, (p1, _) = kos_boot(c, fake)
    c.actions.start("t", p1)
    c.actions.finish("t", p1)
    c.actions.undo_finish("t", p1)
    c.actions.finish("t", p1)
    run(c.kos.flush())
    for _ in range(4):
        run(c.kos.tick())
        run(c.kos.flush())
    assert [b["complete"] for b in sent(fake, "change-tasks-complete")] == [True, False, True]  # 재전송 없음
    assert [(n, v, s) for n, v, s, _ in kos_ops(c)] == [("change-flow-step", "PROCEDURE", "confirmed"),
                                                       ("change-tasks-complete", True, "confirmed"),
                                                       ("change-tasks-complete", False, "confirmed"),
                                                       ("change-tasks-complete", True, "confirmed")]
    assert fake.schedules[0]["tasks"][0]["status"] == "DONE"


def test_kos_first_start_then_undo_supersedes(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = kos_boot(c, fake)
    c.actions.start("t", p1)
    c.actions.undo_start("t", p1)
    run(c.kos.flush())
    for _ in range(3):
        run(c.kos.tick())
    assert [b["step"] for b in sent(fake, "change-flow-step")] == ["PROCEDURE", "PROCEDURE_WAITING"]
    assert [(n, v, s) for n, v, s, _ in kos_ops(c)] == [("change-flow-step", "PROCEDURE", "confirmed"),
                                                       ("change-flow-step", "PROCEDURE_WAITING", "confirmed")]
    assert fake.schedules[0]["flowStep"] == "PROCEDURE_WAITING" and c.board.snapshot().cards[0].state == "waiting"


def test_kos_undo_start_same_step_400_then_confirmed(env):  # noqa: F811
    """flow-step op 은 항상 만든다 — KOS 가 이미 PROCEDURE_WAITING 이면 400 → 다음 조회에서 confirmed(재전송 없음)."""
    c, fake = env
    vid, (p1, _) = kos_boot(c, fake)
    c.actions.start("t", p1)
    run(c.kos.flush())
    fake.schedules[0]["flowStep"] = "PROCEDURE_WAITING"  # 그 사이 KOS 화면에서 되돌림
    assert c.actions.undo_start("t", p1) is True
    run(c.kos.flush())
    assert kos_ops(c)[-1][2:] == ("pending", 1)  # 같은 단계 400
    for _ in range(3):
        run(c.kos.tick())
        run(c.kos.flush())
    assert kos_ops(c)[-1][2] == "confirmed"
    assert [b["step"] for b in sent(fake, "change-flow-step")] == ["PROCEDURE", "PROCEDURE_WAITING"]
