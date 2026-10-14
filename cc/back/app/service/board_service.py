"""현황판 서비스 — 읽기(§5.2) · 조작(§5.3) · 되돌리기 · version · 초기화 · 「이걸 시드로」(§6)."""

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from app.domain import board as B
from app.domain.errors import BadRequest, NotFound
from app.domain.rooms import CORRIDORS, rooms_payload
from app.repository.state_repo import StateRepository
from app.seed.capture import KST
from app.service import bundles as BD
from app.service.events import EventBus
from app.service.snapshot import snapshot_to_state, state_to_snapshot

CUSTOMER_FIELDS = ("scheduleId", "name", "isNew", "nationality", "location", "prevRoom", "flowStep",
                   "receptionAt", "completedAt", "since", "unpaidAmount", "paid")
STEP_FIELDS = ("stepId", "order", "kind", "label", "kosSequence", "ticketId", "assigneeId", "state",
               "assignedAt", "startedAt", "endedAt", "paymentRequired")
DESK = "desk"


def now_ms() -> int:
    return int(time.time() * 1000)


def step_view(d: dict, s: dict) -> dict:
    return {**{k: s.get(k) for k in STEP_FIELDS}, "assigneeName": B.staff_name(d, s.get("assigneeId")) or None}


def customer_view(d: dict, c: dict) -> dict:
    view = {k: c.get(k) for k in CUSTOMER_FIELDS}
    view["unpaidAmount"] = view["unpaidAmount"] or 0
    view["paid"] = bool(view["paid"])
    return {**view, "status": B.status_of(d, c),
            "steps": [step_view(d, s) for s in B.steps_of(d, c["scheduleId"])]}


def staff_work(d: dict, staff_id: str) -> list[dict]:
    """직원의 지금 일 — 진행 중 → 배정(시작 전, 배정 순)."""
    mine = [s for s in d["steps"] if s.get("assigneeId") == staff_id and s["state"] in ("in_progress", "assigned")]
    mine.sort(key=lambda s: (s["state"] != "in_progress", s.get("assignedAt") or 0))
    out = []
    for s in mine:
        c = next((x for x in d["customers"] if x["scheduleId"] == s["scheduleId"]), {})
        out.append({"stepId": s["stepId"], "scheduleId": s["scheduleId"], "customerName": c.get("name"),
                    "location": c.get("location"), "kind": s["kind"], "label": s["label"], "state": s["state"]})
    return out


