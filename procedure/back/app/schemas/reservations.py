"""front 계약 — 예약 현황(SPEC-005 §7). 필드 이름은 계약 그대로(camelCase).

이 모양을 바꾸려면 SPEC-005 §7 부터 고친다. 시각 = ISO(KST 오프셋 +09:00) · 날짜 = `YYYY-MM-DD` · id = ccc 정수 id.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, field_validator

# §5.1 상태 2계층
Main = Literal["reserved", "reception", "consultation", "procedure", "home", "canceled", "noshow"]
Sub = Literal["waiting", "doing", "done"]
Money = int | float


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class State(BaseModel):
    main: Main
    sub: Sub | None


# ------------------------------------------------------------------ §7.2 스케줄 표
class SyncInfo(BaseModel):
    lastOkAt: str | None
    lastError: str | None


class Axis(BaseModel):
    start: str  # "HH:MM"
    end: str


class Zone(BaseModel):
    zoneId: int
    title: str
    order: int
    isDefault: bool


class ZoneCapacity(BaseModel):
    zoneId: int
    capacity: int


class Span(BaseModel):
    start: str  # "HH:MM"
    end: str


class Column(BaseModel):
    groupId: int | None  # null = 「그룹 없음」 칸(§5.2)
    title: str
    order: int
    intervalMinutes: int
    count: int
    capacities: list[ZoneCapacity]
    open: list[Span]


class CardCustomer(BaseModel):
    customerId: int | None
    name: str
    phoneticName: str | None
    gender: str | None
    nationality: str | None
    isNew: bool


class BoardCard(BaseModel):
    reservationId: int
    resourceIndex: int
    groupId: int | None
    zoneId: int | None
    start: str
    end: str
    customer: CardCustomer
    state: State
    paymentRequiredCount: int
    draggable: bool


class Slot(BaseModel):
    groupId: int
    zoneId: int
    start: str
    end: str
    capacity: int | None  # 슬롯 사본이 없으면 null
    count: int | None
    full: bool


class PlusRow(BaseModel):
    groupId: int
    start: str
    plusAllowed: bool


class BoardCounts(BaseModel):
    total: int
    reserved: int
    reception: int
    consultation: int
    procedure: int
    home: int
    canceled: int
    noshow: int


class Notice(BaseModel):
    id: int
    content: str
    releasedAt: str | None


class Amount(BaseModel):
    total: Money | None
    paid: Money | None
    currency: str | None


class ClinicCustomer(BaseModel):
    name: str
    phoneticName: str | None
    nationality: str | None


class ClinicItem(BaseModel):
    reservationId: int
    zoneId: int | None
    customer: ClinicCustomer
    state: State
    receptionAt: str | None
    paymentRequiredCount: int
    amount: Amount | None


class ClinicCounts(BaseModel):
    all: int
    reception: int
    consultation: int
    procedure: int
    home: int


class Clinic(BaseModel):
    counts: ClinicCounts
    items: list[ClinicItem]


class ReservationBoard(BaseModel):
    date: str
    isToday: bool
    now: str
    sync: SyncInfo
    axis: Axis | None
    zones: list[Zone]
    columns: list[Column]
    cards: list[BoardCard]
    slots: list[Slot]
    rows: list[PlusRow]
    counts: BoardCounts
    notices: list[Notice]  # 0.4.0: front 는 첫 번째 하나만(§5.15)
    noticeEditable: bool  # 0.4.0 — 보는 날짜 ≥ 오늘(KST) · [수정하기] 보임(§5.15)
    requests: list[dict]  # D-07 자리만 — 늘 빈 배열
    clinic: Clinic | None


# ------------------------------------------------------------------ §7.3 예약 상세
class Phone(BaseModel):
    countryCode: str | None
    number: str | None


class Sns(BaseModel):
    type: str | None
    accountId: str | None


class Address(BaseModel):
    address: str | None
    detailed: str | None
    zipCode: str | None


class Personal(BaseModel):
    name: str | None
    phoneticName: str | None
    gender: str | None
    dateOfBirth: str | None  # yyyy-MM-dd
    registrationNumber: str | None
    passportNumber: str | None
    passportSurname: str | None
    passportGivenNames: str | None
    passportExpiryDate: str | None  # yyyy-MM-dd
    foreignRegistrationNumber: str | None
    nationality: str | None
    language: str | None
    phone: Phone | None
    additionalPhone: Phone | None
    email: str | None
    sns: Sns | None
    address: Address | None


class IdentityField(BaseModel):
    key: str
    label: str
    filled: bool


class Identity(BaseModel):
    status: Literal["confirmed", "unconfirmed"]
    checkedAt: str | None
    checkedBy: str | None
    method: str | None  # web_manual | app_scan | app_manual(SPEC-004 §6.16 ④-d)
    device: str | None = None  # 앱 스캔 기기 이름
    photoId: int | None = None  # 사진 열람 = GET /api/id-photos/{photoId}(Bearer)
    photoKos: Literal["ok", "failed", "skipped"] | None = None  # 그 사진 KOS 올리기 결과(id_photo.kos_status) · 사진 없으면 null
    kind: Literal["foreign", "domestic"]
    fields: list[IdentityField]
    complete: bool


class DetailCustomer(BaseModel):
    customerId: int
    name: str
    phoneticName: str | None
    gender: str | None
    nationality: str | None
    isNew: bool
    chartNumber: str | None
    age: int | None
    personal: Personal | None
    personalError: str | None
    remark: str | None
    identity: Identity


class Funnel(BaseModel):
    name: str | None
    detail: str | None


class StaffRef(BaseModel):
    staffId: int | None
    name: str


class NameRef(BaseModel):
    name: str


class ReservationInfo(BaseModel):
    sedationRequired: bool
    memo: str | None
    funnel: Funnel | None
    connectedChannel: str | None
    counselor: StaffRef | None
    assignee: NameRef | None
    doctors: list[NameRef]
    desiredDischargeAt: str | None


class HealthItem(BaseModel):
    title: str
    answer: str | None
    memo: str | None
    needsCheck: bool
    empty: bool


class Health(BaseModel):
    state: Literal["none", "ok", "error"]
    submittedAt: str | None
    needCount: int
    items: list[HealthItem]


class PrevProcedure(BaseModel):
    title: str
    status: str | None
    doctors: list[str]


class PreviousVisit(BaseModel):
    date: str
    start: str | None
    result: Literal["completed", "noshow", "canceled", "other"]
    resultRaw: str | None
    zoneTitle: str | None
    groupTitle: str | None
    reservationMemo: str | None
    consultationMemo: str | None
    procedures: list[PrevProcedure]


class Consultation(BaseModel):
    state: Literal["none", "waiting", "doing", "done"]
    counselor: StaffRef | None
    since: str | None
    calledAt: str | None
    calledBy: str | None


class Stages(BaseModel):
    procedure: Literal["none", "waiting", "doing", "done"]
    home: Literal["none", "waiting", "done"]


class FlowTimes(BaseModel):
    """단계 줄 시각(E2E b3 #2) — 그 단계 줄이 지금 상태가 된 시각 · 근거 없으면 null(지어내지 않음)."""

    consultation: str | None  # 대기 · 진행 = 그 단계가 된 시각 · 완료 = 시술 대기가 된 시각(바로 다음) → 아니면 KOS 상담 시작
    procedure: str | None  # 대기 · 진행 · 완료(귀가 대기) = 그 단계가 된 시각 · 귀가 완료 뒤 = KOS 시술 작업 완료 시각
    home: str | None  # 귀가 대기 · 귀가 완료가 된 시각


class Flow(BaseModel):
    receptionAt: str | None
    roomTitle: str | None
    receptionBy: str | None
    consultation: Consultation | None
    stages: Stages
    times: FlowTimes


class Links(BaseModel):
    purchase: str
    prescription: str


class Settlement(BaseModel):
    paymentRequiredCount: int
    amount: Amount | None
    prescriptionCount: int
    links: Links | None


class RoomItem(BaseModel):
    roomId: int
    title: str
    busy: bool
    selected: bool


class CounselorItem(BaseModel):
    staffId: int
    name: str
    busyRoom: str | None


class Can(BaseModel):
    cancel: bool
    editRoute: bool
    receive: bool
    callCounselor: bool
    discharge: bool
    editMemo: bool
    editPersonal: bool
    editRemark: bool
    confirmIdentity: bool
    unconfirmIdentity: bool
    addConsultation: bool


class DisplayItem(BaseModel):
    id: int
    kind: Literal["questionnaire", "scan"]
    status: Literal["pending", "opened", "done", "canceled", "expired"]
    deviceName: str | None
    createdAt: str
    closedAt: str | None


class ReservationDetail(BaseModel):
    reservationId: int
    day: str
    start: str | None
    end: str | None
    groupTitle: str | None
    zoneId: int | None
    zoneTitle: str | None
    state: State
    customer: DetailCustomer
    reservation: ReservationInfo
    health: Health
    previousVisits: list[PreviousVisit]
    flow: Flow | None
    settlement: Settlement | None
    rooms: list[RoomItem]
    roomLocked: bool
    receiveMode: Literal["new", "resume"] | None
    counselors: list[CounselorItem]
    can: Can
    displays: list[DisplayItem] = []  # 띄우기 요청(SPEC-004 §5-3 · 오늘 그 예약 것)



# ------------------------------------------------------------------ §7.4 등록 모달 · 고객 검색
class StaffItem(BaseModel):
    staffId: int
    name: str


class FunnelItem(BaseModel):
    funnelId: int
    name: str


class FormZone(BaseModel):
    zoneId: int
    title: str
    available: bool


class ReservationForm(BaseModel):
    staff: list[StaffItem]
    defaultAssigneeStaffId: int | None
    counselors: list[StaffItem]
    funnels: list[FunnelItem]
    zones: list[FormZone]
    defaultZoneId: int | None
    snsTypes: list[str]  # KOS snsInfo.snsType enum 그대로 — 표시 글자는 front


class SearchItem(BaseModel):
    customerId: int
    chartNumber: str | None
    name: str
    phoneticName: str | None
    dateOfBirth: str | None
    nationality: str | None
    isNew: bool


class CustomerSearch(BaseModel):
    items: list[SearchItem]
    total: int
    page: int
    pageSize: int


# ------------------------------------------------------------------ §7.5 조작 요청 · 응답
class PhoneIn(_Req):
    countryCode: str
    number: str


SNS_TYPES = ("etc", "kakaotalk", "line", "instagram", "whatsapp", "wechat")  # KOS snsInfo.snsType
SnsType = Literal["etc", "kakaotalk", "line", "instagram", "whatsapp", "wechat"]


class SnsIn(_Req):
    type: SnsType
    accountId: str


class NewCustomer(_Req):
    name: str
    phoneticName: str | None = None
    gender: str | None = None
    dateOfBirth: str | None = None  # yyyy-MM-dd
    nationality: str | None = None
    phone: PhoneIn | None = None
    email: str | None = None
    sns: SnsIn | None = None
    passportNumber: str | None = None


class ExistingCustomerRef(_Req):
    customerId: StrictInt


class NewCustomerRef(_Req):
    new: NewCustomer


class CreateReservationRequest(_Req):
    groupId: StrictInt
    zoneId: StrictInt | None = None  # 생략 = §5.5 기본 구역
    start: str
    customer: ExistingCustomerRef | NewCustomerRef
    assigneeStaffId: StrictInt | None = None
    counselorStaffId: StrictInt | None = None
    funnelId: StrictInt | None = None
    funnelDetail: str | None = None
    memo: str | None = None
    desiredDischargeTime: str | None = None  # "HH:MM"


class CreateReservationResponse(BaseModel):
    reservationId: int
    customerId: int


class MoveRequest(_Req):
    resourceIndex: StrictInt
    groupId: StrictInt
    start: str


class CancelRequest(_Req):
    reason: Literal["CANCELED", "NO_SHOW"]


class MemoRequest(_Req):
    memo: str


NOTICE_MAX = 2000  # trim 길이 상한(§5.15 · Q-142)


class NoticeRequest(_Req):
    """§7.5 `PUT /api/reservations/notice` — `noticeId` = 화면이 고친 ccc 행 id(기록용 · Q-143)."""

    date: str
    noticeId: StrictInt | None = None
    content: str


class NoticeResponse(BaseModel):
    ok: Literal[True] = True
    notice: Notice | None  # 지웠거나 빈 날 = null


class ReceptionRequest(_Req):
    roomId: StrictInt
    route: Literal["consultation", "direct"] = "consultation"  # 진행 경로 — ccc 값(KOS consultationRequired 아님 · 10-27)


class ReceptionResponse(BaseModel):
    ok: Literal[True] = True
    flowStep: str | None


class CounselorCallRequest(_Req):
    staffId: StrictInt


class AddressIn(_Req):
    address: str | None = None
    detailed: str | None = None
    zipCode: str | None = None


class PhoneOpt(_Req):
    countryCode: str | None = None
    number: str | None = None


class SnsOpt(_Req):
    type: str | None = None  # 보통 SNS_TYPES — '' · null = 없음 · enum 밖 KOS 값은 그대로 통과(r2 W3)
    accountId: str | None = None

    @field_validator("type", mode="before")
    @classmethod
    def _blank_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class PersonalIn(_Req):
    """§7.3 personal 와 같은 키 — 보낸 키만 바꾼다(`model_fields_set`)."""

    name: str | None = None
    phoneticName: str | None = None
    gender: str | None = None
    dateOfBirth: str | None = None
    registrationNumber: str | None = None
    passportNumber: str | None = None
    passportSurname: str | None = None
    passportGivenNames: str | None = None
    passportExpiryDate: str | None = None
    foreignRegistrationNumber: str | None = None
    nationality: str | None = None
    language: str | None = None
    phone: PhoneOpt | None = None
    additionalPhone: PhoneOpt | None = None
    email: str | None = None
    sns: SnsOpt | None = None
    address: AddressIn | None = None


class PersonalRequest(_Req):
    personal: PersonalIn


class RemarkRequest(_Req):
    memo: str


class IdentityRequest(_Req):
    status: Literal["confirmed", "unconfirmed"]


# 409 코드(도메인 예외) — §7.5 표 · §5.14
RESV_CONFLICT_CODES = (
    "not_identifiable",
    "duplicated_visitor",
    "slot_full",
    "not_movable",
    "not_cancelable",
    "reservation_closed",
    "not_receivable",
    "room_busy",
    "room_locked",
    "room_task_missing",
    "kos_slow",
    "not_consultation",
    "not_counselor",
    "not_home_waiting",
    "not_consultation_addable",
    "payment_required",
    "identity_locked",
    "kos_rejected",
)
