"""SPEC-001 0.2.1 §0-a · 0.3.0 §0-b — 시나리오 시드 · 상담 종료 → 후보만 · [결제 완료] · 시술 완료 메모(방문 카드) ·
원문 그대로 · 위험 단어 · 지정 직원 · 응답에 이메일 등 없음."""

import json
import re
from pathlib import Path

from app.seed.build import build_seed
from tests.helpers import assign, board, check_in, consult_done, customer, err, finish, ok, place, start, step

APP = Path(__file__).resolve().parent.parent / "app"
FIX = Path(__file__).resolve().parent / "fixtures" / "scenario"


def test_consultation_done_gives_candidates_only(client):
    consult_done(client, "sch-1", "c05")
    c = customer(client, "sch-1")
    assert [s["kind"] for s in c["steps"]] == ["consult"]  # 동선에 붙이지 않는다
    assert c["unpaidAmount"] == 1280000 and c["paid"] is False
    assert next(r for r in board(client)["rooms"] if r["id"] == "c05")["unpaidAmount"] == 1280000
    cands = [b for b in ok(client.get("/api/patients/sch-1/procedure-candidates")) if b["source"] == "today"]
    assert [(b["kind"], b["name"], b["left"], b["total"], b.get("paymentRequired")) for b in cands] == [
        ("doctor_consult", "원장 상담", 1, 1, None),
        ("procedure", "울쎄라피 프라임 300shot", 1, 1, True),
        ("procedure", "리쥬란 힐러 2cc", 1, 1, True),
        ("procedure", "시트팩", 1, 1, True),
    ]
    d = ok(client.get("/api/patients/sch-1"))
    assert d["memoRevealed"] and d["unpaidAmount"] == 1280000
    assert not [r for r in d["chart"] if r["label"] in ("오늘 결제", "서비스(0원)")]  # 결제 완료 전


def test_doctor_consult_candidate_not_duplicated(client):
    check_in(client, "sch-1", [{"kind": "consult"}, {"kind": "doctor_consult"}])
    ok(place(client, "sch-1", "c05"))
    st = step(client, "sch-1", "consult")
    ok(assign(client, st["stepId"], "c2"))
    ok(start(client, "c2", st["stepId"]))
    ok(finish(client, "c2", st["stepId"]))
    cands = ok(client.get("/api/patients/sch-1/procedure-candidates"))
    assert not [b for b in cands if b["kind"] == "doctor_consult"]  # 동선에 이미 원장 상담이 있으면 뺀다
    assert [s["kind"] for s in customer(client, "sch-1")["steps"]].count("doctor_consult") == 1


def test_payment_complete_links_tickets(client):
    check_in(client, "sch-4", [{"kind": "consult"}])
    err(client.post("/api/desk/payment-complete", json={"scheduleId": "sch-4"}), "nothing_to_pay")  # 상담 완료 전
    consult_done(client, "sch-1", "c05")
    ok(client.post("/api/desk/add-procedures", json={"scheduleId": "sch-1", "bundleIds": ["today:울쎄라피 프라임 300shot"]}))
    s = customer(client, "sch-1")["steps"][-1]
    assert s["paymentRequired"] and s["ticketId"] is None and s["kosSequence"] == 2
    ok(client.post("/api/desk/payment-complete", json={"scheduleId": "sch-1"}))
    c = customer(client, "sch-1")
    assert c["unpaidAmount"] == 0 and c["paid"] is True
    assert [(x["ticketId"], x["paymentRequired"]) for x in c["steps"]] == [(None, False), ("tk-2", False)]
    cands = {b["bundleId"]: b for b in ok(client.get("/api/patients/sch-1/procedure-candidates"))}
    assert cands["today:리쥬란 힐러 2cc"]["paymentRequired"] is False  # 결제 뒤 후보는 시술권과 함께
    ok(client.post("/api/desk/add-procedures", json={"scheduleId": "sch-1", "bundleIds": ["today:리쥬란 힐러 2cc"]}))
    assert customer(client, "sch-1")["steps"][-1]["ticketId"] == "tk-3"
    chart = {r["label"]: r["value"] for r in ok(client.get("/api/patients/sch-1"))["chart"]}
    assert chart["오늘 결제"] == "[첫방문] 울쎄라 300샷 990,000원, 리쥬란 힐러 2cc 290,000원" and chart["서비스(0원)"] == "시트팩"
    err(client.post("/api/desk/payment-complete", json={"scheduleId": "sch-1"}), "nothing_to_pay")