class BoardService:
    def __init__(self, repo: StateRepository, bus: EventBus, seed_path: Path, clock=now_ms):
        self.repo = repo
        self.bus = bus
        self.seed_path = seed_path
        self.clock = clock
        self._lock = threading.RLock()

    # ── 읽기 ──
    def version(self) -> int:
        return int(self.repo.get_meta("version", 0))

    def state(self) -> dict:
        return self.repo.load_state()

    def board(self) -> dict:
        with self._lock:
            d = self.repo.load_state()
            version = self.version()
        return {
            "rooms": [{**r, "unpaidAmount": sum((c.get("unpaidAmount") or 0) for c in d["customers"]
                                                if B.is_here(c) and c["location"] == r["id"])} for r in rooms_payload()],
            "corridors": CORRIDORS,
            "customers": [customer_view(d, c) for c in d["customers"]],
            "staff": [{**s, "work": staff_work(d, s["staffId"])} for s in d["staff"]],
            "resv": [{k: v for k, v in r.items() if k not in ("procedure", "doctor")} for r in d["resv"]],
            "version": version,
            "now": self.clock(),
        }

    # ── 쓰기 공통: 조작 → commit → 저장 → version+1 → SSE ──
    def _run(self, make_op, actor: str = DESK) -> dict:
        with self._lock:
            before = self.repo.load_state()
            now = self.clock()
            after = B.commit(before, make_op({"now": now, "actor": actor}), now)
            version = self.version() + 1
            self.repo.save_state(after, {"version": version, "undo": {"version": version, "state": before}})
        self.bus.publish(version)
        return {"version": version}

    def _resolve(self, schedule_id: str, requests: list[dict]) -> list[dict]:
        """`bundleId` 가 있는 요청 → 그 묶음의 다음 1장(1회 차감). 없으면 그대로."""
        if not any(r.get("bundleId") for r in requests):
            return requests
        d = self.repo.load_state()
        derived = self.repo.get_reference("derived", schedule_id) or {}
        events = self.repo.get_reference("events", schedule_id) or {}
        cust = next((c for c in d["customers"] if c["scheduleId"] == schedule_id), None)
        return BD.resolve(requests, BD.build(derived, events, cust, B.steps_of(d, schedule_id)))

    def check_in(self, schedule_id: str, steps: list[dict]) -> dict:
        with self._lock:
            items = self._resolve(schedule_id, steps)
            return self._run(lambda ctx: B.check_in(ctx, schedule_id, items))

    def place(self, schedule_id: str, room: str) -> dict:
        return self._run(lambda ctx: B.place(ctx, schedule_id, room))

    def move_sleep(self, schedule_id: str, room: str) -> dict:
        return self._run(lambda ctx: B.move_sleep(ctx, schedule_id, room))

    def return_room(self, schedule_id: str) -> dict:
        return self._run(lambda ctx: B.return_room(ctx, schedule_id))

    def assign(self, step_id: str, staff_id: str) -> dict:
        return self._run(lambda ctx: B.assign(ctx, step_id, staff_id))

    def unassign(self, step_id: str) -> dict:
        return self._run(lambda ctx: B.unassign(ctx, step_id))

    def add_procedures(self, schedule_id: str, items: list[dict]) -> dict:
        with self._lock:
            resolved = self._resolve(schedule_id, items)
            return self._run(lambda ctx: B.add_procedures(ctx, schedule_id, resolved))

    def no_show(self, schedule_id: str) -> dict:
        return self._run(lambda ctx: B.no_show(ctx, schedule_id))

    def reorder(self, schedule_id: str, step_ids: list[str]) -> dict:
        return self._run(lambda ctx: B.reorder(ctx, schedule_id, step_ids))

    def discharge(self, schedule_id: str) -> dict:
        return self._run(lambda ctx: B.discharge(ctx, schedule_id))

    def start(self, staff_id: str, step_id: str) -> dict:
        return self._run(lambda ctx: B.start(ctx, staff_id, step_id), actor=staff_id)

    def _events(self, schedule_id: str) -> dict:
        return self.repo.get_reference("events", schedule_id) or {}

    def _schedule_of_step(self, step_id: str) -> str:
        return B.find_step(self.repo.load_state(), step_id)["scheduleId"]

    def finish(self, staff_id: str, step_id: str) -> dict:
        events = self._events(self._schedule_of_step(step_id))
        return self._run(lambda ctx: B.finish(ctx, staff_id, step_id, events), actor=staff_id)

    def payment_complete(self, schedule_id: str) -> dict:
        events = self._events(schedule_id)
        return self._run(lambda ctx: B.payment_complete(ctx, schedule_id, events))

    def undo(self, version: int) -> dict:
        with self._lock:
            undo = self.repo.get_meta("undo")
            current = self.version()
            if not undo or undo["version"] != version or current != version:
                raise BadRequest("undo_unavailable", "되돌릴 수 있는 건 마지막 조작 하나뿐이에요")
            new_version = current + 1
            self.repo.save_state(undo["state"], {"version": new_version, "undo": None})
        self.bus.publish(new_version)
        return {"version": new_version}

    # ── 시드 ──
    def load_snapshot(self, snap: dict) -> dict:
        """스냅샷으로 DB 를 채운다(초기화 · seed build 공통). version 은 계속 올린다."""
        with self._lock:
            self.repo.replace_reference(snap["reference"])
            state = snapshot_to_state(snap["state"], self.clock())
            version = self.version() + 1
            self.repo.save_state(state, {"version": version, "undo": None, "seedMeta": snap.get("meta", {})})
        self.bus.publish(version)
        return {"version": version}

    def reset(self) -> dict:
        if not self.seed_path.exists():
            raise NotFound("seed_not_found", "seed.json 이 없어요 — 먼저 `python -m app.seed build`")
        return self.load_snapshot(json.loads(self.seed_path.read_text()))

    def snapshot(self) -> dict:
        """지금 DB → 스냅샷(시각은 지금 기준 오프셋)."""
        with self._lock:
            base = self.clock()
            meta = dict(self.repo.get_meta("seedMeta", {}) or {})
            meta.update({"kind": "save", "savedAt": datetime.fromtimestamp(base / 1000, KST).isoformat()})
            return {"meta": meta, "reference": self.repo.all_reference(),
                    "state": state_to_snapshot(self.repo.load_state(), base)}
