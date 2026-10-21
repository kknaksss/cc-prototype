"""ccc 조작(SPEC-003 §7.3) — 조작 1번 = event_log 1줄 + kos_op 0 ~ 2줄(§8). ccc 상태를 먼저 바꾸고 KOS 를 기다리지 않는다.

트랜잭션이 끝나면 `on_change()`(SSE 발행 · 반영 루프 깨우기)를 부른다.
"""

from collections.abc import Callable

from app.domain.clock import Clock
from app.domain.errors import BadRequest, Conflict, Forbidden, NotFound
from app.domain.kos_ops import OpSpec, accept_op, call_ops, cancel_tasks_op, complete_op, flow_step_op, room_op
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

        doctor = 자기 원장으로만(doctorId 생략 또는 자기와 같음) · admin = 원장을 골라 doctorId 필수 · nurse = 못 함.
        """
        if actor.role == "doctor":
            if doctor_id is not None and doctor_id != actor.staff_id:
                raise Forbidden("doctor_forbidden", "본인 이름으로만 수락할 수 있어요")
            doctor_id = actor.staff_id
        elif actor.role == "admin":
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
        if p is None or not p.present or p.kind != "procedure":  # etc(방 배정 등)는 조작 대상이 아니다
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
            # ① KOS 에서 끝나지 않은 비시술 작업(「방 배정」 등) 일괄 취소 → ② PROCEDURE_DONE(사용자 최종 결정 · E2E-3).
            #    시술은 ccc 에서 전부 완료라(완료 반영 대기 중일 수 있어) 취소 대상에서 뺀다. 남은 게 없으면 ① 생략.
            #    카드는 KOS 가 COMPLETED(데스크 귀가)가 되면 조회에서 빠진다(§5.1 조건 2)
            proc_seqs = {p.kos_sequence for p in r.procedures(v)}
            cancel = sorted(s for s in v.open_task_seqs if s not in proc_seqs)
            ev = tx.add_event(now, actor, "home", v.id, {"cancelSequences": cancel})
            tx.update_visit(v.id, flow_step=FLOW_DONE, flow_step_at=now, home_requested_at=now)
            specs = [cancel_tasks_op(v.kos_id, cancel)] if cancel else []
            self._ops(tx, ev, v, [*specs, flow_step_op(v.kos_id, FLOW_DONE)])
        self._done()
