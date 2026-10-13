"""현황판 상태 · 조작 — SPEC-001 0.2.0 §5 (workflow.md 가 정본).

상태 D = {customers, steps, staff, resv, log, stepSeq}.
동선 정본은 관제 DB 다(단계마다 KOS 작업 sequence · ticketId 를 같이 둔다).
- 자동은 없다: 고객 이동 · 단계 추가 · 배정은 사람이 누른다
- 배정 = 데스크, 시작 · 종료 = 그 직원 본인 화면
- 모든 조작은 `commit` 을 지난다: 스냅샷 → 변경(+log) → 상태가 바뀐 고객은 경과 타이머 리셋

조작 함수마다 KOS 반영 자리에 `kos api 연동 필요` 주석만 둔다(SPEC §9). **KOS 를 부르는 코드는 없다.**
"""

import copy
from collections.abc import Callable

from app.domain.errors import BadRequest, NotFound
from app.domain.rooms import RECEPTION, ROOM_IDS, cap_of, is_sleep, is_treatment_room

# KOS 진료 단계(flowStep) — workflow.md 표
RESERVED, RECEPTION_STEP, CONSULTATION_WAITING, CONSULTATION = "RESERVED", "RECEPTION", "CONSULTATION_WAITING", "CONSULTATION"
PROCEDURE_WAITING, PROCEDURE, PROCEDURE_DONE, COMPLETED = "PROCEDURE_WAITING", "PROCEDURE", "PROCEDURE_DONE", "COMPLETED"

KINDS = ("consult", "doctor_consult", "procedure")
KIND_LABEL = {"consult": "상담", "doctor_consult": "원장 상담"}
# 단계 종류 → 배정할 수 있는 직군(§3.2)
KIND_ROLES = {"consult": {"상담사"}, "doctor_consult": {"의사"}, "procedure": {"의사", "피부관리사"}}
PENDING = ("planned", "assigned")
CONSULT_KINDS = ("consult", "doctor_consult")

State = dict
Ctx = dict  # {"now": epoch ms, "actor": staffId | "desk"}
Op = Callable[[State], None]


# ── 찾기 ──────────────────────────────────────────────────────────────


def find_customer(d: State, schedule_id: str) -> dict:
    for c in d["customers"]:
        if c["scheduleId"] == schedule_id:
            return c
    raise NotFound("customer_not_found", f"접수한 고객 {schedule_id} 이 없어요")


def find_step(d: State, step_id: str) -> dict:
    for s in d["steps"]:
        if s["stepId"] == step_id:
            return s
    raise NotFound("step_not_found", f"단계 {step_id} 가 없어요")


def find_staff(d: State, staff_id: str) -> dict:
    for s in d["staff"]:
        if s["staffId"] == staff_id:
            return s
    raise NotFound("staff_not_found", f"직원 {staff_id} 를 찾을 수 없어요")


def steps_of(d: State, schedule_id: str) -> list[dict]:
    return sorted((s for s in d["steps"] if s["scheduleId"] == schedule_id), key=lambda s: s["order"])


def is_here(c: dict) -> bool:
    """접수했고 귀가 전."""
    return c["location"] is not None and c["flowStep"] != COMPLETED


def occupants(d: State, room: str) -> list[dict]:
    return [c for c in d["customers"] if is_here(c) and c["location"] == room]


def held_by(d: State, room: str) -> dict | None:
    """수면시술실로 간 고객이 잡아 둔 원래 방."""
    return next((c for c in d["customers"] if is_here(c) and c.get("prevRoom") == room), None)


def staff_name(d: State, staff_id: str | None) -> str:
    return next((s["name"] for s in d["staff"] if s["staffId"] == staff_id), "")


# ── 방 · 고객 상태(§5.1) ─────────────────────────────────────────────


