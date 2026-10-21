"""SPEC-001 0.2.0 §11 수락 기준 1~7 — API 로(화면 빼고). 시험 픽스처 시나리오(tests/fixtures/scenario)."""

from tests.helpers import (
    assign,
    board,
    check_in,
    consult_done,
    customer,
    err,
    finish,
    ok,
    place,
    staff_of,
    start,
    step,
)


def test_1_seed_is_before_opening(client):
    b = board(client)
    assert [r["scheduleId"] for r in b["resv"]] == ["sch-1", "sch-2", "sch-3", "sch-4", "sch-5"]
    assert [r["st"] for r in b["resv"]] == ["booked", "booked", "canceled", "booked", "booked"]
    assert b["customers"] == []
    assert all(s["work"] == [] for s in b["staff"])
    names = {r["id"]: r["name"] for r in b["rooms"]}
    assert names["reception"] == "접수대기실" and names["s01"] == "수면시술실 01" and "lounge" not in names
    assert all(r["unpaidAmount"] == 0 for r in b["rooms"])


def test_2_first_visit_consult_flow_reveals_memos(client):
    before = ok(client.get("/api/patients/sch-1"))
    assert before["flowStep"] == "RESERVED" and before["visits"] == []  # 접수 전 — 오늘 카드 없음(지난 방문도 없음)
    assert before["reservationMemo"].startswith("**1시 전 아웃 희망**")  # 예약 메모는 예약 때부터 · 원문 그대로

    check_in(client, "sch-1", [{"kind": "consult"}])
    c = customer(client, "sch-1")
    assert c["location"] == "reception" and c["flowStep"] == "RECEPTION"
    got = [(s["kind"], s["label"], s["state"], s["paymentRequired"]) for s in c["steps"]]
    assert got == [("consult", "상담", "planned", False)]
    ok(place(client, "sch-1", "c03"))
    c = customer(client, "sch-1")
    assert c["location"] == "c03" and c["flowStep"] == "CONSULTATION_WAITING" and c["status"]["label"] == "다음 단계 대기"

    st = step(client, "sch-1", "consult")
    ok(assign(client, st["stepId"], "c2"))
    assert customer(client, "sch-1")["status"]["label"] == "상담사B 대기"
    home = ok(client.get("/api/staff/c2/home"))
    assert home["frame"] == "assigned" and [n["stepId"] for n in home["next"]] == [st["stepId"]]
    mid = ok(client.get("/api/patients/sch-1", params={"staffId": "c2"}))
    assert mid["myActions"] == [{"stepId": st["stepId"], "kind": "consult", "action": "start", "label": "상담 시작"}]
    today = mid["visits"][0]
    assert today["today"] and today["locked"] and today["consultation"] is None and today["orderMemo"] is None

    ok(client.post("/api/staff/c2/start", json={"stepId": st["stepId"]}))
    assert customer(client, "sch-1")["flowStep"] == "CONSULTATION"
    ok(finish(client, "c2", st["stepId"]))
    today = ok(client.get("/api/patients/sch-1"))["visits"][0]
    assert not today["locked"] and today["consultation"].startswith("[상담내용]") and today["orderMemo"].startswith("OUT TIME")
    assert today["counselors"] == ["상담사B"]
    assert ok(client.get("/api/staff/c2/home"))["done"][0]["stepId"] == st["stepId"]


