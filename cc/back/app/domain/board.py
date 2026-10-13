"""현황판 상태 계산 · 조작 — 시안 `Ceramique 현황판 v3` 스크립트의 순수 로직을 그대로 옮겼다.

상태 D = {customers, staff, resv, history}. 고객은 scheduleId, 직원은 staffId 로 찾는다(시안은 이름).
모든 변경은 `commit` 을 지난다: 스냅샷 → 변경 → 고객 없는 방은 직원 큐에서 정리 → 상태 바뀐 고객은 타이머 리셋.
"""

import copy
from collections.abc import Callable

from app.domain.errors import BadRequest, NotFound
from app.domain.rooms import ROOM_IDS, is_sleep

RLABEL = {"의사": "원장", "상담사": "상담사", "코디": "코디"}
STATUS_NAME = {"wait": "대기", "consult": "상담", "treat": "시술"}

State = dict
Mutation = Callable[[State, int], None]


def cust_in(d: State, rid: str) -> list[dict]:
    return [c for c in d["customers"] if not c["done"] and c["room"] == rid]


def present_in(d: State, rid: str) -> list[dict]:
    return [s for s in d["staff"] if s["queue"] and s["queue"][0] == rid]


def queued_in(d: State, rid: str) -> list[dict]:
    return [s for s in d["staff"] if rid in s["queue"][1:]]


def current_step(c: dict) -> dict | None:
    return c["order"][c["step"]] if c["step"] < len(c["order"]) else None


def wait_label(c: dict, step: dict | None) -> str:
    if not step:
        return "마무리 대기"
    if step["kind"] == "sleep" and not is_sleep(c["room"]):
        return "수면실 이동 대기"
    if step["kind"] == "doctor":
        return "원장 대기"
    if step["kind"] == "consult":
        return "상담사 대기"
    return f"{RLABEL[step['role']]} 대기 · {step['label']}"


def status_of(d: State, rid: str | None) -> dict | None:
    """방 상태 {key, label} — 시안 statusOf."""
    if not rid:
        return None
    cs = cust_in(d, rid)
    if not cs or rid == "lounge":
        return None
    c = cs[0]
    step = current_step(c)
    if present_in(d, rid):
        key = "consult" if step and step["kind"] in ("consult", "doctor") else "treat"
        return {"key": key, "label": step["label"] if step else "마무리"}
    return {"key": "wait", "label": wait_label(c, step)}


def customer_state(d: State, c: dict) -> tuple[str | None, str]:
    """고객 한 명의 (상태 키, 라벨). 라운지 = lounge, 귀가 = None."""
    if c["done"] or not c["room"]:
        return None, "귀가"
    if c["room"] == "lounge":
        return "lounge", "접수 후 대기"
    st = status_of(d, c["room"])
    if not st:
        return "wait", wait_label(c, current_step(c))
    return st["key"], st["label"]


def _status_key(d: State, c: dict) -> str:
    st = None if c["room"] == "lounge" else status_of(d, c["room"])
    return f"{c['room']}|{c['step']}|{st['key'] if st else ''}"


def commit(state: State, fn: Mutation, now_ms: int) -> State:
    """시안 commit — 새 상태를 돌려준다(입력은 바꾸지 않는다)."""
    snap = state
    d = copy.deepcopy(state)
    fn(d, now_ms)
    occ = {c["room"] for c in d["customers"] if not c["done"] and c["room"] and c["room"] != "lounge"}
    for s in d["staff"]:
        s["queue"] = [r for r in s["queue"] if r in occ]
    before = {c["scheduleId"]: c for c in snap["customers"]}
    for c in d["customers"]:
        if c["done"]:
            continue
        b = before.get(c["scheduleId"])
        if b and _status_key(snap, b) != _status_key(d, c):
            c["since"] = now_ms
    return d


# ── 조작 ─────────────────────────────────────────────────────────────


def find_staff(d: State, staff_id: str) -> dict:
    for s in d["staff"]:
        if s["staffId"] == staff_id:
            return s
    raise NotFound("staff_not_found", f"직원 {staff_id} 를 찾을 수 없어요")


