"""환자 상세 · 예약 상세(SPEC-001 0.3.0 §0-b) · 시술 후보(묶음 n/m).

- **동선이 메인 데이터** — 「오늘 오더」 = 동선(`route`). 메모는 참고용 **원문 그대로**(자르기 · 뽑기 없음)
- 메모 공개 = 쓰인 시점(`app/service/memos.py`). 강조 재료: `riskWords`(설정 목록) · `riskHits` · `mentionedStaffIds`
- 구조화된 값은 KOS 구조 필드만: 아웃 = `desiredDischargeDateTimeUtc`, 예약 시술 = `requestedProcedures`(비면 빈 목록)
"""

from datetime import datetime

from app.domain import board as B
from app.domain.errors import NotFound
from app.repository.state_repo import StateRepository
from app.seed.capture import KST, parse_ts
from app.service import bundles as BD
from app.service import memos

SEX = {"FEMALE": "여", "MALE": "남"}
ACTION_LABEL = {("consult", "start"): "상담 시작", ("consult", "finish"): "상담 종료",
                ("doctor_consult", "start"): "상담 시작", ("doctor_consult", "finish"): "상담 종료",
                ("procedure", "start"): "시술 시작", ("procedure", "finish"): "시술 종료"}


def fmt_hm(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%H:%M") if ms is not None else None


class PatientService:
    def __init__(self, repo: StateRepository, risk_words: list[str]):
        self.repo = repo
        self.risk_words = risk_words

    def _load(self, schedule_id: str):
        d = self.repo.load_state()
        doc = self.repo.get_reference("schedule", schedule_id)
        resv = next((r for r in d["resv"] if r["scheduleId"] == schedule_id), None)
        if not doc or not resv:
            raise NotFound("patient_not_found", f"일정 {schedule_id} 이 없어요")
        cust = next((c for c in d["customers"] if c["scheduleId"] == schedule_id), None)
        return d, doc, self.repo.get_reference("derived", schedule_id) or {}, resv, cust

    def _today(self) -> str:
        return (self.repo.get_meta("seedMeta", {}) or {}).get("date", "")

    def bundles(self, schedule_id: str) -> list[dict]:
        d, _, derived, _, cust = self._load(schedule_id)
        events = self.repo.get_reference("events", schedule_id) or {}
        return BD.build(derived, events, cust, B.steps_of(d, schedule_id))

    def candidates(self, schedule_id: str) -> list[dict]:
        return BD.public(self.bundles(schedule_id))

    def detail(self, schedule_id: str, viewer: str | None = None) -> dict:
        d, doc, derived, resv, cust = self._load(schedule_id)
        steps = B.steps_of(d, schedule_id)
        revealed = bool(cust and cust.get("consultApplied"))
        v = doc.get("visitor") or {}
        r = doc.get("reservation") or {}
        texts = memos.visible_texts(doc, derived, cust)

        def names(kinds: tuple[str, ...], role: str) -> list[str]:
            out = []
            for s in steps:
                if s["kind"] in kinds and s.get("assigneeId") and s["state"] != "skipped":
                    who = next((x for x in d["staff"] if x["staffId"] == s["assigneeId"]), None)
                    if who and who["role"] == role and who["name"] not in out:
                        out.append(who["name"])
            return out

        counselors = names(("consult",), "상담사")
        return {
            "scheduleId": schedule_id,
            "name": resv["name"],
            "nationality": v.get("nationality", ""),
            "sex": SEX.get(v.get("gender"), ""),
            "age": derived.get("age"),
            "isNew": bool(v.get("isNew")),
            "reservationTime": resv.get("time", ""),
            "reservationStatus": resv.get("st"),
            "requestedProcedures": [p.get("name") or p.get("title") or "" for p in r.get("requestedProcedures") or []],
            "flowStep": cust["flowStep"] if cust else "RESERVED",
            "location": cust["location"] if cust else None,
            "prevRoom": cust.get("prevRoom") if cust else None,
            "status": B.status_of(d, cust) if cust else None,
            "since": cust["since"] if cust and B.is_here(cust) else None,
            "leaveTime": fmt_hm(cust["completedAt"]) if cust and cust.get("completedAt") else None,
            "outTime": fmt_hm(parse_ts(r.get("desiredDischargeDateTimeUtc"))),  # KOS 구조 필드만
            "counselor": counselors[0] if counselors else None,
            "doctors": names(("doctor_consult", "procedure"), "의사"),
            "unpaidAmount": (cust or {}).get("unpaidAmount") or 0,
            "paid": bool((cust or {}).get("paid")),
            "memoRevealed": revealed,
            # 메모 — 원문 그대로
            "customerMemo": v.get("memo") or None,
            "reservationMemo": r.get("reservationMemo") or None,
            "visits": memos.visits(doc, derived, cust, steps, self._today()),
            # 강조 재료
            "riskWords": self.risk_words,
            "riskHits": memos.risk_hits(texts, self.risk_words),
            "mentionedStaffIds": memos.mentioned_staff(texts, d["staff"]),
            "chart": self._chart(r, derived, cust, steps),
            "route": self._route(d, steps),
            "tickets": [{k: b[k] for k in ("bundleId", "name", "left", "total")}
                        for b in self.candidates(schedule_id) if b["source"] == "ticket"],
            "myActions": self._actions(steps, viewer),
        }

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
    def _chart(r: dict, derived: dict, cust: dict | None, steps: list[dict]) -> list[dict]:
        """KOS 구조 필드만 — 유입 · 예약 그룹 · 보유 시술권 n/m · 오늘 결제([결제 완료] 뒤)."""
        rows = []
        funnel = ((r.get("funnel") or {}).get("funnel") or {}).get("name")
        detail = (r.get("funnel") or {}).get("funnelDetail")
        if funnel:
            rows.append({"label": "유입", "value": funnel + (f" · {detail}" if detail else "")})
        if r.get("reservationGroupTitle"):
            rows.append({"label": "예약 그룹", "value": r["reservationGroupTitle"]})
        used = {s["ticketId"] for s in steps if s.get("ticketId")}
        held = [(t["name"], len([x for x in t["available"] if x not in used]), t["total"]) for t in derived.get("tickets") or []]
        held = [h for h in held if h[1]]
        if held:
            rows.append({"label": "보유 시술권", "value": ", ".join(f"{n} {left}/{total}회" for n, left, total in held)})
        if cust and cust.get("paid"):
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
    def _route(d: dict, steps: list[dict]) -> list[dict]:
        """동선 = 오늘 오더. 담당자 메모는 넣지 않는다(방문 카드에만)."""
        return [{
            "stepId": s["stepId"], "order": s["order"], "kind": s["kind"], "label": s["label"],
            "assigneeId": s.get("assigneeId"), "assigneeName": B.staff_name(d, s.get("assigneeId")) or None,
            "state": s["state"], "assignedAt": s["assignedAt"], "startedAt": s["startedAt"], "endedAt": s["endedAt"],
            "paymentRequired": bool(s.get("paymentRequired")), "ticketId": s.get("ticketId"),
            "kosSequence": s.get("kosSequence"),
        } for s in steps]
