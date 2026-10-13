"""시드 만들기 — SPEC-001 0.2.1 §0-a · §6. **시나리오 파일**(`data/scenario/`)로 **개원 전** 상태를 만든다.

- `seed.json` = 「아침에 KOS 에서 받아 온 것」: 예약 · 고객 · 보유 시술권 · 이전 상담 기록 · 오늘 근무 직원(`staffIds`)
- `events/<scheduleId>.json` = 「진행하다 KOS 에서 들어오는 것」: 상담 완료 · 결제 완료 · 시술 완료 — 참조 데이터로 넣어 두고
  조작(상담 종료 · [결제 완료] · 시술 종료) 때 꺼내 쓴다
- 형식: orchestration/work/sts-prototype/scenario-format.md. 이름 치환(D-09)은 시나리오가 이미 했다(가짜 이름)
- 직원 · 직군: KOS getAccounts 저장본(`CC_KOS_STAFF_PATH`)의 roleTags → 5직군(§4)
"""

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

from app.seed.capture import hhmm, parse_ts

ANESTHESIA_ONLY = "마취용"  # D-22: 의사 칸의 계정 이름 — 직원에서 뺀다

# roleTags → 직군(§4)
TAG_ROLE = {"DOCTOR": "의사", "COUNSELOR": "상담사", "SKINCARE": "피부관리사", "NURSE": "간호사", "COORDINATOR": "코디"}
ROLE_PRIORITY = ["의사", "상담사", "피부관리사", "간호사", "코디"]
# 배정형(시작 · 종료 버튼) / 순회형(내원 목록) — §3.3
FRAME = {"의사": "assigned", "상담사": "assigned", "피부관리사": "assigned", "간호사": "rounds", "코디": "rounds"}
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
# 고객 이름 앞 국적 접두(`[TW] ` 등) — 화면에 국적 칩이 따로 있어 뗀다(WP7c). 메모 본문은 그대로
NAME_PREFIX = re.compile(r"^\[[A-Z]{2}\]\s*")


def display_name(name: str | None) -> str:
    return NAME_PREFIX.sub("", name or "").strip()


def load_scenario(root: Path) -> tuple[dict, dict[str, dict]]:
    seed_file = root / "seed.json"
    if not seed_file.exists():
        raise FileNotFoundError(f"시나리오 seed.json 이 없어요: {seed_file}")
    seed = json.loads(seed_file.read_text())
    events = {f.stem: json.loads(f.read_text()) for f in sorted((root / "events").glob("*.json"))}
    return seed, events