def find_customer(d: State, schedule_id: str) -> dict:
    for c in d["customers"]:
        if c["scheduleId"] == schedule_id:
            return c
    raise NotFound("customer_not_found", f"고객 {schedule_id} 가 현황판에 없어요")


def check_room(rid: str) -> None:
    if rid not in ROOM_IDS:
        raise BadRequest("unknown_room", f"방 {rid} 는 현황판에 없어요")


def assign(staff_id: str, room: str) -> Mutation:
    def fn(d: State, now: int) -> None:
        x = find_staff(d, staff_id)
        if room not in x["queue"]:
            x["queue"].append(room)

    return fn


def _complete_in(d: State, s: dict, room: str, now: int) -> None:
    front = bool(s["queue"]) and s["queue"][0] == room
    s["queue"] = [r for r in s["queue"] if r != room]
    if not front:
        return
    for c in cust_in(d, room):
        st = current_step(c)
        if not st:
            # 시안에 없는 상태(시드 재구성: 단계는 다 끝났고 귀가 전) — 마무리 담당이 완료하면 귀가
            c["done"], c["room"], c["doneAt"] = True, None, now
            continue
        if st["role"] != s["role"]:
            continue
        d["history"].append({
            "scheduleId": c["scheduleId"], "kind": st["kind"], "label": st["label"], "staffId": s["staffId"],
            "room": room, "startedAt": c["since"], "completedAt": now,
        })
        c["step"] += 1
        if st["kind"] == "sleep" and c.get("prev"):
            c["room"], c["prev"] = c["prev"], None
        if c["step"] >= len(c["order"]):
            c["done"], c["room"], c["doneAt"] = True, None, now


def complete(staff_id: str, room: str) -> Mutation:
    def fn(d: State, now: int) -> None:
        _complete_in(d, find_staff(d, staff_id), room, now)

    return fn


def remove_staff(staff_id: str, room: str) -> Mutation:
    def fn(d: State, now: int) -> None:
        s = find_staff(d, staff_id)
        s["queue"] = [r for r in s["queue"] if r != room]

    return fn


def place(schedule_id: str, room: str) -> Mutation:
    def fn(d: State, now: int) -> None:
        c = find_customer(d, schedule_id)
        if c["done"]:
            raise BadRequest("customer_done", "이미 귀가한 고객이에요")
        if is_sleep(room) and c["room"] != "lounge":
            c["prev"] = c["room"]
        c["room"] = room

    return fn


def check_in(customer: dict, resv_row: dict | None, walk_in_row: dict | None) -> Mutation:
    """시안 checkIn — 예약은 checked 로, 현장 접수는 예약 행을 더한다. 고객은 라운지 · 0단계."""

    def fn(d: State, now: int) -> None:
        if walk_in_row:
            d["resv"].append(walk_in_row)
        elif resv_row:
            for r in d["resv"]:
                if r["scheduleId"] == resv_row["scheduleId"]:
                    r["st"] = "checked"
        d["customers"].append({**customer, "room": "lounge", "step": 0, "since": now, "prev": None, "done": False})

    return fn


def doctor_start(staff_id: str, schedule_id: str) -> Mutation:
    """의사 [진료 시작] — 그 고객 방을 queue[0] 으로(없으면 넣고, 있으면 앞으로)."""

    def fn(d: State, now: int) -> None:
        s = find_staff(d, staff_id)
        room = _customer_room(d, schedule_id)
        s["queue"] = [room] + [r for r in s["queue"] if r != room]

    return fn


def doctor_finish(staff_id: str, schedule_id: str) -> Mutation:
    """의사 [진료 완료] — 그 방에 대해 complete(앞에 없으면 먼저 앞으로)."""

    def fn(d: State, now: int) -> None:
        s = find_staff(d, staff_id)
        room = _customer_room(d, schedule_id)
        s["queue"] = [room] + [r for r in s["queue"] if r != room]
        _complete_in(d, s, room, now)

    return fn


def _customer_room(d: State, schedule_id: str) -> str:
    c = find_customer(d, schedule_id)
    if c["done"] or not c["room"] or c["room"] == "lounge":
        raise BadRequest("customer_not_in_room", "고객이 관리실에 있지 않아요(라운지 · 귀가)")
    return c["room"]
