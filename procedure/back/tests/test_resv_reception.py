"""WORK-007 WP-BE4 — [접수 완료] 묶음 · [실장 호출] · [귀가 완료](SPEC-005 §5.6 · §5.8 · §5.10 · §8 · WP-KOS K8 · K9)."""

import pytest

from app.domain.errors import BadGateway, BadRequest, Conflict, NotFound
from tests.fake_kos import ZONE, ZONE2, kst, rtask, visitor
from tests.resv_env import DESK, load, make_env, rid_of, run

ROOM1 = {"id": "room-1", "zoneId": ZONE, "title": "A-룸1", "order": 1}
ROOM2 = {"id": "room-2", "zoneId": ZONE, "title": "A-룸2", "order": 2}
STEPS = ["recept", "add_task", "read_sequence", "assign_room", "flow_step"]


@pytest.fixture
def env(tmp_path):
    c, fake, mono = make_env(tmp_path)
    waits = []

    async def no_sleep(sec):
        waits.append(sec)

    c.reception.sleep = no_sleep
    with c.repo.tx() as tx:
        tx.upsert("staff", "cs-1", {"name": "상담사 1", "role_tags": ["COUNSELOR"], "active": True})
    return c, fake, waits


def room_id(c, kos_id):
    with c.repo.tx() as tx:
        return next(r.id for r in tx.rooms() if r.kos_id == kos_id)


def receive(c, kos_id, room="room-1"):
    return run(c.reception.run(DESK, rid_of(c, kos_id), room_id(c, room)))


def writes(fake):
    reads = {"get-schedule-detail", "get-visitor", "get-schedules-for-reservation", "get-reservation-slots-by-groups",
             "get-notices", "get-purchase-summaries", "get-schedules-grouped-by-zone"}
    return [p.rsplit("/", 1)[-1] for p, _ in fake.calls if p.rsplit("/", 1)[-1] not in reads
            and "/commands/" in p and not p.endswith(("exchange-token", "sign-in"))]


def sent(fake, name):
    return [b for p, b in fake.calls if p.endswith("/" + name)]


def events(c, t):
    with c.repo.tx() as tx:
        return [e["payload"] for e in tx.events(t)]


def add(c, fake, *a, **kw):
    x = fake.add_resv(*a, **kw)
    load(c)
    return x


# ------------------------------------------------------------------ 새 접수(K8)
def test_new_reception_consultation(env):
    c, fake, waits = env
    x = add(c, fake, "s1")
    n = len(fake.calls)
    assert receive(c, "s1") == "CONSULTATION_WAITING"
    names = [p.rsplit("/", 1)[-1] for p, _ in fake.calls[n:]]
    assert [x for x in names if x not in ("get-schedules-for-reservation", "get-reservation-slots-by-groups", "get-notices",
                                          "get-schedules-grouped-by-zone")] == [
        "get-schedule-detail", "get-visitor", "recept", "get-schedule-detail", "add-flow-tasks", "get-schedule-detail",
        "change-tasks-room", "get-schedule-detail", "change-flow-step", "get-schedule-detail"]
    assert sent(fake, "add-flow-tasks")[-1] == {"scheduleId": "s1", "tasks": [{
        "type": "ETCETERA", "title": "방 배정",
        "etceteraConfiguration": {"etceteraTaskId": "etc-room", "name": "방 배정", "translsMap": {"name": {}}},
        "translsMap": {"title": {}}}]}
    assert sent(fake, "change-tasks-room")[-1] == {"scheduleId": "s1", "sequences": [1], "roomId": "room-1"}
    assert sent(fake, "change-flow-step")[-1] == {"id": "s1", "step": "CONSULTATION_WAITING"}  # 내부 = id
    assert x["flowStep"] == "CONSULTATION_WAITING" and x["tasks"][0]["room"]["id"] == "room-1"
    ev = events(c, "reception")[-1]
    assert ev == {"reservationId": rid_of(c, "s1"), "roomId": room_id(c, "room-1"), "endStep": "CONSULTATION_WAITING",
                  "steps": STEPS}
    assert waits == [1.0, 1.0, 1.0]  # 2 · 4 · 5 — 각 1초 뒤 첫 읽기에 보임
    with c.repo.tx() as tx:
        r = tx.reservation(rid_of(c, "s1"))
    assert r.flow_step == "CONSULTATION_WAITING" and r.room_title == "A-룸1"  # 사본에 바로 실림


