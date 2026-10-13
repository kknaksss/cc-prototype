"""메모 — SPEC-001 0.3.0 §0-b. **양식에 기대지 않는다: 원문 그대로.** 자르기 · 뽑기 · 줄 숨김 없음.

- 공개 = 쓰인 시점: 지난 방문 메모 · 시술 이력 · 보유 시술권 · 고객 메모 = 언제나 / 오늘 예약 메모 = 예약 때부터 /
  오늘 상담 · 오늘 오더 = 오늘 상담 종료(상담 완료 이벤트) 뒤 / 오늘 담당자 메모 = 방문 카드(히스토리)에만, 그 시술 종료 뒤
- 강조 재료만 준다: 위험 단어 목록(설정) · 원문에 이름이 그대로 나오는 오늘 근무 직원(`mentionedStaffIds`, 문자열 일치)
"""


def visible_texts(doc: dict, derived: dict, cust: dict | None) -> list[str]:
    """지금 화면에 보일 수 있는 메모 원문 전부(고객 · 예약 · 오늘 상담/오더(공개 뒤) · 지난 상담/오더)."""
    v = doc.get("visitor") or {}
    r = doc.get("reservation") or {}
    out = [v.get("memo"), r.get("reservationMemo")]
    if cust and cust.get("consultApplied"):
        out += [((cust.get("consultation") or {}).get("content") or {}).get("text"), cust.get("orderMemo")]
    for p in derived.get("pastSchedules") or []:
        out += [((c.get("content") or {}).get("text")) for c in p.get("consultations") or []]
        out.append(p.get("orderMemo"))
    return [t for t in out if t]


def mentioned_staff(texts: list[str], staff: list[dict]) -> list[str]:
    """원문에 이름이 그대로 나오는 오늘 근무 직원 id(지정 요청 — 가공이지만 짐작 아님: 문자열 일치)."""
    joined = "\n".join(texts)
    return [s["staffId"] for s in staff if s.get("name") and len(s["name"]) >= 2 and s["name"] in joined]


def risk_hits(texts: list[str], words: list[str]) -> list[str]:
    joined = "\n".join(texts)
    return [w for w in words if w and w in joined]


def _names(people: list[dict] | None) -> list[str]:
    return [p["name"] for p in people or [] if p.get("name")]


def visits(doc: dict, derived: dict, cust: dict | None, steps: list[dict], today: str) -> list[dict]:
    """방문 카드 — 방문(일정) 하나당 하나, 최근이 위. 오늘 카드는 접수 뒤에만 있고 상담 · 오더는 상담 종료 뒤에 열린다."""
    cards = []
    if cust:
        open_ = bool(cust.get("consultApplied"))
        cons = cust.get("consultation") or {}
        done = [s for s in steps if s["kind"] == "procedure" and s["state"] == "done"]
        cards.append({
            "date": today, "today": True, "locked": not open_,
            "counselors": _names(cons.get("counselors")) if open_ else [],
            "consultation": (cons.get("content") or {}).get("text") if open_ else None,
            "orderMemo": cust.get("orderMemo") if open_ else None,
            "procedures": [s["label"] for s in done],
            "assigneeMemos": [{"label": s["label"], "memo": s["assigneeMemo"]} for s in done if s.get("assigneeMemo")],
        })
    for p in sorted(derived.get("pastSchedules") or [], key=lambda x: x.get("date") or "", reverse=True):
        conss = p.get("consultations") or []
        procs = p.get("procedures") or []
        cards.append({
            "date": p.get("date", ""), "today": False, "locked": False,
            "counselors": [n for c in conss for n in _names(c.get("counselors"))],
            "consultation": "\n\n".join(((c.get("content") or {}).get("text") or "") for c in conss) or None,
            "orderMemo": p.get("orderMemo") or None,
            "procedures": [x.get("title") for x in procs if x.get("title")],
            "assigneeMemos": [{"label": x.get("title") or "", "memo": x["assigneeMemo"]} for x in procs if x.get("assigneeMemo")],
            "synthetic": bool(p.get("synthetic")),
        })
    return cards


def customer_mentions(repo, d: dict, schedule_id: str) -> list[str]:
    doc = repo.get_reference("schedule", schedule_id) or {}
    derived = repo.get_reference("derived", schedule_id) or {}
    cust = next((c for c in d["customers"] if c["scheduleId"] == schedule_id), None)
    return mentioned_staff(visible_texts(doc, derived, cust), d["staff"])