def status_of(d: State, c: dict) -> dict | None:
    """{key, label, need} — key: reception · wait · consult · treat. need(순회형 손 필요): next · discharge · None."""
    if not is_here(c):
        return None
    if c["location"] == RECEPTION:
        return {"key": "reception", "label": "접수 후 대기", "need": None}
    ss = steps_of(d, c["scheduleId"])
    prog = next((s for s in ss if s["state"] == "in_progress"), None)
    if prog:
        return {"key": "consult" if prog["kind"] in CONSULT_KINDS else "treat", "label": prog["label"], "need": None}
    pending = [s for s in ss if s["state"] in PENDING]
    if not pending:
        return {"key": "wait", "label": "귀가 대기", "need": "discharge"}
    nxt = pending[0]
    if nxt["state"] == "assigned":
        return {"key": "wait", "label": f"{staff_name(d, nxt['assigneeId'])} 대기", "need": None}
    done = sorted((s for s in ss if s["state"] == "done"), key=lambda s: s["endedAt"] or 0)
    if done and done[-1]["kind"] == "doctor_consult" and nxt["kind"] == "procedure":
        return {"key": "wait", "label": "원장 대기 · 세팅 준비", "need": "next"}
    return {"key": "wait", "label": "다음 단계 대기", "need": "next"}


def _status_key(d: State, c: dict) -> tuple:
    st = status_of(d, c)
    return (c["location"], st["key"] if st else None, st["label"] if st else None)


def commit(state: State, op: Op, now: int) -> State:
    """새 상태를 돌려준다(입력은 그대로). 상태가 바뀐 고객은 since = now."""
    d = copy.deepcopy(state)
    op(d)
    before = {c["scheduleId"]: c for c in state["customers"]}
    for c in d["customers"]:
        b = before.get(c["scheduleId"])
        if b is None or _status_key(state, b) != _status_key(d, c):
            c["since"] = now
    return d


def _log(d: State, ctx: Ctx, action: str, schedule_id: str | None = None, step_id: str | None = None, detail: str = ""):
    d["log"].append({"at": ctx["now"], "actor": ctx["actor"], "action": action, "scheduleId": schedule_id,
                     "stepId": step_id, "detail": detail})


def _new_step(d: State, schedule_id: str, order: int, item: dict) -> dict:
    d["stepSeq"] = d.get("stepSeq", 0) + 1
    kind = item["kind"]
    return {"stepId": f"st{d['stepSeq']}", "scheduleId": schedule_id, "order": order, "kind": kind,
            "label": (item.get("label") or KIND_LABEL.get(kind) or "").strip(),
            "kosSequence": item.get("kosSequence"), "ticketId": item.get("ticketId"), "assigneeId": None,
            "state": "planned", "assignedAt": None, "startedAt": None, "endedAt": None,
            "paymentRequired": bool(item.get("paymentRequired")), "assigneeMemo": None}


def _check_items(d: State, schedule_id: str, items: list[dict]) -> None:
    for it in items:
        if it.get("kind") not in KINDS:
            raise BadRequest("bad_step_kind", f"단계 종류는 {', '.join(KINDS)} 중 하나예요")
        if it["kind"] == "procedure" and not (it.get("label") or "").strip():
            raise BadRequest("label_required", "시술 단계는 이름(label)이 필요해요")
    used = {s["ticketId"] for s in d["steps"] if s["scheduleId"] == schedule_id and s["ticketId"]}
    for it in items:
        t = it.get("ticketId")
        if t:
            if t in used:
                raise BadRequest("duplicate_ticket", f"시술권 {t} 은 이미 동선에 있어요")
            used.add(t)


def _require_here(c: dict) -> None:
    if not is_here(c):
        raise BadRequest("customer_not_here", "접수 중인 고객이 아니에요(귀가했거나 접수 전)")


# ── 조작(§5.3) — 각 함수가 KOS 반영 자리 ───────────────────────────────


def check_in(ctx: Ctx, schedule_id: str, items: list[dict]) -> Op:
    def op(d: State) -> None:
        row = next((r for r in d["resv"] if r["scheduleId"] == schedule_id), None)
        if row is None:
            raise NotFound("reservation_not_found", f"예약 {schedule_id} 이 없어요")
        if any(c["scheduleId"] == schedule_id for c in d["customers"]):
            raise BadRequest("already_checked_in", "이미 접수한 고객이에요")
        if row["st"] == "canceled":
            raise BadRequest("reservation_canceled", "취소된 예약이에요")
        _check_items(d, schedule_id, items)
        d["customers"].append({
            "scheduleId": schedule_id, "name": row["name"], "isNew": row.get("isNew"),
            "nationality": row.get("nationality", ""), "location": RECEPTION, "prevRoom": None,
            "flowStep": RECEPTION_STEP, "receptionAt": ctx["now"], "completedAt": None, "since": ctx["now"],
            # 진행하다 KOS 에서 들어오는 것(이벤트) — 상담 완료 · 결제 완료 때 채운다(SPEC 0.2.1 §0-a)
            "consultApplied": False, "consultation": None, "orderMemo": None,
            "payment": None, "unpaidAmount": 0, "paid": False,
        })
        for i, it in enumerate(items, start=1):
            d["steps"].append(_new_step(d, schedule_id, i, it))
        row["st"] = "checked"
        _log(d, ctx, "check-in", schedule_id, detail=" → ".join(s["label"] for s in steps_of(d, schedule_id)))
        ## ============kos api 연동 필요 ========================
        ## 공식: changeFlowStep(RECEPTION)
        ## ======================================================

    return op


