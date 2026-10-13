"""현황판 상태 서비스 — 조작(§5.3) · 되돌리기 · version · 초기화(§4.2) · 「이걸 시드로」(§4.3)."""

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from app.domain import board as B
from app.domain.errors import BadRequest, Conflict, NotFound
from app.domain.rooms import CORRIDORS, rooms_payload
from app.repository.state_repo import StateRepository
from app.seed.capture import KST
from app.service.events import EventBus
from app.service.snapshot import snapshot_to_state, state_to_snapshot

CUSTOMER_FIELDS = ("scheduleId", "name", "nationality", "room", "order", "step", "since", "prev", "done")


def now_ms() -> int:
    return int(time.time() * 1000)


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
            st = self.repo.load_state()
            version = self.version()
        return {
            "customers": [{k: c.get(k) for k in CUSTOMER_FIELDS} for c in st["customers"]],
            "staff": st["staff"],
            "resv": st["resv"],
            "rooms": rooms_payload(),
            "corridors": CORRIDORS,
            "version": version,
            "now": self.clock(),
        }

    # ── 쓰기 공통: 시안 commit → 저장 → version+1 → SSE ──
    def _mutate(self, fn: B.Mutation, undoable: bool = True) -> dict:
        with self._lock:
            before = self.repo.load_state()
            after = B.commit(before, fn, self.clock())
            version = self.version() + 1
            undo = {"version": version, "state": before} if undoable else None
            self.repo.save_state(after, {"version": version, "undo": undo})
        self.bus.publish(version)
        return {"version": version}

    def assign(self, staff_id: str, room: str) -> dict:
        B.check_room(room)
        return self._mutate(B.assign(staff_id, room))

    def complete(self, staff_id: str, room: str) -> dict:
        B.check_room(room)
        return self._mutate(B.complete(staff_id, room))

    def remove_staff(self, staff_id: str, room: str) -> dict:
        B.check_room(room)
        return self._mutate(B.remove_staff(staff_id, room))

    def place(self, schedule_id: str, room: str) -> dict:
        B.check_room(room)
        return self._mutate(B.place(schedule_id, room))

    def check_in(self, schedule_id: str | None, name: str | None, order: list[dict] | None) -> dict:
        with self._lock:
            st = self.repo.load_state()
            if schedule_id:
                row = next((r for r in st["resv"] if r["scheduleId"] == schedule_id), None)
                if not row:
                    raise NotFound("reservation_not_found", f"예약 {schedule_id} 이 없어요")
                if row["st"] != "booked" or any(c["scheduleId"] == schedule_id for c in st["customers"]):
                    raise Conflict("already_checked_in", "이미 접수했거나 접수할 수 없는 예약이에요")
                derived = self.repo.get_reference("derived", schedule_id) or {}
                ref = self.repo.get_reference("schedule", schedule_id) or {}
                use = order or derived.get("plannedOrder") or []
                if not use:
                    raise BadRequest("empty_order", "오더가 비어 있어요")
                cust = {"scheduleId": schedule_id, "name": row["name"], "order": use,
                        "nationality": (ref.get("visitor") or {}).get("nationality", "")}
                return self._mutate(B.check_in(cust, row, None))
            if not name or not name.strip():
                raise BadRequest("name_required", "현장 접수는 이름이 필요해요")
            if not order:
                raise BadRequest("empty_order", "오더가 비어 있어요")
            n = int(self.repo.get_meta("walkN", 0)) + 1
            self.repo.set_meta("walkN", n)
            sid = f"walkin-{n}"
            hm = datetime.fromtimestamp(self.clock() / 1000, KST).strftime("%H:%M")
            walk = {"scheduleId": sid, "time": hm, "name": name.strip(), "procedure": "현장 접수", "doctor": "미정",
                    "st": "checked"}
            cust = {"scheduleId": sid, "name": name.strip(), "order": order, "nationality": ""}
            return self._mutate(B.check_in(cust, None, walk))

    def undo(self, version: int) -> dict:
        with self._lock:
            undo = self.repo.get_meta("undo")
            current = self.version()
            if not undo or undo["version"] != version or current != version:
                raise Conflict("undo_unavailable", "되돌릴 수 있는 건 마지막 변경 하나뿐이에요")
            new_version = current + 1
            self.repo.save_state(undo["state"], {"version": new_version, "undo": None})
        self.bus.publish(new_version)
        return {"version": new_version}

    def doctor_start(self, staff_id: str, schedule_id: str) -> dict:
        self._require_doctor(staff_id)
        return self._mutate(B.doctor_start(staff_id, schedule_id))

    def doctor_finish(self, staff_id: str, schedule_id: str) -> dict:
        self._require_doctor(staff_id)
        return self._mutate(B.doctor_finish(staff_id, schedule_id))

    def _require_doctor(self, staff_id: str) -> None:
        s = B.find_staff(self.repo.load_state(), staff_id)
        if s["role"] != "의사":
            raise BadRequest("not_doctor", "진료 시작 · 완료는 의사만 할 수 있어요")

    # ── 시드 ──
    def load_snapshot(self, snap: dict) -> dict:
        """스냅샷으로 DB 를 채운다(초기화 · seed build 공통). version 은 계속 올린다."""
        with self._lock:
            self.repo.replace_reference(snap["reference"])
            state = snapshot_to_state(snap["state"], self.clock())
            version = self.version() + 1
            self.repo.save_state(state, {"version": version, "undo": None, "walkN": snap.get("walkN", 0),
                                         "seedMeta": snap.get("meta", {})})
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
            return {
                "meta": meta,
                "reference": self.repo.all_reference(),
                "state": state_to_snapshot(self.repo.load_state(), base),
                "walkN": int(self.repo.get_meta("walkN", 0)),
            }