def test_direct_procedure_shows_on_procedure_board(env):
    c, fake, _ = env
    add(c, fake, "s1", consult=False)
    assert receive(c, "s1") == "PROCEDURE_WAITING"
    assert sent(fake, "change-flow-step")[-1] == {"id": "s1", "step": "PROCEDURE_WAITING"}
    with c.repo.tx() as tx:
        vid = tx.visit_by_kos()["s1"].id
    cards = [x for x in c.board.snapshot().cards if x.visitId == vid]  # 시술 현황 일정 조회 1회(§4.4) — 바로 시술 카드
    assert [(x.room.title, x.state) for x in cards] == [("A-룸1", "waiting")]
    assert all(p.isRoomTask for p in cards[0].procedures)  # 「방 배정」 줄은 숨는다


def test_noshow_reception(env):
    c, fake, _ = env
    x = add(c, fake, "s1", status="NO_SHOW")
    assert receive(c, "s1") == "CONSULTATION_WAITING"
    assert x["reservation"]["status"] == "IN_PROGRESS"  # recept 가 부도를 받아 진행 중으로(D-47)


def test_identity_incomplete_409(env):
    c, fake, _ = env
    fake.visitors["vis-1"].pop("passportNumber")
    fake.visitors["vis-1"].pop("passportSurname")
    add(c, fake, "s1")
    with pytest.raises(Conflict) as e:
        receive(c, "s1")
    assert e.value.code == "identity_incomplete" and e.value.message == "신분 칸을 채워 주세요 · 여권 영문명 · 여권번호"
    assert e.value.extra == {"fields": ["passportSurname", "passportNumber"]}  # 추가 지시 1 W5 — KOS 키
    assert writes(fake) == [] and not events(c, "reception")


# ------------------------------------------------------------------ 이어 하기(D-48 · E2E #23)
def test_resume_reception_only(env):
    c, fake, _ = env
    fake.visitors["vis-1"].pop("passportNumber")  # 이어 하기는 신분 칸을 안 본다
    add(c, fake, "s1", flow="RECEPTION", status="IN_PROGRESS")
    assert receive(c, "s1", "room-2") == "CONSULTATION_WAITING"
    assert writes(fake) == ["add-flow-tasks", "change-tasks-room", "change-flow-step"]
    assert "get-visitor" not in fake.paths()[-12:]
    assert events(c, "reception")[-1]["steps"] == STEPS[1:]


def test_resume_room_attached_locked(env):
    c, fake, _ = env
    add(c, fake, "s1", flow="RECEPTION", status="IN_PROGRESS",
        tasks=[rtask(1, "ETCETERA", "READY", room=ROOM2, title="방 배정")])
    with pytest.raises(Conflict) as e:
        receive(c, "s1", "room-1")
    assert (e.value.code, e.value.message) == ("room_locked", "이미 배정된 방이 있어요 · A-룸2")
    assert receive(c, "s1", "room-2") == "CONSULTATION_WAITING"
    assert writes(fake) == ["change-flow-step"]  # 작업 · 방 그대로 · 끝 단계만


def test_after_end_step_sends_nothing(env):
    c, fake, _ = env
    add(c, fake, "s1", flow="PROCEDURE_WAITING", status="IN_PROGRESS")
    assert receive(c, "s1") == "PROCEDURE_WAITING"
    assert writes(fake) == [] and not events(c, "reception")


def test_canceled_not_receivable(env):
    c, fake, _ = env
    add(c, fake, "s1", status="CANCELED")
    with pytest.raises(Conflict) as e:
        receive(c, "s1")
    assert e.value.code == "not_receivable" and writes(fake) == []


