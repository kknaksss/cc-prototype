"""외부 연동 API 요청 · 응답(SPEC-008 §6) — 칸 이름 camelCase · 요청은 모르는 키 400 · 모든 칸 설명."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from pydantic_core import PydanticCustomError

NAME_DESC = ("고객 이름(필수). 앞뒤 공백만 지워 KOS 이름 검색에 그대로 보낸다 — **KOS 에 등록된 띄어쓰기 그대로** 보내야 한다"
             "(KOS 검색은 가운데 공백을 그대로 견준다). 앞뒤 공백을 지우면 비는 값은 400")
EMAIL_DESC = ("고객 이메일(필수). 앞뒤 공백을 지우고 소문자로 바꿔 KOS 고객 email 과 정확히 같은지만 본다(형식 검사 없음). "
              "앞뒤 공백을 지우면 비는 값은 400")


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _not_blank(v: str) -> str:
    if not v.strip():
        raise ValueError("빈 값이에요")
    return v


class _NameEmail(_Req):
    """이름 + 이메일 두 칸(둘 다 필수) — 과거 시술 · 예약 내역 요청의 바탕(SPEC-008 §6.4 「요청 모델을 따로 둔다」)."""

    name: str = Field(description=NAME_DESC, examples=["<이름>"])
    email: str = Field(description=EMAIL_DESC, examples=["a@example.com"])

    _blank = field_validator("name", "email")(_not_blank)


LOOKUP_NAME_DESC = ("고객 이름 — `email` 과 함께 보낸다(`customerId` 와 섞지 않는다). 앞뒤 공백만 지워 KOS 이름 검색에 그대로 "
                    "보낸다 — **KOS 에 등록된 띄어쓰기 그대로** 보내야 한다. 앞뒤 공백을 지우면 비는 값은 400")
LOOKUP_EMAIL_DESC = ("고객 이메일 — `name` 과 함께 보낸다. 앞뒤 공백을 지우고 소문자로 바꿔 KOS 고객 email 과 정확히 같은지만 "
                     "본다(형식 검사 없음). 앞뒤 공백을 지우면 비는 값은 400")
CUSTOMER_ID_DESC = ("ccc 고객 id(1 이상 정수 · 문자열 불가) — 이 칸 **하나만** 보낸다(`name` · `email` 과 섞지 않는다). "
                    "다른 응답(접수 목록 · 예약 상세 · 조회)의 `customerId` 와 같은 체계")
BRANCH_MSG = "name + email 둘 다 또는 customerId 하나만 보내야 해요"


class ExtLookupRequest(_Req):
    """고객 조회 요청 — 두 갈래 중 **정확히 하나**: `name` + `email` 둘 다 · 또는 `customerId` 하나만.

    섞이거나(`customerId` + `name` 등) · 한쪽만(`name` 만 · `email` 만) · 빈 요청(`{}`)이면 `400 invalid_request`
    (message `body: …`). 이름 · 이메일은 경로 · 질의가 아니라 본문으로만 받는다(접근 로그에 남지 않게).
    """

    name: str | None = Field(None, description=LOOKUP_NAME_DESC, examples=["<이름>"])
    email: str | None = Field(None, description=LOOKUP_EMAIL_DESC, examples=["a@example.com"])
    customerId: StrictInt | None = Field(None, ge=1, description=CUSTOMER_ID_DESC, examples=[1])

    @field_validator("name", "email")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return v if v is None else _not_blank(v)

    @model_validator(mode="after")
    def _branch(self) -> "ExtLookupRequest":
        by_id = self.customerId is not None and self.name is None and self.email is None
        by_name = self.customerId is None and self.name is not None and self.email is not None
        if not (by_id or by_name):
            raise ValueError(BRANCH_MSG)
        return self


class ExtReservationRequest(_Req):
    """예약 요청 — 그룹 · 구역 · 담당자 · 상담사 · 유입 칸은 없다(보내면 모르는 키라서 400)."""

    name: str = Field(description=NAME_DESC, examples=["<이름>"])
    email: str = Field(description=EMAIL_DESC + ". 새 고객이면 이 이메일로 KOS 고객을 만든다", examples=["a@example.com"])
    start: str = Field(description=(
        "시작 시각 ISO-8601(오프셋이 없으면 KST 로 본다). 끝 = 시작 + 서버 기본 예약 그룹의 간격. ISO 가 아니면 400"),
        examples=["2026-11-20T14:00:00+09:00"])
    memo: str | None = Field(None, description="예약 메모(선택). 비었거나 공백뿐이면 보내지 않는다")

    _blank = field_validator("name", "email")(_not_blank)

    @field_validator("start")
    @classmethod
    def _iso(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("ISO 시각이어야 해요") from None
        return v


class ExtMoney(BaseModel):
    value: int = Field(description="금액(원 단위 정수)")
    currency: str = Field(description="통화 코드(ISO 4217 · 예 `KRW`) — KOS 값 그대로")


class ExtUnit(BaseModel):
    type: str = Field(description="단위 종류 — KOS 값 그대로(예 `SHOT` · `CC` · `UNIT` · `UnitType_UNKNOWN`)")
    value: float | None = Field(description="단위 값 — KOS 값 그대로. KOS 가 주지 않으면 null")


class ExtProcedureRef(BaseModel):
    id: str = Field(description="시술 KOS id(문자열)")
    name: str = Field(description="시술 이름(KOS 값)")


class ExtComposition(BaseModel):
    title: str = Field(description="구성 이름(KOS 값)")
    count: int | None = Field(description="구성의 시술 횟수(KOS `count`)")
    unit: ExtUnit | None = Field(description=(
        "구성 단위 — KOS 구성 `unit` 그대로(`UnitType_UNKNOWN` 도 그대로). KOS 가 주지 않으면 null"))
    listPriceExVat: ExtMoney | None = Field(description=(
        "구성 정가 · **부가세 별도**(KOS `price.amount`). 한 GROUP 옵션의 구성 정가를 다 더하면 옵션 정가다"))
    procedure: ExtProcedureRef | None = Field(description="구성의 시술")


class ExtOption(BaseModel):
    id: str = Field(description="옵션 KOS id(문자열) — 시술권 `optionId` 와 같은 체계")
    type: Literal["SINGLE", "GROUP", "CONSULTATION"] = Field(description=(
        "KOS 옵션 판별자 그대로 — `SINGLE`(시술 1개 · 옵션에 횟수 · 단위 · 시술) · `GROUP`(구성 여럿) · "
        "`CONSULTATION`(상담 · 가격 · 구성 없음)"))
    title: str = Field(description="옵션 이름(KOS 기본 이름)")
    description: str = Field(description="옵션 설명(KOS 값 · 없으면 빈 문자열)")
    translsMap: dict[str, Any] = Field(description="KOS 다국어 맵 그대로(`{칸: {translation: {언어: 값}}}`) · 없으면 `{}`")
    listPriceExVat: ExtMoney | None = Field(description="옵션 정가 · **부가세 별도**(KOS `price.amount`). CONSULTATION 은 null")
    count: int | None = Field(description="SINGLE 의 시술 횟수(KOS `count`). GROUP(구성마다 있음) · CONSULTATION 은 null")
    unit: ExtUnit | None = Field(description=(
        "SINGLE 의 단위 = 이어진 진료항목의 `configuration.unit`. 진료항목이 이어지지 않았거나 단위가 없으면 null. "
        "GROUP · CONSULTATION 은 null"))
    procedure: ExtProcedureRef | None = Field(description="SINGLE 의 시술. GROUP · CONSULTATION 은 null")
    compositions: list[ExtComposition] = Field(description="GROUP 의 구성(KOS 배열 순서). SINGLE · CONSULTATION 은 `[]`")


class ExtProduct(BaseModel):
    id: str = Field(description="상품 KOS id(문자열)")
    title: str = Field(description="상품 이름(KOS 기본 이름)")
    description: str = Field(description="상품 설명(KOS 값 · 없으면 빈 문자열)")
    isEvent: bool = Field(description="이벤트 상품인가(KOS `isEvent`)")
    translsMap: dict[str, Any] = Field(description="KOS 다국어 맵 그대로 · 없으면 `{}`")
    options: list[ExtOption] = Field(description="지금 있는 옵션(KOS 배열 순서 · 지운 옵션 제외)")


class ExtCategory(BaseModel):
    id: str = Field(description="카테고리 KOS id(문자열)")
    name: str = Field(description="카테고리 이름(KOS 기본 이름)")
    order: int = Field(description="KOS 카테고리 순서(오름차순으로 준다)")
    translsMap: dict[str, Any] = Field(description="KOS 다국어 맵 그대로 · 없으면 `{}`")
    products: list[ExtProduct] = Field(description=(
        "이 카테고리에 속한 지금 있는 상품(KOS 상품 목록 순서). 한 상품이 카테고리 여럿에 걸리면 각 카테고리 아래에 다 나온다"))


class ExtMenu(BaseModel):
    syncedAt: str | None = Field(description=(
        "메뉴 동기화가 마지막으로 **전부** 성공한 시각(ISO `+09:00`). 그 뒤 작업 하나가 실패해도 이 값은 그대로다. "
        "한 번도 성공한 적 없으면 null"))
    categories: list[ExtCategory] = Field(description=(
        "지금 있는 카테고리(`order` 오름차순 → id). 메뉴가 비었으면(첫 동기화 전 · 실패) `[]`"))


class ExtCustomer(BaseModel):
    customerId: int = Field(description="ccc 고객 id(직원 API 와 같은 체계 · 정수). KOS 고객 id 는 내지 않는다")
    name: str = Field(description="KOS 고객 이름")
    isNew: bool = Field(description="KOS 신규 고객 여부(`isNew`)")
    lastVisitDate: str | None = Field(description=(
        "최근 방문일 — KOS `lastVisitedDateTimeUtc` 의 KST 날짜 `YYYY-MM-DD`. KOS 가 주지 않으면 null"))


class ExtTicket(BaseModel):
    optionId: str = Field(description="시술권의 옵션 KOS id(산 시점 값). 지금 메뉴에 없는 옵션이어도 그대로 준다")
    optionTitle: str = Field(description="시술권의 옵션 이름(산 시점 값 · 메뉴 이름으로 덮지 않는다)")
    remainingCount: int = Field(description=(
        "남은 장수 — 묶음 안 `AVAILABLE` 시술권 수. `IN_USE`(쓰는 중) · `USED` · `CANCELED` 는 넣지 않는다"))
    inUseCount: int = Field(description=(
        "사용 중 장수 — 묶음 안 `IN_USE`(시술 작업에 붙어 아직 안 끝남) 시술권 수. 남은 장수(`remainingCount`)와 따로 센다"))
    totalCount: int = Field(description=(
        "묶음 안 시술권 장수 합(상태 무관 · 사용 중 장도 센다). GROUP 에서 한 세트를 다 쓰면 그 세트가 빠져 줄 수 있다"))
    purchasedDate: str | None = Field(description="가장 이른 시술권 발행 시각(수납 완료 때)의 KST 날짜 `YYYY-MM-DD`. 없으면 null")
    bundlePrice: ExtMoney = Field(description=(
        "**KOS 묶음 가격 그대로**(`price`). 고객이 낸 돈이 아니다. 산 시점 값에서 출발하지만 GROUP 에서 세트를 다 쓰면 "
        "줄 수 있다. 부가세 포함 여부는 표기하지 않는다"))


class ExtBalance(BaseModel):
    remaining: ExtMoney | None = Field(description="남은 금액(KOS `balance` · 금액 꼴). KOS 가 주지 않으면 null")
    total: ExtMoney | None = Field(description="충전 총액(KOS `total` · 금액 꼴). KOS 가 주지 않으면 null")


class ExtPrepaidCard(BaseModel):
    title: str = Field(description="선불카드 이름(KOS 값)")
    issuedDate: str | None = Field(description="발급일 — KOS `createdDateTimeUtc` 의 KST 날짜 `YYYY-MM-DD`. 없으면 null")
    expiresAt: str | None = Field(description="만료 일시 — KOS `expirationDateTimeUtc` 의 ISO `+09:00`. 없으면 null")
    balance: ExtBalance = Field(description="현금 잔액 `{remaining, total}`(KOS `remainingBalance`)")
    point: ExtBalance = Field(description="포인트 잔액 `{remaining, total}`(KOS `remainingPoint`)")


class ExtLookupResponse(BaseModel):
    customer: ExtCustomer = Field(description=(
        "찾은 고객(상담에 필요한 칸만 — 전화 · 생년월일 · 국적 · 여권 · 차트번호 · 이메일 없음)"))
    tickets: list[ExtTicket] = Field(description=(
        "남은 시술권 — **사용 가능 또는 사용 중 장이 1장 이상인 묶음** 한 줄씩 · KOS 순서(다 쓴 · 다 취소된 묶음은 빠진다). "
        "없으면 `[]`(고객은 있는데 남은 시술권 없음)"))
    prepaidCards: list[ExtPrepaidCard] | None = Field(description=(
        "선불카드(만료되지 않았고 잔액이 남은 카드 · KOS 순서). 없으면 `[]`. **선불카드 조회가 실패하면 null**"
        "(「카드 없음」 `[]` 과 다르다 · `partialErrors` 에 `prepaidCards`)"))
    partialErrors: list[str] = Field(description=(
        "실패한 KOS 읽기 칸 이름 — 지금은 `prepaidCards` 하나뿐. 없으면 `[]`"))


class ExtReservationResponse(BaseModel):
    reservationId: int = Field(description="만든 예약의 ccc id")
    customerId: int = Field(description="예약 고객의 ccc id(새 고객이면 새로 만든 행)")


# ------------------------------------------------------------------ 0.3.0(add1) — 가능 시간대 · 과거 시술 · 예약 내역
class ExtCustomerRequest(_NameEmail):
    """과거 시술 · 예약 내역 요청 — `name` · `email` 둘 다 필수(`customerId` 칸 없음 — 보내면 모르는 키라 400).

    이름 · 이메일은 본문으로만 받는다.
    """


class ExtSlot(BaseModel):
    start: str = Field(description=(
        "칸 시작 ISO `+09:00`(초 단위). 이 값을 그대로 예약(`POST /api/ext/reservations`) `start` 로 보내면 된다"))
    remainingSeats: int = Field(description=(
        "남은 자리 수(1 이상) — 기본 그룹의 켜진 구역마다 `max(0, 정원 − 예약 수)` 를 더한 값. 0 인 칸은 나오지 않는다"))


class ExtAvailability(BaseModel):
    date: str = Field(description="요청 날짜 `YYYY-MM-DD`(KST)")
    intervalMinutes: int = Field(description="기본 예약 그룹의 시간 간격(분). 칸 끝 = `start` + 이 값(예약의 끝과 같다)")
    slots: list[ExtSlot] = Field(description="예약 가능한 칸 — 시각 오름차순. 없으면 `[]`(휴무 요일 · 다 참 · 다 지남)")


class ExtVisit(BaseModel):
    date: str = Field(description="일정 시작의 KST 날짜 `YYYY-MM-DD`")
    start: str = Field(description="일정 시작 ISO `+09:00`(묶음 시작 중 가장 이른 값)")
    result: Literal["completed", "noshow", "canceled", "other"] = Field(description=(
        "결과 — KOS 예약 상태가 `COMPLETED` → `completed` · `NO_SHOW` → `noshow` · `CANCELED` → `canceled` · "
        "그 밖(값 없음 포함) → `other`(직원 「이전 방문」 분류 그대로)"))
    procedures: list[str] = Field(description=(
        "그 일정 작업의 이름(KOS 배열 순서 · 빈 값이면 빈 문자열). 「방 배정」 기타 작업은 뺀다. 작업이 없으면 `[]`"))


class ExtVisits(BaseModel):
    visits: list[ExtVisit] = Field(description=(
        "지금보다 앞선 일정 — 최신 순 · 최대 50건 · 취소 · 부도 포함. 없으면 `[]`(고객은 있는데 지난 일정 없음)"))


class ExtCustomerReservation(BaseModel):
    reservationId: int | None = Field(description=(
        "ccc 예약 id(예약 응답 `reservationId` 와 같은 체계). ccc 사본에 그 일정이 없으면 null — "
        "외부 예약 API 로 만든 예약은 늘 id 가 있다"))
    date: str = Field(description="일정 시작의 KST 날짜 `YYYY-MM-DD`")
    start: str = Field(description="일정 시작 ISO `+09:00`")
    end: str | None = Field(description="첫 예약 묶음(시작 순 첫 번째)의 끝 ISO `+09:00`. 묶음이 없으면 null")
    state: Literal["reserved", "reception", "consultation", "procedure", "home", "canceled", "noshow"] = Field(description=(
        "상태 — 취소 · 부도가 먼저(`canceled` · `noshow`), 아니면 KOS 진행 단계로 정한다: `reserved`(예약 · 모르는 단계) · "
        "`reception`(접수) · `consultation`(상담 대기 · 상담) · `procedure`(시술 대기 · 시술) · `home`(시술 끝 · 귀가)"))


class ExtCustomerReservations(BaseModel):
    reservations: list[ExtCustomerReservation] = Field(description=(
        "오늘(KST) 0시 이후 일정 — 시작 오름차순 · 취소 · 부도 포함 · 개수 상한 없음. 없으면 `[]`"))


# ------------------------------------------------------------------ 0.4.0(charty 1차) — 공통 · 쓰기 응답
class ExtStaffRef(BaseModel):
    staffId: int | None = Field(description="ccc 직원 사본 id(직원 목록 `GET /api/ext/clinics/{clinicId}/staff` 와 같은 체계). "
                                            "사본에 없는 KOS 계정이면 null")
    name: str = Field(description="이름(KOS 값)")


class ExtFunnel(BaseModel):
    name: str | None = Field(description="유입 이름(KOS 유입 코드 이름). 없으면 null")
    detail: str | None = Field(description="유입 상세 글(KOS 값). 없으면 null")


class ExtOk(BaseModel):
    ok: bool = Field(description="늘 `true` — KOS 쓰기가 성공했다(또는 고객 언어가 이미 같은 값이라 쓰지 않았다)")


class _State(BaseModel):
    main: str = Field(description="주 상태 — 직원 예약 현황 2계층 상태 그대로(`reserved` · `reception` · `consultation` · "
                                  "`procedure` · `home` · `canceled` · `noshow`)")
    sub: str | None = Field(description="부 상태(직원 판 그대로 · 예 `waiting` · `doing`). 없으면 null")


# ------------------------------------------------------------------ 예약 상세(§6.12)
class ExtDetailCustomer(BaseModel):
    customerId: int | None = Field(description="ccc 고객 id. 예약에 고객 사본이 없으면 null")
    name: str = Field(description="고객 이름(고객 사본 · 직원 상세와 같은 값)")
    phoneticName: str | None = Field(description="발음 이름(고객 사본)")
    gender: str | None = Field(description="성별(KOS 값 그대로)")
    nationality: str | None = Field(description="국적(KOS 값 그대로)")
    isNew: bool = Field(description="KOS 신규 고객 여부")
    chartNumber: str | None = Field(description="차트 번호(KOS 값)")
    age: int | None = Field(description="그 예약 날짜 기준 나이(KOS 고객 생년월일). 고객 읽기 실패 · 생년월일 없음이면 null")
    language: str | None = Field(description="고객 언어 — KOS 고객 `language` 값 그대로. 고객 읽기 실패 · 값 없음이면 null")
    funnel: ExtFunnel | None = Field(description="고객 유입(KOS 고객 `visitorFunnel`). 없음 · 고객 읽기 실패면 null")


class ExtRequestedProcedure(BaseModel):
    type: str = Field(description="`OPTION`(상품 옵션) · `TICKET`(시술권) — KOS 값 그대로")
    optionId: str | None = Field(description="`OPTION` 의 옵션 KOS id(메뉴 `options[].id` 와 같은 체계). `TICKET` 이면 null")
    optionTitle: str | None = Field(description="`OPTION` 의 옵션 이름. `TICKET` 이면 null")
    productTitle: str | None = Field(description="`OPTION` 의 상품 이름. `TICKET` 이면 null")
    ticketId: str | None = Field(description="`TICKET` 의 시술권 KOS id. `OPTION` 이면 null")
    ticketTitle: str | None = Field(description="`TICKET` 의 시술권 이름. `OPTION` 이면 null")


class ExtDetailReservation(BaseModel):
    memo: str | None = Field(description="예약 메모(KOS `reservationMemo`). **오더 메모 · 상담 메모와 다른 칸**이다")
    desiredDischargeAt: str | None = Field(description="귀가 희망 시각 ISO `+09:00`. 없으면 null")
    funnel: ExtFunnel | None = Field(description="예약 유입. 없으면 null")
    counselor: ExtStaffRef | None = Field(description=(
        "**KOS 희망 상담사**(예약에 지정한 상담사 — 실제로 상담한 사람이 아니다). 없으면 null"))
    orderMemo: str | None = Field(description=(
        "지금 오더 메모(KOS 일정 `orderMemo` 그대로 · 빈 문자열 그대로) — 오더 메모 쓰기가 통째로 바꾸는 칸. "
        "null = KOS 일정 읽기 실패(`partialErrors` 에 `schedule`)"))
    consultationMemo: str | None = Field(description=(
        "지금 상담 메모(= 차트 메모 · KOS 일정 `consultation.consultationMemo` 그대로) — 상담 메모 쓰기가 통째로 바꾸는 칸. "
        "null = KOS 일정 읽기 실패 · 상담 정보 없음"))
    requestedDoctor: ExtStaffRef | None = Field(description="희망 의사(KOS 예약 `doctor`). 없음 · KOS 일정 읽기 실패면 null")
    requestedProcedures: list[ExtRequestedProcedure] | None = Field(description=(
        "희망 시술(KOS 예약 `requestedProcedures` 순서). `[]` = 희망 시술 없음 · null = KOS 일정 읽기 실패"))



class ExtHealth(BaseModel):
    state: str = Field(description="`ok`(제출본 있음) · `none`(제출 안 함) · `error`(문진 읽기 실패 — `partialErrors` 에 "
                                   "`questionnaire`) — 직원 상세 `health` 와 같은 계산")
    submittedAt: str | None = Field(description="제출 시각 ISO `+09:00`. 없으면 null")
    needCount: int = Field(description="확인이 필요한 답 수(직원 상세와 같은 규칙)")
    items: list[dict[str, Any]] = Field(description="「건강 정보」 질문 × 답 — 직원 상세 `health.items` 와 같은 모양")


class ExtPrevProcedure(BaseModel):
    title: str = Field(description="작업 이름(KOS 값 · 「방 배정」 기타 작업은 뺀다)")
    status: str | None = Field(description="작업 상태(KOS 값 그대로)")
    doctors: list[str] = Field(description="그 작업의 의사 이름(KOS 순서)")


class ExtPrevVisit(BaseModel):
    date: str = Field(description="일정 시작의 KST 날짜 `YYYY-MM-DD`")
    start: str = Field(description="일정 시작 ISO `+09:00`")
    result: str = Field(description="결과 — `completed` · `noshow` · `canceled` · `other`(직원 「이전 방문」 분류)")
    resultRaw: str | None = Field(description="KOS 예약 상태 값 그대로")
    zoneTitle: str | None = Field(description="구역 이름")
    groupTitle: str | None = Field(description="예약 그룹 이름(사본에 그 그룹이 있을 때)")
    reservationMemo: str | None = Field(description="그 방문의 예약 메모(KOS 값). 없으면 null")
    consultationMemo: str | None = Field(description="그 방문의 상담 메모(KOS 값). 없으면 null")
    procedures: list[ExtPrevProcedure] = Field(description="그 방문의 작업(의사 이름 포함)")
    counselors: list[ExtStaffRef] = Field(description=(
        "그 방문의 상담자 — KOS 일정 `consultations[].counselors[]`(나온 차례 · 같은 사람은 한 번). 그것이 비면 "
        "`consultation.counselor` 하나. 둘 다 없으면 `[]`"))


class ExtReservationDetail(BaseModel):
    reservationId: int = Field(description="ccc 예약 id")
    day: str = Field(description="예약 날짜 KST `YYYY-MM-DD`")
    start: str | None = Field(description="첫 묶음 시작 ISO `+09:00`. 묶음이 없으면 null")
    end: str | None = Field(description="묶음 끝 중 가장 늦은 값 ISO `+09:00`. 묶음이 없으면 null")
    state: _State = Field(description="2계층 상태(직원 판 그대로)")
    customer: ExtDetailCustomer = Field(description="고객 기본 정보 + 나이 · 언어 · 고객 유입(전화 · 이메일 · 여권 · 주소 없음)")
    reservation: ExtDetailReservation = Field(description="예약 칸")
    health: ExtHealth = Field(description="문진(직원 상세 `health` 와 같은 모양 · 같은 계산)")
    previousVisits: list[ExtPrevVisit] | None = Field(description=(
        "이전 방문(최신 순 · 그 예약 날짜와 같은 날 일정은 뺀다) — **예약 메모 · 상담 메모 · 의사 이름 · 상담자를 준다**"
        "(과거 시술 경로와 다르다). null = 이전 방문 조회 실패(`partialErrors` 에 `previousVisits`)"))
    partialErrors: list[str] = Field(description=(
        "실패한 KOS 읽기 — `schedule`(희망 시술 · 희망 의사 · 지금 메모 둘이 null) · `visitor`(나이 · 언어 · 고객 유입 null) · "
        "`questionnaire`(`health.state = error`) · `previousVisits`(null). 없으면 `[]`"))


# ------------------------------------------------------------------ 쓰기 셋 요청(§6.13 ~ §6.15)
class ExtLanguageRequest(_Req):
    language: str = Field(description=(
        "고객 언어 — KOS 언어 값 그대로(꼴 검사 없이 KOS 에 보낸다 · 예 2자 · 5자 코드). 앞뒤 공백을 지운다. "
        "**빈 문자열 = 비움** · null 은 400"), examples=["ja"])

    @field_validator("language")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class ExtOrderMemoRequest(_Req):
    orderMemo: str = Field(description=(
        "오더 메모 글 전체 — **통째로 바꾼다**(일정 하나에 글 하나). 지금 값은 예약 상세 `reservation.orderMemo`. "
        "빈 문자열은 그대로 보낸다(비움)"), examples=["<오더 메모>"])


CONSULT_MEMO_BLANK = "KOS 는 상담 메모를 비울 수 없어요"


class ExtConsultationMemoRequest(_Req):
    consultationMemo: str = Field(description=(
        "상담 메모(= 차트 메모) 글 전체 — **통째로 바꾼다**. 지금 값은 예약 상세 `reservation.consultationMemo`. "
        "**빈 값은 받지 않는다** — 앞뒤 공백을 지우면 비는 값은 `400`(KOS 가 상담 메모를 비우지 못한다 · 빈 값을 보내면 "
        "200 인데 그대로 남는다). 비우는 쓰기는 없다(오더 메모와 다르다)"), examples=["<상담 메모>"])

    @field_validator("consultationMemo")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        """로컬 e2e 2 — KOS 공개 상담 정보 쓰기는 `""` · null 을 200 으로 받고 값을 바꾸지 않는다 → KOS 를 부르지 않고 400."""
        if not v.strip():
            raise PydanticCustomError("consultation_memo_blank", CONSULT_MEMO_BLANK)
        return v


# ------------------------------------------------------------------ 접수 목록(§6.11)
class ExtBoardCustomer(BaseModel):
    customerId: int | None = Field(description="ccc 고객 id. 사본에 고객이 없으면 null")
    name: str = Field(description="고객 이름(고객 사본)")
    phoneticName: str | None = Field(description="발음 이름")
    gender: str | None = Field(description="성별(KOS 값)")
    nationality: str | None = Field(description="국적(KOS 값)")
    isNew: bool = Field(description="KOS 신규 고객 여부")


class ExtBoardRow(BaseModel):
    reservationId: int = Field(description="ccc 예약 id — 예약 상세 · 오더 메모 · 상담 메모 경로의 id")
    start: str | None = Field(description="첫 묶음 시작 ISO `+09:00`. 묶음이 없으면 null")
    end: str | None = Field(description="묶음 끝 중 가장 늦은 값 ISO `+09:00`. 묶음이 없으면 null")
    state: _State = Field(description="2계층 상태(직원 판 그대로)")
    customer: ExtBoardCustomer = Field(description="고객(직원 예약 현황 카드 고객 칸과 같은 값)")
    receptionAt: str | None = Field(description=(
        "접수 시각 ISO `+09:00`(KOS 접수 시각) — **귀가한 예약도 준다**. 접수 전이면 null. "
        "접수 뒤인데 KOS 가 비워 준 일정도 null"))
    counselor: ExtStaffRef | None = Field(description=(
        "**KOS 희망 상담사**(예약에 지정한 상담사 — 실제로 상담한 사람이 아니다 · 예약 상세 `reservation.counselor` 와 같은 값). "
        "없으면 null"))
    roomTitle: str | None = Field(description="관리실 — 작업에 붙은 방 중 **가장 늦게 배정된 방** 이름. 방이 없으면 null")
    consultation: bool = Field(description=(
        "상담 거침(CC 판정) — 접수 뒤이고 ① 지금 상담 대기 · 상담 ② CC 접수가 상담 대기로 끝남 ③ CC 「상담 추가」 중 하나. "
        "취소 · 부도 · 접수 전이면 false. KOS 「상담 필요」 체크는 보지 않는다"))
    firstConsultationWaitingAt: str | None = Field(description=(
        "처음 상담 대기가 된 시각 ISO `+09:00` — KOS 단계 변경 이력에서 찾은 값. **`consultation` 과 따로 정한다** "
        "(`consultation = false` 여도 값이 있을 수 있다 — KOS 웹에서만 상담 대기를 지나간 일정). null = 접수 전 · 취소 · 부도 · "
        "아직 못 찾음(이력에 없음 · 조회 실패 · 다음 단계 변화 전 · 요청당 상한 · 다른 요청이 확인 중 · 그날 끝까지 못 찾음)"))


class ExtSync(BaseModel):
    lastOkAt: str | None = Field(description=(
        "그날 KOS 날짜 조회가 마지막으로 성공한 시각 ISO `+09:00`(직원 예약 현황 `sync` 와 같은 값)"))
    lastError: str | None = Field(description="마지막 날짜 조회 실패 문구 — 있으면 이 목록은 낡은 사본일 수 있다. 없으면 null")


class ExtBoard(BaseModel):
    date: str = Field(description="오늘 KST `YYYY-MM-DD`")
    now: str = Field(description="서버 지금 시각 ISO `+09:00`")
    sync: ExtSync = Field(description="사본 신선도")
    partialErrors: list[str] = Field(description=(
        "일부 KOS 읽기가 실패했거나 아직 못 한 칸 이름 — 지금은 `consultationHistory`(아직 확인하지 못한 처음 상담 대기 "
        "시각이 있다)만 있다. 없으면 `[]`"))
    reservations: list[ExtBoardRow] = Field(description=(
        "오늘 예약 — 예약 1건 = 1줄(묶음이 여럿이어도) · 상태로 거르지 않는다(취소 · 부도 · 귀가 포함) · 시작 오름차순 → id"))


# ------------------------------------------------------------------ 병원 정보 · 직원 목록(§6.16 · §6.17)
class ExtAddress(BaseModel):
    address: str | None = Field(description="주소(KOS 값 · 비면 null)")
    detailed: str | None = Field(description="상세 주소(KOS 값 · 비면 null)")
    zipCode: str | None = Field(description="우편번호(KOS 값 · 비면 null)")


class ExtDayHours(BaseModel):
    enabled: bool = Field(description="그 요일 운영하나(시작 · 끝이 다 있을 때만 true)")
    start: str | None = Field(description="운영 시작 KST `HH:MM`")
    end: str | None = Field(description="운영 끝 KST `HH:MM`")
    breakStart: str | None = Field(description="쉬는 시간 시작 KST `HH:MM`. 없으면 null")
    breakEnd: str | None = Field(description="쉬는 시간 끝 KST `HH:MM`. 없으면 null")


class ExtDayOff(BaseModel):
    startDate: str = Field(description="휴무 첫날 KST `YYYY-MM-DD`")
    endDate: str = Field(description="휴무 마지막 날 KST `YYYY-MM-DD`(하루 휴무면 `startDate` 와 같다 · 여러 날 휴무는 한 원소)")


class ExtClinic(BaseModel):
    clinicId: int = Field(description=(
        "CC 고정 값 `1` — CC 서버 하나 = KOS 병원 하나. 직원 목록 경로(`/api/ext/clinics/{clinicId}/staff`)에 쓴다. "
        "**전역 유일하지 않다**(CC 서버 여럿을 모으면 겹친다)"))
    name: str | None = Field(description="병원 이름(KOS 값 · 비면 null)")
    phone: str | None = Field(description="대표 전화(KOS 값 그대로 · 국가 번호를 붙이지 않는다 · 비면 null)")
    address: ExtAddress | None = Field(description="주소. 세 칸이 모두 비면 null")
    operatingHours: dict[str, ExtDayHours] = Field(description=(
        "**병원 기본 운영 시간**(예약 그룹별 시간표가 아니다) — 요일 키 `monday` … `sunday`"))
    daysOff: list[ExtDayOff] = Field(description="병원 기본 휴무 — 오늘(KST) ~ 오늘 + 90일 · KOS 차례. 없으면 `[]`")


class ExtStaff(BaseModel):
    staffId: int | None = Field(description=(
        "ccc 직원 사본 id(접수 목록 · 예약 상세의 `counselor.staffId` 와 같은 체계). 사본에 아직 없는 계정이면 null"))
    name: str = Field(description="이름(KOS 지금 값)")
    roleName: str | None = Field(description=(
        "KOS 역할 이름(지점마다 설정이 다름 · 예 「CS팀(콜센터)」 = 외주 직원). 외주 직원은 이 칸으로 가른다"))
    roleTags: list[str] = Field(description=(
        "역할 태그(`ADMIN` · `DOCTOR` · `COUNSELOR` · `NURSE` · `SKINCARE` · `CALL_COUNSELOR` · `COORDINATOR`) — ccc 직원 "
        "사본 값. 사본에 없는 계정이면 `[]`. `CALL_COUNSELOR` 가 있다고 외주가 아니다(코디 · 관리자에게도 붙는다)"))
    active: bool = Field(description="활성 계정인가(KOS 값 · 비활성 직원도 싣는다)")


class ExtStaffList(BaseModel):
    clinicId: int = Field(description="요청한 `clinicId`")
    staff: list[ExtStaff] = Field(description="직원 — KOS 차례 · KOS 시스템 계정 · 제외 목록 계정은 뺀다")
