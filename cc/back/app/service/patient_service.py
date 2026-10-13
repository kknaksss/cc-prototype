"""환자 상세 — SPEC-001 §5.5. KOS 참조 문서(이름 치환본) + 현황판 상태에서 계산한다."""

from datetime import datetime

from app.domain import board as B
from app.domain.errors import NotFound
from app.domain.rooms import map_kos_room, room_name
from app.repository.state_repo import StateRepository
from app.seed.capture import KST, parse_ts
from app.service import memo_parse as M

ANESTHESIA_ONLY = "마취용"
SEX = {"FEMALE": "여", "MALE": "남"}


def fmt_hm(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%H:%M") if ms is not None else None


def _doctor_names(task: dict) -> list[str]:
    return [d["name"] for d in task.get("doctors") or [] if d.get("name") and d["name"] != ANESTHESIA_ONLY]


class PatientService:
    def __init__(self, repo: StateRepository):
        self.repo = repo

    def detail(self, schedule_id: str) -> dict:
        state = self.repo.load_state()
        cust = next((c for c in state["customers"] if c["scheduleId"] == schedule_id), None)
        resv = next((r for r in state["resv"] if r["scheduleId"] == schedule_id), None)
        doc = self.repo.get_reference("schedule", schedule_id)
        if not doc and not cust and not resv:
            raise NotFound("patient_not_found", f"일정 {schedule_id} 이 없어요")
        derived = self.repo.get_reference("derived", schedule_id) or {}
        hist = [h for h in state["history"] if h["scheduleId"] == schedule_id]

        board = None
        if cust and not cust["done"]:
            key, label = B.customer_state(state, cust)
            board = {"room": cust["room"], "state": key, "label": label, "since": cust["since"]}

        out = {
            "scheduleId": schedule_id,
            "name": (cust or resv or {}).get("name") or ((doc or {}).get("visitor") or {}).get("name", ""),
            "nationality": "", "sex": "", "age": None, "firstVisit": True,
            "reservationTime": (resv or {}).get("time", ""),
            "leaveTime": fmt_hm(cust.get("doneAt")) if cust and cust["done"] else None,
            "outTime": None, "counselor": None, "doctors": [],
            "board": board,
            "cautions": [], "order": None, "consult": None, "reception": None,
            "chart": [], "history": [], "route": [],
            "tickets": derived.get("tickets", []),
        }
        if not doc:  # 현장 접수 — KOS 참조 없음(이름 · 오더만)
            out["route"] = self._route_from_order(cust, hist)
            return out

        v = doc.get("visitor") or {}
        r = doc.get("reservation") or {}
        tasks = sorted(doc.get("tasks") or [], key=lambda t: t.get("sequence") or 0)
        cons_text = ((doc.get("consultations") or [{}])[0].get("content") or {}).get("text") \
            or (doc.get("consultation") or {}).get("consultationMemo")
        order_memo = doc.get("orderMemo")
        resv_memo = r.get("reservationMemo")
        counselor = ((doc.get("consultation") or {}).get("counselor") or {}).get("name") or None

        out.update({
            "nationality": v.get("nationality", ""),
            "sex": SEX.get(v.get("gender"), ""),
            "age": derived.get("age"),
            "firstVisit": bool(derived.get("firstVisit", v.get("isNew", True))),
            "outTime": M.out_time(order_memo, resv_memo) or self._desired_out(r),
            "counselor": counselor,
            "doctors": list(dict.fromkeys(n for t in tasks if t.get("status") != "CANCELED" for n in _doctor_names(t))),
            "cautions": self._cautions(v.get("memo"), order_memo, cons_text, resv_memo),
        })

        lines, anesthesia = M.order_lines(order_memo)
        if lines:
            out["order"] = {"lines": lines, "anesthesia": anesthesia,
                            "source": "오더 메모" + (f" · 상담실장 {counselor}" if counselor else "")}
        summary = M.consult_summary(cons_text)
        if summary:
            out["consult"] = {"lines": summary,
                              "source": "상담 메모(구분선 위)" + (f" · 상담실장 {counselor}" if counselor else "")}
        rl = M.lines_of(resv_memo)
        while rl and not rl[0].strip():
            rl.pop(0)
        while rl and not rl[-1].strip():
            rl.pop()
        if rl:
            assignee = (r.get("reservationAssignee") or {}).get("name")
            out["reception"] = {"lines": rl, "source": "예약 메모" + (f" · 예약 담당 {assignee}" if assignee else "")}

        out["chart"] = self._chart(r, derived, resv_memo)
        out["history"] = self._history(out["firstVisit"], cons_text, counselor)
        out["route"] = self._route(tasks, doc, derived, cust, hist)
        return out

    @staticmethod
    def _desired_out(r: dict) -> str | None:
        return fmt_hm(parse_ts(r.get("desiredDischargeDateTimeUtc")))

    @staticmethod
    def _cautions(visitor_memo, order_memo, cons_text, resv_memo) -> list[dict]:
        out: list[dict] = []
        if visitor_memo and visitor_memo.strip():
            out.append({"text": M.clean(visitor_memo).strip(), "source": "고객 메모"})
        _, cons_copy = M.split_consult(cons_text)
        merged: dict[str, list[str]] = {}
        for src, ls in (("오더 메모", M.lines_of(order_memo)), ("상담 메모 사본", cons_copy)):
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
    def _chart(r: dict, derived: dict, resv_memo) -> list[dict]:
        rows = []
        funnel = ((r.get("funnel") or {}).get("funnel") or {}).get("name")
        detail = (r.get("funnel") or {}).get("funnelDetail")
        if funnel:
            rows.append({"label": "유입", "value": funnel + (f" · {detail}" if detail else "")})
        if derived.get("groupTitle"):
            rows.append({"label": "예약 그룹", "value": derived["groupTitle"]})
        comp = M.companions(resv_memo)
        if comp:
            rows.append({"label": "동행", "value": comp})
        tickets = derived.get("tickets") or []
        if tickets:
            rows.append({"label": "보유 시술권", "value": ", ".join(f"{t['name']} {t['left']}/{t['total']}회" for t in tickets)})
        if derived.get("prepaid"):
            rows.append({"label": "선불 잔액", "value": f"{derived['prepaid']:,}원"})
        paid = [p for p in derived.get("purchases") or [] if p["amount"] > 0]
        free = [p for p in derived.get("purchases") or [] if p["amount"] <= 0]
        if paid:
            rows.append({"label": "오늘 결제", "value": ", ".join(f"{p['title']} {p['amount']:,}원" for p in paid)})
        if free:
            rows.append({"label": "서비스(0원)", "value": ", ".join(p["title"] for p in free)})
        return rows

    @staticmethod
    def _history(first_visit: bool, cons_text, counselor) -> list[dict]:
        out = [{"label": "이 병원", "value": "첫 방문 — 이전 시술 기록 없음" if first_visit else "재방문",
                "source": "KOS 일정"}]
        lines = M.other_clinic_history(cons_text)
        src = "상담 메모" + (f" · 상담실장 {counselor}" if counselor else "")
        if lines:
            out += [{"label": "타 병원", "value": ln, "source": src} for ln in lines]
        else:
            out.append({"label": "타 병원", "value": "상담 메모에 이력 없음", "source": ""})
        return out

    @staticmethod
    def _step_status(idx: int | None, cust: dict | None) -> str:
        if idx is None or not cust:
            return "later"
        if cust["done"] or idx < cust["step"]:
            return "done"
        return "now" if idx == cust["step"] else "later"

    @staticmethod
    def _hist_for(hist: list[dict], step: dict | None, used: set[int]) -> dict | None:
        if not step:
            return None
        for i, h in enumerate(hist):
            if i not in used and h["kind"] == step["kind"] and h["label"] == step["label"]:
                used.add(i)
                return h
        return None

    def _route(self, tasks, doc, derived, cust, hist) -> list[dict]:
        order = (cust or {}).get("order") or derived.get("plannedOrder") or []
        task_step = derived.get("taskStep") or {}
        used: set[int] = set()
        hist_by_step: dict[int, dict | None] = {}
        for i, st in enumerate(order):
            hist_by_step[i] = self._hist_for(hist, st, used)

        def times(idx: int | None, status: str) -> tuple[str | None, str | None]:
            h = hist_by_step.get(idx) if idx is not None else None
            if status == "done" and h:
                return fmt_hm(h["startedAt"]), fmt_hm(h["completedAt"])
            if status == "now" and cust:
                return fmt_hm(cust["since"]), None
            return None, None

        out = []
        if order and order[0]["kind"] == "consult":
            status = self._step_status(0, cust)
            ready, done = times(0, status)
            counselor = ((doc.get("consultation") or {}).get("counselor") or {}).get("name")
            h = hist_by_step.get(0)
            out.append({"room": room_name(h["room"]) if h and h.get("room") else "", "task": "상담",
                        "staff": f"상담실장 {counselor}" if counselor else "", "status": status,
                        "readyAt": ready, "completedAt": done, "memo": ""})
        for t in tasks:
            idx = task_step.get(str(t.get("sequence")))
            if t.get("status") == "CANCELED":
                status = "canceled"
            else:
                status = self._step_status(idx, cust)
            ready, done = times(idx, status) if status != "canceled" else (None, None)
            rid = map_kos_room((t.get("room") or {}).get("title"))
            staff = [f"원장 {n}" for n in _doctor_names(t)] + [a["name"] for a in t.get("assignees") or [] if a.get("name")]
            out.append({
                "room": room_name(rid) if rid else ((t.get("room") or {}).get("title") or ""),
                "task": t.get("title") or (t.get("etceteraConfiguration") or {}).get("name") or "",
                "staff": " · ".join(staff), "status": status, "readyAt": ready, "completedAt": done,
                "memo": M.clean(t.get("assigneeMemo")).strip() if status == "done" else "",
            })
        return out

    def _route_from_order(self, cust, hist) -> list[dict]:
        if not cust:
            return []
        used: set[int] = set()
        out = []
        for i, st in enumerate(cust["order"]):
            status = self._step_status(i, cust)
            h = self._hist_for(hist, st, used)
            ready = fmt_hm(h["startedAt"]) if status == "done" and h else (fmt_hm(cust["since"]) if status == "now" else None)
            out.append({"room": room_name(h["room"]) if h and h.get("room") else "", "task": st["label"],
                        "staff": "", "status": status, "readyAt": ready,
                        "completedAt": fmt_hm(h["completedAt"]) if status == "done" and h else None, "memo": ""})
        return out