# ------------------------------------------------------------------ 방 검사
def test_room_checks(env):
    c, fake, _ = env
    add(c, fake, "busy", "vis-2", flow="PROCEDURE", status="IN_PROGRESS", tasks=[rtask(1, room=ROOM1, status="READY")])
    add(c, fake, "s1")
    with pytest.raises(Conflict) as e:
        receive(c, "s1", "room-1")
    assert e.value.code == "room_busy"
    with pytest.raises(BadRequest):
        receive(c, "s1", "room-b1")  # 다른 구역 방
    with pytest.raises(NotFound):
        run(c.reception.run(DESK, rid_of(c, "s1"), 999))
    with c.repo.tx() as tx:
        tx.con.execute("DELETE FROM etc_task_def")
    with pytest.raises(Conflict) as e:
        receive(c, "s1", "room-2")
    assert e.value.code == "room_task_missing" and writes(fake) == []


def test_room_task_env_override(tmp_path):
    c, fake, _ = make_env(tmp_path, kos_room_task_id="etc-custom")

    async def no_sleep(_):
        return None

    c.reception.sleep = no_sleep
    add(c, fake, "s1")
    receive(c, "s1")
    assert sent(fake, "add-flow-tasks")[-1]["tasks"][0]["etceteraConfiguration"]["etceteraTaskId"] == "etc-custom"


def test_other_zone_room(env):
    c, fake, _ = env
    add(c, fake, "z", grp="grp-3", zone=ZONE2, minutes=15)
    assert receive(c, "z", "room-b1") == "CONSULTATION_WAITING"
    assert sent(fake, "change-tasks-room")[-1]["roomId"] == "room-b1"


# ------------------------------------------------------------------ 멈춤 · 다시 누름 · 지연
def test_step_failure_stops_and_retry_resumes(env):
    c, fake, _ = env
    add(c, fake, "s1")
    fake.resv_fail = {"add-flow-tasks": (400, {"className": "InvalidRequestException"})}
    with pytest.raises(Conflict) as e:
        receive(c, "s1")
    assert (e.value.code, e.value.extra) == ("kos_rejected", {"step": "add_task"})
    assert writes(fake) == ["recept", "add-flow-tasks"]  # 거절된 뒤 되돌리지 않는다(cancel-reception 없음)
    assert events(c, "reception")[-1] == {"reservationId": rid_of(c, "s1"), "roomId": room_id(c, "room-1"), "endStep": None,
                                          "steps": ["recept"]}
    assert events(c, "kos_rejected")[-1]["op"] == "add-flow-tasks"
    fake.resv_fail = {}
    assert receive(c, "s1") == "CONSULTATION_WAITING"  # 다시 누르면 남은 단계만
    assert writes(fake) == ["recept", "add-flow-tasks", "add-flow-tasks", "change-tasks-room", "change-flow-step"]


def test_unavailable_502_with_step(env):
    c, fake, _ = env
    add(c, fake, "s1")
    fake.resv_fail = {"change-flow-step": (503, {})}
    with pytest.raises(BadGateway) as e:
        receive(c, "s1")
    assert (e.value.code, e.value.extra) == ("kos_unavailable", {"step": "flow_step"})
    assert events(c, "reception")[-1]["steps"] == STEPS[:4]


def test_slow_reflection(env):
    c, fake, waits = env
    add(c, fake, "s1")
    fake.delay = {"change-tasks-room": 2}  # 0초엔 안 보이고 다음 읽기에(K8 주의 4)
    assert receive(c, "s1") == "CONSULTATION_WAITING"
    assert waits.count(1.0) == 4
    fake.visitors["vis-2"] = visitor("vis-2")
    add(c, fake, "s2", "vis-2")
    fake.delay = {"recept": 9}
    with pytest.raises(Conflict) as e:
        receive(c, "s2", "room-2")
    assert (e.value.code, e.value.extra) == ("kos_slow", {"step": "recept"})
    assert e.value.message == "KOS 반영이 늦어요 · 잠시 뒤 다시 눌러 주세요"


