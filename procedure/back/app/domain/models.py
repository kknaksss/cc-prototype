"""도메인 값 — repository 가 행을 이것으로 바꿔 넘긴다(ORM · sqlite 는 repository 밖으로 안 나간다)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

FLOW_WAITING = "PROCEDURE_WAITING"
FLOW_DOING = "PROCEDURE"
FLOW_DONE = "PROCEDURE_DONE"
BOARD_FLOW_STEPS = (FLOW_WAITING, FLOW_DOING, FLOW_DONE)

TASK_DONE = "DONE"
TASK_CANCELED = "CANCELED"
TASK_WAITING = "WAITING"
TASK_READY = "READY"


@dataclass
class Staff:
    id: int
    kos_id: str
    name: str
    role_tags: list[str]
    active: bool
    is_doctor: bool


@dataclass
class Account:
    """ccc 로그인 계정(SPEC-004 §3.1) — 토큰 sub · event_log.actor = login_id."""

    id: int
    login_id: str
    role: str  # admin | doctor | nurse | coordinator
    name: str
    staff_id: int | None
    active: bool
    card: bool
    password_hash: str | None = None  # bcrypt — 없으면 로그인 불가(OQ-601)


@dataclass
class Room:
    id: int
    kos_id: str
    zone_kos_id: str | None
    title: str
    order: int


@dataclass
class Customer:
    id: int
    kos_id: str
    name: str
    phonetic_name: str | None
    nationality: str | None
    is_new: bool
    chart_number: str | None
    gender: str | None = None  # 예약 현황(SPEC-005 §3.2)


@dataclass
class Visit:
    id: int
    kos_id: str
    customer_id: int | None
    zone_kos_id: str | None
    flow_step: str | None
    flow_step_at: datetime | None
    order_memo: str | None
    room_id: int | None
    room_assigned_at: datetime | None
    present: bool
    home_requested_at: datetime | None
    open_task_seqs: list[int] = field(default_factory=list)


@dataclass
class Procedure:
    id: int
    visit_id: int
    kos_sequence: int
    kos_order: int | None
    title: str
    kos_status: str | None
    payment_required: bool
    doctor_staff_ids: list[int]
    assignee_staff_ids: list[int]
    doctor_assigned_at: datetime | None
    doctor_call_at: datetime | None
    completed_at: datetime | None
    present: bool
    started_at: datetime | None
    room_kos_id: str | None = None
    kind: str = "procedure"  # procedure | etc(ETCETERA) — 규칙은 type 무관 · etc + 방 = 「방 배정」만 예외(2026-10-25)


@dataclass
class Anesthesia:
    id: int
    visit_id: int
    started_at: datetime
    ended_at: datetime | None


@dataclass
class Call:
    id: int
    visit_id: int
    kind: str  # all | one
    target_staff_id: int | None
    created_at: datetime
    reassigned_from_call_id: int | None
    procedure_ids: list[int] = field(default_factory=list)


@dataclass
class Accept:
    id: int
    call_id: int
    procedure_id: int
    doctor_staff_id: int
    accepted_at: datetime


@dataclass
class KosOp:
    id: int
    event_id: int | None
    visit_id: int
    seq: int
    api: str  # open | internal
    path: str
    body: dict[str, Any]
    expect: dict[str, Any]
    status: str  # pending | sent | confirmed | failed
    attempts: int
    checks: int
    last_error: str | None


@dataclass
class AcceptLog:
    """event_log(call_accept) 한 줄 — 「최근 수락」."""

    at: datetime
    visit_id: int | None
    doctor_staff_id: int
    count: int


@dataclass
class World:
    """스냅샷 · 규칙 계산에 필요한 것 전부(한 지점 · 한 구역 · 오늘 — 작다)."""

    staff: dict[int, Staff]
    rooms: dict[int, Room]
    customers: dict[int, Customer]
    visits: dict[int, Visit]
    procedures: dict[int, Procedure]
    anesthesia: list[Anesthesia]
    calls: dict[int, Call]
    accepts: list[Accept]
    ops: list[KosOp]  # 전부(카드 「KOS 반영 실패」 판정에 confirmed 도 쓴다)
    recent_accepts: list[AcceptLog]
    sync_ok_at: datetime | None = None
    sync_error: str | None = None


# ------------------------------------------------------------------ 예약 현황(SPEC-005 §3.2)
@dataclass
class Zone:
    id: int
    kos_id: str
    title: str
    order: int
    is_default: bool
    present: bool


@dataclass
class ResvGroup:
    id: int
    kos_id: str
    title: str
    order: int
    interval_minutes: int
    capacities: list[dict[str, Any]]  # [{zoneKosId, capacity}] — 켜진 구역만
    timetable: dict[str, dict[str, Any]]  # monday … sunday → {enabled, start, end, breakStart, breakEnd}(KST HH:MM)
    present: bool


@dataclass
class Reservation:
    id: int
    kos_id: str
    customer_id: int | None
    day: str | None
    zone_kos_id: str | None
    status: str | None
    flow_step: str | None
    flow_step_at: datetime | None
    reception_at: datetime | None
    resources: list[dict[str, Any]]  # [{kosId, groupKosId, zoneKosId, startAt, endAt, doctors[{id,name}]}]
    consultation_required: bool
    sedation_required: bool
    counselor: dict[str, Any] | None
    assignee: dict[str, Any] | None
    memo: str | None
    funnel: dict[str, Any] | None
    connected_channel: str | None
    desired_discharge_at: datetime | None
    purchase_ids: list[str]
    prescription_ids: list[str]
    tasks: list[dict[str, Any]]  # [{type, sequence, title, status, paymentRequired, roomKosId, roomTitle, roomAssignedAt}]
    room_kos_id: str | None
    room_title: str | None
    present: bool


@dataclass
class ResvSlot:
    group_kos_id: str
    zone_kos_id: str
    start_at: datetime
    end_at: datetime | None
    capacity: int | None
    reservation_count: int | None


@dataclass
class Notice:
    id: int
    kos_id: str
    content: str
    released_at: datetime | None


@dataclass
class FunnelCode:
    id: int
    kos_id: str
    name: str
    order: int
    closed: bool
    is_default: bool


@dataclass
class IdentityCheck:
    customer_id: int
    status: str
    method: str
    checked_at: datetime
    actor: str
