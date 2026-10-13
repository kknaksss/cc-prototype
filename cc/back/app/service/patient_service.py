"""환자 상세(SPEC-001 0.2.0 §3.4 · 0.2.1 §0-a — 0.1.0 §5.5 안 A 위에) · 시술 후보(§5.4).

- 원천: 시드(예약 · 고객 · 보유 시술권 · 지난 방문) + 이벤트로 들어온 것(고객 상태에 보관 — 상담 기록 · 오더 메모 · 결제)
- 메모 공개 시점: 예약 메모 · 고객 메모는 처음부터. 상담 메모 · 오더 메모와 거기서 온 ⚠ 주의는 **상담 완료 이벤트 뒤**
  (상담 단계 종료 때 들어온다). 담당자 메모는 시술 완료 이벤트 뒤 동선의 그 줄에. 차트 「오늘 결제」는 [결제 완료] 뒤
- 출처는 칸 이름만(작성자 이름 없음). 상단 카드의 상담실장 · 원장은 관제 배정(동선 정본)에서
"""

from datetime import datetime

from app.domain import board as B
from app.domain.errors import NotFound
from app.repository.state_repo import StateRepository
from app.seed.capture import KST, parse_ts
from app.service import memo_parse as M

SEX = {"FEMALE": "여", "MALE": "남"}
ACTION_LABEL = {("consult", "start"): "상담 시작", ("consult", "finish"): "상담 종료",
                ("doctor_consult", "start"): "상담 시작", ("doctor_consult", "finish"): "상담 종료",
                ("procedure", "start"): "시술 시작", ("procedure", "finish"): "시술 종료"}


