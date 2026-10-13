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
    assert before["flowStep"] == "RESERVED" and before["order"] is None and before["consult"] is None

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
    assert home["frame"] == "assigned" and [n["stepId"] for n in home["next"]] == [st["stepId"]]  # 상담사 화면 「다음」
    mid = ok(client.get("/api/patients/sch-1", params={"staffId": "c2"}))
    assert mid["myActions"] == [{"stepId": st["stepId"], "kind": "consult", "action": "start", "label": "상담 시작"}]
    assert mid["order"] is None and not mid["memoRevealed"]

    ok(client.post("/api/staff/c2/start", json={"stepId": st["stepId"]}))
    c = customer(client, "sch-1")
    assert c["flowStep"] == "CONSULTATION" and c["status"]["key"] == "consult"
    ok(finish(client, "c2", st["stepId"]))
    after = ok(client.get("/api/patients/sch-1"))
    assert after["memoRevealed"] and after["order"] and after["consult"]  # 상담 · 오더 메모가 이때 열림
    assert after["counselor"] == "상담사B"
    assert ok(client.get("/api/staff/c2/home"))["done"][0]["stepId"] == st["stepId"]


def test_3_procedures_reorder_assign_start_finish(client):
    consult_done(client, "sch-1", "c05")
    ss = customer(client, "sch-1")["steps"]
    assert [s["kind"] for s in ss] == ["consult", "doctor_consult", "procedure", "procedure", "procedure"]
    # 순서 바꾸기 — 남은 단계만 보내도 된다(시트팩을 시술 맨 앞으로)
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
    err(start(client, "d2", p1["stepId"]), "not_my_step")  # 배정 안 된 직원은 시작 못 함
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

    p2 = step(client, "sch-1", "procedure", 1)
    ok(assign(client, p2["stepId"], "s1"))
    ok(start(client, "s1", p2["stepId"]))
    ok(finish(client, "s1", p2["stepId"]))
    assert [s["state"] for s in customer(client, "sch-1")["steps"]] == ["done", "done", "done", "done", "planned"]
    ids = [s["stepId"] for s in customer(client, "sch-1")["steps"]]
    swapped = [ids[1], ids[0]] + ids[2:]
    err(client.post("/api/desk/reorder", json={"scheduleId": "sch-1", "stepIds": swapped}), "done_step_moved")


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


def test_6_revisit_default_tickets(client):
    r = next(x for x in board(client)["resv"] if x["scheduleId"] == "sch-2")
    assert r["isNew"] is False
    cands = ok(client.get("/api/patients/sch-2/procedure-candidates"))
    assert [(c["label"], c["ticketId"], c["source"]) for c in cands] == [
        ("리쥬란 힐러 2cc", "t-a", "ticket"), ("주름보톡스(국산)", "t-c", "ticket")]  # USED 장은 빠짐
    check_in(client, "sch-2", [{"kind": "procedure", "label": c["label"], "ticketId": c["ticketId"]} for c in cands])
    assert [s["ticketId"] for s in customer(client, "sch-2")["steps"]] == ["t-a", "t-c"]
    assert ok(client.get("/api/patients/sch-2/procedure-candidates")) == []
    d = ok(client.get("/api/patients/sch-2"))
    assert d["isNew"] is False and d["tickets"] == [{"name": "리쥬란 힐러 2cc", "left": 1, "total": 2},
                                                   {"name": "주름보톡스(국산)", "left": 1, "total": 1}]
    past = d["pastSchedules"][0]
    assert past["date"] == "2026-09-20" and past["procedures"] == ["리쥬란 힐러 2cc"] and past["synthetic"]
    assert past["order"]["lines"] == ["1. 리쥬란 힐러 2cc(얼전)"]  # 빈 번호 줄 「2.」 숨김
    assert {"label": "이 병원", "value": "2026-09-20 · 리쥬란 힐러 2cc", "source": "지난 방문"} in d["history"]


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
    err(client.post("/api/desk/add-procedures", json={"scheduleId": "sch-1", "items": [
        {"label": "A", "ticketId": "x"}, {"label": "B", "ticketId": "x"}]}), "duplicate_ticket")
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
