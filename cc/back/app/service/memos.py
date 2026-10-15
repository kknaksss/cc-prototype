"""메모 — SPEC-001 0.3.0 §0-b. **양식에 기대지 않는다: 원문 그대로.** 자르기 · 뽑기 · 줄 숨김 없음.

- 공개 = 쓰인 시점: 지난 방문 메모 · 시술 이력 · 보유 시술권 · 고객 메모 = 언제나 / 오늘 예약 메모 = 예약 때부터 /
  오늘 상담 · 오늘 오더 = 오늘 상담 종료(상담 완료 이벤트) 뒤 / 오늘 담당자 메모 = 방문 카드(히스토리)에만, 그 시술 종료 뒤
"""


def append(text: str | None, lines: list[str]) -> str | None:
    """원문 끝에 데스크가 덧붙인 줄(SPEC-002 §5.1). 둘 다 없으면 None."""
    return "\n".join([x for x in [text or ""] if x] + lines) or None


def _names(people: list[dict] | None) -> list[str]:
    return [p["name"] for p in people or [] if p.get("name")]


def visits(doc: dict, derived: dict, cust: dict | None, steps: list[dict], today: str,
           consult_adds: list[str] | None = None) -> list[dict]:
    """방문 카드 — 방문(일정) 하나당 하나, 최근이 위. 오늘 카드는 접수 뒤에만 있고 상담 · 오더는 상담 종료 뒤에 열린다.
    데스크가 덧붙인 상담 메모 줄은 공개 시점 예외 — 잠겨 있어도 `consultation` 에 그 줄만 보인다(SPEC-002 §5.1)."""
    cards = []
    if cust:
        open_ = bool(cust.get("consultApplied"))
        cons = cust.get("consultation") or {}
        done = [s for s in steps if s["kind"] == "procedure" and s["state"] == "done"]
        cards.append({
            "date": today, "today": True, "locked": not open_,
            "counselors": _names(cons.get("counselors")) if open_ else [],
            "consultation": append((cons.get("content") or {}).get("text") if open_ else None, consult_adds or []),
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
