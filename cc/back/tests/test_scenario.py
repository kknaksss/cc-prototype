"""SPEC-001 0.2.1 §0-a — 시나리오 시드 · 상담 완료 이벤트 · [결제 완료] · 시술 완료 이벤트 · 응답에 이메일 등 없음."""

import json
import re

from app.seed.build import build_seed
from tests.helpers import assign, board, check_in, consult_done, customer, err, finish, ok, start


def test_consultation_done_adds_tasks_unpaid(client):
    consult_done(client, "sch-1", "c05")
    c = customer(client, "sch-1")
    added = [s for s in c["steps"] if s["kind"] != "consult"]
    got = [(s["kind"], s["label"], s["kosSequence"], s["state"], s["paymentRequired"], s["ticketId"]) for s in added]
    assert got == [
        ("doctor_consult", "원장 상담", 1, "planned", True, None),
        ("procedure", "울쎄라피 프라임 300shot", 2, "planned", True, None),
        ("procedure", "리쥬란 힐러 2cc", 3, "planned", True, None),
        ("procedure", "시트팩", 4, "planned", True, None),
    ]
    assert c["unpaidAmount"] == 1280000 and c["paid"] is False
    room = next(r for r in board(client)["rooms"] if r["id"] == "c05")
    assert room["unpaidAmount"] == 1280000
    assert c["flowStep"] == "CONSULTATION"  # 남은 단계가 생겨 귀가 대기가 아님
    d = ok(client.get("/api/patients/sch-1"))
    assert d["memoRevealed"] and d["unpaidAmount"] == 1280000
    # 빈 번호 「4.」 숨김
    assert d["order"]["lines"] == ["- 마취크림 : 40분", "1. 울쎄라 300샷(얼전)", "2. 리쥬란 2cc", "3. 시트팩"]
    assert d["order"]["anesthesia"] == "- 마취크림 : 40분" and d["outTime"] == "3시"
    assert {"text": "특이사항 — 아스피린 복용", "source": "오더 메모 · 상담 메모"} in d["cautions"]
    assert {"text": "임플란트 — 앞니 O", "source": "상담 메모"} in d["cautions"]
    assert "고민:처짐" in d["consult"]["lines"]
    assert {"label": "타 병원", "value": "H) 2월 울쎄라 하심", "source": "상담 메모"} in d["history"]
    assert not [r for r in d["chart"] if r["label"] in ("오늘 결제", "서비스(0원)")]  # 결제 완료 전
    assert ok(client.get("/api/patients/sch-1/procedure-candidates")) == []  # 이벤트 시술은 이미 동선에


def test_payment_complete(client):
    check_in(client, "sch-4", [{"kind": "consult"}])
    err(client.post("/api/desk/payment-complete", json={"scheduleId": "sch-4"}), "nothing_to_pay")  # 상담 완료 전
    consult_done(client, "sch-1", "c05")
    ok(client.post("/api/desk/payment-complete", json={"scheduleId": "sch-1"}))
    c = customer(client, "sch-1")
    assert c["unpaidAmount"] == 0 and c["paid"] is True
    assert all(not s["paymentRequired"] for s in c["steps"])
    assert [s["ticketId"] for s in c["steps"]] == [None, None, "tk-2", "tk-3", "tk-4"]  # 원장 상담은 시술권 없음
    d = ok(client.get("/api/patients/sch-1"))
    chart = {r["label"]: r["value"] for r in d["chart"]}
    assert chart["오늘 결제"] == "[첫방문] 울쎄라 300샷 990,000원, 리쥬란 힐러 2cc 290,000원" and chart["서비스(0원)"] == "시트팩"
    err(client.post("/api/desk/payment-complete", json={"scheduleId": "sch-1"}), "nothing_to_pay")


def test_task_done_reveals_assignee_memo(client):
    consult_done(client, "sch-1", "c05")
    p = next(s for s in customer(client, "sch-1")["steps"] if s["kosSequence"] == 2)
    route = {r["stepId"]: r for r in ok(client.get("/api/patients/sch-1"))["route"]}
    assert route[p["stepId"]]["memo"] == "" and route[p["stepId"]]["paymentRequired"]
    ok(assign(client, p["stepId"], "d1"))
    ok(start(client, "d1", p["stepId"]))
    assert {r["stepId"]: r for r in ok(client.get("/api/patients/sch-1"))["route"]}[p["stepId"]]["memo"] == ""
    ok(finish(client, "d1", p["stepId"]))
    route = {r["stepId"]: r for r in ok(client.get("/api/patients/sch-1"))["route"]}
    assert route[p["stepId"]]["memo"] == "어시 간호A / 시트증정"
    # 이벤트가 없는 시술(시트팩 seq 4)은 메모 없음
    p4 = next(s for s in customer(client, "sch-1")["steps"] if s["kosSequence"] == 4)
    ok(assign(client, p4["stepId"], "s1"))
    ok(start(client, "s1", p4["stepId"]))
    ok(finish(client, "s1", p4["stepId"]))
    assert {r["stepId"]: r for r in ok(client.get("/api/patients/sch-1"))["route"]}[p4["stepId"]]["memo"] == ""


def test_consult_without_event_and_empty_event(client):
    consult_done(client, "sch-4", "c06", counselor_id="c1")  # 상담만 하심 — 시술 0 · 금액 0
    c = customer(client, "sch-4")
    assert [s["kind"] for s in c["steps"]] == ["consult"] and c["unpaidAmount"] == 0
    assert c["flowStep"] == "PROCEDURE_DONE" and c["status"]["label"] == "귀가 대기"
    consult_done(client, "sch-5", "c07", counselor_id="c1")  # 이벤트 파일 없음
    d = ok(client.get("/api/patients/sch-5"))
    assert d["memoRevealed"] and d["order"] is None and d["consult"] is None


def test_staff_backup_rule_without_staff_ids(scenario, accounts):
    seed, events = scenario
    snap, notes = build_seed({**seed, "staffIds": []}, events, accounts)
    roles = {s["staffId"]: s["role"] for s in snap["state"]["staff"]}
    assert roles == {"c1": "상담사", "c2": "상담사", "k1": "코디", "k2": "코디"}  # 이벤트 상담사 + COORDINATOR 활성
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
    for key in ('"email"', '"dateOfBirth"', '"phoneNumber"', '"chartNumber"', "1990-05-01"):
        assert key not in text
    staff = {s["name"] for s in b["staff"]}
    for r in b["resv"]:
        d = ok(client.get(f"/api/patients/{r['scheduleId']}"))
        srcs = [c["source"] for c in d["cautions"]] + [h["source"] for h in d["history"]]
        srcs += [sec["source"] for sec in (d["order"], d["consult"], d["reception"]) if sec]
        assert not [s for s in srcs if any(n in s for n in staff)]



def test_name_prefix_removed(client):
    """WP7c — 고객 이름 앞 국적 접두(`[TW] `)를 뗀다. 국적 값은 그대로."""
    check_in(client, "sch-4", [])
    rows = {r["scheduleId"]: r for r in board(client)["resv"]}
    assert rows["sch-4"]["name"] == "CHEN YU" and rows["sch-4"]["nationality"] == "TW"
    assert rows["sch-5"]["name"] == "SATO AOI"
    assert customer(client, "sch-4")["name"] == "CHEN YU"
    assert ok(client.get("/api/patients/sch-4"))["name"] == "CHEN YU"
    rounds = ok(client.get("/api/staff/n1/home"))["patients"]
    assert [p["name"] for p in rounds] == ["CHEN YU"]
    assert "[TW]" not in json.dumps(board(client), ensure_ascii=False)