# ------------------------------------------------------------------ [실장 호출](K5 · §5.8)
def test_counselor_call(env):
    c, fake, _ = env
    add(c, fake, "s1", flow="CONSULTATION_WAITING", status="IN_PROGRESS")
    with c.repo.tx() as tx:
        sid = {s.kos_id: s.id for s in tx.staff()}
    run(c.reception.counselor_call(DESK, rid_of(c, "s1"), sid["cs-1"]))
    assert sent(fake, "update-reservation")[-1] == {"scheduleId": "s1", "counselor": {"id": "cs-1", "name": "상담사 1"}}
    assert events(c, "counselor_call")[-1] == {"reservationId": rid_of(c, "s1"), "counselorStaffId": sid["cs-1"]}
    load(c)
    d = run(c.resv.detail(rid_of(c, "s1")))
    assert d.flow.consultation.counselor.name == "상담사 1" and d.flow.consultation.calledBy == "desk1"
    with pytest.raises(Conflict) as e:
        run(c.reception.counselor_call(DESK, rid_of(c, "s1"), sid["doc-a"]))
    assert e.value.code == "not_counselor"
    with pytest.raises(NotFound):
        run(c.reception.counselor_call(DESK, rid_of(c, "s1"), 999))
    add(c, fake, "s2", "vis-2")
    with pytest.raises(Conflict) as e:
        run(c.reception.counselor_call(DESK, rid_of(c, "s2"), sid["cs-1"]))
    assert e.value.code == "not_consultation"


# ------------------------------------------------------------------ [귀가 완료](K9 · K9b)
def test_discharge(env):
    c, fake, _ = env
    x = add(c, fake, "s1", flow="PROCEDURE_DONE", status="IN_PROGRESS", tasks=[rtask(1, status="DONE")])
    run(c.reception.discharge(DESK, rid_of(c, "s1")))
    assert sent(fake, "change-flow-step")[-1] == {"scheduleId": "s1", "step": "COMPLETED"}  # 공개 = scheduleId
    assert x["flowStep"] == "COMPLETED" and events(c, "discharge") == [{"reservationId": rid_of(c, "s1")}]


def test_discharge_blocked(env):
    c, fake, _ = env
    add(c, fake, "pay", flow="PROCEDURE_DONE", status="IN_PROGRESS", tasks=[rtask(1, paid=True)])
    add(c, fake, "rc", "vis-2", flow="PROCEDURE", status="IN_PROGRESS")
    with pytest.raises(Conflict) as e:
        run(c.reception.discharge(DESK, rid_of(c, "pay")))
    assert e.value.code == "payment_required" and writes(fake) == []
    with pytest.raises(Conflict) as e:
        run(c.reception.discharge(DESK, rid_of(c, "rc")))
    assert e.value.code == "not_home_waiting"


def test_discharge_kos_rejects(env):
    """K9b — 수납 필요 0 · 안 끝난 시술이 남아 KOS 가 400 → 409 kos_rejected."""
    c, fake, _ = env
    add(c, fake, "s1", flow="PROCEDURE_DONE", status="IN_PROGRESS", tasks=[rtask(1)])
    fake.resv_fail = {"change-flow-step": (400, {"className": "com.x.InvalidRequestException"})}
    with pytest.raises(Conflict) as e:
        run(c.reception.discharge(DESK, rid_of(c, "s1")))
    assert (e.value.code, e.value.message) == ("kos_rejected", "KOS 가 거절했어요 (InvalidRequestException)")
    assert events(c, "kos_rejected")[-1]["httpStatus"] == 400 and not events(c, "discharge")


def test_reception_today_cache_refreshed(env):
    c, fake, _ = env
    add(c, fake, "s1", start=kst(11))
    run(c.resv.board("2026-10-22"))
    c.kos.resv.invalidate("2026-10-21")
    n = fake.paths().count("get-schedules-for-reservation")
    receive(c, "s1")
    assert fake.paths().count("get-schedules-for-reservation") > n
