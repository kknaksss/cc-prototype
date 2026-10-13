"""로그인(§6) · 직원 첫 화면(§5.2)."""

from app.domain import board as B
from app.domain.errors import BadRequest
from app.repository.state_repo import StateRepository

DESK = {"staffId": "desk", "name": "데스크", "role": "데스크"}
LOGIN_ROLES = ("의사", "코디")


class StaffService:
    def __init__(self, repo: StateRepository):
        self.repo = repo

    def accounts(self) -> list[dict]:
        staff = self.repo.load_state()["staff"]
        return [DESK] + [{"staffId": s["staffId"], "name": s["name"], "role": s["role"]}
                         for role in LOGIN_ROLES for s in staff if s["role"] == role]

    def login(self, staff_id: str) -> dict:
        if staff_id == DESK["staffId"]:
            return {**DESK, "home": "/desk"}
        s = B.find_staff(self.repo.load_state(), staff_id)
        return {"staffId": s["staffId"], "name": s["name"], "role": s["role"], "home": "/staff"}

    def home(self, staff_id: str) -> dict:
        state = self.repo.load_state()
        if staff_id == DESK["staffId"]:
            raise BadRequest("no_staff_home", "데스크는 현황판(/api/board)을 써요")
        me = B.find_staff(state, staff_id)
        if me["role"] == "의사":
            return self._doctor(state, me)
        if me["role"] == "코디":
            return self._codi(state)
        raise BadRequest("no_staff_home", f"{me['role']} 첫 화면은 이번 PoC 범위가 아니에요")

    @staticmethod
    def _row(state: dict, c: dict) -> dict:
        resv = next((r for r in state["resv"] if r["scheduleId"] == c["scheduleId"]), {})
        key, label = B.customer_state(state, c)
        return {
            "scheduleId": c["scheduleId"], "name": c["name"], "nationality": c.get("nationality", ""),
            "time": resv.get("time", ""), "procedure": resv.get("procedure", ""),
            "room": None if c["done"] else c["room"], "state": key, "label": label,
            "since": None if c["done"] else c["since"],
        }

    def _doctor(self, state: dict, me: dict) -> dict:
        def first_in(rid: str | None) -> dict | None:
            cs = B.cust_in(state, rid) if rid else []
            return self._row(state, cs[0]) if cs else None

        current = first_in(me["queue"][0] if me["queue"] else None)
        nxt = first_in(me["queue"][1] if len(me["queue"]) > 1 else None)
        skip = {x["scheduleId"] for x in (current, nxt) if x}
        done, seen = [], set()
        for h in state["history"]:
            if h.get("staffId") != me["staffId"] or h["scheduleId"] in skip or h["scheduleId"] in seen:
                continue
            c = next((x for x in state["customers"] if x["scheduleId"] == h["scheduleId"]), None)
            if c:
                seen.add(h["scheduleId"])
                done.append(self._row(state, c))
        return {"current": current, "next": nxt, "done": done}

    def _codi(self, state: dict) -> dict:
        rows = [self._row(state, c) for c in state["customers"] if not c["done"]]
        rows.sort(key=lambda r: r["since"] or 0)
        summary = {"wait": 0, "consult": 0, "treat": 0}
        for r in rows:
            summary["wait" if r["state"] in ("lounge", "wait") else r["state"]] += 1
        return {"patients": rows, "summary": summary}