def place(ctx: Ctx, schedule_id: str, room: str) -> Op:
    def op(d: State) -> None:
        c = find_customer(d, schedule_id)
        _require_here(c)
        if c["location"] != RECEPTION:
            raise BadRequest("not_in_reception", "접수대기실에 있는 고객만 방에 넣을 수 있어요")
        if room not in ROOM_IDS or not is_treatment_room(room):
            raise BadRequest("not_treatment_room", f"{room} 은 고객을 넣는 관리실이 아니에요")
        if len(occupants(d, room)) >= cap_of(room):
            raise BadRequest("room_full", "방 정원이 찼어요")
        if held_by(d, room):
            raise BadRequest("room_held", "수면시술실로 간 다른 고객이 돌아올 방이에요")
        c["location"] = room
        if any(s["kind"] == "consult" and s["state"] != "done" for s in steps_of(d, schedule_id)):
            c["flowStep"] = CONSULTATION_WAITING
        _log(d, ctx, "place", schedule_id, detail=room)
        ## ============kos api 연동 필요 ========================
        ## 공식: changeFlowStep(CONSULTATION_WAITING)
        ## 방: 공개 없음 — KOS 요청(KOS 화면 「방」)
        ## ======================================================

    return op


def move_sleep(ctx: Ctx, schedule_id: str, room: str) -> Op:
    def op(d: State) -> None:
        c = find_customer(d, schedule_id)
        _require_here(c)
        if not is_sleep(room):
            raise BadRequest("not_sleep_room", f"{room} 은 수면시술실이 아니에요")
        if not is_treatment_room(c["location"]):
            raise BadRequest("not_in_room", "관리실에 있는 고객만 수면시술실로 옮길 수 있어요")
        if len(occupants(d, room)) >= cap_of(room):
            raise BadRequest("no_free_slot", "그 수면시술실에 빈 칸이 없어요")
        c["prevRoom"], c["location"] = c["location"], room
        _log(d, ctx, "move-sleep", schedule_id, detail=f"{c['prevRoom']} → {room}")
        ## ============kos api 연동 필요 ========================
        ## 방: 공개 없음 — KOS 요청(KOS 화면 「방」)
        ## ======================================================

    return op


def return_room(ctx: Ctx, schedule_id: str) -> Op:
    def op(d: State) -> None:
        c = find_customer(d, schedule_id)
        _require_here(c)
        if not is_sleep(c["location"]) or not c.get("prevRoom"):
            raise BadRequest("not_in_sleep_room", "수면시술실에 있는 고객이 아니에요")
        back = c["prevRoom"]
        c["location"], c["prevRoom"] = back, None
        _log(d, ctx, "return-room", schedule_id, detail=back)
        ## ============kos api 연동 필요 ========================
        ## 방: 공개 없음 — KOS 요청(KOS 화면 「방」)
        ## ======================================================

    return op


