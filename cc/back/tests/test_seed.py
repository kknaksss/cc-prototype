"""시드 build(10-09 14:45) · 이름 치환 대조 — SPEC-001 §4.1 · §9-1."""

import json
import re

from app.domain.rooms import ROOM_IDS
from app.seed.names import NAME_LINE, normalize

HANGUL = re.compile(r"[가-힣]")


def test_build_1009(seed):
    st = seed["state"]
    assert len(st["resv"]) == 27
    here = [c for c in st["customers"] if not c["done"]]
    assert len(here) == 5
    assert all(c["room"] == "lounge" or c["room"] in ROOM_IDS for c in here)
    assert all(isinstance(c["sinceOffset"], int) and c["sinceOffset"] >= 0 for c in here)
    roles = {s["role"] for s in st["staff"]}
    assert roles == {"의사", "상담사", "코디"}
    assert not any(s["name"] == "마취용" for s in st["staff"])
    assert {r["st"] for r in st["resv"]} <= {"booked", "checked", "noshow", "canceled"}
    assert st["history"], "T 이전에 끝난 단계는 완료 기록으로"


def _real_names(capture) -> set[str]:
    names: set[str] = set()
    for d in capture.schedules():
        v = d["visitor"]
        names.update(x for x in (v.get("name"), v.get("phoneticName")) if x)
        names.update(c["visitor"]["name"] for c in d.get("consultations") or [])
        memos = [d.get("orderMemo"), d["reservation"].get("reservationMemo"), v.get("memo"),
                 (d.get("consultation") or {}).get("consultationMemo")]
        memos += [(c.get("content") or {}).get("text") for c in d.get("consultations") or []]
        for m in memos:
            names.update(x.group(2).strip() for x in NAME_LINE.finditer(m or "") if x.group(2).strip())
    return names


def _staff_and_funnel_names(capture) -> set[str]:
    """직원 · 유입처 이름 — 다른 날 고객과 같아도 바꾸지 않는다(D-09 · design-staff-r2 이슈 3)."""
    out: set[str] = set()
    for d in capture.schedules():
        for t in d.get("tasks") or []:
            for k in ("doctors", "assignees", "calledDoctors"):
                out.update(p["name"] for p in t.get(k) or [] if p.get("name"))
        for c in d.get("consultations") or []:
            out.update(p["name"] for p in c.get("counselors") or [] if p.get("name"))
        for ew in d.get("etceteraWorks") or []:
            out.update(p["name"] for p in ew.get("assignees") or [] if p.get("name"))
        out.add(((d.get("reservation") or {}).get("reservationAssignee") or {}).get("name") or "")
        funnel = ((d.get("reservation") or {}).get("funnel") or {}).get("funnel") or {}
        out.update(re.split(r"[()]", funnel.get("name") or ""))
    return {x.strip() for x in out if x and x.strip()}


def _all_responses(client) -> str:
    board = client.get("/api/board").json()
    blobs = [board, client.get("/api/staff").json()]
    blobs += [client.get(f"/api/staff/{s['staffId']}/home").json() for s in board["staff"]]
    blobs += [client.get(f"/api/patients/{r['scheduleId']}").json() for r in board["resv"]]
    return json.dumps(blobs, ensure_ascii=False)


def _hits(text: str, names: set[str]) -> list[str]:
    norm = normalize(text)
    hits = []
    for raw in sorted(names):
        n = normalize(raw)
        if len(n) < 2:
            continue
        if HANGUL.search(raw):
            # 두 글자 이름은 낱말 안 부분 일치(「아이이슈링크」의 「이이」)를 빼고 본다
            pat = re.escape(raw) if len(n) >= 3 else rf"(?<![가-힣]){re.escape(raw)}(?![가-힣])"
            if re.search(pat, text):
                hits.append(raw)
        elif raw in text or (len(n) >= 6 and n in norm):
            hits.append(raw)
    return hits


def test_no_real_customer_names_in_any_response(client, capture):
    names = _real_names(capture)
    assert len(names) > 177  # visitor.name 177건(고유 173) + phoneticName + 메모 「이름 :」 값
    exempt = _staff_and_funnel_names(capture)
    hits = _hits(_all_responses(client), names)
    leaked = [h for h in hits if h not in exempt]
    assert leaked == [], leaked


def test_no_phone_chart_birth_in_responses(client, capture):
    text = _all_responses(client)
    for key in ('"chartNumber"', '"dateOfBirth"', '"phoneNumber"', '"phone"'):
        assert key not in text
    todays = [d for d in capture.schedules() if d["id"] in {r["scheduleId"] for r in client.get("/api/board").json()["resv"]}]
    for d in todays:
        v = d["visitor"]
        phone = (v.get("phone") or {}).get("phoneNumber")
        if phone and len(phone) >= 7:
            assert phone not in text
        dob = (v.get("dateOfBirth") or "")[:10]
        if dob:
            assert dob not in text
    assert not re.search(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)", text.replace("010-****-****", ""))
