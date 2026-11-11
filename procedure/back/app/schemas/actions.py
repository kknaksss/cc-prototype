"""front 계약 — 로그인 · 조작 · 기타 요청/응답(SPEC-003 §7.1 · §7.3 · §7.4)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


# §7.1 로그인 — 아이디 + 비밀번호(OQ-601 닫음 · 정상 로그인)
class LoginRequest(_Req):
    """로그인 요청 — 아이디 + 비밀번호. 모르는 키가 있으면 400 invalid_request."""

    id: str = Field(description="로그인 아이디(ccc 계정 login_id)")
    password: str = Field(description="비밀번호 평문. 서버는 bcrypt 해시와 비교한다(72바이트를 넘으면 틀린 비밀번호로 본다)")


Role = Literal["admin", "doctor", "nurse", "coordinator", "counselor"]  # coordinator = SPEC-005 §3.4 · counselor = SPEC-004 §3.7


class LoginResponse(BaseModel):
    """로그인 성공 — 토큰과 그 계정 정보."""

    token: str = Field(description=(
        "세션 토큰. 이후 요청 헤더 `Authorization: Bearer <token>` 에 싣는다(SSE 는 `?token=`). "
        "서버가 서명한 불투명 문자열 — 클라이언트는 풀지 않는다"))
    expiresAt: str = Field(description=(
        "토큰 만료 시각 — ISO 8601 · KST(+09:00) · 초 단위. 발급 시각 + env `PROC_SESSION_HOURS`(기본 12시간)"))
    id: str = Field(description="로그인 아이디(login_id)")
    role: Role = Field(description=(
        "역할 — `admin` 관리자 · `doctor` 원장 · `nurse` 간호사 · `coordinator` 코디 · `counselor` 상담사"))
    name: str = Field(description="계정 표시 이름")
    staffId: int | None = Field(description=(
        "ccc 직원(staff) id — `doctor` · `counselor` 계정만 값이 있다(KOS 직원 사본의 id). "
        "`admin` · `nurse` · `coordinator` 는 null"))


class MeResponse(BaseModel):
    """지금 로그인한 계정 — DB 의 현재 값."""

    id: str = Field(description="로그인 아이디(login_id)")
    role: Role = Field(description=(
        "역할 — `admin` 관리자 · `doctor` 원장 · `nurse` 간호사 · `coordinator` 코디 · `counselor` 상담사"))
    name: str = Field(description="계정 표시 이름")
    staffId: int | None = Field(description=(
        "ccc 직원(staff) id — `doctor` · `counselor` 계정만 값이 있다. `admin` · `nurse` · `coordinator` 는 null"))


# §7.3 조작
class TargetAll(_Req):
    """호출 대상 — 원장 전체."""

    kind: Literal["all"] = Field(description="`all` = 전체 호출(원장 누구나 수락 가능)")


class TargetOne(_Req):
    """호출 대상 — 원장 한 명 지정."""

    kind: Literal["one"] = Field(description="`one` = 지정 호출(그 원장만 수락 가능)")
    doctorId: int = Field(description=(
        "지정할 원장의 ccc staff id(스냅샷 `doctors[].id`). 원장 목록에 없으면 409 doctor_not_listed"))


class CreateCallRequest(_Req):
    """[의사 호출] 요청 — 호출할 시술과 대상."""

    procedureIds: list[int] = Field(description=(
        "호출할 시술 id(스냅샷 `cards[].procedures[].id`) — 같은 카드의 대기(`wait`) 시술만. 중복은 한 번으로 친다. "
        "빈 배열 = 409 no_procedures"))
    target: Annotated[TargetAll | TargetOne, Field(discriminator="kind", description=(
        "호출 대상 — `{\"kind\": \"all\"}` 전체 호출 또는 `{\"kind\": \"one\", \"doctorId\": <id>}` 지정 호출"))]


class AcceptRequest(_Req):
    """doctor = 생략하면 자기 원장(SPEC-004 §3.4) · admin = 필수(없으면 400 invalid_request).

    본문 자체는 필수 — `doctorId` 를 생략할 때도 `{}` 를 보낸다(본문 없이 보내면 400 invalid_request).
    """

    doctorId: int | None = Field(None, description=(
        "수락할 원장의 ccc staff id. `doctor` 계정 = 생략(또는 자기 staffId · 본문은 `{}` 라도 보내야 한다) — "
        "다른 값이면 403 doctor_forbidden. "
        "`admin` · `coordinator` · `counselor` = 필수(null · 생략이면 400 invalid_request)"))


class BoardOrderRequest(_Req):
    """카드 드래그 순서(SPEC-003 0.4.0 §7.3) — 귀가 대기 아닌 카드 전부의 새 순서 · 빈 배열 = 오늘 순서 지움.

    StrictInt — 문자열 `"3"` · 실수 `3.0` · 불리언 `true` 도 400(같은 id 두 번은 service 가 400).
    """

    visitIds: list[StrictInt] = Field(description=(
        "카드(visit) id 를 화면 위→아래 순서로. 정수만(문자열 · 실수 · 불리언 = 400). 같은 id 두 번 = 400 invalid_request. "
        "지금 카드가 아니거나 귀가 대기 카드인 id 는 오류 없이 빠진다. 빈 배열 = 오늘(KST) 순서를 지움"))


class OkResponse(BaseModel):
    """성공 — 본문은 `{"ok": true}` 뿐."""

    ok: Literal[True] = Field(True, description="늘 true")


class StartResponse(OkResponse):
    """[시작] · [시작] 되돌리기 결과."""

    flowStepChanged: bool = Field(description=(
        "고객(카드) 단계가 바뀌었나. [시작] = 그 고객의 첫 [시작]이라 시술 대기 → 시술 진행으로 바꿨으면 true. "
        "[시작] 되돌리기 = 진행 · 완료 시술이 0 이 되어 고객을 시술 대기로 돌렸으면 true"))


class BoardOrderResponse(OkResponse):
    """카드 순서 저장 결과."""

    visitIds: list[int] = Field(description=(  # 거르기 뒤 저장된 목록
        "실제로 저장된 순서 — 보낸 순서에서 지금 카드가 아닌 id · 귀가 대기 카드를 뺀 것(보낸 순서 유지)"))


class CallCreatedResponse(BaseModel):
    """새로 만든 호출."""

    callId: int = Field(description="새 호출 id(스냅샷 `calls[].callId` · `procedures[].call.id`)")


class AcceptResponse(BaseModel):
    """수락 결과."""

    acceptedProcedureIds: list[int] = Field(description=(
        "이번에 수락된 시술 id — 그 호출에서 아직 수락 안 된 대기 시술 전부. KOS 작업 sequence 순"))


# SPEC-004 §5-1.1 푸시 기기
class DeviceRequest(_Req):
    """푸시 기기 등록 요청(앱)."""

    token: str = Field(pattern=r"^[0-9a-fA-F]{32,200}$", description=(  # APNs 기기 토큰(16진)
        "APNs 기기 토큰 — 16진 문자열 32 ~ 200자. 서버는 소문자로 바꿔 저장한다"))
    name: str | None = Field(default=None, min_length=1, max_length=40, description=(  # 기기 이름(0.4.0 · D7-27)
        "기기 이름(1 ~ 40자 — 길이는 공백을 지우기 전에 잰다 · 저장할 때 앞뒤 공백을 지움). 생략 · null = 기존 이름 유지. "
        "처음 등록하는 기기인데 생략 · null 이면 `kind` 가 tablet 이면 「iPad」 · 그 밖은 「iPhone」. 공백만(`\"   \"`) "
        "보내면 길이 검사를 통과해 빈 문자열로 저장한다(기본 이름이 붙지 않음 · 기존 이름도 빈 문자열로 바뀜)"))
    kind: Literal["phone", "tablet"] | None = Field(None, description=(
        "기기 종류 — `phone` 폰 · `tablet` 태블릿. 생략 = 기존 값 유지"))
    installId: str | None = Field(default=None, min_length=1, max_length=100, description=(  # 설치 단위 id(E2E batch 1 #1)
        "앱 설치 단위 id(1 ~ 100자 · 앞뒤 공백은 지워 저장). 공백만 보내면 생략과 같다. "
        "같은 installId 의 기존 행이 있으면 그 행에 새 토큰을 넣어 deviceId 를 유지한다"))


class DeviceResponse(OkResponse):
    """등록된 기기."""

    deviceId: int = Field(description=(
        "ccc 기기 id — SSE `?deviceId=` · 띄우기 요청 · 여권 스캔에서 이 기기를 가리킬 때 쓴다"))


# SPEC-004 §5-4 알림 · 설정
NotificationKind = Literal["doctor_call", "counselor_call"]
_KIND_DESC = "알림 종류 — `doctor_call` 원장 호출 · `counselor_call` 상담사 호출"


class NotificationTarget(BaseModel):
    """알림이 가리키는 대상 — 해당 없는 키는 null."""

    visitId: int | None = Field(None, description="원장 호출 알림의 카드(visit) id. 상담사 호출은 null")
    callId: int | None = Field(None, description="원장 호출 알림의 호출 id. 상담사 호출은 null")
    reservationId: int | None = Field(None, description="상담사 호출 알림의 ccc 예약 id. 원장 호출은 null")


class NotificationItem(BaseModel):
    """알림 한 건(받는 계정 1명 기준)."""

    id: int = Field(description="알림 id")
    kind: NotificationKind = Field(description=_KIND_DESC)
    title: str = Field(description="제목 — 「원장 호출」 또는 「상담사 호출」")
    body: str = Field(description=(
        "본문(고객 이름 · 시술 이름 없음). 원장 호출 = `<방> · 시술 N건 · 전체 호출|지정 호출`(방을 못 찾으면 `<방>` "
        "자리에 글자 그대로 「방」 · N = 그 호출에 담긴 시술 수 전체 — 그 뒤 수락 · 시작돼도 그대로) · "
        "상담사 호출 = `<방> · 상담 대기`(방이 없으면 「상담 대기」)"))
    createdAt: str = Field(description="만든 시각 — ISO 8601 · KST(+09:00) · 초")
    readAt: str | None = Field(description="읽은 시각 — ISO 8601 · KST(+09:00) · 초. null = 안 읽음")
    target: NotificationTarget = Field(description="알림이 가리키는 호출 · 카드 · 예약")


class NotificationList(BaseModel):
    """오늘(KST) 알림 목록."""

    unread: int = Field(description="오늘(KST 00:00 이후) 안 읽은 알림 수 — 50건 제한과 상관없이 전부 센다")
    items: list[NotificationItem] = Field(description=(
        "오늘(KST 00:00 이후) 알림 — 새것 먼저(만든 시각 · id 내림차순) · 최대 50건"))


class NotificationReadRequest(_Req):
    """ids 없으면 그 계정 전부. 푸시를 눌러 열 때는 payload 의 callId · reservationId 로 찾는다(§5-4 「읽음」).

    본문 자체는 필수 — 세 조건을 모두 생략할 때도 `{}` 를 보낸다(본문 없이 보내면 400 invalid_request).
    """

    ids: list[StrictInt] | None = Field(None, description=(
        "읽음으로 할 알림 id(정수만). 생략 · null = id 로 거르지 않음. 빈 배열 = 아무것도 안 고침. "
        "세 조건을 모두 생략하면(본문 `{}`) 그 계정의 안 읽은 알림 전부(오늘 것만이 아님)"))
    callId: StrictInt | None = Field(None, description="이 호출 id 의 알림만(다른 조건과 AND)")
    reservationId: StrictInt | None = Field(None, description="이 예약 id 의 알림만(다른 조건과 AND)")


class NotificationReadResponse(OkResponse):
    """읽음 처리 결과."""

    read: int = Field(description="이번에 읽음으로 바뀐 알림 수(이미 읽은 것 · 남의 것은 세지 않음)")


class NotificationSetting(BaseModel):
    """알림 종류 하나의 켜짐 여부."""

    kind: NotificationKind = Field(description=_KIND_DESC)
    enabled: bool = Field(description=(
        "true = 받음(저장한 적 없으면 true) · false = 서버가 그 계정에 알림 행 · 푸시를 만들지 않음"))


class NotificationSettings(BaseModel):
    """그 계정 역할이 받는 알림 종류의 설정."""

    items: list[NotificationSetting] = Field(description=(
        "역할이 받는 종류만 — `doctor` · `admin` = [doctor_call] · `counselor` = [counselor_call] · "
        "`nurse` · `coordinator` = 빈 배열"))


class NotificationSettingRequest(_Req):
    """알림 설정 바꾸기."""

    kind: str = Field(description=(
        "알림 종류(`doctor_call` | `counselor_call`) — 그 역할이 받는 종류여야 한다(아니면 400 setting_not_allowed)"))
    enabled: bool = Field(description="true = 받기 · false = 끄기")


# §7.4 기타
class KosTokens(BaseModel):
    """KOS 토큰 보유 여부."""

    open: bool = Field(description="KOS 공개(open) API 토큰이 서버 DB 에 저장돼 있나")
    internal: bool = Field(description="KOS 내부(internal) API 토큰이 서버 DB 에 저장돼 있나")


class HealthResponse(BaseModel):
    """서버 상태."""

    ok: bool = Field(description="늘 true(응답이 오면 서버가 살아 있음)")
    kos: KosTokens = Field(description="KOS 토큰 두 종류가 저장돼 있나 — 값 자체는 싣지 않는다")


class ErrorBody(BaseModel):
    """오류 내용(옛 정의 — 문서의 오류 응답은 app/api/docs.py 의 ErrorResponse)."""

    code: str = Field(description="오류 코드(영문 snake_case)")
    message: str = Field(description="사람이 읽는 한국어 문구")


class ErrorResponse(BaseModel):
    """모든 오류 응답 `{error:{code, message}}`."""

    error: ErrorBody = Field(description="오류 내용")


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
_DKIND_DESC = "종류 — `questionnaire` 고객 문진(고객 웹 링크) · `scan` 여권 스캔(앱)"


class DisplayTarget(BaseModel):
    """띄우기를 보낼 수 있는 기기(코디 계정 기기)."""

    deviceId: int = Field(description="ccc 기기 id")
    name: str = Field(description="기기 이름(없으면 「iPhone」)")
    kind: str | None = Field(description="기기 종류 `phone` | `tablet`. 등록 때 안 보냈으면 null")
    lastSeenAt: str | None = Field(description=(
        "그 기기가 마지막으로 등록 · SSE 연결 · pending 조회 등을 한 시각 — ISO 8601 · KST(+09:00) · 초"))
    online: bool = Field(description="지금 그 기기로 연 SSE 연결이 서버(메모리)에 있나")


class CreateDisplayRequest(_Req):
    """띄우기 요청 만들기."""

    reservationId: StrictInt = Field(description="ccc 예약 id(정수만). 없으면 404 not_found")
    kind: DisplayKind = Field(description=_DKIND_DESC)
    deviceId: StrictInt | None = Field(None, description=(  # 없으면 QR 만
        "보낼 기기 id(`GET /api/devices/targets` 의 deviceId). 생략 · null = 기기에 보내지 않음(QR · 링크만). "
        "없는 기기 = 404 device_not_found"))


class CreateDisplayResponse(BaseModel):
    """만든 띄우기 요청."""

    id: int = Field(description="띄우기 요청 id(requestId)")
    qrToken: str | None = Field(description=(  # 스캔 종류만(`ccc://display?t=`) · 문진 종류 = null
        "스캔 종류만 — QR 에 실을 1회용 토큰 원문(앱이 `POST /api/display-requests/claim` 에 보냄). 문진 종류 = null"))
    qrUrl: str | None = Field(None, description=(  # 문진 종류만 — 고객 웹 링크(SPEC-006 §6.6)
        "문진 종류만 — 고객 문진 웹 링크 `{PROC_FRONT_ORIGIN}/q#<토큰>`(고객 폰으로 여는 주소). 스캔 종류 = null"))
    expiresAt: str = Field(description=(
        "여는 시한 — 만든 시각 + env `PROC_DISPLAY_TTL_MIN`(기본 10분) · ISO 8601 · KST(+09:00) · 초. "
        "이때까지 열리지 않으면 expired"))


class DisplayRequestItem(BaseModel):
    """pending · claim 항목(코디 결정 2026-10-27 — SSE display 와 같은 키 + 상태 · 만료)."""

    requestId: int = Field(description="띄우기 요청 id")
    kind: DisplayKind = Field(description=_DKIND_DESC)
    reservationId: int = Field(description="ccc 예약 id")
    customerId: int | None = Field(description="그 예약의 ccc 고객 id. 예약에 고객이 없으면 null")
    deviceId: int | None = Field(description="그 요청을 받을 기기 id. null = 기기 없이 만든 요청(QR 만)")
    status: DisplayStatus = Field(description=(
        "상태 — `pending` 아직 안 엶 · `opened` 열림(스캔 = 기기가 pending 조회 · claim 으로 받아감 / 문진 = 고객이 링크를 엶) · "
        "`done` 끝남(스캔 저장 · 문진 제출 · close done) · `canceled` 닫힘(close canceled 또는 같은 예약 · 종류의 새 요청) · "
        "`expired` 시한 지남"))
    expiresAt: str = Field(description="여는 시한 — ISO 8601 · KST(+09:00) · 초")
    qrUrl: str | None = Field(None, description=(  # 문진 종류 · pending 일 때만(SPEC-006 §6.6)
        "문진 종류이면서 pending 일 때만 — 고객 문진 웹 링크. 그 밖은 null"))


class DisplayPending(BaseModel):
    """그 기기에 열린 띄우기 요청."""

    items: list[DisplayRequestItem] = Field(description="그 기기의 pending · opened 요청 — 만든 순(오래된 것 먼저)")


class ClaimDisplayRequest(_Req):
    """QR 로 띄우기 요청 받기."""

    qrToken: str = Field(min_length=1, max_length=200, description="QR 에서 읽은 토큰(1 ~ 200자) — 만들 때 받은 `qrToken`")
    deviceId: StrictInt | None = Field(None, description=(
        "부르는 기기 id(자기 계정 기기여야 — 아니면 404 device_not_found). 주면 그 요청을 이 기기 것으로 바꾼다"))


class CloseDisplayRequest(_Req):
    """띄우기 요청 닫기."""

    status: Literal["done", "canceled"] = Field(description="닫는 상태 — `done` 끝냄 · `canceled` 취소")


# SPEC-006 고객 문진 웹 — 공개 응답은 허용 키 모델(extra 금지 · §7.1)
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionnaireLanguage(_Strict):
    """문진 화면 언어."""

    code: str = Field(description=(
        "양식 언어 — `ko` · `ja` · `zh-Hans` · `zh-Hant` · `en` · `id` 중 하나. 쿼리 `lang` 이 이 6개 중 하나면 그 값, "
        "아니면 서버가 고른 값"))
    source: Literal["kos_language", "nationality", "default"] = Field(description=(
        "서버가 언어를 고른 근거 — `kos_language` KOS 고객 언어 · `nationality` 국적 대응표 · `default` 둘 다 없어 기본(en). "
        "`lang` 으로 바꿔도 이 값은 서버 판단 그대로"))
    options: list[str] = Field(description="고를 수 있는 언어 — 늘 `[ko, ja, zh-Hans, zh-Hant, en, id]` 이 순서")


class QuestionnairePhone(_Strict):
    """휴대폰 번호."""

    countryCode: str = Field("", description="국가 번호(KOS 꼴 그대로). 없으면 빈 문자열")
    phoneNumber: str = Field("", description="번호(KOS 꼴 그대로). 없으면 빈 문자열. KOS 는 저장할 때 맨 앞 0 을 뗀다")


class QuestionnairePrefill(_Strict):
    """미리 채움 — KOS 고객 값(읽기 실패면 이름만)."""

    name: str | None = Field(description="KOS 고객 이름(없으면 ccc 사본 이름)")
    phone: QuestionnairePhone = Field(description="KOS 고객 휴대폰(없으면 빈 문자열 둘)")
    address: str = Field(description="KOS 고객 주소. 없으면 빈 문자열")
    addressDetail: str = Field(description="KOS 고객 상세 주소. 없으면 빈 문자열")
    dateOfBirth: str | None = Field(description="생년월일 `yyyyMMdd`(제출 꼴과 같음). 없으면 null")  # yyyyMMdd(제출 꼴과 같음)
    gender: str | None = Field(description="KOS 고객 성별 값 그대로. 없으면 null")


class PublicQuestionnairePages(_Strict):
    """문진 양식."""

    pages: list[dict] = Field(description=(  # KOS 양식 pages 중 객체 항목만 그대로
        "KOS 공개 문진 양식 응답의 `pages` 배열 중 객체인 항목만 그대로(서버는 내용을 바꾸거나 고르지 않는다)"))


class PublicQuestionnaireForm(_Strict):
    """공개 GET 응답 — reservationId · customerId · KOS id 없음."""

    customerName: str = Field(description="고객 이름(ccc 사본)")
    language: QuestionnaireLanguage = Field(description="화면 언어와 고를 수 있는 언어")
    form: PublicQuestionnairePages = Field(description="문진 양식")
    agreements: list[dict] = Field(description=(  # KOS 약관 그대로
        "KOS 약관 응답의 배열(`data` 가 배열이면 그것 · 아니면 `agreements`) 중 객체인 항목만 그대로. 그 결과가 비었으면 "
        "양식 응답의 `agreements` 배열(객체 항목만)로 대신한다"))
    prefill: QuestionnairePrefill = Field(description="미리 채움 값")
    fillUntil: str = Field(description=(  # 쓰는 시한(처음 연 뒤 PROC_QWEB_FILL_MIN)
        "제출 시한 — 처음 연 시각 + env `PROC_QWEB_FILL_MIN`(기본 60분) · ISO 8601 · KST(+09:00) · 초. 지나면 링크 만료(410)"))


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")  # KOS 가 받는 그 밖 키(inputType · translsMap 등)는 그대로 넘긴다


class QuestionnaireAnswer(_Loose):
    """답 하나 — 양식의 선택지 객체 꼴. 여기 없는 키도 그대로 KOS 로 넘긴다."""

    parentQuestionId: str | int = Field(description="질문 id(양식 값 그대로)")
    parentQuestionTitle: str = Field(description="질문 제목")
    id: str | int = Field(description="고른 답(선택지) id")
    title: str = Field(description="고른 답 제목")
    inputText: str | None = Field(None, description="고객이 직접 쓴 글(있을 때)")
    subText: str | None = Field(None, description="선택지 보조 글(있을 때)")


class QuestionnaireAgreement(_Loose):
    """약관 하나 — 받은 약관 객체에 동의 여부를 붙인 꼴. 그 밖 키는 그대로 KOS 로 넘긴다."""

    agreed: bool = Field(description="동의했나")


class PublicQuestionnaireSubmit(BaseModel):
    """공개 POST 본문 — 요청 행은 토큰이 정한다(deviceId · displayRequestId 등 그 밖 키 = 400 invalid_request).

    registrationNumber · phoneticName 은 이름으로 받아 service 가 400 questionnaire_field 로 거른다.
    """

    model_config = ConfigDict(extra="forbid")

    language: str = Field(description="고객이 쓴 언어 코드 — ccc 기록에만 남기고 KOS 로 보내지 않는다")
    name: str = Field(description="이름")
    dateOfBirth: str = Field(pattern=r"^\d{8}$", description="생년월일 `yyyyMMdd`(숫자 8자리)")  # yyyyMMdd
    gender: str = Field(description="성별(KOS 가 받는 값)")
    phone: QuestionnairePhone = Field(description="휴대폰")
    address: str = Field("", description="주소(생략하면 보내지 않음)")
    addressDetail: str = Field("", description="상세 주소(생략하면 보내지 않음)")
    agreements: list[QuestionnaireAgreement] = Field(description="약관 동의")
    answers: list[QuestionnaireAnswer] = Field(description="문진 답")
    registrationNumber: str | None = Field(None, description="받지 않는 칸 — 보내면(null 이라도) 400 questionnaire_field")
    phoneticName: str | None = Field(None, description="받지 않는 칸 — 보내면(null 이라도) 400 questionnaire_field")


# SPEC-004 §6.16 여권 스캔 · 사진
class ScanPhotoResult(BaseModel):
    """여권 사진 저장 결과."""

    ccc: Literal["ok", "disabled"] = Field(description=(
        "ccc 저장 — `ok` 저장함 · `disabled` env `PROC_PHOTO_DIR` 가 비어 저장하지 않음"))
    kos: Literal["ok", "failed", "skipped"] = Field(description=(  # skipped = ccc 사진 저장이 꺼져 KOS 로도 안 올림
        "KOS 고객 이미지 올리기 — `ok` 올림 · `failed` 실패(고객 수정 · ccc 사진은 남음 — "
        "`POST /api/id-photos/{photo_id}/kos-retry` 로 다시) · `skipped` ccc 저장이 꺼져 올리지 않음"))


class PassportScanResponse(OkResponse):
    """여권 스캔 저장 결과."""

    personal: Literal["ok"] = Field(description="고객 정보 수정 — 성공하면 늘 `ok`(바꿀 칸이 없어도 ok)")
    skipped: list[str] = Field(description="늘 빈 배열")
    photo: ScanPhotoResult | None = Field(description=(  # null = 손 입력 · 사진 없음(리뷰 r1 FAIL-2)
        "사진 저장 결과. null = 사진 없이 보냄(손 입력)"))
    photoId: int | None = Field(description=(
        "ccc 신분증 사진 id(`GET /api/id-photos/{photo_id}`). null = 사진 없음 또는 ccc 저장이 꺼짐"))


class KosRetryResponse(OkResponse):
    """KOS 다시 올리기 결과."""

    kos: Literal["ok", "failed"] = Field(description="`ok` 올림(이미 ok 였으면 다시 올리지 않고 ok) · `failed` 또 실패")


class PhotoDeleteResponse(OkResponse):
    """사진 삭제 결과."""

    kos: Literal["deleted", "not_found", "skipped"] = Field(description=(  # skipped = KOS 로 안 올라간 사진(사진 폴더 꺼짐 등)
        "KOS 쪽 — `deleted` KOS 이미지도 지움 · `not_found` KOS 에서 같은 파일을 못 찾음(올리기 실패 · 이미 지움) · "
        "`skipped` KOS 를 부르지 않음(KOS 로 올리지 않은 사진 · 또는 고객 행이 없음)"))
