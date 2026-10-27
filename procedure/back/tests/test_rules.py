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
    """T6 — [의사 호출] 은 호출할 수 있는(pickable) 작업이 1개 이상일 때만."""
    s = seed_staff(ctr.repo)
    only_room = seed_visit(ctr.repo, 1, procs=0)
    add_etc(ctr, only_room["visit"], 9, "방 배정", "room-1")  # 작업 0개 · 「방 배정」만
    busy = seed_visit(ctr.repo, 2, procs=2, doctors={1: [s["A"]], 2: [s["A"]]})
    ctr.actions.start("t", busy["procs"][0])
    assert card(ctr, busy["visit"]).canCall  # 대기 시술 1개 남음
    ctr.actions.start("t", busy["procs"][1])
    c1, c2 = card(ctr, only_room["visit"]), card(ctr, busy["visit"])
    assert not c1.canCall and not c1.canHome  # 「방 배정」만 → 호출 꺼짐(시술이 없으니 귀가 대기도 아님)
    assert not c2.canCall and not c2.canHome  # 전부 진행 중 · 대기 시술 0


# ---- 2026-10-25 규칙 하나 — 작업은 type 무관 전부 시술 · 예외 = 「방 배정」(방 붙은 ETCETERA)
def add_etc(c, vid, seq, title, room_kos_id=None, status="NOT_STARTED", doctors=None):
    with c.repo.tx() as tx:
        return tx.upsert_procedure(vid, seq, {"kos_order": seq, "title": title, "kos_status": status, "kind": "etc",
                                              "room_kos_id": room_kos_id, "doctor_staff_ids": doctors or []})


def test_room_task_in_snapshot_flagged(ctr):
    """③ 「방 배정」(여럿이어도 전부)은 procedures[] 에 실리고 isRoomTask=true · 판정 플래그 전부 false."""
    s = seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, procs=2, doctors={1: [s["A"]]})
    room1 = add_etc(ctr, v["visit"], 8, "방 배정", "room-1", status="READY")
    room2 = add_etc(ctr, v["visit"], 9, "방 점유", "room-2", status="READY")
    rows = {p.id: p for p in card(ctr, v["visit"]).procedures}
    assert set(rows) == {*v["procs"], room1, room2}
    for rid in (room1, room2):
        p = rows[rid]
        assert p.isRoomTask and p.kind == "etc" and not (p.pickable or p.canStart or p.canFinish)
    assert not any(rows[pid].isRoomTask for pid in v["procs"])
    from app.domain.errors import NotFound

    with pytest.raises(NotFound):
        ctr.actions.create_call("t", v["visit"], [room1], "all", None)
    with pytest.raises(NotFound):
        ctr.actions.start("t", room1)


def test_roomless_etc_is_procedure(ctr):
    """① 방 없는 ETCETERA(시트팩)는 일반 시술 — 체크 · 시작 · 종료 · 전부 완료에 든다."""
    s = seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, procs=1, doctors={1: [s["A"]]})
    pack = add_etc(ctr, v["visit"], 9, "시트팩", doctors=[s["A"]])
    p = proc(ctr, v["visit"], pack)
    assert p.kind == "etc" and not p.isRoomTask and p.pickable and p.canStart
    ctr.actions.start("t", v["procs"][0])
    ctr.actions.finish("t", v["procs"][0])
    c = card(ctr, v["visit"])
    assert not c.canHome and c.canCall  # 시트팩이 남아 전부 완료 아님
    ctr.actions.start("t", pack)
    assert proc(ctr, v["visit"], pack).canFinish
    ctr.actions.finish("t", pack)
    c = card(ctr, v["visit"])
    assert c.canHome and not c.canCall and proc(ctr, v["visit"], pack).state == "done"


def test_room_task_excluded_from_rules(ctr):
    """③ canCall · 전부 완료(canHome) · paymentRequired · need 는 「방 배정」 유무와 상관없이 같다."""
    s = seed_staff(ctr.repo)
    a = seed_visit(ctr.repo, 1, procs=2, doctors={1: [s["A"]], 2: [s["A"]]})
    b = seed_visit(ctr.repo, 2, procs=2, doctors={1: [s["A"]], 2: [s["A"]]})
    add_etc(ctr, b["visit"], 8, "방 배정", "room-2", status="READY")
    with ctr.repo.tx() as tx:
        tx.update_procedure(a["procs"][0], payment_required=True)
        tx.update_procedure(b["procs"][0], payment_required=True)
        tx.upsert_procedure(b["visit"], 8, {"payment_required": True})  # 「방 배정」의 수납 표시는 판정에 안 든다

    def flags(vid):
        c = card(ctr, vid)
        return c.canCall, c.canHome, c.paymentRequired, c.need

    assert flags(a["visit"]) == flags(b["visit"]) == (True, False, True, None)
    for v in (a, b):
        for pid in v["procs"]:
            ctr.actions.start("t", pid)
            ctr.actions.finish("t", pid)
    assert flags(a["visit"])[:3] == flags(b["visit"])[:3] == (False, True, True)  # 「방 배정」(READY)을 기다리지 않음
    assert card(ctr, a["visit"]).need.why == card(ctr, b["visit"]).need.why == "home"


def test_sheet_pack_payment_counts(ctr):
    """① 시트팩 등 ETCETERA 의 수납 필요도 일반 시술과 같이 든다."""
    seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, procs=1)
    pack = add_etc(ctr, v["visit"], 9, "시트팩")
    assert not card(ctr, v["visit"]).paymentRequired
    with ctr.repo.tx() as tx:
        tx.update_procedure(pack, payment_required=True)
    assert card(ctr, v["visit"]).paymentRequired


def test_called_sheet_pack_with_room_is_not_room_task(ctr):
    """「방 배정」 = 방 붙은 ETCETERA + ccc 가 호출한 적 없음 — 시트팩 호출로 방이 붙어도 isRoomTask=false · 판정 유지."""
    s = seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, procs=1, doctors={1: [s["A"]]})
    pack = add_etc(ctr, v["visit"], 9, "시트팩")
    room_task = add_etc(ctr, v["visit"], 8, "방 배정", "room-1", status="READY")
    call = ctr.actions.create_call("t", v["visit"], [pack], "all", None)
    with ctr.repo.tx() as tx:
        assert tx.procedures_of(v["visit"])[9].room_kos_id == "room-1"  # 호출 전 방 넣기로 방이 붙음
    p = proc(ctr, v["visit"], pack)
    assert not p.isRoomTask and p.call.id == call and p.pickable and not p.canStart  # 수락 전
    assert proc(ctr, v["visit"], room_task).isRoomTask  # 호출 안 된 「방 배정」은 그대로
    ctr.actions.accept(admin(), call, s["A"])
    ctr.actions.start("t", pack)
    ctr.actions.finish("t", pack)
    ctr.actions.start("t", v["procs"][0])
    assert not card(ctr, v["visit"]).canHome
    ctr.actions.finish("t", v["procs"][0])
    c = card(ctr, v["visit"])
    assert c.canHome and proc(ctr, v["visit"], pack).state == "done"  # 시트팩은 전부 완료 판정에 들어 있었다
    ctr.actions.home("t", v["visit"])
    with ctr.repo.tx() as tx:
        assert tx.events("home")[-1]["payload"] == {"cancelSequences": [8]}  # 취소 = 「방 배정」만