def test_3_procedures_reorder_assign_start_finish(client):
    consult_done(client, "sch-1", "c05")
    assert [s["kind"] for s in customer(client, "sch-1")["steps"]] == ["consult"]  # 이벤트 시술은 동선에 안 붙음
    cands = ok(client.get("/api/patients/sch-1/procedure-candidates"))
    ids = [b["bundleId"] for b in cands if b["source"] == "today"]
    assert ids == ["today:doctor_consult", "today:울쎄라피 프라임 300shot", "today:리쥬란 힐러 2cc", "today:시트팩"]
    ok(client.post("/api/desk/add-procedures", json={"scheduleId": "sch-1", "bundleIds": ids}))
    ss = customer(client, "sch-1")["steps"]
    assert [s["kind"] for s in ss] == ["consult", "doctor_consult", "procedure", "procedure", "procedure"]
    assert [s["kosSequence"] for s in ss] == [None, 1, 2, 3, 4]
    assert [b for b in ok(client.get("/api/patients/sch-1/procedure-candidates")) if b["source"] == "today" and b["left"]] == []
    # 순서 바꾸기 — 남은 단계만(시트팩을 시술 맨 앞으로)
    pending = [s["stepId"] for s in ss if s["state"] == "planned"]
    new = [pending[0], pending[3], pending[1], pending[2]]
    ok(client.post("/api/desk/reorder", json={"scheduleId": "sch-1", "stepIds": new}))
    assert [s["stepId"] for s in customer(client, "sch-1")["steps"]][1:] == new

    dc = step(client, "sch-1", "doctor_consult")
    err(assign(client, dc["stepId"], "s1"), "role_mismatch")
    ok(assign(client, dc["stepId"], "d1"))
    ok(start(client, "d1", dc["stepId"]))
    ok(finish(client, "d1", dc["stepId"]))
    c = customer(client, "sch-1")
    assert c["flowStep"] == "PROCEDURE_WAITING" and c["status"]["label"] == "원장 대기 · 세팅 준비"

    p1 = step(client, "sch-1", "procedure", 0)
    err(start(client, "d2", p1["stepId"]), "not_my_step")
    ok(assign(client, p1["stepId"], "d1"))
    ok(start(client, "d1", p1["stepId"]))
    assert customer(client, "sch-1")["flowStep"] == "PROCEDURE"
    err(client.post("/api/desk/reorder", json={"scheduleId": "sch-1", "stepIds": new}), "step_in_progress")
    ok(finish(client, "d1", p1["stepId"]))
    c = customer(client, "sch-1")
    assert c["status"]["label"] == "다음 단계 대기" and c["status"]["need"] == "next"
    rounds = ok(client.get("/api/staff/n1/home"))
    row = next(p for p in rounds["patients"] if p["scheduleId"] == "sch-1")
    assert rounds["frame"] == "rounds" and row["need"] == "next" and len(row["procedures"]) == 3
    ids2 = [s["stepId"] for s in customer(client, "sch-1")["steps"]]
    err(client.post("/api/desk/reorder", json={"scheduleId": "sch-1", "stepIds": [ids2[1], ids2[0]] + ids2[2:]}),
        "done_step_moved")


def test_4_sleep_room_holds_original(client):
    for sid in ("sch-4", "sch-5"):
        check_in(client, sid, [{"kind": "consult"}])
    ok(place(client, "sch-4", "c01"))
    err(client.post("/api/desk/move-sleep", json={"scheduleId": "sch-4", "room": "c02"}), "not_sleep_room")
    ok(client.post("/api/desk/move-sleep", json={"scheduleId": "sch-4", "room": "s01"}))
    c = customer(client, "sch-4")
    assert c["location"] == "s01" and c["prevRoom"] == "c01"
    err(place(client, "sch-5", "c01"), "room_held")
    ok(place(client, "sch-5", "c02"))
    err(client.post("/api/desk/move-sleep", json={"scheduleId": "sch-5", "room": "s01"}), "no_free_slot")
    ok(client.post("/api/desk/return-room", json={"scheduleId": "sch-4"}))
    assert customer(client, "sch-4")["location"] == "c01" and customer(client, "sch-4")["prevRoom"] is None
    err(client.post("/api/desk/return-room", json={"scheduleId": "sch-4"}), "not_in_sleep_room")