def staff_roles(accounts: list[dict], seed: dict, events: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """오늘 근무 직원 → 5직군.

    - 목록 = `staffIds`(오늘 근무 — 더미 스케줄). 없으면 백업: 이벤트에 나온 직원 + COORDINATOR 태그 활성 직원(코디)
    - 직군 = roleTags. 태그가 여럿이면 ① 나온 칸(이벤트 상담사 → 상담사 · 이벤트 작업 의사/담당) ② 그래도 여럿이면
      DOCTOR > COUNSELOR > SKINCARE > NURSE > COORDINATOR. 오늘 상담사는 이벤트에 나오는 상담사이므로, 이벤트에 상담사로 나오지
      않은 사람은 COUNSELOR 태그를 직군 후보에서 뺀다(코디 · 콜 상담 태그를 함께 가진 코디가 상담사로 잡히지 않게)
    """
    by_id = {a["id"]: a for a in accounts}
    hint: dict[str, set[str]] = {}
    for ev in events.values():
        done = ev.get("consultationDone") or {}
        for p in (done.get("consultation") or {}).get("counselors") or []:
            hint.setdefault(p.get("id"), set()).add("상담사")
        for t in done.get("tasks") or []:  # 보통 비어 온다(배정은 데스크 몫)
            for p in t.get("doctors") or []:
                hint.setdefault(p.get("id"), set()).add("의사")
            for p in t.get("assignees") or []:
                hint.setdefault(p.get("id"), set()).update({"간호사", "피부관리사"})
    notes: list[str] = []
    forced: dict[str, str] = {}
    if seed.get("staffIds"):
        ids = list(dict.fromkeys(seed["staffIds"]))
        missing = [i for i in hint if i and i not in ids and "상담사" in hint[i]]
        if missing:
            notes.append(f"이벤트 상담사 {len(missing)}명이 staffIds 에 없어 더했어요")
            ids += missing
    else:
        ids = [i for i in hint if i]
        for a in accounts:
            if a.get("activate") and "COORDINATOR" in (a.get("roleTags") or []) and a["id"] not in ids:
                ids.append(a["id"])
                forced[a["id"]] = "코디"
        notes.append("staffIds 가 없어 백업 규칙(이벤트 등장 직원 + COORDINATOR 활성 직원)")

    staff = []
    for sid in ids:
        acc = by_id.get(sid)
        if not acc or acc.get("name") == ANESTHESIA_ONLY:
            notes.append(f"직원 {sid} — kos-staff.json 에 없거나 마취용이라 뺐어요")
            continue
        tag_roles = {TAG_ROLE[t] for t in acc.get("roleTags") or [] if t in TAG_ROLE}
        h = hint.get(sid, set())
        if "상담사" not in h and len(tag_roles) > 1:
            tag_roles.discard("상담사")
        if not tag_roles:
            notes.append(f"{acc['name']} — 5직군 태그가 없어 뺐어요({acc.get('roleTags')})")
            continue
        role = forced.get(sid) or next(r for r in ROLE_PRIORITY if r in ((tag_roles & h) or tag_roles))
        staff.append({"staffId": sid, "name": acc["name"], "role": role, "frame": FRAME[role]})
    staff.sort(key=lambda s: (ROLE_PRIORITY.index(s["role"]), s["name"]))
    return staff, notes


def _age(dob: str | None, day: date) -> int | None:
    if not dob:
        return None
    try:
        b = datetime.fromisoformat(dob.replace("Z", "+00:00").replace(" ", "T")).date()
    except ValueError:
        return None
    if b >= day:
        return None  # 이상값(생년이 그해 · 미래)
    return day.year - b.year - ((day.month, day.day) < (b.month, b.day))


def _tickets(bundles) -> list[dict]:
    """보유 시술권(getTicketBundlesQuery) — 시술권 묶음별 이름 · AVAILABLE 장 id · 전체 장 수(KOS 값만)."""
    out = []
    for b in bundles or []:
        for ts in b.get("ticketSets") or []:
            tks = ts.get("tickets") or []
            out.append({
                "name": ts.get("title") or (ts.get("procedure") or {}).get("name") or "",
                "available": [x["id"] for x in tks if x.get("status") == "AVAILABLE" and x.get("id")],
                "total": len(tks),
            })
    return out


def build_seed(seed: dict, events: dict[str, dict], accounts: list[dict]) -> tuple[dict, list[str]]:
    """개원 전 시드 — 예약 전부(booked/canceled), 접수 · 위치 · 단계 · 로그 없음(§6)."""
    day = date.fromisoformat(seed["date"])
    staff, notes = staff_roles(accounts, seed, events)
    tickets_by_visitor = seed.get("ticketBundles") or {}
    past_by_visitor = seed.get("pastSchedules") or {}

    schedules = sorted(seed.get("schedules") or [], key=lambda s: (s["reservation"]["startDateTime"], s["id"]))
    ref_schedule, derived, ref_events, resv = {}, {}, {}, []
    for s in schedules:
        sid = s["id"]
        doc = json.loads(json.dumps(s))
        v = doc.setdefault("visitor", {})
        v["name"] = display_name(v.get("name"))
        age = _age(v.get("dateOfBirth"), day)
        for k in ("dateOfBirth", "phone", "chartNumber", "phoneticName"):  # 응답에 내보내지 않는 칸(나이는 계산값만)
            v.pop(k, None)
        ref_schedule[sid] = doc
        vid = v.get("id")
        derived[sid] = {
            "age": age,
            "isNew": bool(v.get("isNew")),
            "tickets": _tickets(tickets_by_visitor.get(vid)),
            "pastSchedules": past_by_visitor.get(vid) or [],
        }
        if sid in events:
            ref_events[sid] = events[sid]
        r = doc.get("reservation") or {}
        resv.append({
            "scheduleId": sid,
            "time": hhmm(parse_ts(r.get("startDateTime"))),
            "name": v.get("name", ""),
            "isNew": bool(v.get("isNew")),
            "nationality": v.get("nationality", ""),
            # KOS 예약 칸 그대로 — 비어 있으면 빈 값
            "procedure": ", ".join(p.get("name") or p.get("title") or "" for p in r.get("requestedProcedures") or []),
            "doctor": (r.get("doctor") or {}).get("name") or "",
            "st": "canceled" if r.get("status") == "CANCELED" else "booked",
        })
    missing = sorted(set(events) - set(ref_schedule))
    if missing:
        notes.append(f"seed.json 에 없는 일정의 이벤트 {len(missing)}개는 뺐어요")

    snapshot = {
        "meta": {"date": seed["date"], "kind": "build", "source": "scenario", "builtAt": datetime.now(UTC).isoformat()},
        "reference": {"schedule": ref_schedule, "derived": derived, "events": ref_events},
        "state": {"customers": [], "steps": [], "staff": staff, "resv": resv, "log": [], "stepSeq": 0},
    }
    return snapshot, notes
