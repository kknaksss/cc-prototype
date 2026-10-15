"""SPEC-002 §4 · §5.1 — 시드 칸 · 응답 칸 · 시술권 차감 시점 · 추가 요청 메모 · 시술 후보 정정."""

from tests.helpers import assign, board, check_in, consult_done, customer, err, finish, ok, place, start, step

VIP = {"phoneticName": "린메이", "phone": "+886 900 000 001", "vip": True}
KR = {"phoneticName": None, "phone": "+82 10 0000 0002", "vip": False}
NONE = {"phoneticName": None, "phone": None, "vip": False}  # 시나리오에 칸이 없는 고객
KEYS = ("phoneticName", "phone", "vip")


def pick(x: dict) -> dict:
    return {k: x[k] for k in KEYS}


def resv(client, sid):
    return next(r for r in board(client)["resv"] if r["scheduleId"] == sid)


def patient(client, sid):
    return ok(client.get(f"/api/patients/{sid}"))


def memo(client, sid, category, text):
    return client.post("/api/desk/memo", json={"scheduleId": sid, "category": category, "text": text})


def holding(client, sid, bundle_id):
    return next(t for t in patient(client, sid)["tickets"] if t["bundleId"] == bundle_id)


# ── 1 · 2. 시드 칸 → 고객이 나오는 응답 전부 ──


def test_seed_fields_in_board_resv(client):
    assert pick(resv(client, "sch-1")) == VIP
    assert pick(resv(client, "sch-2")) == KR
    assert pick(resv(client, "sch-4")) == NONE
    assert all("memoAdds" not in r for r in board(client)["resv"])


def test_person_fields_everywhere(client):
    assert pick(patient(client, "sch-1")) == VIP  # 예약 상세(접수 전)
    consult_done(client, "sch-1")  # 접수 → c01 → 상담사 c2 시작 · 종료
    assert pick(customer(client, "sch-1")) == VIP
    assert pick(patient(client, "sch-1")) == VIP
    # 직원 홈 — 배정형(완료 줄) · 순회형(내원 목록)
    home = ok(client.get("/api/staff/c2/home"))
    assert pick(home["done"][0]) == VIP
    rounds = ok(client.get("/api/staff/k1/home"))
    assert pick(next(p for p in rounds["patients"] if p["scheduleId"] == "sch-1")) == VIP
    # 현황판 직원의 지금 일
    check_in(client, "sch-2", [{"kind": "consult"}])
    ok(place(client, "sch-2", "c02"))
    ok(assign(client, step(client, "sch-2", "consult")["stepId"], "c1"))
    work = next(s for s in board(client)["staff"] if s["staffId"] == "c1")["work"]
    assert pick(work[0]) == KR


def test_seed_build_reads_fields(seed):
    rows = {r["scheduleId"]: r for r in seed["state"]["resv"]}
    assert pick(rows["sch-1"]) == VIP and pick(rows["sch-4"]) == NONE
    v = seed["reference"]["schedule"]["sch-1"]["visitor"]
    assert "phone" not in v and "phoneticName" not in v and v["categories"][0]["name"] == "vip500"


def test_seed_save_keeps_fields(client, container):
    snap = container.board.snapshot()
    assert pick(next(r for r in snap["state"]["resv"] if r["scheduleId"] == "sch-1")) == VIP


# ── 3. 시술권 차감 = 시술 완료 · 5. 후보 정정(§4) ──


def test_ticket_deducted_on_finish_and_candidates(client):
    pz = "ticket:grp-potenza"
    assert holding(client, "sch-2", pz) == {"bundleId": pz, "name": "포텐자 펌핑팁", "left": 7, "total": 10}
    # 접수 모달(접수 전)에는 보유 시술권 후보가 있다
    assert {c["bundleId"] for c in ok(client.get("/api/patients/sch-2/procedure-candidates"))} >= {pz, "ticket:p0-1"}
    check_in(client, "sch-2", [{"bundleId": pz}, {"kind": "consult"}])
    assert holding(client, "sch-2", pz)["left"] == 7  # 접수 = 오늘 사용 예정, 차감 아님
    # 접수 뒤 상담 종료 전 — 보유 시술권 후보 없음
    assert [c for c in ok(client.get("/api/patients/sch-2/procedure-candidates")) if c["source"] == "ticket"] == []

    ok(place(client, "sch-2", "c01"))
    cs = step(client, "sch-2", "consult")["stepId"]
    ok(assign(client, cs, "c1"))
    ok(start(client, "c1", cs))
    ok(finish(client, "c1", cs))  # 상담 종료 → 후보 다시. 동선에 회차가 있는 묶음(포텐자)은 통째로 빠진다
    ids = [c["bundleId"] for c in ok(client.get("/api/patients/sch-2/procedure-candidates")) if c["source"] == "ticket"]
    assert ids == ["ticket:p0-0", "ticket:p0-1"]
    ok(client.post("/api/desk/add-procedures", json={"scheduleId": "sch-2", "bundleIds": ["ticket:p0-1"]}))
    err(client.post("/api/desk/add-procedures", json={"scheduleId": "sch-2", "bundleIds": ["ticket:p0-1"]}), "unknown_bundle")

    ps = step(client, "sch-2", "procedure")["stepId"]
    ok(assign(client, ps, "s1"))
    ok(start(client, "s1", ps))
    assert holding(client, "sch-2", pz)["left"] == 7  # 진행 중 = 아직
    ok(finish(client, "s1", ps))
    assert holding(client, "sch-2", pz)["left"] == 6  # 완료 = 차감
    chart = {r["label"]: r["value"] for r in patient(client, "sch-2")["chart"]}
    assert "포텐자 펌핑팁 6/10회" in chart["보유 시술권"]


