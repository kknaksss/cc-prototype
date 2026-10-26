"""스냅샷 만들기(SPEC-003 §7.2) — 규칙 계산은 여기 한 곳(front 는 다시 계산하지 않는다)."""

from datetime import datetime, time

from app.domain.clock import Clock, in_window, iso, kst_day
from app.domain.models import Procedure, Visit
from app.domain.rules import ANES_LIMIT_MIN, CALL_LIMIT_MIN, Rules
from app.repository.repo import Repository
from app.schemas import board as s


class BoardService:
    def __init__(self, repo: Repository, clock: Clock, window: tuple[time, time]):
        self.repo = repo
        self.clock = clock
        self.window = window

    def rules(self) -> Rules:
        return Rules(self.repo.world(), self.clock.now())

    def snapshot(self) -> s.BoardSnapshot:
        now = self.clock.now()
        world, order = self.repo.world_and_order(kst_day(now))
        r = Rules(world, now)
        w = r.w

        doctors = []
        for d in r.doctors():
            room = r.busy_room(d.id)
            doctors.append(s.Doctor(id=d.id, name=d.name, busy=room is not None, busyRoom=room))
        doctors.sort(key=lambda d: d.busy)  # 비어 있는 원장 먼저(이름 순 유지)

        cards = [self._card(r, v) for v in r.cards()]
        far = datetime.max.replace(tzinfo=now.tzinfo)
        visits = {v.id: v for v in r.cards()}
        # cards[] 배열 순서 = 화면 순서(§5.12 · §7.2): ① 오늘 순서 목록에 있는 카드(목록 자리 순) → ② 목록 밖 카드(입실순)
        # → ③ 귀가 대기(귀가 대기 시각 순 · 목록 자리는 무시). 목록에 있어도 사라진 카드는 그냥 건너뛴다
        pos = {vid: i for i, vid in enumerate(order)}

        def rank(c: s.Card) -> tuple:
            v = visits[c.visitId]
            if c.state == "home":
                return (2, 0, v.flow_step_at or far, c.visitId)
            if c.visitId in pos:
                return (0, pos[c.visitId], far, c.visitId)
            return (1, 0, v.room_assigned_at or far, c.visitId)

        cards.sort(key=rank)

        calls = []
        for c in r.open_calls():
            v = w.visits[c.visit_id]
            cust = w.customers.get(v.customer_id) if v.customer_id else None
            calls.append(s.OpenCall(
                callId=c.id, visitId=v.id, room=self._room(r, v),
                customer=s.CallCustomer(name=cust.name if cust else "", nationality=cust.nationality if cust else None),
                kind=c.kind, targetDoctorId=c.target_staff_id, createdAt=iso(c.created_at),
                procedures=[s.CallProcedure(id=p.id, title=p.title) for p in r.receivable(c)],
            ))

        recent = []
        for a in w.recent_accepts:
            v = w.visits.get(a.visit_id) if a.visit_id else None
            doc = w.staff.get(a.doctor_staff_id)
            recent.append(s.RecentAccept(at=iso(a.at), room=r.room_title(v) if v else "", doctorName=doc.name if doc else "",
                                         count=a.count))

        not_home = [c for c in cards if c.state != "home"]
        counts = s.Counts(
            all=len(cards),
            need=sum(1 for c in cards if c.need),
            waiting=sum(1 for c in cards if c.state == "waiting"),
            anes=sum(1 for c in not_home if c.anesthesia.runningSince),
            call=sum(1 for c in not_home if r.open_calls(visits[c.visitId])),
            doing=sum(1 for c in cards if c.state == "doing"),
        )
        return s.BoardSnapshot(
            now=iso(now),
            sync=s.SyncInfo(lastOkAt=iso(w.sync_ok_at), lastError=w.sync_error, inWindow=in_window(now, self.window)),
            doctors=doctors, counts=counts, limits=s.Limits(callMin=CALL_LIMIT_MIN, anesMin=ANES_LIMIT_MIN),
            cards=cards, calls=calls, recentAccepts=recent,
        )

    # ------------------------------------------------------------------
    def _room(self, r: Rules, v: Visit) -> s.Room:
        room = r.w.rooms.get(v.room_id) if v.room_id is not None else None
        return s.Room(id=room.id, title=room.title, order=room.order) if room else s.Room(id=0, title="", order=0)

    def _proc(self, r: Rules, v: Visit, p: Procedure) -> s.Procedure:
        call = r.effective_call(p)
        pc = None
        if call is not None:
            acc = r.accept_of(call, p)
            pc = s.ProcCall(id=call.id, kind=call.kind, targetDoctorId=call.target_staff_id, createdAt=iso(call.created_at),
                            acceptedBy=acc.doctor_staff_id if acc else None, acceptedAt=iso(acc.accepted_at) if acc else None)
        doc = r.shown_doctor(p)
        state = r.proc_state(p)
        return s.Procedure(
            id=p.id, kind="etc" if p.kind == "etc" else "procedure", sequence=p.kos_sequence, title=p.title, state=state,
            kosStatus=p.kos_status,
            startedAt=iso(p.started_at), completedAt=iso(p.completed_at) if state == "done" else None,
            doctor=s.DoctorRef(id=doc.id, name=doc.name) if doc else None, call=pc,
            pickable=r.pickable(v, p), canStart=r.start_block(v, p) is None,
            canFinish=not r.is_room_task(p) and state == "doing", isRoomTask=r.is_room_task(p),
        )

    def _card(self, r: Rules, v: Visit) -> s.Card:
        w = r.w
        cust = w.customers.get(v.customer_id) if v.customer_id else None
        home = r.is_home(v)
        running = r.running_anes(v)
        need = r.need(v)
        ops = [o for o in w.ops if o.visit_id == v.id]
        # 「KOS 반영 실패」는 그 visit 의 뒤 op 이 confirmed 될 때까지 남는다(리뷰 W1)
        last_ok = max((o.seq for o in ops if o.status == "confirmed"), default=0)
        failed = [s.KosFailure(op=o.path.rsplit("/", 1)[-1], error=o.last_error)
                  for o in ops if o.status == "failed" and o.seq > last_ok]
        pending = any(o.status in ("pending", "sent") for o in ops)
        all_done = r.all_done(v)
        return s.Card(
            visitId=v.id, room=self._room(r, v), inAt=iso(v.room_assigned_at), homeAt=iso(v.flow_step_at) if home else None,
            customer=s.Customer(name=cust.name if cust else "", phoneticName=cust.phonetic_name if cust else None,
                                nationality=cust.nationality if cust else None, isNew=cust.is_new if cust else False,
                                chartNumber=cust.chart_number if cust else None),
            state=r.visit_state(v), paymentRequired=r.payment_required(v), orderMemo=v.order_memo,
            anesthesia=s.Anesthesia(runningSince=iso(running.started_at) if running else None,
                                    lastMinutes=r.last_anes_minutes(v), long=r.anes_long(v),
                                    canStart=not home and running is None, canEnd=not home and running is not None),
            procedures=[self._proc(r, v, p) for p in r.ordered_procedures(v)],
            # T6: 호출할 수 있는(pickable) 작업이 1개 이상일 때만
            canCall=not home and not all_done and any(r.pickable(v, p) for p in r.procedures(v)),
            canHome=not home and all_done,
            need=s.Need(why=need[0], since=iso(need[1]), limitMin=need[2]) if need else None,
            kos=s.KosState(status="failed" if failed else "pending" if pending else "ok", failed=failed),
        )
