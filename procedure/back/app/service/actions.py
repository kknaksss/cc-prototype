"""ccc 조작(SPEC-003 §7.3) — 조작 1번 = event_log 1줄 + kos_op 0 ~ 2줄(§8). ccc 상태를 먼저 바꾸고 KOS 를 기다리지 않는다.

트랜잭션이 끝나면 `on_change()`(SSE 발행 · 반영 루프 깨우기)를 부른다.
"""

from collections.abc import Callable

from app.domain.clock import Clock, iso, kst_day
from app.domain.errors import BadRequest, Conflict, Forbidden, NotFound
from app.domain.kos_ops import (
    OpSpec,
    accept_op,
    call_ops,
    cancel_tasks_op,
    complete_op,
    flow_step_op,
    room_op,
    uncomplete_op,
)
from app.domain.models import FLOW_DOING, FLOW_DONE, FLOW_WAITING, TASK_DONE, TASK_READY, TASK_WAITING, Account, Call, Visit
from app.domain.rules import Rules
from app.repository.repo import Repository, Tx

MESSAGES = {
    "visit_home": "귀가 대기 고객이에요",
    "anesthesia_running": "이미 마취 중이에요",
    "anesthesia_not_running": "진행 중인 마취가 없어요",
    "procedure_not_waiting": "대기 중인 시술이 아니에요",
    "no_procedures": "호출할 시술을 고르세요",
    "doctor_not_listed": "원장 목록에 없는 계정이에요",
    "nothing_to_accept": "받을 시술이 없어요",
    "doctor_mismatch": "지정된 원장이 아니에요",
    "not_designated_call": "지정 호출이 아니에요",
    "call_not_accepted": "호출이 아직 수락되지 않았어요",
    "no_doctor": "담당의가 없어요",
    "procedure_not_started": "시작하지 않은 시술이에요",
    "procedures_not_done": "끝나지 않은 시술이 있어요",
    "procedure_not_doing": "진행 중인 시술이 아니에요",
    "procedure_not_done": "완료된 시술이 아니에요",
}


def conflict(code: str) -> Conflict:
    return Conflict(code, MESSAGES[code])


