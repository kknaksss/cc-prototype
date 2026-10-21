"""WP2 — 규칙(§5): 카드 조건 · 원장 목록 · 유효 호출 · 수락 범위 · [시작] 조건 · 확인이 필요 · 현황 수."""

from datetime import timedelta

import pytest

from app.config import Settings
from app.container import build_container
from app.domain.clock import Clock
from tests.helpers import T0, admin, seed_staff, seed_visit


@pytest.fixture
def ctr(tmp_path):
    clock = Clock()
    clock.set(T0)
    return build_container(Settings(_env_file=None, proc_db_path=str(tmp_path / "r.db")), clock)


def snap(c):
    return c.board.snapshot()


def card(c, vid):
    return next(x for x in snap(c).cards if x.visitId == vid)


def proc(c, vid, pid):
    return next(p for p in card(c, vid).procedures if p.id == pid)


def test_card_conditions(ctr):
    seed_staff(ctr.repo)
    a = seed_visit(ctr.repo, 1)
    seed_visit(ctr.repo, 2, room=False)  # 방 없음 = 라운지
    seed_visit(ctr.repo, 3, flow="CONSULTATION")
    d = seed_visit(ctr.repo, 4, flow="PROCEDURE_DONE")
    ids = [x.visitId for x in snap(ctr).cards]
    assert ids == [a["visit"], d["visit"]]  # 귀가 대기는 맨 뒤
    assert card(ctr, d["visit"]).state == "home"


def test_doctor_list_excludes_system_anes_inactive(ctr):
    s = seed_staff(ctr.repo)
    names = {d.id for d in snap(ctr).doctors}
    assert names == {s["A"], s["B"], s["C"]}


def test_hidden_doctor_not_shown_and_no_start(ctr):
    s = seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, doctors={1: [s["SYS"]], 2: [s["A"]]})
    p1, p2 = (proc(ctr, v["visit"], pid) for pid in v["procs"][:2])
    assert p1.doctor is None and not p1.canStart  # 시스템 계정은 담당의가 아니다
    assert p2.doctor.id == s["A"] and p2.canStart
    assert not proc(ctr, v["visit"], v["procs"][2]).canStart  # 담당의 미정


def test_effective_call_and_accept_scope(ctr):
    s = seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, doctors={1: [s["A"]]})
    vid, (p1, p2, p3) = v["visit"], v["procs"]
    c1 = ctr.actions.create_call("t", vid, [p1, p2], "all", None)
    assert not proc(ctr, vid, p1).canStart and proc(ctr, vid, p1).call.id == c1
    # p1 을 새로 지정 호출 → p1 의 유효 호출이 c2 로 넘어감 · c1 은 p2 만 받는다
    c2 = ctr.actions.create_call("t", vid, [p1], "one", s["B"])
    assert ctr.actions.accept(admin(), c1, s["A"]) == [p2]
    assert proc(ctr, vid, p2).canStart and proc(ctr, vid, p2).doctor.id == s["A"]
    assert not proc(ctr, vid, p1).canStart
    calls = snap(ctr).calls
    assert [(c.callId, [p.id for p in c.procedures]) for c in calls] == [(c2, [p1])]
    assert proc(ctr, vid, p3).pickable and proc(ctr, vid, p3).call is None


def test_need_order_and_counts(ctr):
    s = seed_staff(ctr.repo)
    v1 = seed_visit(ctr.repo, 1)
    v2 = seed_visit(ctr.repo, 2, doctors={1: [s["A"]]}, procs=1)
    ctr.actions.create_call("t", v1["visit"], [v1["procs"][0]], "all", None)
    ctr.actions.anesthesia_start("t", v1["visit"])
    assert card(ctr, v1["visit"]).need is None
    ctr.clock.set(T0 + timedelta(minutes=5))
    n = card(ctr, v1["visit"]).need
    assert n.why == "call" and n.limitMin == 5
    ctr.clock.set(T0 + timedelta(minutes=20))
    assert card(ctr, v1["visit"]).need.why == "anes"  # 마취가 호출보다 앞
    pid = v2["procs"][0]
    ctr.actions.start("t", pid)
    ctr.actions.finish("t", pid)
    c2 = card(ctr, v2["visit"])
    assert c2.need.why == "home" and c2.canHome and not c2.canCall
    counts = snap(ctr).counts
    assert counts.model_dump() == {"all": 2, "need": 2, "waiting": 1, "anes": 1, "call": 1, "doing": 1}


def test_anesthesia_display(ctr):
    seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1)
    ctr.actions.anesthesia_start("t", v["visit"])
    a = card(ctr, v["visit"]).anesthesia
    assert a.runningSince and a.canEnd and not a.canStart
    ctr.clock.set(T0 + timedelta(minutes=7, seconds=30))
    ctr.actions.anesthesia_end("t", v["visit"])
    a = card(ctr, v["visit"]).anesthesia
    assert a.lastMinutes == 7 and a.canStart and a.runningSince is None


def test_procedure_order_and_doctor_busy(ctr):
    s = seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, doctors={1: [s["A"]], 2: [s["A"]], 3: [s["B"]]})
    vid, (p1, p2, p3) = v["visit"], v["procs"]
    ctr.actions.start("t", p3)
    ctr.actions.finish("t", p3)
    ctr.actions.start("t", p2)
    assert [p.id for p in card(ctr, vid).procedures] == [p3, p2, p1]
    busy = {d.id: d.busyRoom for d in snap(ctr).doctors}
    assert busy[s["A"]] == "A-룸1" and busy[s["B"]] is None
    assert snap(ctr).doctors[-1].id == s["A"]  # 비어 있는 원장 먼저


def test_canceled_procedure_excluded(ctr):
    s = seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, procs=2, doctors={1: [s["A"]]})
    with ctr.repo.tx() as tx:
        tx.update_procedure(v["procs"][1], kos_status="CANCELED")
    ctr.actions.start("t", v["procs"][0])
    ctr.actions.finish("t", v["procs"][0])
    c = card(ctr, v["visit"])
    assert [p.id for p in c.procedures] == [v["procs"][0]] and c.canHome


def test_can_call_needs_pickable_procedure(ctr):
    """T6 — [의사 호출] 은 호출할 수 있는(pickable) 시술이 1개 이상일 때만."""
    s = seed_staff(ctr.repo)
    only_etc = seed_visit(ctr.repo, 1, procs=0)
    with ctr.repo.tx() as tx:  # 시술 0개 · 기타 작업(방 배정)만
        tx.upsert_procedure(only_etc["visit"], 9, {"kos_order": 9, "title": "방 배정", "kos_status": "READY", "kind": "etc"})
    busy = seed_visit(ctr.repo, 2, procs=2, doctors={1: [s["A"]], 2: [s["A"]]})
    ctr.actions.start("t", busy["procs"][0])
    assert card(ctr, busy["visit"]).canCall  # 대기 시술 1개 남음
    ctr.actions.start("t", busy["procs"][1])
    c1, c2 = card(ctr, only_etc["visit"]), card(ctr, busy["visit"])
    assert not c1.canCall and not c1.canHome  # 기타 작업만 → 호출 꺼짐(시술이 없으니 귀가 대기도 아님)
    assert not c2.canCall and not c2.canHome  # 전부 진행 중 · 대기 시술 0