def assign(ctx: Ctx, step_id: str, staff_id: str) -> Op:
    def op(d: State) -> None:
        s = find_step(d, step_id)
        who = find_staff(d, staff_id)
        _require_here(find_customer(d, s["scheduleId"]))
        if who["role"] not in KIND_ROLES[s["kind"]]:
            raise BadRequest("role_mismatch", f"{s['label']} 단계에는 {'/'.join(sorted(KIND_ROLES[s['kind']]))} 만 배정해요")
        if s["state"] not in PENDING:
            raise BadRequest("step_locked", "이미 진행 중이거나 끝난 단계예요")
        s.update(assigneeId=staff_id, state="assigned", assignedAt=ctx["now"])
        _log(d, ctx, "assign", s["scheduleId"], step_id, who["name"])
        if s["kind"] == "consult":
            ## ============kos api 연동 필요 ========================
            ## 비공식: consultation/v1/commands/create-consultation (counselorIds) — KOS 화면 상담사 지정
            ## ======================================================
            pass
        elif s["kind"] == "doctor_consult":
            ## ============kos api 연동 필요 ========================
            ## 비공식: consultation/v1/commands/change-consultation-doctors (doctorIds)
            ## ======================================================
            pass
        elif who["role"] == "의사":
            ## ============kos api 연동 필요 ========================
            ## 비공식: schedule/flow/v1/commands/change-tasks-doctors {scheduleId, sequences[], doctorIds[]}
            ## — KOS 화면 「집도의」
            ## ======================================================
            pass
        else:
            ## ============kos api 연동 필요 ========================
            ## 비공식: schedule/flow/v1/commands/change-tasks-assignees {scheduleId, sequences[], assigneeIds[]}
            ## — KOS 화면 「담당자」
            ## ======================================================
            pass

    return op


def unassign(ctx: Ctx, step_id: str) -> Op:
    def op(d: State) -> None:
        s = find_step(d, step_id)
        if s["state"] != "assigned":
            code = "not_assigned" if s["state"] == "planned" else "step_locked"
            raise BadRequest(code, "배정만 된 단계만 해제할 수 있어요")
        who = staff_name(d, s["assigneeId"])
        s.update(assigneeId=None, state="planned", assignedAt=None)
        _log(d, ctx, "unassign", s["scheduleId"], step_id, who)
        ## ============kos api 연동 필요 ========================
        ## 공개 없음 — KOS 요청(KOS 화면 「담당자」 · 「집도의」 해제)
        ## ======================================================

    return op


def add_procedures(ctx: Ctx, schedule_id: str, items: list[dict]) -> Op:
    def op(d: State) -> None:
        c = find_customer(d, schedule_id)
        _require_here(c)
        items_ = [{**it, "kind": "procedure"} for it in items]
        if not items_:
            raise BadRequest("empty_items", "추가할 시술이 없어요")
        _check_items(d, schedule_id, items_)
        last = max((s["order"] for s in steps_of(d, schedule_id)), default=0)
        for i, it in enumerate(items_, start=1):
            d["steps"].append(_new_step(d, schedule_id, last + i, it))
        _log(d, ctx, "add-procedures", schedule_id, detail=", ".join(it["label"] for it in items_))
        ## ============kos api 연동 필요 ========================
        ## 공개 없음 · 내부 미확인 — KOS 요청(시술 추가: 시술권 ticketId 로 작업 생성)
        ## ======================================================

    return op


def reorder(ctx: Ctx, schedule_id: str, step_ids: list[str]) -> Op:
    def op(d: State) -> None:
        c = find_customer(d, schedule_id)
        _require_here(c)
        ss = steps_of(d, schedule_id)
        if any(s["state"] == "in_progress" for s in ss):
            raise BadRequest("step_in_progress", "진행 중인 단계가 있으면 순서를 바꿀 수 없어요")
        by_id = {s["stepId"]: s for s in ss}
        pending = [s for s in ss if s["state"] in PENDING]
        if len(set(step_ids)) != len(step_ids):
            raise BadRequest("bad_step_list", "같은 단계가 두 번 있어요")
        if set(step_ids) == set(by_id):  # 전체 목록 — 끝난 단계 자리는 그대로여야
            for i, s in enumerate(ss):
                if s["state"] not in PENDING and step_ids[i] != s["stepId"]:
                    raise BadRequest("done_step_moved", "끝났거나 진행 안 한 단계의 위치는 바꿀 수 없어요")
            new = [by_id[x] for x in step_ids]
        elif set(step_ids) == {s["stepId"] for s in pending}:  # 남은 단계만 — 그 자리끼리 바꾼다
            it = iter(by_id[x] for x in step_ids)
            new = [next(it) if s["state"] in PENDING else s for s in ss]
        else:
            raise BadRequest("bad_step_list", "stepIds 는 그 고객의 단계 전부 또는 남은 단계 전부여야 해요")
        for i, s in enumerate(new, start=1):
            s["order"] = i
        _log(d, ctx, "reorder", schedule_id, detail=" → ".join(s["label"] for s in new))
        ## ============kos api 연동 필요 ========================
        ## 공개 없음 · 내부 미확인 — KOS 요청(KOS 화면 「우선순위」)
        ## ======================================================

    return op