def test_skipped_ticket_not_deducted(client):
    check_in(client, "sch-2", [{"bundleId": "ticket:grp-potenza"}])
    ok(client.post("/api/desk/discharge", json={"scheduleId": "sch-2"}))  # 진행 안 함
    assert holding(client, "sch-2", "ticket:grp-potenza")["left"] == 7


# ── 4. 추가 요청 메모 ──


def test_memo_reservation_and_consultation(client):
    v0 = board(client)["version"]
    assert ok(memo(client, "sch-1", "reservation", "  우산 맡김  ")) == {"version": v0 + 1}
    p = patient(client, "sch-1")
    assert p["reservationMemo"].endswith("상담사A 지정 요청\n우산 맡김")
    # 상담 메모 — 접수 뒤 상담 종료 전에도 덧붙인 줄은 바로 보인다(잠금 예외)
    check_in(client, "sch-1", [{"kind": "consult"}])
    ok(memo(client, "sch-1", "consultation", "목 주름도 상담 원함"))
    today = patient(client, "sch-1")["visits"][0]
    assert today["today"] and today["locked"] and today["consultation"] == "목 주름도 상담 원함"
    # 상담 종료 이벤트가 상담 메모를 채워도 덧붙인 줄은 남는다(끝에)
    ok(place(client, "sch-1", "c01"))
    cs = step(client, "sch-1", "consult")["stepId"]
    ok(assign(client, cs, "c2"))
    ok(start(client, "c2", cs))
    ok(finish(client, "c2", cs))
    today = patient(client, "sch-1")["visits"][0]
    assert not today["locked"]
    assert today["consultation"].startswith("[상담내용]\n고민:처짐") and today["consultation"].endswith("\n목 주름도 상담 원함")
    ok(memo(client, "sch-1", "consultation", "둘째 줄"))
    assert patient(client, "sch-1")["visits"][0]["consultation"].endswith("목 주름도 상담 원함\n둘째 줄")
    log = [x for x in container_log(client) if x["action"] == "memo"]
    assert len(log) == 3


def container_log(client):
    return client.app.state.container.repo.load_state()["log"]


def test_memo_empty_original(client):
    ok(memo(client, "sch-3", "reservation", "첫 줄"))  # 원문이 빈 예약 메모(취소 예약)
    assert patient(client, "sch-3")["reservationMemo"] == "첫 줄"


def test_memo_errors_and_undo(client):
    for text in ("", "   "):
        err(memo(client, "sch-1", "reservation", text), "empty_memo")
    err(memo(client, "sch-1", "order", "x"), "invalid_request")
    r = memo(client, "nope", "reservation", "x")
    assert r.status_code == 404 and r.json()["error"]["code"] == "reservation_not_found"
    v = ok(memo(client, "sch-1", "reservation", "되돌릴 줄"))["version"]
    ok(client.post("/api/desk/undo", json={"version": v}))
    assert "되돌릴 줄" not in patient(client, "sch-1")["reservationMemo"]


def test_check_in_with_memo(client):
    ok(client.post("/api/desk/check-in", json={"scheduleId": "sch-2", "steps": [{"kind": "consult"}],
                                               "memo": {"category": "reservation", "text": "보호자 동행"}}))
    assert patient(client, "sch-2")["reservationMemo"] == "재내원 · 리쥬란 이어서\n보호자 동행"
    ok(client.post("/api/desk/check-in", json={"scheduleId": "sch-4", "steps": [{"kind": "consult"}],
                                               "memo": {"category": "consultation", "text": "통역 먼저"}}))
    assert patient(client, "sch-4")["visits"][0]["consultation"] == "통역 먼저"
    # 빈 메모를 주면 접수 전체가 400(접수도 안 된다) — 메모가 없으면 memo 칸을 빼고 보낸다
    err(client.post("/api/desk/check-in", json={"scheduleId": "sch-5", "steps": [],
                                                "memo": {"category": "reservation", "text": " "}}), "empty_memo")
    assert all(c["scheduleId"] != "sch-5" for c in board(client)["customers"])
