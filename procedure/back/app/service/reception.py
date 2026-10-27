"""[접수 완료] 묶음 · [실장 호출] · [귀가 완료] · [+ 상담 추가](SPEC-005 §5.6 · §5.8 · §5.10 · §8 · 10-27 E2E).

묶음은 0단계에서 지금 KOS 단계 · 작업을 읽고 남은 단계만 간다(이어 하기). 실패하면 거기서 멈추고 되돌리지 않는다(D-48).
끝 단계를 보낸 뒤에는 바로 응답한다 — 사본에 끝 단계를 먼저 싣고, KOS 반영 확인 · 시술 현황 조회는 뒤에서(10-27 #14).
"""

import asyncio
import contextlib
import logging
from typing import Any

from app.domain.clock import KST
from app.domain.errors import BadGateway, BadRequest, Conflict, NotFound
from app.domain.models import Account, Reservation, Room
from app.domain.reservation_rules import (
    AFTER_END_FLOWS,
    CLOSED_MAINS,
    CONSULT_ADD_FLOWS,
    ROOM_TASK_TITLE,
    reception_room_task,
    state_of,
)
from app.kos.reservation_sync import PATH_DETAIL, apply_schedule, tasks_of
from app.service import kos_errors
from app.service.reservations import (
    PATH_UPDATE,
    ReservationService,
    ResvContext,
    _counselors,
    busy_rooms,
)

log = logging.getLogger("procedure.resv")

PATH_RECEPT = "schedule/v1/commands/recept"
PATH_ADD_TASKS = "schedule/v1/commands/add-flow-tasks"
PATH_TASKS_ROOM = "schedule/flow/v1/commands/change-tasks-room"
PATH_FLOW_STEP = "schedule/v1/commands/change-flow-step"  # 내부 — 키 = id(RM§2.3)
PATH_OPEN_FLOW_STEP = "schedule/open/v1/commands/change-flow-step"  # 공개 — 키 = scheduleId
READ_GAP = 0.5  # 반영 기다림 간격 — 0.5초 × 10 = 5초까지(§5.6 의 1초 × 5 와 같은 한도 · 10-27 #14)
READ_TRIES = 10
FOLLOW_UP_SEC = 3.0  # 끝 단계 뒤 KOS 반영 확인까지(데모 시험 0 ~ 3초 — reservation-reception-test-report)
END_STEP = {"consultation": "CONSULTATION_WAITING", "direct": "PROCEDURE_WAITING"}  # 진행 경로 → 끝 단계(D-32 · D-33)
SLOW = "KOS 반영이 늦어요 · 잠시 뒤 다시 눌러 주세요"


