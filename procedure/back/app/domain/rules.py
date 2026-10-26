"""상태 · 규칙 계산(SPEC-003 §5) — HTTP · DB 를 모른다. 같은 World 로 스냅샷과 조작 검사가 같은 답을 낸다."""

from datetime import datetime

from app.domain.clock import minutes_between
from app.domain.models import (
    BOARD_FLOW_STEPS,
    FLOW_DOING,
    FLOW_DONE,
    FLOW_WAITING,
    TASK_CANCELED,
    TASK_DONE,
    Accept,
    Anesthesia,
    Call,
    Procedure,
    Staff,
    Visit,
    World,
)

CALL_LIMIT_MIN = 5  # D-20 호출 미수락
ANES_LIMIT_MIN = 20  # D-20 마취 길어짐

VISIT_STATE = {FLOW_WAITING: "waiting", FLOW_DOING: "doing", FLOW_DONE: "home"}


class Rules:
    def __init__(self, world: World, now: datetime):
        self.w = world
        self.now = now
        # 유효 호출 = 그 시술이 들어간 가장 최근 호출(D-25). id 는 만든 순서대로 는다
        self._effective: dict[int, Call] = {}
        for call in sorted(world.calls.values(), key=lambda c: c.id):
            for pid in call.procedure_ids:
                self._effective[pid] = call
        self._accepts: dict[tuple[int, int], Accept] = {(a.call_id, a.procedure_id): a for a in world.accepts}
        self._called = {pid for call in world.calls.values() for pid in call.procedure_ids}
        self._cards = [v for v in world.visits.values()
                       if v.present and v.flow_step in BOARD_FLOW_STEPS and v.room_id is not None]
        self._card_ids = {v.id for v in self._cards}

    # ---- 원장 목록(§4.6)
    def doctors(self) -> list[Staff]:
        return sorted((s for s in self.w.staff.values() if s.is_doctor), key=lambda s: s.name)

    def is_listed_doctor(self, staff_id: int | None) -> bool:
        s = self.w.staff.get(staff_id) if staff_id is not None else None
        return bool(s and s.is_doctor)

    def busy_room(self, staff_id: int) -> str | None:
        """그 원장이 집도의인 진행 중 시술의 방(없으면 비어 있음)."""
        for v in self.cards():
            for p in self.procedures(v):
                if self.proc_state(p) == "doing" and staff_id in p.doctor_staff_ids:
                    return self.room_title(v)
        return None

    # ---- 「방 배정」 — 작업 규칙의 유일한 예외(2026-10-25)
    def is_room_task(self, p: Procedure) -> bool:
        """「방 배정」 = 방 붙은 ETCETERA 이면서 ccc 가 한 번도 호출하지 않은 작업.

        「방 배정」은 호출 대상이 아니므로 호출된 적이 있으면 「방 배정」일 수 없다 — 시트팩 등을 호출하면 호출 전 방 넣기
        (change-tasks-room · 로컬 room_kos_id)로 방이 붙어도 일반 시술로 남는다. 스냅샷에는 싣고(`isRoomTask` — front 가 숨김)
        판정(체크 · 호출 · 시작 · 종료 · 전부 완료 · 수납)에서는 뺀다. [귀가 대기] 취소 대상은 안 끝난 「방 배정」뿐.
        카드 방 고르기(`kos/sync.py` `_card_room_task`)는 type 무관(다른 판정).
        """
        return p.kind == "etc" and bool(p.room_kos_id) and p.id not in self._called

    # ---- 카드(§5.1)
    def cards(self) -> list[Visit]:
        return list(self._cards)

    def is_card(self, v: Visit) -> bool:
        return v.id in self._card_ids

    def visit_state(self, v: Visit) -> str:
        return VISIT_STATE.get(v.flow_step or "", "waiting")

    def is_home(self, v: Visit) -> bool:
        return v.flow_step == FLOW_DONE

    def room_title(self, v: Visit) -> str:
        r = self.w.rooms.get(v.room_id) if v.room_id is not None else None
        return r.title if r else ""

    def items(self, v: Visit) -> list[Procedure]:
        """카드에 보이는 작업 — KOS 목록에 있고 취소 아닌 작업 전부 · sequence 순.

        type(PROCEDURE · ETCETERA) 무관 · 「방 배정」도 싣는다(판정은 `procedures`). 빼는 것은 CANCELED 뿐(2026-10-25).
        """
        ps = [p for p in self.w.procedures.values() if p.visit_id == v.id and p.present and p.kos_status != TASK_CANCELED]
        return sorted(ps, key=lambda p: p.kos_sequence)

    def procedures(self, v: Visit) -> list[Procedure]:
        """시술 = 카드 작업 중 「방 배정」을 뺀 전부(type 무관) — 호출 · 시작 · 종료 · 전부 완료 · 수납 판정이 이것을 본다."""
        return [p for p in self.items(v) if not self.is_room_task(p)]

    def ordered_procedures(self, v: Visit) -> list[Procedure]:
        """표시 순서 = 완료(완료 시각 순) → 진행 → 대기(sequence 순) — §5.9."""
        rank = {"done": 0, "doing": 1, "wait": 2}
        far = datetime.max.replace(tzinfo=self.now.tzinfo)
        return sorted(self.items(v), key=lambda p: (rank[self.proc_state(p)],
                                                          (p.completed_at or far) if self.proc_state(p) == "done" else far,
                                                          p.kos_sequence))

    def all_done(self, v: Visit) -> bool:
        ps = self.procedures(v)
        return bool(ps) and all(self.proc_state(p) == "done" for p in ps)

    def payment_required(self, v: Visit) -> bool:
        return any(p.payment_required for p in self.procedures(v))

    # ---- 시술 상태(§5.9)
    def proc_state(self, p: Procedure) -> str:
        if p.kos_status == TASK_DONE:
            return "done"
        if p.started_at is not None:
            return "doing"
        return "wait"

    def effective_call(self, p: Procedure) -> Call | None:
        return self._effective.get(p.id)

    def accept_of(self, call: Call, p: Procedure) -> Accept | None:
        return self._accepts.get((call.id, p.id))

    def has_doctor(self, p: Procedure) -> bool:
        return any(self.is_listed_doctor(sid) for sid in p.doctor_staff_ids)

    def shown_doctor(self, p: Procedure) -> Staff | None:
        """집도의 표시 — 원장 목록 계정만(시스템 · 마취용은 이름을 안 보인다, D-11)."""
        for sid in p.doctor_staff_ids:
            if self.is_listed_doctor(sid):
                return self.w.staff[sid]
        return None

    def pickable(self, v: Visit, p: Procedure) -> bool:
        return not self.is_room_task(p) and not self.is_home(v) and self.proc_state(p) == "wait"

    def start_block(self, v: Visit, p: Procedure) -> str | None:
        """[시작] 을 막는 이유(§5.6) — None 이면 켜짐."""
        if self.is_home(v):
            return "visit_home"
        if self.is_room_task(p) or self.proc_state(p) != "wait":
            return "procedure_not_waiting"
        call = self.effective_call(p)
        if call is not None:
            return None if self.accept_of(call, p) else "call_not_accepted"
        return None if self.has_doctor(p) else "no_doctor"

    # ---- 호출 · 수락(§5.4 · §5.5)
    def receivable(self, call: Call) -> list[Procedure]:
        """그 호출이 유효 호출인 시술 중 아직 수락 안 된 대기 시술(D-27)."""
        v = self.w.visits.get(call.visit_id)
        if v is None or not self.is_card(v) or self.is_home(v):
            return []
        listed = {p.id: p for p in self.procedures(v)}
        out = []
        for pid in call.procedure_ids:
            p = listed.get(pid)
            if p and self.effective_call(p) is call and not self.accept_of(call, p) and self.proc_state(p) == "wait":
                out.append(p)
        return sorted(out, key=lambda p: p.kos_sequence)

    def open_calls(self, v: Visit | None = None) -> list[Call]:
        """받을 시술이 남은 호출 — 오래된 순."""
        calls = [c for c in self.w.calls.values() if (v is None or c.visit_id == v.id) and self.receivable(c)]
        return sorted(calls, key=lambda c: (c.created_at, c.id))

    # ---- 마취(§5.3)
    def anesthesia(self, v: Visit) -> list[Anesthesia]:
        return sorted((a for a in self.w.anesthesia if a.visit_id == v.id), key=lambda a: (a.started_at, a.id))

    def running_anes(self, v: Visit) -> Anesthesia | None:
        return next((a for a in self.anesthesia(v) if a.ended_at is None), None)

    def anes_long(self, v: Visit) -> bool:
        anes = self.running_anes(v)
        return bool(anes and minutes_between(anes.started_at, self.now) >= ANES_LIMIT_MIN)

    def last_anes_minutes(self, v: Visit) -> int | None:
        ended = [a for a in self.anesthesia(v) if a.ended_at is not None]
        return minutes_between(ended[-1].started_at, ended[-1].ended_at) if ended else None

    # ---- 확인이 필요(§5.8) — 귀가 대기 전 → 마취 → 호출, 하나만
    def need(self, v: Visit) -> tuple[str, datetime, int] | None:
        if self.is_home(v):
            return None
        if self.all_done(v):
            last = max((p.completed_at for p in self.procedures(v) if p.completed_at), default=None)
            return ("home", last or self.now, 0)
        anes = self.running_anes(v)
        if anes and self.anes_long(v):
            return ("anes", anes.started_at, ANES_LIMIT_MIN)
        calls = self.open_calls(v)
        if calls and minutes_between(calls[0].created_at, self.now) >= CALL_LIMIT_MIN:
            return ("call", calls[0].created_at, CALL_LIMIT_MIN)
        return None