def test_5_discharge_midway_skips_rest(client, container):
    check_in(client, "sch-4", [{"kind": "consult"}, {"kind": "procedure", "label": "시술 가"},
                               {"kind": "procedure", "label": "시술 나"}])
    ok(place(client, "sch-4", "t01"))
    st = step(client, "sch-4", "consult")
    ok(assign(client, st["stepId"], "c1"))
    ok(start(client, "c1", st["stepId"]))
    err(client.post("/api/desk/discharge", json={"scheduleId": "sch-4"}), "step_in_progress")
    ok(finish(client, "c1", st["stepId"]))
    ok(client.post("/api/desk/discharge", json={"scheduleId": "sch-4"}))
    c = customer(client, "sch-4")
    assert c["location"] is None and c["flowStep"] == "COMPLETED" and c["status"] is None
    assert [s["state"] for s in c["steps"]] == ["done", "skipped", "skipped"]
    log = container.repo.load_state()["log"]
    skips = [x for x in log if x["scheduleId"] == "sch-4" and x["action"] == "skip"]
    assert len(skips) == 2 and all(x["detail"].startswith("진행 안 함") for x in skips)
    assert log[-1]["action"] == "discharge"


def test_6_revisit_bundles_and_visits(client):
    """재내원 — 후보 = 시술권 묶음 n/m, 고르면 1회 차감 · 지난 방문 카드는 언제나, 오늘 카드는 잠금."""
    cands = ok(client.get("/api/patients/sch-2/procedure-candidates"))
    assert [(c["bundleId"], c["name"], c["left"], c["total"], c["source"]) for c in cands] == [
        ("ticket:p0-0", "리쥬란 힐러 2cc", 1, 2, "ticket"), ("ticket:p0-1", "주름보톡스(국산)", 1, 1, "ticket"),
        ("ticket:grp-potenza", "포텐자 펌핑팁", 7, 10, "ticket")]
    before = ok(client.get("/api/patients/sch-2"))
    assert [v["today"] for v in before["visits"]] == [False]  # 접수 전: 지난 카드만
    past = before["visits"][0]
    assert past["date"] == "2026-09-20" and not past["locked"] and past["counselors"] == ["상담사A"]
    assert past["consultation"].startswith("[상담내용]\n고민:\nH)")  # 원문 그대로(빈 양식 줄 포함)
    assert past["orderMemo"] == "OUT TIME : x\n1. 리쥬란 힐러 2cc(얼전)\n2." and past["procedures"] == ["리쥬란 힐러 2cc"]
    assert before["tickets"] == [{k: c[k] for k in ("bundleId", "name", "left", "total")} for c in cands]

    check_in(client, "sch-2", [{"bundleId": "ticket:grp-potenza"}])
    assert [s["ticketId"] for s in customer(client, "sch-2")["steps"]] == ["pz-3"]
    # SPEC-002 §4: 접수 뒤 상담 종료 전엔 보유 시술권 후보 없음 · 차감은 시술 완료 때(D-32)라 n/m 그대로
    assert [c for c in ok(client.get("/api/patients/sch-2/procedure-candidates")) if c["source"] == "ticket"] == []
    err(client.post("/api/desk/add-procedures", json={"scheduleId": "sch-2", "bundleIds": ["ticket:p0-1"]}), "unknown_bundle")
    after = ok(client.get("/api/patients/sch-2"))
    assert next(t for t in after["tickets"] if t["bundleId"] == "ticket:grp-potenza")["left"] == 7
    assert [v["today"] for v in after["visits"]] == [True, False] and after["visits"][0]["locked"]  # 최근이 위


def test_no_show(client):
    ok(client.post("/api/desk/no-show", json={"scheduleId": "sch-5"}))
    row = next(r for r in board(client)["resv"] if r["scheduleId"] == "sch-5")
    assert row["st"] == "noshow"
    err(client.post("/api/desk/no-show", json={"scheduleId": "sch-5"}), "not_booked")
    err(client.post("/api/desk/check-in", json={"scheduleId": "sch-5", "steps": []}), "reservation_noshow")
    check_in(client, "sch-4", [])
    err(client.post("/api/desk/no-show", json={"scheduleId": "sch-4"}), "not_booked")


