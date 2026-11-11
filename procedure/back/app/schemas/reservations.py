"""front 계약 — 예약 현황(SPEC-005 §7). 필드 이름은 계약 그대로(camelCase).

이 모양을 바꾸려면 SPEC-005 §7 부터 고친다. 시각 = ISO(KST 오프셋 +09:00) · 날짜 = `YYYY-MM-DD` · id = ccc 정수 id.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

# §5.1 상태 2계층
Main = Literal["reserved", "reception", "consultation", "procedure", "home", "canceled", "noshow"]
Sub = Literal["waiting", "doing", "done"]
Money = int | float

_ISO = "ISO-8601 초 단위 · KST 오프셋(`+09:00`)"


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class State(BaseModel):
    """예약 2계층 상태 — KOS 예약 status · flowStep 에서 계산(취소 · 부도가 먼저)."""

    main: Main = Field(description=(
        "주 상태. `reserved` = 예약(KOS flowStep RESERVED 또는 모르는 단계) · `reception` = 접수(RECEPTION) · "
        "`consultation` = 상담(CONSULTATION_WAITING · CONSULTATION) · `procedure` = 시술(PROCEDURE_WAITING · PROCEDURE) · "
        "`home` = 귀가(PROCEDURE_DONE · COMPLETED) · `canceled` = KOS status CANCELED · `noshow` = KOS status NO_SHOW"))
    sub: Sub | None = Field(description=(
        "부상태. `waiting` = 대기(CONSULTATION_WAITING · PROCEDURE_WAITING · PROCEDURE_DONE=귀가 대기) · "
        "`doing` = 진행(CONSULTATION · PROCEDURE) · `done` = 완료(COMPLETED=귀가 완료). 부상태가 없는 주 상태"
        "(reserved · reception · canceled · noshow)는 null"))


# ------------------------------------------------------------------ §7.2 스케줄 표
class SyncInfo(BaseModel):
    """그 날짜 KOS 조회 상태(사본 `sync_state("resv:<날짜>")`)."""

    lastOkAt: str | None = Field(description=(
        f"그 날짜 KOS 조회가 마지막으로 성공한 시각({_ISO}). 한 번도 성공하지 않았으면 null. "
        "하루 예약 조회가 실패하면 이전 성공 시각이 그대로 남는다"))
    lastError: str | None = Field(description=(
        "마지막 조회의 오류 글자(KOS 오류 이름 · 상태만). 하루 예약 조회 실패 = 그 오류 · 정원 · 공지 · 금액 실패 = "
        "`정원: …` · `공지: …` · `금액: …` 을 `; ` 로 이은 것 · 서버에 KOS 설정이 없으면 `KOS 설정이 비어 있어요`. 오류 없으면 "
            "null"))


class Axis(BaseModel):
    """세로 시간축(KST)."""

    start: str = Field(description="축 시작 `HH:MM`(KST). 기본 06:00 · 그보다 이른 카드가 있으면 30분 단위로 내린다")  # "HH:MM"
    end: str = Field(description="축 끝 `HH:MM`(KST). 기본 22:00 · 그보다 늦게 끝나는 카드가 있으면 30분 단위로 올린다(최대 "
        "24:00)")


class Zone(BaseModel):
    """구역(KOS zone 사본 중 지금 KOS 목록에 있는 것)."""

    zoneId: int = Field(description="ccc 구역 id")
    title: str = Field(description="구역 이름(KOS title)")
    order: int = Field(description="KOS 구역 순서 값. 목록은 이 값 → id 오름차순")
    isDefault: bool = Field(description="KOS 구역의 `isDefault` 값 그대로")


class ZoneCapacity(BaseModel):
    """칸(예약 그룹)에서 켜진 구역 하나의 줄당 정원."""

    zoneId: int = Field(description="ccc 구역 id")
    capacity: int = Field(description="그 구역의 한 줄(간격 하나)당 정원(KOS `intervalCapacity` · 명)")


class Span(BaseModel):
    """운영 구간 한 조각(KST)."""

    start: str = Field(description="구간 시작 `HH:MM`(KST)")  # "HH:MM"
    end: str = Field(description="구간 끝 `HH:MM`(KST)")


class Column(BaseModel):
    """스케줄 표 칸 하나 = KOS 예약 그룹 하나(+ 필요할 때 「그룹 없음」 칸)."""

    groupId: int | None = Field(description=(
        # null = 「그룹 없음」 칸(§5.2)
        "ccc 예약 그룹 id. null = 「그룹 없음」 칸 — 사본에 없는 그룹에 걸린 카드가 있을 때만 맨 끝에 하나 붙는다"))
    title: str = Field(description="칸 이름(KOS 예약 그룹 title). 「그룹 없음」 칸은 `그룹 없음`")
    order: int = Field(description="KOS 그룹 순서 값. 칸 목록은 이 값 → id 순. 「그룹 없음」 칸 = 가장 큰 order + 1")
    intervalMinutes: int = Field(description="줄 간격(분) — KOS `intervalMinutes`(없으면 30). 「그룹 없음」 칸 = 30")
    count: int = Field(description=(
        "이 칸에 묶음이 하나라도 있는 예약 수(취소 · 부도 뺌). 한 예약이 이 칸에 묶음 둘이어도 1"))
    capacities: list[ZoneCapacity] = Field(description=(
        "이 그룹에서 켜진 구역별 정원 — 구역 order 순. 켜진 구역이 없거나 「그룹 없음」 칸이면 []"))
    open: list[Span] = Field(description=(
        "그 날짜 요일의 운영 구간(쉬는 시간을 뺀 조각들 · 시간 순). 그 요일이 꺼졌거나 「그룹 없음」 칸이면 []"))


class CardCustomer(BaseModel):
    """카드에 보이는 고객(ccc 고객 사본)."""

    customerId: int | None = Field(description="ccc 고객 id. 예약에 고객이 없으면 null")
    name: str = Field(description="고객 이름. 고객이 없으면 빈 문자열")
    phoneticName: str | None = Field(description="발음 이름(KOS phoneticName). 없으면 null")
    gender: str | None = Field(description="성별 — KOS 값 그대로. 없으면 null")
    nationality: str | None = Field(description="국적 — KOS 값 그대로(내국인 판정은 `KR`). 없으면 null")
    isNew: bool = Field(description="KOS 고객 `isNew` 값 그대로. 고객이 없으면 false")


class BoardCard(BaseModel):
    """예약 카드 — 예약의 묶음(occupiedResource) 하나당 한 장."""

    reservationId: int = Field(description="ccc 예약 id")
    resourceIndex: int = Field(description="그 예약의 묶음 순번(0부터 · 묶음 시작 시각 순). 이동 요청의 `resourceIndex`")
    groupId: int | None = Field(description="묶음의 ccc 예약 그룹 id. 그룹이 사본에 없으면 null(「그룹 없음」 칸)")
    zoneId: int | None = Field(description="묶음 구역(없으면 예약 구역)의 ccc 구역 id. 구역이 사본에 없으면 null")
    start: str = Field(description=f"묶음 시작 시각({_ISO})")
    end: str = Field(description=f"묶음 끝 시각({_ISO})")
    customer: CardCustomer = Field(description="고객")
    state: State = Field(description="예약 상태")
    paymentRequiredCount: int = Field(description=(
        "수납 필요 작업 수 — KOS 작업 중 paymentRequired 이고 취소 아닌 것(방만 붙은 「방 배정」 류 기타 작업 · "
        "ccc 가 호출하지 않은 것은 뺀다)"))
    draggable: bool = Field(description="끌어서 옮길 수 있는지. 지금 코드는 모든 상태에서 true")


class Slot(BaseModel):
    """칸 × 켜진 구역 × 줄 하나의 정원 상태(KOS 슬롯 사본)."""

    groupId: int = Field(description="ccc 예약 그룹 id")
    zoneId: int = Field(description="ccc 구역 id")
    start: str = Field(description=f"줄 시작({_ISO})")
    end: str = Field(description=f"줄 끝 = 시작 + 칸 간격({_ISO})")
    capacity: int | None = Field(description="KOS 슬롯 정원. 슬롯 사본이 없으면 null")  # 슬롯 사본이 없으면 null
    count: int | None = Field(description="KOS 슬롯 예약 수(`reservationCount`). 슬롯 사본이 없으면 null")
    full: bool = Field(description="꽉 참 = capacity · count 가 모두 있고 count ≥ capacity. 슬롯 사본이 없으면 false")


class PlusRow(BaseModel):
    """칸의 줄 하나 — [+](등록) 버튼을 켤지."""

    groupId: int = Field(description="ccc 예약 그룹 id(「그룹 없음」 칸은 줄이 없다)")
    start: str = Field(description=f"줄 시작({_ISO})")
    plusAllowed: bool = Field(description="그 줄에서 켜진 구역 중 하나라도 꽉 차지 않았으면 true. 켜진 구역이 없으면 false")


class BoardCounts(BaseModel):
    """그 날짜 예약 수(예약 단위 · 카드 단위 아님)."""

    total: int = Field(description="취소 · 부도를 뺀 예약 수")
    reserved: int = Field(description="주 상태 reserved 예약 수")
    reception: int = Field(description="주 상태 reception 예약 수")
    consultation: int = Field(description="주 상태 consultation 예약 수")
    procedure: int = Field(description="주 상태 procedure 예약 수")
    home: int = Field(description="주 상태 home 예약 수")
    canceled: int = Field(description="주 상태 canceled 예약 수")
    noshow: int = Field(description="주 상태 noshow 예약 수")


class Notice(BaseModel):
    """그 날짜 공지(KOS 공지 사본)."""

    id: int = Field(description="ccc 공지 행 id(저장 요청의 `noticeId`)")
    content: str = Field(description="공지 글")
    releasedAt: str | None = Field(description=f"KOS 게시 시각(`releaseDateTimeUtc` · {_ISO}). 없으면 null")


class Amount(BaseModel):
    """수납 금액(KOS 수납 요약 합)."""

    total: Money | None = Field(description=(
        "전체 금액 = 수납 항목 `priceV2.amount.value` 합. 정수면 정수, 아니면 소수. 코드상 금액이 있으면 늘 숫자"))
    paid: Money | None = Field(description=(
        "결제 금액 = 거래 중 status APPROVED 이고 취소 참조(canceledRefId)가 없는 것의 `price.value` 합. 코드상 금액이 있으면 늘 "
            "숫자"))
    currency: str | None = Field(description="통화 — KOS 값 그대로(처음 보인 값). 없으면 null")


class ClinicCustomer(BaseModel):
    """원내 현황 고객."""

    name: str = Field(description="고객 이름. 고객이 없으면 빈 문자열")
    phoneticName: str | None = Field(description="발음 이름. 없으면 null")
    nationality: str | None = Field(description="국적 — KOS 값 그대로. 없으면 null")


class ClinicItem(BaseModel):
    """원내 현황 한 줄 — 오늘 접수 ~ 귀가 대기 사이 예약."""

    reservationId: int = Field(description="ccc 예약 id")
    zoneId: int | None = Field(description="예약 구역의 ccc 구역 id. 사본에 없으면 null")
    customer: ClinicCustomer = Field(description="고객")
    state: State = Field(description="예약 상태")
    receptionAt: str | None = Field(description=f"KOS 접수 시각(`receptionDateTimeUtc` · {_ISO}). 없으면 null")
    paymentRequiredCount: int = Field(description="수납 필요 작업 수(카드와 같은 계산)")
    amount: Amount | None = Field(description=(
        "그 예약 수납들의 금액 합(오늘 날짜 조회 때 KOS 에서 읽어 메모리에 둔 값). 수납 id 가 없거나 읽은 금액이 없으면 null"))


class ClinicCounts(BaseModel):
    """원내 현황 수(두 구역 합)."""

    all: int = Field(description="원내 현황 예약 수(items 길이)")
    reception: int = Field(description="주 상태 reception 수")
    consultation: int = Field(description="주 상태 consultation 수")
    procedure: int = Field(description="주 상태 procedure 수")
    home: int = Field(description="주 상태 home 수(귀가 대기)")


class Clinic(BaseModel):
    """원내 현황 — 오늘만."""

    counts: ClinicCounts = Field(description="상태별 수")
    items: list[ClinicItem] = Field(description=(
        "KOS 단계가 RECEPTION ~ PROCEDURE_DONE 이고 취소 · 부도 아닌 오늘 예약. 순서 = 구역 order → 접수 시각 → 예약 id"))


class ReservationBoard(BaseModel):
    """예약 스케줄 표(§7.2) — 그 날짜 사본으로 조립."""

    date: str = Field(description="보는 날짜 `YYYY-MM-DD`(KST)")
    isToday: bool = Field(description="보는 날짜가 오늘(KST)이면 true")
    now: str = Field(description=f"서버 지금 시각({_ISO})")
    sync: SyncInfo = Field(description="그 날짜 KOS 조회 상태")
    axis: Axis | None = Field(description="세로 시간축. 코드상 늘 값이 있다(null 안 씀)")
    zones: list[Zone] = Field(description="구역(지금 KOS 목록에 있는 것) — order → id 순")
    columns: list[Column] = Field(description="칸(예약 그룹) — order → id 순 · 필요하면 끝에 「그룹 없음」 칸")
    cards: list[BoardCard] = Field(description=(
        "카드(예약 묶음당 한 장) — 순서 = 칸 order(그룹 없음 = 맨 뒤) → 시작 → 예약 id → resourceIndex. "
        "취소 · 부도 카드도 실린다"))
    slots: list[Slot] = Field(description="칸 × 켜진 구역 × 줄 정원 — 칸 순 → 줄 시각 순 → 구역 order 순")
    rows: list[PlusRow] = Field(description="칸마다 줄 전부(축 시작을 칸 간격으로 내린 곳 ~ 축 끝) — 칸 순 → 줄 시각 순")
    counts: BoardCounts = Field(description="상태별 예약 수")
    notices: list[Notice] = Field(description=(
        # 0.4.0: front 는 첫 번째 하나만(§5.15)
        "그 날짜(KST) 게시 시각인 공지 중 지우지 않은 것 — 게시 시각 → id 순. front 는 첫 번째 하나만 쓴다"))
    # 0.4.0 — 보는 날짜 ≥ 오늘(KST) · [수정하기] 보임(§5.15)
    noticeEditable: bool = Field(description="보는 날짜 ≥ 오늘(KST)이면 true — 공지 [수정하기]를 보인다")
    requests: list[dict] = Field(description="자리만 있는 칸 — 늘 빈 배열")  # D-07 자리만 — 늘 빈 배열
    clinic: Clinic | None = Field(description="원내 현황. 보는 날짜가 오늘일 때만 · 아니면 null")


# ------------------------------------------------------------------ §7.3 예약 상세
class Phone(BaseModel):
    """전화번호(KOS 값 그대로)."""

    countryCode: str | None = Field(description="국가 번호 — KOS 값 그대로. 없으면 null")
    number: str | None = Field(description="번호(KOS `phoneNumber`). 없으면 null")


class Sns(BaseModel):
    """SNS(KOS snsInfo)."""

    type: str | None = Field(description="SNS 종류(KOS `snsType`). 없으면 null")
    accountId: str | None = Field(description="SNS 계정 id. 없으면 null")


class Address(BaseModel):
    """주소(KOS address)."""

    address: str | None = Field(description="주소. 없으면 null")
    detailed: str | None = Field(description="상세 주소(KOS `detailedAddress`). 없으면 null")
    zipCode: str | None = Field(description="우편번호. 없으면 null")


class Personal(BaseModel):
    """고객 개인 정보 — KOS get-visitor 응답 값 그대로(없는 값 = null)."""

    name: str | None = Field(description="이름")
    phoneticName: str | None = Field(description="발음 이름")
    gender: str | None = Field(description="성별 — KOS 값 그대로")
    dateOfBirth: str | None = Field(description="생년월일 `YYYY-MM-DD`(KOS 값 앞 10자)")  # yyyy-MM-dd
    registrationNumber: str | None = Field(description="주민등록번호 — KOS 값 그대로")
    passportNumber: str | None = Field(description="여권 번호")
    passportSurname: str | None = Field(description="여권 성(영문)")
    passportGivenNames: str | None = Field(description="여권 이름(영문)")
    passportExpiryDate: str | None = Field(description="여권 만료일 `YYYY-MM-DD`(KOS 값 앞 10자)")  # yyyy-MM-dd
    foreignRegistrationNumber: str | None = Field(description="외국인 등록번호")
    nationality: str | None = Field(description="국적 — KOS 값 그대로")
    language: str | None = Field(description="언어 — KOS 값 그대로")
    phone: Phone | None = Field(description="전화번호(KOS phoneNumber). 없으면 null")
    additionalPhone: Phone | None = Field(description="추가 전화번호(KOS additionalPhoneNumber). 없으면 null")
    email: str | None = Field(description="이메일")
    sns: Sns | None = Field(description="SNS. 없으면 null")
    address: Address | None = Field(description="주소. 없으면 null")


class IdentityField(BaseModel):
    """신분 확인용 칸 하나."""

    key: str = Field(description=(
        "KOS 고객 키 — 외국인: `passportSurname`(여권 영문명 · 성 또는 이름 하나만 있어도 채움) · `dateOfBirth` · "
        "`passportNumber` / 내국인: `dateOfBirth` · `registrationNumber`"))
    label: str = Field(description="한국어 칸 이름(여권 영문명 · 생년월일 · 여권번호 · 주민등록번호)")
    filled: bool = Field(description="KOS 값이 비어 있지 않으면 true")


class Identity(BaseModel):
    """신분 확인 표시(ccc 기록) + 신분 칸 채움 상태(KOS get-visitor)."""

    status: Literal["confirmed", "unconfirmed"] = Field(description=(
        "`confirmed` = 그 고객의 가장 최근 신분 확인 기록이 confirmed · `unconfirmed` = 기록 없음 또는 최근 기록이 unconfirmed"))
    checkedAt: str | None = Field(description=f"가장 최근 기록 시각({_ISO}). 기록이 없으면 null")
    checkedBy: str | None = Field(description="가장 최근 기록을 남긴 계정 이름(계정을 못 찾으면 로그인 아이디). 기록이 없으면 "
        "null")
    method: str | None = Field(description=(
        "가장 최근 기록 방법 — `web_manual` = `PUT /api/customers/{id}/identity`(confirmed · unconfirmed 둘 다) 또는 "
        "신분증 사진 삭제로 자동으로 남는 unconfirmed 기록 · `app_scan` = 앱 여권 스캔 · `app_manual` = 앱 직접 입력. "
        "기록이 없으면 null"))  # web_manual | app_scan | app_manual(SPEC-004 §6.16 ④-d)
    device: str | None = Field(None, description="앱 기록(`app_scan` · `app_manual`)의 기기 이름. 웹 기록이거나 기기 정보가 "
        "없으면 null")  # 앱 스캔 기기 이름
    photoId: int | None = Field(None, description=(
        # 사진 열람 = GET /api/id-photos/{photoId}(Bearer)
        "그 기록의 신분증 사진 id — 열람 = `GET /api/id-photos/{photoId}`(Bearer). 사진이 없으면 null"))
    photoKos: Literal["ok", "failed", "skipped"] | None = Field(None, description=(
        # 그 사진 KOS 올리기 결과(id_photo.kos_status) · 사진 없으면 null
        "그 사진의 KOS 올리기 결과 — `ok` = 올림 · `failed` = 실패 · `skipped` = 올리지 않음. 사진이 없으면 null"))
    kind: Literal["foreign", "domestic"] = Field(description="`domestic` = KOS 국적이 `KR` · `foreign` = 그 밖(국적 비어 있음 "
        "포함)")
    fields: list[IdentityField] = Field(description="kind 에 따른 신분 칸. KOS 고객 정보를 못 읽었으면 []")
    complete: bool = Field(description="fields 가 모두 채워졌으면 true. KOS 고객 정보를 못 읽었으면 false")


class DetailCustomer(BaseModel):
    """상세의 고객."""

    customerId: int = Field(description="ccc 고객 id. 예약에 고객이 없으면 0")
    name: str = Field(description="고객 이름(ccc 사본). 고객이 없으면 빈 문자열")
    phoneticName: str | None = Field(description="발음 이름. 없으면 null")
    gender: str | None = Field(description="성별 — KOS 값 그대로. 없으면 null")
    nationality: str | None = Field(description="국적 — KOS 값 그대로. 없으면 null")
    isNew: bool = Field(description="KOS 고객 `isNew` 값 그대로")
    chartNumber: str | None = Field(description="KOS 차트 번호. 없으면 null")
    age: int | None = Field(description="예약 날짜 기준 만 나이(KOS 생년월일). 생년월일을 모르면 null")
    personal: Personal | None = Field(description="KOS 개인 정보. KOS get-visitor 를 못 읽었으면 null(이유는 personalError)")
    personalError: str | None = Field(description=(
        "personal 이 null 인 이유 — `고객 정보 없음`(고객 없음) · `KOS 설정이 비어 있어요` · `고객 응답 형식` · KOS 오류 이름. "
            "읽었으면 null"))
    remark: str | None = Field(description="고객 특이사항(KOS 고객 `memo`). 없거나 못 읽었으면 null")
    identity: Identity = Field(description="신분 확인")
    funnel: "VisitorFunnel | None" = Field(None, description=(
        # KOS 고객 유입 채널(관리 묶음 visitorFunnel · E2E batch 3 #2)
        "KOS 고객 유입 채널(관리 묶음 visitorFunnel). 유입 코드 · 상세가 둘 다 비었거나 못 읽었으면 null"))


class VisitorFunnel(BaseModel):
    """KOS 고객 유입 채널."""

    funnelId: int | None = Field(description=(
        # ccc funnel_code id(KOS FUNNEL 코드) · 코드 목록에 없으면 null
        "ccc 유입 코드 id(KOS FUNNEL 코드). 코드 목록 사본에 없으면 null"))
    name: str | None = Field(description="유입 코드 이름. 코드 목록 사본에 없으면 null")
    detail: str | None = Field(description="유입 상세 글(KOS `funnelDetail`). 비었으면 null")


class Funnel(BaseModel):
    """예약에 붙은 유입 채널(KOS reservation.funnel)."""

    name: str | None = Field(description="유입 코드 이름(KOS 값). 비었으면 null")
    detail: str | None = Field(description="유입 상세 글. 비었으면 null")


class StaffRef(BaseModel):
    """직원 참조."""

    staffId: int | None = Field(description="ccc 직원 id. KOS 사람 id 가 ccc 직원 사본에 없으면 null")
    name: str = Field(description="이름 — KOS 값(비었으면 ccc 직원 이름)")


class NameRef(BaseModel):
    """이름만 있는 참조."""

    name: str = Field(description="이름 — KOS 값 그대로")


class ReservationInfo(BaseModel):
    """예약 정보(KOS 예약 값 사본)."""

    sedationRequired: bool = Field(description="KOS 예약 `sedationRequired` 값 그대로 — 읽기만")
    memo: str | None = Field(description="예약 메모(KOS `reservationMemo`). 없으면 null")
    funnel: Funnel | None = Field(description="예약 유입 채널. 없으면 null")
    connectedChannel: str | None = Field(description="KOS 예약 `connectedChannel` 값 그대로. 없거나 빈 값이면 null")
    counselor: StaffRef | None = Field(description="예약 담당 상담사(KOS reservation.counselor). 없으면 null")
    assignee: NameRef | None = Field(description="예약 담당자(KOS reservationAssignee). 없으면 null")
    doctors: list[NameRef] = Field(description="묶음들에 지정된 의사 이름 — 묶음 순서대로 · 같은 이름은 한 번만")
    desiredDischargeAt: str | None = Field(description=f"희망 귀가 시각(KOS `desiredDischargeDateTimeUtc` · {_ISO}). 없으면 null")


class HealthItem(BaseModel):
    """건강 정보 질문 하나 × 답."""

    title: str = Field(description="질문 제목(KOS 문진 양식 「건강 정보」 쪽)")
    answer: str | None = Field(description="고른 답 제목들을 ` · ` 로 이은 것(답 seq 순). 없으면 null")
    memo: str | None = Field(description="답에 적은 메모들을 ` · ` 로 이은 것. 없으면 null")
    needsCheck: bool = Field(description="확인 필요 — 답이 비지 않았고, 고른 답이 모두 `없음` · `아니오` 인 경우가 아니면 true")
    empty: bool = Field(description="고른 답도 메모도 없으면 true")


class Health(BaseModel):
    """건강 정보(문진)."""

    state: Literal["none", "ok", "error"] = Field(description=(
        "`ok` = 제출본 있음 · `none` = 제출본 없음 · `error` = KOS 문진 양식 또는 제출본 읽기 실패(ccc 고객 웹 제출이 더 "
            "새로우면 "
        "제출본 실패는 error 가 아님)"))
    submittedAt: str | None = Field(description=f"쓴 제출본의 제출 시각({_ISO}). state 가 ok 가 아니면 null")
    needCount: int = Field(description="needsCheck 가 true 인 항목 수. ok 가 아니면 0")
    items: list[HealthItem] = Field(description=(
        "「건강 정보」 쪽 질문 — 질문 sequence 순. error 면 [] · none 이면 질문만(답 빈 칸)"))


class PrevProcedure(BaseModel):
    """이전 방문의 작업 하나(「방 배정」 기타 작업은 뺀다)."""

    title: str = Field(description="작업 제목. 없으면 빈 문자열")
    status: str | None = Field(description="KOS 작업 status 값 그대로. 없으면 null")
    doctors: list[str] = Field(description="그 작업 의사 이름들 — KOS 순서")


class PreviousVisit(BaseModel):
    """이전 방문(같은 고객의 다른 날 KOS 일정)."""

    date: str = Field(description="방문 날짜 `YYYY-MM-DD`(KST)")
    start: str | None = Field(description=f"일정 시작 시각({_ISO})")
    result: Literal["completed", "noshow", "canceled", "other"] = Field(description=(
        "KOS 예약 status → `completed`(COMPLETED) · `noshow`(NO_SHOW) · `canceled`(CANCELED) · `other`(그 밖)"))
    resultRaw: str | None = Field(description="KOS 예약 status 원래 값. 없으면 null")
    zoneTitle: str | None = Field(description="구역 이름(KOS). 없으면 null")
    groupTitle: str | None = Field(description="첫 묶음의 예약 그룹 이름(ccc 사본 · 지금 없는 그룹 포함). 모르면 null")
    reservationMemo: str | None = Field(description="그 예약 메모. 없으면 null")
    consultationMemo: str | None = Field(description="KOS 상담 메모. 없으면 null")
    procedures: list[PrevProcedure] = Field(description="작업들 — KOS 순서")


class Consultation(BaseModel):
    """상담 카드 — 상담 단계이거나 ccc 가 상담을 거치게 한 예약에만."""

    state: Literal["none", "waiting", "doing", "done"] = Field(description=(
        "`waiting` = KOS 단계 CONSULTATION_WAITING · `doing` = CONSULTATION · `none` = 아직 RECEPTION · `done` = 그 밖(상담 뒤 "
            "단계)"))
    counselor: StaffRef | None = Field(description="예약 담당 상담사(KOS reservation.counselor). 없으면 null")
    since: str | None = Field(description=f"상담 진행이 된 시각(KOS flowStepUpdatedDateTimeUtc · {_ISO}). state 가 doing 이 "
        f"아니면 null")
    calledAt: str | None = Field(description=f"마지막 [실장 호출] 시각(ccc event_log · {_ISO}). 호출 기록이 없으면 null")
    calledBy: str | None = Field(description="마지막 [실장 호출]을 누른 계정 이름(못 찾으면 로그인 아이디). 없으면 null")


class Stages(BaseModel):
    """시술 · 귀가 단계 줄 상태."""

    procedure: Literal["none", "waiting", "doing", "done"] = Field(description=(
        "`waiting` = PROCEDURE_WAITING · `doing` = PROCEDURE · `done` = PROCEDURE_DONE · COMPLETED · `none` = 그 전"))
    home: Literal["none", "waiting", "done"] = Field(description="`waiting` = PROCEDURE_DONE(귀가 대기) · `done` = COMPLETED · "
        "`none` = 그 전")


class FlowTimes(BaseModel):
    """단계 줄 시각(E2E b3 #2) — 그 단계 줄이 지금 상태가 된 시각 · 근거 없으면 null(지어내지 않음)."""

    consultation: str | None = Field(description=(
        f"상담 줄 시각({_ISO}) — 대기 · 진행 = 그 단계가 된 시각 · 완료 = 지금 단계가 시술 대기면 그 시각, 아니면 KOS 상담 시작 "
            f"시각"
        # 대기 · 진행 = 그 단계가 된 시각 · 완료 = 시술 대기가 된 시각(바로 다음) → 아니면 KOS 상담 시작
        "(예약 시작과 같은 값은 버림). 상담 카드가 없거나 근거 없으면 null"))
    procedure: str | None = Field(description=(
        f"시술 줄 시각({_ISO}) — 시술 대기 · 진행 · 귀가 대기 = 그 단계가 된 시각 · 귀가 완료 = KOS 시술(PROCEDURE · DONE) 작업 "
        # 대기 · 진행 · 완료(귀가 대기) = 그 단계가 된 시각 · 귀가 완료 뒤 = KOS 시술 작업 완료 시각
        "완료 시각 중 마지막. 근거 없으면 null"))
    # 귀가 대기 · 귀가 완료가 된 시각
    home: str | None = Field(description=f"귀가 줄 시각({_ISO}) — 귀가 대기 · 귀가 완료가 된 시각. 그 전이면 null")


class Flow(BaseModel):
    """내원 현황 — 접수 뒤(주 상태가 reserved · canceled · noshow 아님)에만."""

    receptionAt: str | None = Field(description=f"KOS 접수 시각({_ISO}). 없으면 null")
    roomTitle: str | None = Field(description="카드 방 이름(방이 붙은 KOS 작업 중 배정 시각이 가장 늦은 것). 없으면 null")
    receptionBy: str | None = Field(description="ccc [접수 완료]를 마지막으로 누른 계정 이름(못 찾으면 로그인 아이디). ccc 접수 "
        "기록이 없으면 null")
    consultation: Consultation | None = Field(description=(
        "상담 카드. 지금 상담 단계이거나 ccc 접수가 상담 대기로 끝났거나 [+ 상담 추가]를 했으면 실린다 · 아니면 null"))
    stages: Stages = Field(description="시술 · 귀가 단계 줄 상태")
    times: FlowTimes = Field(description="단계 줄 시각")


class Links(BaseModel):
    """KOS 웹 바로가기."""

    purchase: str = Field(description="KOS 웹 그 일정의 수납 탭 URL")
    prescription: str = Field(description="KOS 웹 그 일정의 기타 작업(처방) 탭 URL")


class Settlement(BaseModel):
    """정산 — 주 상태 home 일 때만."""

    paymentRequiredCount: int = Field(description="수납 필요 작업 수(카드와 같은 계산)")
    amount: Amount | None = Field(description="KOS 수납 요약에서 바로 읽은 금액. 수납이 없거나 읽기 실패면 null")
    prescriptionCount: int = Field(description="KOS 일정 `prescriptionIds` 수")
    links: Links | None = Field(description="KOS 웹 링크. 서버 env `KOS_WEB_BASE` 가 비었거나 고객이 없으면 null")


class RoomItem(BaseModel):
    """접수 때 고를 방 — 그 예약 구역의 방."""

    roomId: int = Field(description="ccc 방 id(접수 요청 `roomId`)")
    title: str = Field(description="방 이름")
    busy: bool = Field(description=(
        "사용 중 — 오늘 같은 구역에서 접수 ~ 시술 진행 중(취소 · 부도 아님)인 다른 예약의 안 취소된 작업에 붙은 방. 고정된 방은 "
            "false"))
    selected: bool = Field(description="이어 하기에서 이미 붙은(고정된) 방이면 true")


class CounselorItem(BaseModel):
    """[실장 호출] 상담사 목록 한 줄."""

    staffId: int = Field(description="ccc 직원 id(호출 요청 `staffId`)")
    name: str = Field(description="상담사 이름")
    busyRoom: str | None = Field(description=(
        "오늘 그 상담사가 상담 중(CONSULTATION)인 예약 중 가장 늦게 그 단계가 된 것의 카드 방 이름(방 없으면 `-`). 상담 중이 "
            "아니면 null"))


class Can(BaseModel):
    """버튼 켜짐 — 서버 규칙 계산 결과."""

    cancel: bool = Field(description="[취소] — 주 상태 reserved")
    editRoute: bool = Field(description="진행 경로 고르기 — 주 상태 reserved · noshow")
    receive: bool = Field(description="[접수 완료] — receiveMode 가 null 이 아님")
    callCounselor: bool = Field(description="[실장 호출] — KOS 단계 CONSULTATION_WAITING · CONSULTATION 이고 취소 · 부도 아님")
    discharge: bool = Field(description="[귀가 완료] — KOS 단계 PROCEDURE_DONE · 취소 · 부도 아님 · 수납 필요 0")
    editMemo: bool = Field(description="예약 메모 고치기 — 취소 아님 · KOS 단계 COMPLETED 아님(부도는 됨)")
    editPersonal: bool = Field(description="고객 정보 고치기 — 늘 true")
    editRemark: bool = Field(description="특이사항 고치기 — 늘 true")
    confirmIdentity: bool = Field(description="[신분 확인] — identity.status 가 unconfirmed")
    unconfirmIdentity: bool = Field(description="[미확인으로] — confirmed 이고, 그 고객의 오늘 예약 중 접수 뒤 단계가 없음")
    addConsultation: bool = Field(description="[+ 상담 추가] — KOS 단계 PROCEDURE_WAITING · PROCEDURE · PROCEDURE_DONE 이고 취소 "
        "· 부도 아님")


class DisplayItem(BaseModel):
    """그 예약의 오늘 띄우기 요청(문진 · 스캔)."""

    id: int = Field(description="띄우기 요청 id")
    kind: Literal["questionnaire", "scan"] = Field(description="`questionnaire` = 고객 문진 · `scan` = 여권 스캔")
    status: Literal["pending", "opened", "done", "canceled", "expired"] = Field(description=(
        "`pending` = 보냄(아직 안 엶) · `opened` = 열림 · `done` = 끝 · `canceled` = 닫음/새 요청으로 대체 · `expired` = 시간 "
            "지남"))
    deviceName: str | None = Field(description="받는 기기 이름. 기기가 없거나 못 찾으면 null")
    createdAt: str = Field(description=f"요청 시각({_ISO})")
    # 문진 = 고객이 처음 연 때(SPEC-006 §6.6)
    openedAt: str | None = Field(None, description=f"처음 열린 시각({_ISO} · 문진 = 고객이 처음 연 때). 아직이면 null")
    closedAt: str | None = Field(description=f"닫힌 시각({_ISO}). 아직이면 null")
    qrUrl: str | None = Field(None, description=(
        # 문진 종류 · pending 일 때만 — 데스크 새로고침 때 QR 다시 그리기
        "문진 QR URL — 문진 종류이고 pending 일 때만(데스크 새로고침 때 QR 다시 그리기). 그 밖은 null"))


class ReservationDetail(BaseModel):
    """예약 상세(§7.3)."""

    reservationId: int = Field(description="ccc 예약 id")
    day: str = Field(description="예약 날짜 `YYYY-MM-DD`(KST · 사본에 날짜가 없으면 오늘)")
    start: str | None = Field(description=f"첫 묶음 시작({_ISO}). 묶음이 없으면 null")
    end: str | None = Field(description=f"묶음들 중 가장 늦은 끝({_ISO}). 묶음이 없으면 null")
    groupTitle: str | None = Field(description="첫 묶음의 예약 그룹 이름. 모르면 null")
    zoneId: int | None = Field(description="예약 구역 ccc id. 사본에 없으면 null")
    zoneTitle: str | None = Field(description="예약 구역 이름. 사본에 없으면 null")
    state: State = Field(description="예약 상태")
    customer: DetailCustomer = Field(description="고객")
    reservation: ReservationInfo = Field(description="예약 정보")
    health: Health = Field(description="건강 정보(문진)")
    previousVisits: list[PreviousVisit] = Field(description="이전 방문 — 그 예약 날짜(KST)와 같은 날은 뺌 · 최신 순. KOS 읽기 "
        "실패면 []")
    flow: Flow | None = Field(description="내원 현황. 주 상태가 reserved · canceled · noshow 면 null")
    settlement: Settlement | None = Field(description="정산. 주 상태 home 일 때만 · 아니면 null")
    rooms: list[RoomItem] = Field(description="그 예약 구역의 방(order → 이름 → id 순). receiveMode 가 null 이면 []")
    roomLocked: bool = Field(description="이어 하기이고 「방 배정」 작업에 이미 방이 붙었으면 true(그 방만 selected)")
    receiveMode: Literal["new", "resume"] | None = Field(description=(
        "[접수 완료] 갈래 — `new` = 새 접수(주 상태 reserved · noshow) · `resume` = 이어 하기(reception) · "
        "null = 접수 대상 아님"))
    counselors: list[CounselorItem] = Field(description="상담사 목록(이름 순). 상담 카드(flow.consultation)가 없으면 []")
    can: Can = Field(description="버튼 켜짐")
    # 띄우기 요청(SPEC-004 §5-3 · 오늘 그 예약 것)
    displays: list[DisplayItem] = Field([], description="그 예약의 오늘(KST) 띄우기 요청 — id 순")
    funnelCodes: list["FunnelItem"] = Field([], description=(
        # 유입 채널 드롭다운 — 예약 등록과 같은 FUNNEL 코드(닫힌 것 빼고)
        "유입 채널 드롭다운 — 닫히지 않은 KOS FUNNEL 코드(order → id 순)"))



# ------------------------------------------------------------------ §7.4 등록 모달 · 고객 검색
class StaffItem(BaseModel):
    """직원 한 명."""

    staffId: int = Field(description="ccc 직원 id")
    name: str = Field(description="직원 이름")


class FunnelItem(BaseModel):
    """유입 코드 한 개(KOS FUNNEL 코드 사본)."""

    funnelId: int = Field(description="ccc 유입 코드 id(요청의 `funnelId`)")
    name: str = Field(description="유입 코드 이름")


class FormZone(BaseModel):
    """등록 때 고를 구역."""

    zoneId: int = Field(description="ccc 구역 id")
    title: str = Field(description="구역 이름")
    available: bool = Field(description=(
        "고를 수 있는지 — groupId 가 없으면 늘 true · 있으면 그 그룹에서 켜진 구역이고, "
        "start 도 있으면 그 줄 슬롯이 꽉 차지 않음"))


class ReservationForm(BaseModel):
    """예약 등록 모달 목록(§7.4)."""

    staff: list[StaffItem] = Field(description="담당자 후보 — 활성 직원(env `KOS_EXCLUDE_ACCOUNT_IDS` 제외) · 이름 → id 순")
    defaultAssigneeStaffId: int | None = Field(description="기본 담당자 = KOS 시스템 계정(internal 토큰 계정)의 ccc 직원 id. 못 "
        "찾으면 null")
    counselors: list[StaffItem] = Field(description="상담사 후보 — 역할 태그 COUNSELOR · 활성 · 시스템 계정 · 제외 목록 뺌 · "
        "이름 순")
    funnels: list[FunnelItem] = Field(description="유입 코드 — 닫히지 않은 것 · order → id 순")
    zones: list[FormZone] = Field(description="구역(지금 KOS 목록에 있는 것) — order → id 순")
    defaultZoneId: int | None = Field(description="기본 구역 — env `KOS_ZONE_ID` 구역이 available 이면 그것 · 아니면 첫 "
        "available 구역 · 없으면 null")
    # KOS snsInfo.snsType enum 그대로 — 표시 글자는 front
    snsTypes: list[str] = Field(description="SNS 종류 값(KOS snsInfo.snsType enum) — 표시 글자는 front 가 붙인다")


class SearchItem(BaseModel):
    """고객 검색 결과 한 명(KOS get-visitors · ccc 사본에 넣은 뒤)."""

    customerId: int = Field(description="ccc 고객 id(KOS 고객을 사본에 넣은 행)")
    chartNumber: str | None = Field(description="KOS 차트 번호. 없으면 null")
    name: str = Field(description="이름. 없으면 빈 문자열")
    phoneticName: str | None = Field(description="발음 이름. 없으면 null")
    dateOfBirth: str | None = Field(description="생년월일 `YYYY-MM-DD`(KOS 값 앞 10자). 없으면 null")
    nationality: str | None = Field(description="국적 — KOS 값 그대로. 없으면 null")
    isNew: bool = Field(description="KOS `isNew` 값 그대로")


class CustomerSearch(BaseModel):
    """고객 검색 한 페이지."""

    items: list[SearchItem] = Field(description="검색 결과 — KOS 최근 방문 시각(lastVisitedDateTimeUtc) 내림차순 · 최대 20명")
    total: int = Field(description="전체 결과 수(KOS `count`). KOS 가 주지 않으면 이 페이지 items 수")
    page: int = Field(description="요청한 페이지(1부터)")
    pageSize: int = Field(description="페이지 크기 — 늘 20")


# ------------------------------------------------------------------ §7.5 조작 요청 · 응답
class PhoneIn(_Req):
    """새 고객 전화번호(둘 다 필수)."""

    countryCode: str = Field(description="국가 번호 — KOS `countryCode` 로 그대로 보낸다")
    number: str = Field(description="번호 — KOS `phoneNumber` 로 그대로 보낸다")


SNS_TYPES = ("etc", "kakaotalk", "line", "instagram", "whatsapp", "wechat")  # KOS snsInfo.snsType
SnsType = Literal["etc", "kakaotalk", "line", "instagram", "whatsapp", "wechat"]


class SnsIn(_Req):
    """새 고객 SNS."""

    type: SnsType = Field(description="SNS 종류(KOS snsType enum) — 이 6개 밖이면 400")
    accountId: str = Field(description="SNS 계정 id")


class NewCustomer(_Req):
    """새 고객 — 이름 + (전화 · SNS · 이메일 · 여권번호 · 생년월일 중 하나 이상) 이 있어야 한다(없으면 409 not_identifiable)."""

    name: str = Field(description="이름(필수 · 앞뒤 공백을 지워 보낸다 · 비면 409 not_identifiable)")
    phoneticName: str | None = Field(None, description="발음 이름. 비면 보내지 않는다")
    gender: str | None = Field(None, description="성별 — KOS 값으로 그대로 보낸다. 비면 보내지 않는다")
    dateOfBirth: str | None = Field(None, description="생년월일 `YYYY-MM-DD` — `date.fromisoformat` 이 못 읽으면 400"
        "(`20240101` 같은 꼴도 통과 · KOS 에는 `YYYY-MM-DD` 로 바꿔 보냄) · 비면 보내지 않는다")  # yyyy-MM-dd
    nationality: str | None = Field(None, description="국적 — KOS 값으로 그대로 보낸다. 비면 보내지 않는다")
    phone: PhoneIn | None = Field(None, description="전화번호. 국가 번호 · 번호 둘 다 있어야 구분 정보로 친다")
    email: str | None = Field(None, description="이메일")
    sns: SnsIn | None = Field(None, description="SNS. 종류 · 계정 id 둘 다 있어야 구분 정보로 친다")
    passportNumber: str | None = Field(None, description="여권 번호")


class ExistingCustomerRef(_Req):
    """이미 있는 고객 고르기."""

    customerId: StrictInt = Field(description="ccc 고객 id(고객 검색 결과). 사본에 없으면 404")


class NewCustomerRef(_Req):
    """새 고객 만들기 — KOS 중복 검사 뒤 KOS 에 고객을 만든다."""

    new: NewCustomer = Field(description="새 고객 정보")


class CreateReservationRequest(_Req):
    """예약 등록 요청. 모르는 키를 보내면 400."""

    groupId: StrictInt = Field(description="ccc 예약 그룹 id(칸). 없으면 400")
    zoneId: StrictInt | None = Field(None, description=(
        "ccc 구역 id. 그 그룹에서 꺼진 구역이면 400. 생략 = env `KOS_ZONE_ID` 구역(켜짐 · 자리 있음) → 구역 order 순 첫 자리 "
            "있는 구역 → "
        "첫 켜진 구역"))  # 생략 = §5.5 기본 구역
    start: str = Field(description=(
        "시작 시각 ISO-8601(오프셋 없으면 KST 로 본다). 끝 = 시작 + 그룹 간격. 날짜 = 이 시각의 KST 날짜. 형식이 틀리면 400"))
    customer: ExistingCustomerRef | NewCustomerRef = Field(description="`{customerId}`(기존 고객) 또는 `{new: {...}}`(새 고객) "
        "중 하나")
    assigneeStaffId: StrictInt | None = Field(None, description="담당자 ccc 직원 id. 없는 직원이면 400. 생략 = KOS 시스템 계정")
    counselorStaffId: StrictInt | None = Field(None, description="상담사 ccc 직원 id — 상담사 목록에 없으면 400. 생략 = 보내지 "
        "않음")
    funnelId: StrictInt | None = Field(None, description="유입 코드 ccc id — 없거나 닫힌 코드면 400. 생략 = 보내지 않음")
    funnelDetail: str | None = Field(None, description="유입 상세 글 — funnelId 가 있을 때만 쓰인다")
    memo: str | None = Field(None, description="예약 메모. 비면 보내지 않는다")
    desiredDischargeTime: str | None = Field(None, description="희망 귀가 시각 `HH:MM`(예약 날짜 KST 00:00 + 시×60+분). "
        "`정수:정수` 꼴이 아니면 400 — 범위 검사는 없다(`25:99` · `9:5` 도 통과) · 비면 보내지 않는다")  # "HH:MM"


class CreateReservationResponse(BaseModel):
    """예약 등록 결과."""

    reservationId: int = Field(description="만든 예약의 ccc id")
    customerId: int = Field(description="예약 고객 ccc id(새 고객이면 새로 만든 행)")


class MoveRequest(_Req):
    """예약 묶음 이동 요청(같은 날짜 안 · 구역은 그대로 · 길이 그대로)."""

    resourceIndex: StrictInt = Field(description="옮길 묶음 순번(카드 `resourceIndex`). 범위 밖이면 400")
    groupId: StrictInt = Field(description="옮겨 갈 ccc 예약 그룹 id. 없으면 400")
    start: str = Field(description=(
        "새 시작 ISO-8601(오프셋 없으면 KST). 원래 묶음과 같은 KST 날짜 · 그 칸 간격 경계(초 0)여야 한다(아니면 400)"))


class CancelRequest(_Req):
    """예약 취소 요청."""

    reason: Literal["CANCELED", "NO_SHOW"] = Field(description="KOS 취소 사유 — `CANCELED` = 취소 · `NO_SHOW` = 부도")


class MemoRequest(_Req):
    """예약 메모 저장 요청."""

    memo: str = Field(description="예약 메모 전체(빈 문자열 = 비움). 지금 값과 같으면 KOS 를 부르지 않는다")


NOTICE_MAX = 2000  # trim 길이 상한(§5.15 · Q-142)


class NoticeRequest(_Req):
    """§7.5 `PUT /api/reservations/notice` — `noticeId` = 화면이 고친 ccc 행 id(기록용 · Q-143)."""

    date: str = Field(description="공지 날짜 `YYYY-MM-DD`(KST). 비거나 꼴이 틀리면 400 · 오늘보다 앞이면 409 notice_past_date")
    noticeId: StrictInt | None = Field(None, description=(
        "화면이 보여 준 ccc 공지 행 id. KOS 에서 다시 읽은 그 날 공지에 있으면 그것을 저장 대상으로 · 없거나 null 이면 KOS 응답 "
            "첫 공지"))
    content: str = Field(description=(
        "공지 글. 앞뒤 공백을 뺀 길이 ≤ 2000(넘으면 400). 빈 값(공백만 포함) = 그 날 공지 지우기 · 고치기는 공백을 지우지 않은 "
            "값을, "
        "새로 쓰기는 지운 값을 보낸다"))


class NoticeResponse(BaseModel):
    """공지 저장 결과."""

    ok: Literal[True] = Field(True, description="늘 true")
    # 지웠거나 빈 날 = null
    notice: Notice | None = Field(description="저장 뒤 다시 읽은 공지. 지웠거나 · 그 날 공지가 없고 빈 값을 보냈거나 · "
        "저장 뒤 다시 읽은 사본에서 그 공지를 못 찾았으면 null")


class ReceptionRequest(_Req):
    """[접수 완료] 요청."""

    roomId: StrictInt = Field(description="ccc 방 id(상세 `rooms[]`). 방이 이미 붙었으면 그 방이어야 한다")
    route: Literal["consultation", "direct"] = Field("consultation", description=(
        # 진행 경로 — ccc 값(KOS consultationRequired 아님 · 10-27)
        "진행 경로 — `consultation`(기본) = 끝 단계 상담 대기(CONSULTATION_WAITING) · `direct` = 끝 단계 시술 "
            "대기(PROCEDURE_WAITING)"))


class ReceptionResponse(BaseModel):
    """[접수 완료] 결과."""

    ok: Literal[True] = Field(True, description="늘 true")
    flowStep: str | None = Field(description=(
        "KOS 단계 — 보낸 끝 단계(CONSULTATION_WAITING · PROCEDURE_WAITING). KOS 가 이미 끝 단계 이후였으면 그 지금 단계"
        "(보내지 않음). 코드상 null 은 오지 않는다"))


class CounselorCallRequest(_Req):
    """[실장 호출] 요청."""

    staffId: StrictInt = Field(description="부를 상담사의 ccc 직원 id(상세 `counselors[]`)")


class AddressIn(_Req):
    """주소 고치기 — null · 빈 값 = 비움."""

    address: str | None = Field(None, description="주소. null = 빈 문자열로 보냄")
    detailed: str | None = Field(None, description="상세 주소(KOS detailedAddress). null = 빈 문자열로 보냄")
    zipCode: str | None = Field(None, description="우편번호. null = 빈 문자열로 보냄")


class PhoneOpt(_Req):
    """전화번호 고치기 — null = 빈 문자열."""

    countryCode: str | None = Field(None, description="국가 번호. null = 빈 문자열로 보냄")
    number: str | None = Field(None, description="번호. null = 빈 문자열로 보냄")


class SnsOpt(_Req):
    """SNS 고치기."""

    type: str | None = Field(None, description=(
        # 보통 SNS_TYPES — '' · null = 없음 · enum 밖 KOS 값은 그대로 통과(r2 W3)
        "SNS 종류 — 보통 `snsTypes` 값. 빈 문자열 · 공백 · null = 없음(빈 문자열로 보냄). enum 밖 값도 그대로 보낸다"))
    accountId: str | None = Field(None, description="SNS 계정 id. null = 빈 문자열로 보냄")

    @field_validator("type", mode="before")
    @classmethod
    def _blank_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class PersonalIn(_Req):
    """§7.3 personal 와 같은 키 — 보낸 키만 바꾼다(`model_fields_set`)."""

    name: str | None = Field(None, description="이름. 보내면 앞뒤 공백을 지워 바꾼다 · null/빈 값 = 비움")
    phoneticName: str | None = Field(None, description="발음 이름. null/빈 값 = 비움")
    gender: str | None = Field(None, description="성별 — KOS 값. null/빈 값 = 비움")
    dateOfBirth: str | None = Field(None, description="생년월일 `YYYY-MM-DD` — `date.fromisoformat` 이 못 읽으면 400"
        "(`20240101` 같은 꼴도 통과 · KOS 에는 `YYYY-MM-DD` 로 바꿔 보냄) · null/빈 값 = 비움")
    registrationNumber: str | None = Field(None, description="주민등록번호. null/빈 값 = 비움")
    passportNumber: str | None = Field(None, description="여권 번호. null/빈 값 = 비움")
    passportSurname: str | None = Field(None, description="여권 성(영문). null/빈 값 = 비움")
    passportGivenNames: str | None = Field(None, description="여권 이름(영문). null/빈 값 = 비움")
    passportExpiryDate: str | None = Field(None, description="여권 만료일 `YYYY-MM-DD` — `date.fromisoformat` 이 못 읽으면 "
        "400(`20240101` 같은 꼴도 통과 · KOS 에는 `YYYY-MM-DD` 로 바꿔 보냄) · null/빈 값 = 비움")
    foreignRegistrationNumber: str | None = Field(None, description="외국인 등록번호. null/빈 값 = 비움")
    nationality: str | None = Field(None, description="국적 — KOS 값. null/빈 값 = 비움")
    language: str | None = Field(None, description="언어 — KOS 값. null/빈 값 = 비움")
    phone: PhoneOpt | None = Field(None, description="전화번호. null 을 보내면 바꾸지 않는다")
    additionalPhone: PhoneOpt | None = Field(None, description="추가 전화번호. null 을 보내면 바꾸지 않는다")
    email: str | None = Field(None, description="이메일. null/빈 값 = 비움")
    sns: SnsOpt | None = Field(None, description="SNS. null 을 보내면 바꾸지 않는다")
    address: AddressIn | None = Field(None, description="주소. null 을 보내면 바꾸지 않는다")


class PersonalRequest(_Req):
    """고객 개인 정보 고치기 요청."""

    personal: PersonalIn = Field(description="바꿀 키만 담은 개인 정보")


class RemarkRequest(_Req):
    """고객 특이사항 저장 요청."""

    memo: str = Field(description="특이사항 전체(KOS 고객 memo · 빈 문자열 = 비움). 지금 값과 같으면 KOS 를 부르지 않는다")


class FunnelRequest(_Req):
    """KOS 고객 유입 채널(E2E batch 3 #2) — funnelId = ccc funnel_code id(null = 비움) · funnelDetail 은 보낼 때만 고침."""

    funnelId: StrictInt | None = Field(description="ccc 유입 코드 id(필수 키 · null = 비움). 없거나 닫힌 코드면 400")
    funnelDetail: str | None = Field(None, description="유입 상세 글. 키를 보내면 앞뒤 공백을 지워 바꾼다(null = 비움) · 안 "
        "보내면 지금 값 그대로")


class IdentityRequest(_Req):
    """신분 확인 표시 요청."""

    status: Literal["confirmed", "unconfirmed"] = Field(description="`confirmed` = 신분 확인함 · `unconfirmed` = 미확인으로 "
        "되돌림")


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

DetailCustomer.model_rebuild()
ReservationDetail.model_rebuild()
