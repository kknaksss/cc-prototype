"""로그인(§7) · 직원 첫 화면(§3.3 · §5.2) — 배정형(의사 · 상담사 · 피부관리사) / 순회형(코디 · 간호사)."""

from app.domain import board as B
from app.domain.errors import BadRequest
from app.repository.state_repo import StateRepository

DESK = {"staffId": "desk", "name": "데스크", "role": "데스크", "frame": "desk"}


class StaffService:
    def __init__(self, repo: StateRepository):
        self.repo = repo

    def accounts(self) -> list[dict]:
        staff = self.repo.load_state()["staff"]
        return [DESK] + [{k: s[k] for k in ("staffId", "name", "role", "frame")} for s in staff]

    def login(self, staff_id: str) -> dict:
        if staff_id == DESK["staffId"]:
            return {**DESK, "home": "/desk"}
        s = B.find_staff(self.repo.load_state(), staff_id)
        return {"staffId": s["staffId"], "name": s["name"], "role": s["role"], "frame": s["frame"], "home": "/staff"}

    def home(self, staff_id: str) -> dict:
        d = self.repo.load_state()
        if staff_id == DESK["staffId"]:
            raise BadRequest("no_staff_home", "데스크는 현황판(/api/board)을 써요")
        me = B.find_staff(d, staff_id)
        if me["frame"] == "assigned":
            return {"frame": "assigned", **self._assigned(d, me)}
        return {"frame": "rounds", **self._rounds(d)}

    @staticmethod
    def _resv(d: dict, schedule_id: str) -> dict:
        return next((r for r in d["resv"] if r["scheduleId"] == schedule_id), {})

    def _item(self, d: dict, s: dict) -> dict:
        c = next((x for x in d["customers"] if x["scheduleId"] == s["scheduleId"]), {})
        return {
            "stepId": s["stepId"], "scheduleId": s["scheduleId"], "kind": s["kind"], "label": s["label"],
            "state": s["state"], "assignedAt": s["assignedAt"], "startedAt": s["startedAt"], "endedAt": s["endedAt"],
            "name": c.get("name"), "nationality": c.get("nationality", ""), "isNew": c.get("isNew"),
            "location": c.get("location"), "time": self._resv(d, s["scheduleId"]).get("time", ""),
            "status": B.status_of(d, c) if c else None, "unpaidAmount": c.get("unpaidAmount") or 0,
        }

    def _assigned(self, d: dict, me: dict) -> dict:
        mine = [s for s in d["steps"] if s.get("assigneeId") == me["staffId"]]
        current = next((s for s in mine if s["state"] == "in_progress"), None)
        nxt = sorted((s for s in mine if s["state"] == "assigned"), key=lambda s: s["assignedAt"] or 0)
        done = sorted((s for s in mine if s["state"] == "done"), key=lambda s: s["endedAt"] or 0)
        return {"current": self._item(d, current) if current else None,
                "next": [self._item(d, s) for s in nxt], "done": [self._item(d, s) for s in done]}

    def _rounds(self, d: dict) -> dict:
        rows = []
        for c in d["customers"]:
            if not B.is_here(c):
                continue
            st = B.status_of(d, c)
            rows.append({
                "scheduleId": c["scheduleId"], "name": c["name"], "nationality": c.get("nationality", ""),
                "isNew": c.get("isNew"), "location": c["location"], "prevRoom": c.get("prevRoom"),
                "time": self._resv(d, c["scheduleId"]).get("time", ""), "status": st, "need": st["need"] if st else None,
                "since": c["since"], "unpaidAmount": c.get("unpaidAmount") or 0,
                # 오늘 시술 목록(간호사 준비용) — 데스크가 넣은 시술 단계
                "procedures": [{"stepId": s["stepId"], "label": s["label"], "state": s["state"],
                                "assigneeName": B.staff_name(d, s.get("assigneeId")) or None}
                               for s in B.steps_of(d, c["scheduleId"]) if s["kind"] == "procedure"],
            })
        rows.sort(key=lambda r: r["since"] or 0)
        summary = {"wait": 0, "consult": 0, "treat": 0, "needNext": 0, "needDischarge": 0}
        for r in rows:
            key = r["status"]["key"] if r["status"] else "wait"
            summary["wait" if key in ("reception", "wait") else key] += 1
            if r["need"] == "next":
                summary["needNext"] += 1
            elif r["need"] == "discharge":
                summary["needDischarge"] += 1
        return {"patients": rows, "summary": summary}
