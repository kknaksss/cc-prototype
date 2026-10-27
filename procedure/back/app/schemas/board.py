"""front 계약 — 스냅샷(SPEC-003 §7.2). SSE `board` 이벤트 본문도 이 모양 + `version`(§7.5).

필드 이름은 계약 그대로(camelCase). 이 모양을 바꾸려면 SPEC-003 §7 부터 고친다.
시각은 전부 ISO 8601 · KST 오프셋(+09:00) 문자열.
"""

from typing import Literal

from pydantic import BaseModel

VisitState = Literal["waiting", "doing", "home"]
ProcState = Literal["wait", "doing", "done"]
CallKind = Literal["all", "one"]
NeedWhy = Literal["home", "anes", "call"]
KosStatus = Literal["ok", "pending", "failed"]


class SyncInfo(BaseModel):
    lastOkAt: str | None
    lastError: str | None
    inWindow: bool


class Doctor(BaseModel):
    id: int
    name: str
    busy: bool
    busyRoom: str | None


class Counts(BaseModel):
    all: int
    need: int
    waiting: int
    anes: int
    call: int
    doing: int


class Limits(BaseModel):
    """「확인이 필요」 기준(분) — front 는 상수를 두지 않고 이 값만 쓴다(리뷰 S5)."""

    callMin: int
    anesMin: int


class Room(BaseModel):
    id: int
    title: str
    order: int


class Customer(BaseModel):
    name: str
    phoneticName: str | None
    nationality: str | None
    isNew: bool
    chartNumber: str | None


class Anesthesia(BaseModel):
    runningSince: str | None
    lastMinutes: int | None
    long: bool  # 진행 중 마취가 anesMin 이상(need 우선순위와 상관없이 빨강 표시)
    canStart: bool
    canEnd: bool


class DoctorRef(BaseModel):
    id: int
    name: str


class ProcCall(BaseModel):
    id: int
    kind: CallKind
    targetDoctorId: int | None
    createdAt: str
    acceptedBy: int | None
    acceptedAt: str | None


class Procedure(BaseModel):
    id: int
    kind: Literal["procedure", "etc"]  # etc = KOS ETCETERA — 규칙은 type 무관(「방 배정」은 isRoomTask)
    sequence: int
    title: str
    state: ProcState
    # KOS 작업 status 원문(NOT_STARTED · WAITING · READY · DONE · CANCELED) — 반영 대기 중이면 ccc 가 바꾼 값
    kosStatus: str | None
    startedAt: str | None
    completedAt: str | None
    doctor: DoctorRef | None
    call: ProcCall | None
    pickable: bool
    canStart: bool
    canFinish: bool
    isRoomTask: bool  # 「방 배정」(방 붙은 ETCETERA) — front 는 그리지 않는다 · 판정에서 빠짐(2026-10-25)
    # 되돌리기 아이콘(SPEC-003 §5.13) — back 이 계산 · 「방 배정」 · 귀가 대기 카드는 늘 false(기본값 false — 가짜 보드 예시용)
    canUndoStart: bool = False
    canUndoFinish: bool = False


class Need(BaseModel):
    why: NeedWhy
    since: str
    limitMin: int


class KosFailure(BaseModel):
    op: str
    error: str | None


class KosState(BaseModel):
    status: KosStatus
    failed: list[KosFailure]


class Card(BaseModel):
    visitId: int
    room: Room
    inAt: str | None
    homeAt: str | None
    customer: Customer
    state: VisitState
    paymentRequired: bool
    orderMemo: str | None
    anesthesia: Anesthesia
    procedures: list[Procedure]
    canCall: bool
    canHome: bool
    need: Need | None
    kos: KosState


class CallCustomer(BaseModel):
    name: str
    nationality: str | None


class CallProcedure(BaseModel):
    id: int
    title: str


class OpenCall(BaseModel):
    callId: int
    visitId: int
    room: Room
    customer: CallCustomer
    kind: CallKind
    targetDoctorId: int | None
    createdAt: str
    procedures: list[CallProcedure]


class RecentAccept(BaseModel):
    at: str
    room: str
    doctorName: str
    count: int


class BoardSnapshot(BaseModel):
    now: str
    sync: SyncInfo
    doctors: list[Doctor]
    counts: Counts
    limits: Limits
    cards: list[Card]
    calls: list[OpenCall]
    recentAccepts: list[RecentAccept]


class BoardEvent(BoardSnapshot):
    """SSE `board` 이벤트 본문 = 스냅샷 + version(보낼 때마다 1 씩 증가)."""

    version: int