def start(ctx: Ctx, staff_id: str, step_id: str) -> Op:
    def op(d: State) -> None:
        s = find_step(d, step_id)
        find_staff(d, staff_id)
        c = find_customer(d, s["scheduleId"])
        _require_here(c)
        if s["state"] != "assigned" or s["assigneeId"] != staff_id:
            raise BadRequest("not_my_step", "나에게 배정된(시작 전) 단계가 아니에요")
        if any(x["state"] == "in_progress" for x in steps_of(d, s["scheduleId"])):
            raise BadRequest("customer_busy", "이 고객은 다른 단계가 진행 중이에요")
        s.update(state="in_progress", startedAt=ctx["now"])
        if s["kind"] in CONSULT_KINDS:
            c["flowStep"] = CONSULTATION
            ## ============kos api 연동 필요 ========================
            ## 공식: changeFlowStep(CONSULTATION)
            ## ======================================================
        else:
            c["flowStep"] = PROCEDURE
            ## ============kos api 연동 필요 ========================
            ## 공식: changeFlowStep(PROCEDURE)
            ## ======================================================
        _log(d, ctx, "start", s["scheduleId"], step_id, s["label"])

    return op


def _tasks_to_items(tasks: list[dict]) -> list[dict]:
    """상담사가 넣은 시술(KOS tasks[] 모양) → 동선 단계. 시술권 전이면 ticketId 없음 · 수납필요."""
    items = []
    for t in sorted(tasks or [], key=lambda t: t.get("sequence") or 0):
        if t.get("type") == "ETCETERA":
            items.append({"kind": "doctor_consult", "kosSequence": t.get("sequence"),
                          "paymentRequired": bool(t.get("paymentRequired"))})
        else:
            ticket = ((t.get("procedureConfiguration") or {}).get("ticketConfiguration") or {}).get("ticketId") or None
            items.append({"kind": "procedure", "label": t.get("title") or "", "kosSequence": t.get("sequence"),
                          "ticketId": ticket, "paymentRequired": bool(t.get("paymentRequired"))})
    return items


def _apply_consultation_done(d: State, ctx: Ctx, c: dict, event: dict) -> None:
    """상담 완료 이벤트 — 상담 기록 · 오더 메모 공개 · 상담사가 넣은 시술(수납필요)을 뒤에 붙임 · 미결제 금액."""
    c["consultApplied"] = True
    if not event:
        return
    c["consultation"] = event.get("consultation")
    c["orderMemo"] = event.get("orderMemo")
    c["payment"] = event.get("payment")
    c["unpaidAmount"] = int(((event.get("payment") or {}).get("totalAmount")) or 0)
    have = {s["kosSequence"] for s in steps_of(d, c["scheduleId"]) if s.get("kosSequence") is not None}
    used = {s["ticketId"] for s in steps_of(d, c["scheduleId"]) if s.get("ticketId")}
    last = max((s["order"] for s in steps_of(d, c["scheduleId"])), default=0)
    added = []
    for it in _tasks_to_items(event.get("tasks")):
        if it["kosSequence"] in have or (it.get("ticketId") and it["ticketId"] in used):
            continue
        last += 1
        step = _new_step(d, c["scheduleId"], last, it)
        d["steps"].append(step)
        added.append(step["label"])
    detail = f"시술 {len(added)}개 추가(수납필요) · 미결제 {c['unpaidAmount']:,}원"
    _log(d, ctx, "consultation-done", c["scheduleId"], detail=detail + (f" · {', '.join(added)}" if added else ""))