def test_7_login_five_roles_frames(client):
    accounts = ok(client.get("/api/staff"))
    assert accounts[0] == {"staffId": "desk", "name": "데스크", "role": "데스크", "frame": "desk"}
    got = {(a["staffId"], a["role"]) for a in accounts[1:]}
    assert got == {("d1", "의사"), ("d2", "의사"), ("c1", "상담사"), ("c2", "상담사"), ("s1", "피부관리사"), ("s2", "피부관리사"),
                   ("n1", "간호사"), ("n2", "간호사"), ("k1", "코디"), ("k2", "코디")}  # 마취용 제외 · 이벤트 상담사 더함
    frame = {"의사": "assigned", "상담사": "assigned", "피부관리사": "assigned", "간호사": "rounds", "코디": "rounds"}
    for a in accounts[1:]:
        r = ok(client.post("/api/login", json={"staffId": a["staffId"], "password": "x"}))
        assert r["home"] == "/staff" and r["frame"] == frame[a["role"]]
        assert ok(client.get(f"/api/staff/{a['staffId']}/home"))["frame"] == frame[a["role"]]
    r = client.post("/api/login", json={"staffId": "nobody"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "staff_not_found"


def test_blocks_and_undo(client):
    check_in(client, "sch-1", [{"kind": "consult"}])
    err(client.post("/api/desk/check-in", json={"scheduleId": "sch-1", "steps": []}), "already_checked_in")
    err(client.post("/api/desk/check-in", json={"scheduleId": "sch-3", "steps": []}), "reservation_canceled")
    err(place(client, "sch-1", "s01"), "not_treatment_room")
    check_in(client, "sch-4", [{"kind": "consult"}])
    check_in(client, "sch-5", [{"kind": "consult"}])
    ok(place(client, "sch-1", "c01"))
    err(place(client, "sch-4", "c01"), "room_full")
    ok(place(client, "sch-4", "t01"))
    v = ok(place(client, "sch-5", "t01"))["version"]  # 2인관리실 정원 2
    ok(client.post("/api/desk/undo", json={"version": v}))
    assert customer(client, "sch-5")["location"] == "reception"
    assert client.post("/api/desk/undo", json={"version": v + 1}).json()["error"]["code"] == "undo_unavailable"
    st = step(client, "sch-1", "consult")
    err(client.post("/api/desk/unassign", json={"stepId": st["stepId"]}), "not_assigned")
    ok(assign(client, st["stepId"], "c1"))
    ok(client.post("/api/desk/unassign", json={"stepId": st["stepId"]}))
    err(finish(client, "c1", st["stepId"]), "not_in_progress")
    r = client.post("/api/desk/assign", json={"stepId": "nope", "staffId": "c1"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "step_not_found"
    ok(client.post("/api/desk/add-procedures", json={"scheduleId": "sch-1", "items": [{"label": "직접 추가"}]}))
    assert step(client, "sch-1", "procedure")["label"] == "직접 추가"
    assert staff_of(client, "의사")


def test_reset_and_save(client, container):
    check_in(client, "sch-1", [{"kind": "consult"}])
    ok(client.post("/api/admin/reset"))
    assert board(client)["customers"] == []
    check_in(client, "sch-1", [{"kind": "consult"}])
    ok(place(client, "sch-1", "c04"))
    from app.seed.__main__ import _backup, _write

    path = container.settings.seed_path
    assert _backup(path) is not None
    _write(path, container.board.snapshot())
    ok(client.post("/api/desk/discharge", json={"scheduleId": "sch-1"}))
    ok(client.post("/api/admin/reset"))
    c = customer(client, "sch-1")
    assert c["location"] == "c04" and c["flowStep"] == "CONSULTATION_WAITING"
    assert abs(board(client)["now"] - c["since"]) < 60_000