def test_task_done_memo_only_in_visit_card(client):
    consult_done(client, "sch-1", "c05")
    ok(client.post("/api/desk/add-procedures", json={"scheduleId": "sch-1", "bundleIds": ["today:울쎄라피 프라임 300shot"]}))
    p = customer(client, "sch-1")["steps"][-1]
    ok(assign(client, p["stepId"], "d1"))
    ok(start(client, "d1", p["stepId"]))
    assert ok(client.get("/api/patients/sch-1"))["visits"][0]["assigneeMemos"] == []
    ok(finish(client, "d1", p["stepId"]))
    d = ok(client.get("/api/patients/sch-1"))
    assert d["visits"][0]["assigneeMemos"] == [{"label": "울쎄라피 프라임 300shot", "memo": "어시 간호A / 시트증정"}]
    assert d["visits"][0]["procedures"] == ["울쎄라피 프라임 300shot"]
    assert all("memo" not in r for r in d["route"])  # 동선에는 담당자 메모 없음


def test_consult_without_event_and_empty_event(client):
    consult_done(client, "sch-4", "c06", counselor_id="c1")  # 상담만 — 후보 0 · 금액 0
    c = customer(client, "sch-4")
    assert [s["kind"] for s in c["steps"]] == ["consult"] and c["unpaidAmount"] == 0
    assert c["flowStep"] == "PROCEDURE_DONE" and c["status"]["label"] == "귀가 대기"
    assert ok(client.get("/api/patients/sch-4"))["visits"][0]["consultation"] == "[상담내용]\n상담만 하심\n------\n"
    consult_done(client, "sch-5", "c07", counselor_id="c1")  # 이벤트 파일 없음
    today = ok(client.get("/api/patients/sch-5"))["visits"][0]
    assert not today["locked"] and today["consultation"] is None and today["orderMemo"] is None


def test_memos_raw_no_unfounded_marks(client):
    raw = json.loads((FIX / "seed.json").read_text())["schedules"][0]["reservation"]["reservationMemo"]
    ev = json.loads((FIX / "events" / "sch-1.json").read_text())["consultationDone"]
    d = ok(client.get("/api/patients/sch-1"))
    assert d["reservationMemo"] == raw  # 원문 그대로
    consult_done(client, "sch-1", "c05")
    d = ok(client.get("/api/patients/sch-1"))
    assert d["visits"][0]["consultation"] == ev["consultation"]["content"]["text"]
    assert d["visits"][0]["orderMemo"] == ev["orderMemo"]
    # WP12 — 근거 없는 표시(지정 직원 추정 · 위험 단어) 없음
    for gone in ("cautions", "order", "consult", "reception", "history", "pastSchedules", "riskWords", "riskHits",
                 "mentionedStaffIds"):
        assert gone not in d
    assert d["outTime"] is None  # 메모 속 아웃 시각은 뽑지 않는다(KOS desiredDischargeDateTimeUtc 만)
    b = board(client)
    cust = next(c for c in b["customers"] if c["scheduleId"] == "sch-1")
    assert "mentionedStaffIds" not in cust and "riskWords" not in b
    row = next(r for r in board(client)["resv"] if r["scheduleId"] == "sch-1")
    assert "procedure" not in row and "doctor" not in row


def test_no_memo_form_parsing_in_code():
    """양식 문자열 가공 0 — 메모를 자르거나 뽑는 코드가 없다(grep, 주석 · 독스트링 제외)."""
    patterns = [r"------", r"OUT\s*TIME", r"특이사항", r"임플란트 여부", r"\[상담내용\]", r"받은\s*시술"]
    hits = []
    for p in APP.rglob("*.py"):
        in_doc = False
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if line.count('"""') == 1:
                in_doc = not in_doc
                continue
            if in_doc or '"""' in line:
                continue
            code = line.split("#", 1)[0]
            if any(re.search(pt, code) for pt in patterns):
                hits.append(f"{p.relative_to(APP)}:{i}: {line.strip()}")
    assert hits == []
    assert not (APP / "service" / "memo_parse.py").exists()


def test_staff_backup_rule_without_staff_ids(scenario, accounts):
    seed, events = scenario
    snap, notes = build_seed({**seed, "staffIds": []}, events, accounts)
    roles = {s["staffId"]: s["role"] for s in snap["state"]["staff"]}
    assert roles == {"c1": "상담사", "c2": "상담사", "k1": "코디", "k2": "코디"}
    assert any("백업 규칙" in n for n in notes)