def finish(ctx: Ctx, staff_id: str, step_id: str, events: dict | None = None) -> Op:
    events = events or {}

    def op(d: State) -> None:
        s = find_step(d, step_id)
        find_staff(d, staff_id)
        if s["state"] != "in_progress":
            raise BadRequest("not_in_progress", "진행 중인 단계가 아니에요")
        if s["assigneeId"] != staff_id:
            raise BadRequest("not_my_step", "내가 진행 중인 단계가 아니에요")
        c = find_customer(d, s["scheduleId"])
        s.update(state="done", endedAt=ctx["now"])
        _log(d, ctx, "finish", s["scheduleId"], step_id, s["label"])
        if s["kind"] == "consult" and not c.get("consultApplied"):
            _apply_consultation_done(d, ctx, c, events.get("consultationDone") or {})
        if s["kind"] == "procedure" and s.get("kosSequence") is not None:
            done = (events.get("taskDone") or {}).get(str(s["kosSequence"])) or {}
            s["assigneeMemo"] = done.get("assigneeMemo") or None  # 시술 완료 이벤트 — 그 작업의 담당자 메모
        if not any(x["state"] in PENDING for x in steps_of(d, s["scheduleId"])):
            c["flowStep"] = PROCEDURE_DONE
        elif s["kind"] == "doctor_consult":
            c["flowStep"] = PROCEDURE_WAITING
        if s["kind"] == "procedure":
            ## ============kos api 연동 필요 ========================
            ## 비공식: schedule/flow/v1/commands/change-tasks-complete {scheduleId, sequences[], complete:true}
            ## — KOS 화면 「시술 완료하기」, 시술권 차감 미확인. 다음 단계가 없으면 공식 changeFlowStep(PROCEDURE_DONE)
            ## ======================================================
            pass
        else:
            ## ============kos api 연동 필요 ========================
            ## 공식: updateScheduleConsultationInfo(차티 기록 → 상담 메모)
            ## 원장 상담 끝이면 공식 changeFlowStep(PROCEDURE_WAITING)
            ## ======================================================
            pass

    return op


def payment_complete(ctx: Ctx, schedule_id: str, event: dict | None) -> Op:
    """[결제 완료] — 수납필요 해제 · 미결제 0 · 시술권(ticketId) 연결 · 차트 「오늘 결제」 공개(SPEC 0.2.1 §0-a)."""

    def op(d: State) -> None:
        c = find_customer(d, schedule_id)
        _require_here(c)
        ss = steps_of(d, schedule_id)
        if c.get("paid") or not (c.get("unpaidAmount") or any(s.get("paymentRequired") for s in ss)):
            raise BadRequest("nothing_to_pay", "수납할 것이 없어요(상담 완료 전이거나 이미 결제 완료)")
        by_seq = {str(k): v for k, v in ((event or {}).get("ticketIdsBySequence") or {}).items()}
        used = {s["ticketId"] for s in ss if s.get("ticketId")}
        linked = 0
        for s in ss:
            t = by_seq.get(str(s.get("kosSequence")))
            if t and not s.get("ticketId") and t not in used:
                s["ticketId"] = t
                used.add(t)
                linked += 1
            s["paymentRequired"] = False
        c.update(unpaidAmount=0, paid=True)
        _log(d, ctx, "payment-complete", schedule_id, detail=f"시술권 {linked}장 연결")
        ## ============kos api 연동 필요 ========================
        ## KOS 결제 조회 — 공식: getPurchaseSummariesByVisitor · getTicketBundlesQuery
        ## (결제는 KOS 에서 한다. 이 버튼 = 결제 결과 · 생긴 시술권 불러오기)
        ## ======================================================

    return op


def discharge(ctx: Ctx, schedule_id: str) -> Op:
    def op(d: State) -> None:
        c = find_customer(d, schedule_id)
        _require_here(c)
        ss = steps_of(d, schedule_id)
        if any(s["state"] == "in_progress" for s in ss):
            raise BadRequest("step_in_progress", "진행 중인 단계가 있어요 — 먼저 종료해야 해요")
        for s in ss:
            if s["state"] in PENDING:
                s["state"] = "skipped"
                _log(d, ctx, "skip", schedule_id, s["stepId"], f"진행 안 함 · {s['label']}")
        c.update(location=None, prevRoom=None, flowStep=COMPLETED, completedAt=ctx["now"])
        _log(d, ctx, "discharge", schedule_id)
        ## ============kos api 연동 필요 ========================
        ## 비공식: schedule/v1/commands/cancel-flow-tasks {scheduleId, sequences[], reason:"CANCEL"}
        ## — 남은 단계(KOS 화면 「시술 취소하기」)
        ## → 공식: changeFlowStep(PROCEDURE_DONE → COMPLETED)
        ## ======================================================

    return op


# 조작 함수 목록 — 시험이 「주석 수 = 조작 함수 수」를 센다
OPERATIONS = (check_in, place, move_sleep, return_room, assign, unassign, add_procedures, reorder, start, finish,
              payment_complete, discharge)
