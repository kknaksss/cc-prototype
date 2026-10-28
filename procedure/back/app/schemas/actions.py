"""front 계약 — 로그인 · 조작 · 기타 요청/응답(SPEC-003 §7.1 · §7.3 · §7.4)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


# §7.1 로그인 — 아이디 + 비밀번호(OQ-601 닫음 · 정상 로그인)
class LoginRequest(_Req):
    id: str
    password: str


Role = Literal["admin", "doctor", "nurse", "coordinator", "counselor"]  # coordinator = SPEC-005 §3.4 · counselor = SPEC-004 §3.7


class LoginResponse(BaseModel):
    token: str
    expiresAt: str
    id: str
    role: Role
    name: str
    staffId: int | None


class UnlockRequest(_Req):
    """문진 잠금 나가기(SPEC-004 §3.3 r2) — 지금 로그인 계정 비밀번호 확인만 · 새 토큰 없음."""

    password: str
    deviceId: StrictInt | None = None


class MeResponse(BaseModel):
    id: str
    role: Role
    name: str
    staffId: int | None


# §7.3 조작
class TargetAll(_Req):
    kind: Literal["all"]


class TargetOne(_Req):
    kind: Literal["one"]
    doctorId: int


class CreateCallRequest(_Req):
    procedureIds: list[int]
    target: Annotated[TargetAll | TargetOne, Field(discriminator="kind")]


class AcceptRequest(_Req):
    """doctor = 생략하면 자기 원장(SPEC-004 §3.4) · admin = 필수(없으면 400 invalid_request)."""

    doctorId: int | None = None


class BoardOrderRequest(_Req):
    """카드 드래그 순서(SPEC-003 0.4.0 §7.3) — 귀가 대기 아닌 카드 전부의 새 순서 · 빈 배열 = 오늘 순서 지움.

    StrictInt — 문자열 `"3"` · 실수 `3.0` · 불리언 `true` 도 400(같은 id 두 번은 service 가 400).
    """

    visitIds: list[StrictInt]


class OkResponse(BaseModel):
    ok: Literal[True] = True


class StartResponse(OkResponse):
    flowStepChanged: bool


class BoardOrderResponse(OkResponse):
    visitIds: list[int]  # 거르기 뒤 저장된 목록


class CallCreatedResponse(BaseModel):
    callId: int


class AcceptResponse(BaseModel):
    acceptedProcedureIds: list[int]


# SPEC-004 §5-1.1 푸시 기기
class DeviceRequest(_Req):
    token: str = Field(pattern=r"^[0-9a-fA-F]{32,200}$")  # APNs 기기 토큰(16진)
    name: str | None = Field(default=None, min_length=1, max_length=40)  # 기기 이름(0.4.0 · D7-27)
    kind: Literal["phone", "tablet"] | None = None
    installId: str | None = Field(default=None, min_length=1, max_length=100)  # 설치 단위 id(E2E batch 1 #1)


class DeviceResponse(OkResponse):
    deviceId: int


# SPEC-004 §5-4 알림 · 설정
NotificationKind = Literal["doctor_call", "counselor_call"]


class NotificationTarget(BaseModel):
    visitId: int | None = None
    callId: int | None = None
    reservationId: int | None = None


class NotificationItem(BaseModel):
    id: int
    kind: NotificationKind
    title: str
    body: str
    createdAt: str
    readAt: str | None
    target: NotificationTarget


class NotificationList(BaseModel):
    unread: int
    items: list[NotificationItem]


class NotificationReadRequest(_Req):
    """ids 없으면 그 계정 전부. 푸시를 눌러 열 때는 payload 의 callId · reservationId 로 찾는다(§5-4 「읽음」)."""

    ids: list[StrictInt] | None = None
    callId: StrictInt | None = None
    reservationId: StrictInt | None = None


class NotificationReadResponse(OkResponse):
    read: int


class NotificationSetting(BaseModel):
    kind: NotificationKind
    enabled: bool


class NotificationSettings(BaseModel):
    items: list[NotificationSetting]


class NotificationSettingRequest(_Req):
    kind: str
    enabled: bool


# §7.4 기타
class KosTokens(BaseModel):
    open: bool
    internal: bool


class HealthResponse(BaseModel):
    ok: bool
    kos: KosTokens


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """모든 오류 응답 `{error:{code, message}}`."""

    error: ErrorBody


# 409 코드(도메인 예외) — §7.3 표
CONFLICT_CODES = (
    "visit_home",
    "anesthesia_running",
    "anesthesia_not_running",
    "procedure_not_waiting",
    "no_procedures",
    "doctor_not_listed",
    "nothing_to_accept",
    "doctor_mismatch",
    "not_designated_call",
    "call_not_accepted",
    "no_doctor",
    "procedure_not_started",
    "procedures_not_done",
    "procedure_not_doing",
    "procedure_not_done",
)


# SPEC-004 §5-3 띄우기 요청
DisplayKind = Literal["questionnaire", "scan"]
DisplayStatus = Literal["pending", "opened", "done", "canceled", "expired"]


class DisplayTarget(BaseModel):
    deviceId: int
    name: str
    kind: str | None
    lastSeenAt: str | None
    online: bool


class CreateDisplayRequest(_Req):
    reservationId: StrictInt
    kind: DisplayKind
    deviceId: StrictInt | None = None  # 없으면 QR 만


class CreateDisplayResponse(BaseModel):
    id: int
    qrToken: str
    expiresAt: str


class DisplayRequestItem(BaseModel):
    """pending · claim 항목(코디 결정 2026-10-27 — SSE display 와 같은 키 + 상태 · 만료)."""

    requestId: int
    kind: DisplayKind
    reservationId: int
    customerId: int | None
    deviceId: int | None
    status: DisplayStatus
    expiresAt: str


class DisplayPending(BaseModel):
    items: list[DisplayRequestItem]


class ClaimDisplayRequest(_Req):
    qrToken: str = Field(min_length=1, max_length=200)
    deviceId: StrictInt | None = None


class CloseDisplayRequest(_Req):
    status: Literal["done", "canceled"]


# SPEC-004 §6.15 문진
class QuestionnaireLanguage(BaseModel):
    code: str
    source: Literal["kos_language", "nationality", "default"]
    options: list[str]


class QuestionnairePhone(BaseModel):
    countryCode: str = ""
    phoneNumber: str = ""


class QuestionnairePrefill(BaseModel):
    name: str | None
    phone: QuestionnairePhone
    address: str
    addressDetail: str
    dateOfBirth: str | None  # yyyyMMdd(제출 꼴과 같음)
    gender: str | None


class QuestionnaireFormPages(BaseModel):
    model_config = ConfigDict(extra="allow")

    pages: list[dict]  # KOS 양식 그대로(translsMap 포함)


class QuestionnaireForm(BaseModel):
    reservationId: int
    customerName: str
    language: QuestionnaireLanguage
    form: QuestionnaireFormPages
    agreements: list[dict]  # KOS 약관 그대로(translsMap · required · type)
    prefill: QuestionnairePrefill
    todaySubmitted: bool


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")  # KOS 가 받는 그 밖 키(inputType · translsMap 등)는 그대로 넘긴다


class QuestionnaireAnswer(_Loose):
    parentQuestionId: str | int
    parentQuestionTitle: str
    id: str | int
    title: str
    inputText: str | None = None
    subText: str | None = None


class QuestionnaireAgreement(_Loose):
    agreed: bool


class QuestionnaireSubmit(BaseModel):
    """registrationNumber · phoneticName 을 보내면 400 questionnaire_field(그래서 extra 대신 이름으로 받아 거른다)."""

    model_config = ConfigDict(extra="forbid")

    displayRequestId: StrictInt | None = None
    deviceId: StrictInt | None = None
    language: str
    name: str
    dateOfBirth: str = Field(pattern=r"^\d{8}$")  # yyyyMMdd
    gender: str
    phone: QuestionnairePhone
    address: str = ""
    addressDetail: str = ""
    agreements: list[QuestionnaireAgreement]
    answers: list[QuestionnaireAnswer]
    registrationNumber: str | None = None
    phoneticName: str | None = None


# SPEC-004 §6.16 여권 스캔 · 사진
class ScanPhotoResult(BaseModel):
    ccc: Literal["ok", "disabled"]
    kos: Literal["ok", "failed", "skipped"]  # skipped = ccc 사진 저장이 꺼져 KOS 로도 안 올림


class PassportScanResponse(OkResponse):
    personal: Literal["ok"]
    skipped: list[str]
    photo: ScanPhotoResult | None  # null = 손 입력 · 사진 없음(리뷰 r1 FAIL-2)
    photoId: int | None


class KosRetryResponse(OkResponse):
    kos: Literal["ok", "failed"]
