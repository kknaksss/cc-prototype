"""외부 연동 API 요청 · 응답(SPEC-008 §6) — 칸 이름 camelCase · 요청은 모르는 키 400 · 모든 칸 설명."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class ExtLookupRequest(_Req):
    """고객 조회 요청 — 이름 · 이메일은 경로 · 질의가 아니라 본문으로만 받는다(접근 로그에 남지 않게)."""

    name: str = Field(description=NAME_DESC, examples=["<이름>"])
    email: str = Field(description=EMAIL_DESC, examples=["a@example.com"])

    _blank = field_validator("name", "email")(_not_blank)


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
    totalCount: int = Field(description=(
        "묶음 안 시술권 장수 합(상태 무관). GROUP 에서 한 세트를 다 쓰면 그 세트가 빠져 줄 수 있다"))
    purchasedDate: str | None = Field(description="가장 이른 시술권 발행 시각(수납 완료 때)의 KST 날짜 `YYYY-MM-DD`. 없으면 null")
    bundlePrice: ExtMoney = Field(description=(
        "**KOS 묶음 가격 그대로**(`price`). 고객이 낸 돈이 아니다. 산 시점 값에서 출발하지만 GROUP 에서 세트를 다 쓰면 "
        "줄 수 있다. 부가세 포함 여부는 표기하지 않는다"))


class ExtLookupResponse(BaseModel):
    customer: ExtCustomer = Field(description=(
        "찾은 고객(상담에 필요한 칸만 — 전화 · 생년월일 · 국적 · 여권 · 차트번호 · 이메일 없음)"))
    tickets: list[ExtTicket] = Field(description=(
        "남은 시술권(사용 가능한 묶음) 한 줄씩 · KOS 순서. 없으면 `[]`(고객은 있는데 남은 시술권 없음)"))


class ExtReservationResponse(BaseModel):
    reservationId: int = Field(description="만든 예약의 ccc id")
    customerId: int = Field(description="예약 고객의 ccc id(새 고객이면 새로 만든 행)")