class ReceptionService:
    def __init__(self, resv: ReservationService):
        self.resv = resv
        self.sleep = asyncio.sleep  # 시험이 바꿔 끼운다
        self.read_gap = READ_GAP
        self.follow_up_sec = FOLLOW_UP_SEC
        self._bg: set[asyncio.Task] = set()
        self.spawn = self._spawn  # 응답 뒤 할 일 — 시험이 바꿔 끼운다

    # ------------------------------------------------------------------ 공통
    @property
    def repo(self):
        return self.resv.repo

    def _reservation(self, reservation_id: int) -> Reservation:
        with self.repo.tx() as tx:
            return self.resv._reservation(tx, reservation_id)

    async def _read(self, actor: Account, r: Reservation, step: str | None) -> dict[str, Any]:
        resp = await self.resv.kos_write(actor, "get-schedule-detail", self.resv.client().internal(
            PATH_DETAIL, {"scheduleId": r.kos_id}), reservation_id=r.id, step=step)
        data = resp.get("data")
        if not isinstance(data, dict):
            raise BadGateway("kos_unavailable", "KOS 일정 응답 형식", step=step)
        with self.repo.tx() as tx:
            apply_schedule(tx, data, self.resv.clock.now(), r.day)
        return data

    async def _wait(self, actor: Account, r: Reservation, step: str, seen, *, now: bool = False) -> dict[str, Any]:
        """read_gap 간격 최대 READ_TRIES 번 다시 읽기 — seen(일정) 이 참이면 그 일정. 안 보이면 409 kos_slow.

        now = 첫 읽기를 기다리지 않는다(바로 보이는 쓰기 — change-tasks-room).
        """
        for i in range(READ_TRIES):
            if i or not now:
                await self.sleep(self.read_gap)
            sch = await self._read(actor, r, step)
            if seen(sch):
                return sch
        raise Conflict("kos_slow", SLOW, step=step)

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    async def _follow_up(self, actor: Account, r: Reservation) -> None:
        """응답 뒤 — KOS 반영을 기다려 사본을 다시 읽고(캐시 비움) 시술 현황 조회 1회. 실패해도 조작 결과는 그대로."""
        await self.sleep(self.follow_up_sec)
        with contextlib.suppress(Exception):
            await self._read(actor, r, None)
        self._after(r)
        await self._procedure_board()

    def _after(self, r: Reservation) -> None:
        self.resv.after_write(r.day)

    async def _procedure_board(self) -> None:
        """단계 · 방이 바뀐 뒤 시술 현황 일정 조회 1회(§4.4) — 실패해도 조작 결과는 그대로."""
        rt = self.resv.runtime
        if rt is None:
            return
        try:
            await rt.tick()
        except Exception as e:
            log.warning("시술 현황 조회 실패: %s", kos_errors.describe(e))

    # ------------------------------------------------------------------ §5.6 [접수 완료]
    async def run(self, actor: Account, reservation_id: int, room_id: int, route: str = "consultation") -> str | None:
        r = self._reservation(reservation_id)
        with self.repo.tx() as tx:
            room = next((x for x in tx.rooms() if x.id == room_id), None)
            room_task_id = self.resv.s.kos_room_task_id or next(
                (k for k, title, deleted in tx.etc_task_defs() if title.strip() == ROOM_TASK_TITLE and not deleted), None)
        if room is None:
            raise NotFound("없는 방이에요")
        await self.resv.ensure_today()  # 「사용 중」 = 오늘 사본(§4.2 W7)

        # 0 — 지금 KOS 단계 · 작업으로 갈래를 다시 정한다
        sch = await self._read(actor, r, None)
        r = self._reservation(reservation_id)
        flow = sch.get("flowStep")
        status = (sch.get("reservation") or {}).get("status")
        if status == "CANCELED":
            raise Conflict("not_receivable", "접수할 수 없는 예약이에요")
        if flow in AFTER_END_FLOWS:  # 반영 지연 · 두 번 누름 — 보내지 않고 성공
            return flow
        if flow not in ("RESERVED", "RECEPTION"):  # 신분 조건 없음(10-27 U2 뒤집음)
            raise Conflict("not_receivable", "접수할 수 없는 예약이에요")
        if not room_task_id:
            raise Conflict("room_task_missing", "「방 배정」 기타 작업을 찾지 못했어요")
        self._check_room(r, room, tasks_of(sch))

        done: list[str] = []
        try:
            if flow == "RESERVED":  # 1 접수 → 2 반영 기다림
                await self._send(actor, r, "recept", PATH_RECEPT, {"scheduleId": r.kos_id})
                done.append("recept")
                sch = await self._wait(actor, r, "recept", lambda s: s.get("flowStep") != "RESERVED")
            task = reception_room_task(tasks_of(sch))
            if task is None:  # 3 「방 배정」 작업 추가 → 4 sequence 읽기
                await self._send(actor, r, "add_task", PATH_ADD_TASKS, {"scheduleId": r.kos_id, "tasks": [{
                    "type": "ETCETERA", "title": ROOM_TASK_TITLE,
                    "etceteraConfiguration": {"etceteraTaskId": room_task_id, "name": ROOM_TASK_TITLE,
                                              "translsMap": {"name": {}}},
                    "translsMap": {"title": {}}}]})
                done.append("add_task")
                sch = await self._wait(actor, r, "read_sequence", lambda s: reception_room_task(tasks_of(s)) is not None)
                task = reception_room_task(tasks_of(sch))
                done.append("read_sequence")
            seq = task["sequence"]  # type: ignore[index]
            if not task.get("roomKosId"):  # type: ignore[union-attr]  # 5 방 지정 → 보일 때까지
                await self._send(actor, r, "assign_room", PATH_TASKS_ROOM,
                                 {"scheduleId": r.kos_id, "sequences": [seq], "roomId": room.kos_id})
                done.append("assign_room")
                await self._wait(actor, r, "assign_room", lambda s: any(
                    t["sequence"] == seq and t["roomKosId"] for t in tasks_of(s)), now=True)
            end_step = END_STEP[route]  # 6 끝 단계 = 접수 때 고른 진행 경로(KOS consultationRequired 아님 · 10-27)
            await self._send(actor, r, "flow_step", PATH_FLOW_STEP, {"id": r.kos_id, "step": end_step})
            done.append("flow_step")
        except (Conflict, BadGateway):
            self._log_reception(actor, r, room, None, done)
            self._after(r)
            raise
        self._log_reception(actor, r, room, end_step, done)
        self._settle(actor, r, end_step)
        return end_step

    def _settle(self, actor: Account, r: Reservation, step: str) -> None:
        """단계를 보낸 뒤 — 사본에 그 단계를 먼저 싣고(KOS 는 0 ~ 3초 뒤 보임) 바로 응답 · 확인은 뒤에서."""
        self.resv.pin_step(r.kos_id, step)
        self.spawn(self._follow_up(actor, r))

    async def _send(self, actor: Account, r: Reservation, step: str, path: str, body: dict[str, Any]) -> None:
        name = path.rsplit("/", 1)[-1]
        await self.resv.kos_write(actor, name, self.resv.client().internal(path, body), reservation_id=r.id, step=step)

    def _check_room(self, r: Reservation, room: Room, tasks: list[dict[str, Any]]) -> None:
        attached = (reception_room_task(tasks) or {}).get("roomKosId")
        if attached:  # 붙은 방 고정(D-48)
            if room.kos_id != attached:
                with self.repo.tx() as tx:
                    title = next((x.title for x in tx.rooms() if x.kos_id == attached), "")
                raise Conflict("room_locked", f"이미 배정된 방이 있어요 · {title}".rstrip(" ·"))
            return
        if room.zone_kos_id != r.zone_kos_id:
            raise BadRequest("invalid_request", "roomId: 그 예약 구역의 방이 아니에요")
        today = self.resv.clock.now().astimezone(KST).date().isoformat()
        with self.repo.tx() as tx:
            busy = busy_rooms(tx.reservations(today), r.zone_kos_id, exclude_id=r.id)
        if room.kos_id in busy:
            raise Conflict("room_busy", "사용 중인 방이에요")

    def _log_reception(self, actor: Account, r: Reservation, room: Room, end_step: str | None, steps: list[str]) -> None:
        if not steps and end_step is None:
            return
        with self.repo.tx() as tx:
            self.resv._event(tx, actor, "reception", {"reservationId": r.id, "roomId": room.id, "endStep": end_step,
                                                      "steps": steps})

    # ------------------------------------------------------------------ §5.8 [실장 호출]
    async def counselor_call(self, actor: Account, reservation_id: int, staff_id: int) -> None:
        r = self._reservation(reservation_id)
        with self.repo.tx() as tx:
            staff = tx.staff()
            system = tx.token("internal")
        st = next((x for x in staff if x.id == staff_id), None)
        if st is None:
            raise NotFound("없는 직원이에요")
        main = state_of(r.status, r.flow_step)[0]
        if r.flow_step not in ("CONSULTATION_WAITING", "CONSULTATION") or main in CLOSED_MAINS:
            raise Conflict("not_consultation", "상담 단계가 아니에요")
        if st not in _counselors(staff, system[2] if system else None, self.resv.s.exclude_account_ids):
            raise Conflict("not_counselor", "상담사가 아니에요")
        await self.resv.kos_write(actor, "update-reservation", self.resv.client().internal(
            PATH_UPDATE, {"scheduleId": r.kos_id, "counselor": {"id": st.kos_id, "name": st.name}}), reservation_id=r.id)
        with self.repo.tx() as tx:
            self.resv._event(tx, actor, "counselor_call", {"reservationId": r.id, "counselorStaffId": st.id})
        self._after(r)

    # ------------------------------------------------------------------ §5.10 [귀가 완료]
    async def discharge(self, actor: Account, reservation_id: int) -> None:
        r = self._reservation(reservation_id)
        main = state_of(r.status, r.flow_step)[0]
        if r.flow_step != "PROCEDURE_DONE" or main in CLOSED_MAINS:
            raise Conflict("not_home_waiting", "귀가 대기가 아니에요")
        with self.repo.tx() as tx:
            pay = ResvContext(tx).payment(r)
        if pay >= 1:  # 수납 필요가 남으면 보내지 않는다(D-41)
            raise Conflict("payment_required", "수납 필요가 남아 있어요")
        await self.resv.kos_write(actor, "change-flow-step", self.resv.client().open(
            PATH_OPEN_FLOW_STEP, {"scheduleId": r.kos_id, "step": "COMPLETED"}), reservation_id=r.id)
        with self.repo.tx() as tx:
            self.resv._event(tx, actor, "discharge", {"reservationId": r.id})
        self._after(r)
        await self._procedure_board()

    # ------------------------------------------------------------------ [+ 상담 추가](10-27 E2E #15 · OQ-750 뒤집음)
    async def consultation_add(self, actor: Account, reservation_id: int) -> str:
        """상담 뒤(시술 대기 ~ 귀가 대기) 고객을 상담 대기로 되돌린다 — 공개 change-flow-step(CONSULTATION_WAITING).

        상담 기록은 만들지 않는다(KOS [상담 시작]이 만든다 · 10-26). 지금 단계는 KOS 에서 다시 읽어 정한다.
        """
        r = self._reservation(reservation_id)
        sch = await self._read(actor, r, None)
        r = self._reservation(reservation_id)
        flow = sch.get("flowStep")
        main = state_of((sch.get("reservation") or {}).get("status"), flow)[0]
        if flow not in CONSULT_ADD_FLOWS or main in CLOSED_MAINS:
            raise Conflict("not_consultation_addable", "상담을 추가할 수 없는 단계예요")
        step = "CONSULTATION_WAITING"
        await self.resv.kos_write(actor, "change-flow-step", self.resv.client().open(
            PATH_OPEN_FLOW_STEP, {"scheduleId": r.kos_id, "step": step}), reservation_id=r.id)
        with self.repo.tx() as tx:
            self.resv._event(tx, actor, "consultation_add", {"reservationId": r.id, "fromStep": flow})
        self._settle(actor, r, step)
        return step