class ActionService:
    def __init__(self, repo: Repository, clock: Clock, on_change: Callable[[], None] = lambda: None):
        self.repo = repo
        self.clock = clock
        self.on_change = on_change
        # 호출이 생긴 뒤(커밋 뒤) — 원장 호출 푸시(SPEC-004 §5-1.2). (call_id, 누른 계정 login_id)
        self.on_call: Callable[[int, str], None] = lambda call_id, actor: None

    # ------------------------------------------------------------------ 공통
    def _visit(self, r: Rules, visit_id: int) -> Visit:
        v = r.w.visits.get(visit_id)
        if v is None or not r.is_card(v):
            raise NotFound()
        return v

    def _ops(self, tx: Tx, event_id: int, visit: Visit, specs: list[OpSpec]) -> None:
        now = self.clock.now()
        for spec in specs:
            tx.add_op(event_id, visit.id, spec.api, spec.path, spec.body, spec.expect, now)

    def _done(self) -> None:
        self.on_change()

    # ------------------------------------------------------------------ 마취(D-23 · KOS 없음)
    def anesthesia_start(self, actor: str, visit_id: int) -> None:
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            v = self._visit(r, visit_id)
            if r.is_home(v):
                raise conflict("visit_home")
            if r.running_anes(v):
                raise conflict("anesthesia_running")
            ev = tx.add_event(now, actor, "anes_start", v.id, {})
            tx.start_anesthesia(v.id, now, ev)
        self._done()

    def anesthesia_end(self, actor: str, visit_id: int) -> None:
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            v = self._visit(r, visit_id)
            running = r.running_anes(v)
            if running is None:
                raise conflict("anesthesia_not_running")
            ev = tx.add_event(now, actor, "anes_end", v.id, {"anesthesiaId": running.id})
            tx.end_anesthesia(running.id, now, ev)
        self._done()

    # ------------------------------------------------------------------ 호출(D-24 ~ D-26)
    def _new_call(self, tx: Tx, r: Rules, actor: str, v: Visit, kind: str, target: int | None, procedure_ids: list[int],
                  event_type: str, from_call: int | None = None) -> int:
        now = self.clock.now()
        procs = [r.w.procedures[pid] for pid in procedure_ids]
        seqs = sorted(p.kos_sequence for p in procs)
        ev = tx.add_event(now, actor, event_type, v.id, {"kind": kind, "targetDoctorId": target, "procedureIds": procedure_ids,
                                                         "fromCallId": from_call})
        call_id = tx.add_call(v.id, kind, target, now, ev, procedure_ids, from_call)
        tx.set_event_payload(ev, {"callId": call_id, "kind": kind, "targetDoctorId": target, "procedureIds": procedure_ids,
                                  "fromCallId": from_call})
        for p in procs:  # ccc 즉시 — 호출함(WAITING)
            tx.update_procedure(p.id, kos_status=TASK_WAITING, doctor_call_at=now)
        # ① 카드 방을 고른 작업에 넣기(KOS: 방 없는 작업 호출 = 400 roomId NotFound) — 이미 다 그 방이면 보내지 않고 confirmed
        room = r.w.rooms.get(v.room_id) if v.room_id is not None else None
        if room is not None:
            spec = room_op(v.kos_id, seqs, room.kos_id)
            same = all(p.room_kos_id == room.kos_id for p in procs)
            tx.add_op(ev, v.id, spec.api, spec.path, spec.body, spec.expect, now, status="confirmed" if same else "pending")
            for p in procs:
                tx.update_procedure(p.id, room_kos_id=room.kos_id)
        # ② 담당자 → ③ 호출
        self._ops(tx, ev, v, call_ops(v.kos_id, seqs))
        return call_id

    def create_call(self, actor: str, visit_id: int, procedure_ids: list[int], kind: str, doctor_id: int | None) -> int:
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            v = self._visit(r, visit_id)
            if r.is_home(v):
                raise conflict("visit_home")
            ids = list(dict.fromkeys(procedure_ids))
            if not ids:
                raise conflict("no_procedures")
            listed = {p.id: p for p in r.procedures(v)}
            for pid in ids:
                if pid not in listed:
                    raise NotFound("이 고객의 시술이 아니에요")
                if r.proc_state(listed[pid]) != "wait":
                    raise conflict("procedure_not_waiting")
            if kind == "one" and not r.is_listed_doctor(doctor_id):
                raise conflict("doctor_not_listed")
            call_id = self._new_call(tx, r, actor, v, kind, doctor_id if kind == "one" else None, ids, "call_create")
        self._done()
        self.on_call(call_id, actor)
        return call_id

    def _call(self, r: Rules, call_id: int) -> Call:
        call = r.w.calls.get(call_id)
        if call is None:
            raise NotFound()
        return call

    def reassign_all(self, actor: str, call_id: int) -> int:
        """[다른 원장에게] = 같은 받을 시술로 「전체」 호출을 새로 만든다(D-27). 기존 지정 호출은 그대로."""
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            call = self._call(r, call_id)
            if call.kind != "one":
                raise conflict("not_designated_call")
            procs = r.receivable(call)
            if not procs:
                raise conflict("nothing_to_accept")
            v = r.w.visits[call.visit_id]
            new_id = self._new_call(tx, r, actor, v, "all", None, [p.id for p in procs], "call_reassign_all", call.id)
        self._done()
        self.on_call(new_id, actor)
        return new_id

    def accept(self, actor: Account, call_id: int, doctor_id: int | None, source: str = "app") -> list[int]:
        """수락(SPEC-004 §3.4) — 검사 순서: 역할 403(요청만 보고) → 404 → not_your_call 403 → 409.

        doctor = 자기 원장으로만(doctorId 생략 또는 자기와 같음) · admin · coordinator = 원장을 골라 doctorId 필수 ·
        nurse = 못 함.
        """
        if actor.role == "doctor":
            if doctor_id is not None and doctor_id != actor.staff_id:
                raise Forbidden("doctor_forbidden", "본인 이름으로만 수락할 수 있어요")
            doctor_id = actor.staff_id
        elif actor.role in ("admin", "coordinator"):  # 코디 = 관리자와 같다(SPEC-005 §3.4 · r1 F2)
            if doctor_id is None:
                raise BadRequest("invalid_request", "doctorId: 원장을 골라 주세요")
        else:
            raise Forbidden("role_forbidden", "이 계정은 수락할 수 없어요")
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            call = self._call(r, call_id)
            if actor.role == "doctor" and call.kind == "one" and call.target_staff_id != doctor_id:
                raise Forbidden("not_your_call", "다른 원장을 지정한 호출이에요")
            if not r.is_listed_doctor(doctor_id):
                raise conflict("doctor_not_listed")
            if call.kind == "one" and call.target_staff_id != doctor_id:
                raise conflict("doctor_mismatch")
            procs = r.receivable(call)
            if not procs:
                raise conflict("nothing_to_accept")
            v = r.w.visits[call.visit_id]
            ids = [p.id for p in procs]
            ev = tx.add_event(now, actor.login_id, "call_accept", v.id,
                              {"callId": call.id, "doctorId": doctor_id, "procedureIds": ids, "byRole": actor.role,
                               "source": source})  # push(알림 액션) | app | web
            for p in procs:
                tx.add_accept(call.id, p.id, doctor_id, now, ev)
                tx.update_procedure(p.id, doctor_staff_ids=[doctor_id], kos_status=TASK_READY, doctor_assigned_at=now)
            doctor = r.w.staff[doctor_id]
            self._ops(tx, ev, v, [accept_op(v.kos_id, sorted(p.kos_sequence for p in procs), doctor.kos_id)])
        self._done()
        return ids

    # ------------------------------------------------------------------ [시작] · [종료] (D-29 ~ D-32)
    def _procedure(self, r: Rules, procedure_id: int):
        p = r.w.procedures.get(procedure_id)
        if p is None or not p.present or r.is_room_task(p):  # type 무관 조작 대상 · 「방 배정」만 아님(2026-10-25)
            raise NotFound()
        v = self._visit(r, p.visit_id)
        return v, p

    def start(self, actor: str, procedure_id: int) -> bool:
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            v, p = self._procedure(r, procedure_id)
            block = r.start_block(v, p)
            if block:
                raise conflict(block)
            first = v.flow_step == FLOW_WAITING
            ev = tx.add_event(now, actor, "proc_start", v.id, {"procedureId": p.id, "flowStepChanged": first})
            tx.update_procedure(p.id, started_at=now, started_event_id=ev)
            if first:  # 그 고객의 첫 [시작] → 시술 진행
                tx.update_visit(v.id, flow_step=FLOW_DOING, flow_step_at=now)
                self._ops(tx, ev, v, [flow_step_op(v.kos_id, FLOW_DOING)])
        self._done()
        return first

    def finish(self, actor: str, procedure_id: int) -> None:
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            v, p = self._procedure(r, procedure_id)
            if r.proc_state(p) != "doing":
                raise conflict("procedure_not_started")
            ev = tx.add_event(now, actor, "proc_finish", v.id, {"procedureId": p.id})
            tx.update_procedure(p.id, kos_status=TASK_DONE, completed_at=now)
            self._ops(tx, ev, v, [complete_op(v.kos_id, p.kos_sequence)])
        self._done()

    # ------------------------------------------------------------------ 되돌리기(§5.13 — D-28 을 [시작] · [종료]에 한해 뒤집음)
    def undo_start(self, actor: str, procedure_id: int) -> bool:
        """진행 → 시술 대기. 호출 · 수락 · 집도의는 그대로. 진행 · 완료가 0 이 되면 고객도 시술 대기 + flow-step op(항상).

        → 고객을 시술 대기로 돌렸나(flowStepChanged).
        """
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            v, p = self._procedure(r, procedure_id)
            block = r.undo_start_block(v, p)
            if block:
                raise conflict(block)
            back = r.back_to_waiting(v, p)
            ev = tx.add_event(now, actor, "proc_undo_start", v.id,
                              {"procedureId": p.id, "startedAt": iso(p.started_at),
                               "startedEventId": tx.started_event_id(p.id), "flowStepChanged": back})
            tx.update_procedure(p.id, started_at=None, started_event_id=None)
            if back:  # 첫 [시작]의 거울 — KOS 값을 따로 읽지 않고 늘 만든다(400 이면 같은 단계 규칙 · §8)
                tx.update_visit(v.id, flow_step=FLOW_WAITING, flow_step_at=now)
                self._ops(tx, ev, v, [flow_step_op(v.kos_id, FLOW_WAITING)])
        self._done()
        return back

    def undo_finish(self, actor: str, procedure_id: int) -> None:
        """완료 → 시술 중(옛 [시작] 시각 그대로). kos_status 즉시 값 = READY(WP-KOS K2). 고객 상태는 그대로."""
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            v, p = self._procedure(r, procedure_id)
            block = r.undo_finish_block(v, p)
            if block:
                raise conflict(block)
            ev = tx.add_event(now, actor, "proc_undo_finish", v.id, {"procedureId": p.id, "completedAt": iso(p.completed_at)})
            tx.update_procedure(p.id, completed_at=None, kos_status=TASK_READY)
            self._ops(tx, ev, v, [uncomplete_op(v.kos_id, p.kos_sequence)])
        self._done()

    # ------------------------------------------------------------------ [귀가 대기] (D-33)
    def home(self, actor: str, visit_id: int) -> None:
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            v = self._visit(r, visit_id)
            if r.is_home(v):
                raise conflict("visit_home")
            if not r.all_done(v):
                raise conflict("procedures_not_done")
            # ① 안 끝난 「방 배정」 취소 → ② PROCEDURE_DONE(E2E-3). 다른 작업은 전부 완료여야 귀가 대기라 취소할 것이 없다
            #    (2026-10-25). 「방 배정」이 없거나 이미 끝났으면 ① 생략. 카드는 KOS COMPLETED(데스크 귀가)면 조회에서 빠진다
            cancel = sorted(p.kos_sequence for p in r.items(v) if r.is_room_task(p) and r.proc_state(p) != "done")
            ev = tx.add_event(now, actor, "home", v.id, {"cancelSequences": cancel})
            tx.update_visit(v.id, flow_step=FLOW_DONE, flow_step_at=now, home_requested_at=now)
            specs = [cancel_tasks_op(v.kos_id, cancel)] if cancel else []
            self._ops(tx, ev, v, [*specs, flow_step_op(v.kos_id, FLOW_DONE)])
        self._done()

    # ------------------------------------------------------------------ 카드 순서(SPEC-003 0.4.0 §5.12 · KOS 없음)
    def board_order(self, actor: str, visit_ids: list[int]) -> list[int]:
        """오늘(KST) 순서를 통째로 바꾼다 → 거르기 뒤 저장된 목록. 역할 = 세 역할 모두(SPEC-004 §3.4).

        같은 id 두 번만 400 — 지금 카드가 아닌 id(없는 visit · 사라진 카드 · 다른 날 · 귀가 대기)는 오류 없이 뺀다.
        event_log(board_order) 1줄 · kos_op 0줄.
        """
        if len(set(visit_ids)) != len(visit_ids):
            raise BadRequest("invalid_request", "visitIds: 같은 id 가 두 번 있어요")
        now = self.clock.now()
        day = kst_day(now)
        with self.repo.tx() as tx:
            r = Rules(tx.world(), now)
            movable = {v.id for v in r.cards() if not r.is_home(v)}
            kept = [vid for vid in visit_ids if vid in movable]
            ev = tx.add_event(now, actor, "board_order", None, {"day": day, "visitIds": kept})
            tx.put_board_order(day, kept, now, actor, ev)
        self._done()
        return kept