def fmt_hm(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%H:%M") if ms is not None else None


def _section(lines: list[str], source: str) -> dict | None:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return {"lines": lines, "source": source} if lines else None


class PatientService:
    def __init__(self, repo: StateRepository):
        self.repo = repo

    def _load(self, schedule_id: str) -> tuple[dict, dict, dict, dict | None, dict | None]:
        d = self.repo.load_state()
        doc = self.repo.get_reference("schedule", schedule_id)
        resv = next((r for r in d["resv"] if r["scheduleId"] == schedule_id), None)
        if not doc or not resv:
            raise NotFound("patient_not_found", f"일정 {schedule_id} 이 없어요")
        cust = next((c for c in d["customers"] if c["scheduleId"] == schedule_id), None)
        return d, doc, self.repo.get_reference("derived", schedule_id) or {}, resv, cust

    def detail(self, schedule_id: str, viewer: str | None = None) -> dict:
        d, doc, derived, resv, cust = self._load(schedule_id)
        steps = B.steps_of(d, schedule_id)
        revealed = bool(cust and cust.get("consultApplied"))

        v = doc.get("visitor") or {}
        r = doc.get("reservation") or {}
        consult_memo = ((cust.get("consultation") or {}).get("content") or {}).get("text") if revealed else None
        order_memo = cust.get("orderMemo") if revealed else None
        resv_memo = r.get("reservationMemo")

        def names(kinds: tuple[str, ...], role: str) -> list[str]:
            out = []
            for s in steps:
                if s["kind"] in kinds and s.get("assigneeId") and s["state"] != "skipped":
                    who = next((x for x in d["staff"] if x["staffId"] == s["assigneeId"]), None)
                    if who and who["role"] == role and who["name"] not in out:
                        out.append(who["name"])
            return out

        counselors = names(("consult",), "상담사")
        out = {
            "scheduleId": schedule_id,
            "name": resv["name"],
            "nationality": v.get("nationality", ""),
            "sex": SEX.get(v.get("gender"), ""),
            "age": derived.get("age"),
            "isNew": bool(v.get("isNew")),
            "reservationTime": resv.get("time", ""),
            "flowStep": cust["flowStep"] if cust else "RESERVED",
            "location": cust["location"] if cust else None,
            "prevRoom": cust.get("prevRoom") if cust else None,
            "status": B.status_of(d, cust) if cust else None,
            "since": cust["since"] if cust and B.is_here(cust) else None,
            "leaveTime": fmt_hm(cust["completedAt"]) if cust and cust.get("completedAt") else None,
            "outTime": M.out_time(order_memo, resv_memo) or fmt_hm(parse_ts(r.get("desiredDischargeDateTimeUtc"))),
            "counselor": counselors[0] if counselors else None,
            "doctors": names(("doctor_consult", "procedure"), "의사"),
            "memoRevealed": revealed,
            "unpaidAmount": (cust or {}).get("unpaidAmount") or 0,
            "paid": bool((cust or {}).get("paid")),
            "cautions": self._cautions(v.get("memo"), order_memo, consult_memo, resv_memo),
            "order": None, "consult": None,
            "reception": _section(M.drop_empty_form(M.lines_of(resv_memo)), "예약 메모"),
            "chart": self._chart(r, derived, resv_memo, cust),
            "history": self._history(bool(v.get("isNew")), consult_memo, derived.get("pastSchedules") or []),
            "pastSchedules": self._past(derived.get("pastSchedules") or []),
            "route": self._route(d, steps),
            "tickets": [{"name": t["name"], "left": len(t["available"]), "total": t["total"]}
                        for t in derived.get("tickets") or [] if t["available"]],
            "myActions": self._actions(steps, viewer),
        }
        lines, anesthesia = M.order_lines(order_memo)
        if lines:
            out["order"] = {"lines": lines, "anesthesia": anesthesia, "source": "오더 메모"}
        out["consult"] = _section(M.consult_summary(consult_memo), "상담 메모")
        return out

    @staticmethod
    def _actions(steps: list[dict], viewer: str | None) -> list[dict]:
        if not viewer:
            return []
        out = []
        for s in steps:
            if s.get("assigneeId") != viewer:
                continue
            act = "start" if s["state"] == "assigned" else "finish" if s["state"] == "in_progress" else None
            if act:
                out.append({"stepId": s["stepId"], "kind": s["kind"], "action": act, "label": ACTION_LABEL[(s["kind"], act)]})
        return out

    @staticmethod
    def _cautions(visitor_memo, order_memo, consult_memo, resv_memo) -> list[dict]:
        out: list[dict] = []
        if visitor_memo and visitor_memo.strip():
            out.append({"text": M.clean(visitor_memo).strip(), "source": "고객 메모"})
        _, cons_copy = M.split_consult(consult_memo)
        merged: dict[str, list[str]] = {}
        for src, ls in (("오더 메모", M.lines_of(order_memo) if order_memo else []), ("상담 메모", cons_copy)):
            for tag, value in M.tag_blocks(ls):
                text = f"{tag} — {value}"
                if src not in merged.setdefault(text, []):
                    merged[text].append(src)
        out += [{"text": t, "source": " · ".join(srcs)} for t, srcs in merged.items()]
        flags: dict[str, list[str]] = {}
        for src, memo in (("오더 메모", order_memo), ("예약 메모", resv_memo)):
            for ln in M.leading_flag_lines(memo):
                if src not in flags.setdefault(ln, []):
                    flags[ln].append(src)
        out += [{"text": t, "source": " · ".join(srcs)} for t, srcs in flags.items()]
        return out

    @staticmethod
    def _chart(r: dict, derived: dict, resv_memo, cust: dict | None) -> list[dict]:
        rows = []
        funnel = ((r.get("funnel") or {}).get("funnel") or {}).get("name")
        detail = (r.get("funnel") or {}).get("funnelDetail")
        if funnel:
            rows.append({"label": "유입", "value": funnel + (f" · {detail}" if detail else "")})
        if r.get("reservationGroupTitle"):
            rows.append({"label": "예약 그룹", "value": r["reservationGroupTitle"]})
        comp = M.companions(resv_memo)
        if comp:
            rows.append({"label": "동행", "value": comp})
        tickets = [t for t in derived.get("tickets") or [] if t["available"]]
        if tickets:
            value = ", ".join(f"{t['name']} {len(t['available'])}/{t['total']}회" for t in tickets)
            rows.append({"label": "보유 시술권", "value": value})
        if cust and cust.get("paid"):  # 「오늘 결제」는 [결제 완료] 뒤에만(§0-a)
            items = [(it.get("productOptionTitle") or it.get("productTitle") or "",
                      int((((it.get("cost") or {}).get("totalAmount")) or {}).get("value") or 0))
                     for it in (cust.get("payment") or {}).get("items") or []]
            paid = [f"{t} {a:,}원" for t, a in items if a > 0]
            free = [t for t, a in items if a <= 0]
            if paid:
                rows.append({"label": "오늘 결제", "value": ", ".join(paid)})
            if free:
                rows.append({"label": "서비스(0원)", "value": ", ".join(free)})
        return rows

    @staticmethod
    def _history(is_new: bool, consult_memo, past: list[dict]) -> list[dict]:
        out = [{"label": "이 병원", "value": "첫 방문" if is_new else "재방문", "source": ""}]
        for p in past:
            procs = ", ".join(x.get("title") or "" for x in p.get("procedures") or [] if x.get("title"))
            if procs:
                out.append({"label": "이 병원", "value": f"{p.get('date', '')} · {procs}", "source": "지난 방문"})
        out += [{"label": "타 병원", "value": ln, "source": "상담 메모"} for ln in M.other_clinic_history(consult_memo)]
        return out

    @staticmethod
    def _past(past: list[dict]) -> list[dict]:
        """재내원 — 지난 방문(시드 pastSchedules): 날짜 · 상담 메모(상담 요약 · 오더지) · 오더 메모 · 받은 시술."""
        out = []
        for p in sorted(past, key=lambda x: x.get("date") or "", reverse=True):
            cons = (p.get("consultations") or [{}])[0]
            text = (cons.get("content") or {}).get("text")
            out.append({
                "date": p.get("date", ""),
                "consult": _section(M.consult_summary(text), "상담 메모"),
                "order": _section(M.order_lines(p.get("orderMemo"))[0], "오더 메모"),
                "procedures": [x.get("title") for x in p.get("procedures") or [] if x.get("title")],
                "synthetic": bool(p.get("synthetic")),
            })
        return out

    @staticmethod
    def _route(d: dict, steps: list[dict]) -> list[dict]:
        return [{
            "stepId": s["stepId"], "order": s["order"], "kind": s["kind"], "label": s["label"],
            "assigneeId": s.get("assigneeId"), "assigneeName": B.staff_name(d, s.get("assigneeId")) or None,
            "state": s["state"], "assignedAt": s["assignedAt"], "startedAt": s["startedAt"], "endedAt": s["endedAt"],
            "paymentRequired": bool(s.get("paymentRequired")), "ticketId": s.get("ticketId"),
            "kosSequence": s.get("kosSequence"),
            "memo": (s.get("assigneeMemo") or "").strip() if s["state"] == "done" else "",  # 시술 완료 이벤트
        } for s in steps]

    # ── §5.4 시술 후보 ──
    def candidates(self, schedule_id: str) -> list[dict]:
        """상담사가 넣은 시술(상담 완료 이벤트 뒤 — 동선에서 빠진 것) + 보유 시술권(AVAILABLE). 동선에 있는 것은 뺀다."""
        d, _, derived, _, cust = self._load(schedule_id)
        steps = B.steps_of(d, schedule_id)
        used_tickets = {s["ticketId"] for s in steps if s.get("ticketId")}
        used_seq = {s["kosSequence"] for s in steps if s.get("kosSequence") is not None}
        out: list[dict] = []
        seen: set[str] = set()
        if cust and cust.get("consultApplied"):
            event = (self.repo.get_reference("events", schedule_id) or {}).get("consultationDone") or {}
            for t in sorted(event.get("tasks") or [], key=lambda t: t.get("sequence") or 0):
                seq = t.get("sequence")
                ticket = ((t.get("procedureConfiguration") or {}).get("ticketConfiguration") or {}).get("ticketId") or None
                if seq in used_seq or (ticket and ticket in used_tickets):
                    continue
                if t.get("type") == "ETCETERA":
                    out.append({"kind": "doctor_consult", "label": "원장 상담", "ticketId": None, "kosSequence": seq,
                                "source": "task", "kosTitle": t.get("title") or ""})
                else:
                    out.append({"kind": "procedure", "label": t.get("title") or "", "ticketId": ticket, "kosSequence": seq,
                                "source": "task", "paymentRequired": bool(t.get("paymentRequired"))})
                if ticket:
                    seen.add(ticket)
        for ts in derived.get("tickets") or []:
            for tid in ts["available"]:
                if tid in seen or tid in used_tickets:
                    continue
                seen.add(tid)
                out.append({"kind": "procedure", "label": ts["name"], "ticketId": tid, "kosSequence": None, "source": "ticket"})
        return out