def test_responses_have_no_email_birth_phone(client, accounts):
    consult_done(client, "sch-1", "c05")
    ok(client.post("/api/desk/payment-complete", json={"scheduleId": "sch-1"}))
    check_in(client, "sch-2", [])
    b = board(client)
    blobs = [b, client.get("/api/staff").json()]
    blobs += [client.get(f"/api/staff/{s['staffId']}/home").json() for s in b["staff"]]
    for r in b["resv"]:
        blobs.append(client.get(f"/api/patients/{r['scheduleId']}").json())
        blobs.append(client.get(f"/api/patients/{r['scheduleId']}/procedure-candidates").json())
    text = json.dumps(blobs, ensure_ascii=False)
    assert not [a["email"] for a in accounts if a["email"] in text]
    assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", text)
    for key in ('"email"', '"dateOfBirth"', '"phoneNumber"', '"chartNumber"', "1990-05-01", '"cautions"', '"members"'):
        assert key not in text


def test_name_prefix_removed(client):
    """WP7c — 고객 이름 앞 국적 접두(`[TW] `)를 뗀다. 국적 값은 그대로."""
    check_in(client, "sch-4", [])
    rows = {r["scheduleId"]: r for r in board(client)["resv"]}
    assert rows["sch-4"]["name"] == "CHEN YU" and rows["sch-4"]["nationality"] == "TW"
    assert rows["sch-5"]["name"] == "SATO AOI"
    assert customer(client, "sch-4")["name"] == "CHEN YU"
    assert ok(client.get("/api/patients/sch-4"))["name"] == "CHEN YU"
    assert [p["name"] for p in ok(client.get("/api/staff/n1/home"))["patients"]] == ["CHEN YU"]


def test_fix1_candidates_left_is_next_not_discharge(client):
    """상담 종료 뒤 남은 단계가 없어도 오늘 후보 · 미결제가 있으면 「다음 단계 대기」(확인 필요)."""
    consult_done(client, "sch-1", "c05")
    st = customer(client, "sch-1")["status"]
    assert st == {"key": "wait", "label": "다음 단계 대기", "need": "next"}
    rounds = ok(client.get("/api/staff/n1/home"))
    assert next(p for p in rounds["patients"] if p["scheduleId"] == "sch-1")["need"] == "next"
    # 결제만 끝나도 후보가 남아 있으면 그대로
    ok(client.post("/api/desk/payment-complete", json={"scheduleId": "sch-1"}))
    assert customer(client, "sch-1")["status"]["need"] == "next"
    # 오늘 결제 시술을 다 넣고 다 끝내면 귀가 대기
    ids = [b["bundleId"] for b in ok(client.get("/api/patients/sch-1/procedure-candidates"))
           if b["source"] == "today" and b["kind"] == "procedure"]
    ok(client.post("/api/desk/add-procedures", json={"scheduleId": "sch-1", "bundleIds": ids}))
    for s in [x for x in customer(client, "sch-1")["steps"] if x["state"] == "planned"]:
        ok(assign(client, s["stepId"], "d1"))
        ok(start(client, "d1", s["stepId"]))
        ok(finish(client, "d1", s["stepId"]))
    assert customer(client, "sch-1")["status"] == {"key": "wait", "label": "귀가 대기", "need": "discharge"}


def test_fix1_only_held_tickets_left_is_discharge(client):
    """보유 시술권(지난 결제분)만 남은 재내원 고객은 귀가 대기 그대로."""
    check_in(client, "sch-2", [{"kind": "consult"}])
    ok(place(client, "sch-2", "c06"))
    st = step(client, "sch-2", "consult")
    ok(assign(client, st["stepId"], "c1"))
    ok(start(client, "c1", st["stepId"]))
    ok(finish(client, "c1", st["stepId"]))  # sch-2 는 상담 완료 이벤트 없음
    assert [b["source"] for b in ok(client.get("/api/patients/sch-2/procedure-candidates"))] == ["ticket"] * 3
    assert customer(client, "sch-2")["status"] == {"key": "wait", "label": "귀가 대기", "need": "discharge"}
    # 미결제만 있어도(이벤트 시술 0) 확인 필요 — sch-4 는 금액 0 · 시술 0 이라 귀가 대기
    consult_done(client, "sch-4", "c07", counselor_id="c1")
    assert customer(client, "sch-4")["status"]["need"] == "discharge"
