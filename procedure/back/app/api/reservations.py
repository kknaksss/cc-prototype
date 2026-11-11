"""예약 현황 API(SPEC-005 §7) — HTTP 만. 규칙 · KOS 호출은 service 가 한다.

GET 넷(§7.2 ~ §7.4)은 `PROC_FAKE_BOARD` 면 지어낸 값 · 조작(§7.5)은 `require_real_board`(403 fake_board).
10-27 E2E: PUT route 없앰(진행 경로 = 접수 본문 route) · POST consultation-add 넣음 · 0.4.0 PUT notice(D-61).
역할은 네 개 모두 ○(§7.1 · D-30) — 로그인만 본다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import Actor, Ctr, require_real_board
from app.api.docs import FAKE_BOARD, INVALID, KOS_REJECTED, KOS_UNAVAILABLE, T_CUSTOMER, T_RESV, UNAUTHORIZED, errors
from app.schemas.actions import OkResponse
from app.schemas.reservations import (
    CancelRequest,
    CounselorCallRequest,
    CreateReservationRequest,
    CreateReservationResponse,
    CustomerSearch,
    FunnelRequest,
    IdentityRequest,
    MemoRequest,
    MoveRequest,
    NoticeRequest,
    NoticeResponse,
    PersonalRequest,
    ReceptionRequest,
    ReceptionResponse,
    RemarkRequest,
    ReservationBoard,
    ReservationDetail,
    ReservationForm,
)
from app.service import fake_reservations as fake

router = APIRouter(prefix="/api")  # 태그는 route 마다(예약 · 고객 두 가지)
write = [Depends(require_real_board)]

# ------------------------------------------------------------------ 문서 공통 글
WHO = "**호출 가능**: 로그인한 모든 계정(admin · doctor · nurse · coordinator · counselor) — 역할 검사 없음."
FAKE_GET = ("**가짜 모드**: 서버 env `PROC_FAKE_BOARD` 가 켜져 있으면 KOS · DB 를 보지 않고 지어낸 고정 값"
            "(`app/service/fake_reservations.py` — 「고객 A」 꼴 이름 · 작은 가짜 금액)을 돌려준다.")
WRITE_COMMON = ("**공통**: 조작은 KOS 에 동기로 쓴다(성공 응답 = KOS 200 뒤). "
                "KOS 호출 자체가 실패하면 event_log 에 `kos_rejected` 1줄을 남기고 409 `kos_rejected`(KOS 4xx · 401 제외) 또는 "
                "502 `kos_unavailable`(네트워크 · 5xx · 401)을 준다. 서버에 KOS 설정이 없을 때 · KOS 응답 모양이 틀릴 때 "
                "나는 502 `kos_unavailable` 은 KOS 호출 밖에서 나므로 event_log 를 남기지 않는다. "
                "서버 env `PROC_FAKE_BOARD` 가 켜져 있으면 403 `fake_board`.")
NOT_FOUND_RESV = (404, "not_found", "없는 예약 id(ccc 사본에 없음)")
NOT_FOUND_CUST = (404, "not_found", "없는 고객 id(ccc 사본에 없음)")
RESV_ID = Path(description="ccc 예약 id(스케줄 표 `cards[].reservationId`)")
CUST_ID = Path(description="ccc 고객 id(`customer.customerId` · 고객 검색 `items[].customerId`)")
ResvId = Annotated[int, RESV_ID]
CustId = Annotated[int, CUST_ID]


# ------------------------------------------------------------------ 조회(§7.2 ~ §7.4) — /board · /form 이 /{id} 보다 먼저
@router.get(
    "/reservations/board", response_model=ReservationBoard, tags=[T_RESV],
    summary="예약 스케줄 표(하루)",
    description=f"""그 날짜의 예약 스케줄 표 — 칸(예약 그룹) · 구역 · 카드(예약 묶음) · 정원 · [+] 줄 · 상태별 수 · 공지 ·
원내 현황(오늘만).

{WHO}

**동작**: 그 날짜 사본이 낡았으면(env `KOS_RESV_CACHE_SEC` 캐시) 먼저 KOS 에서 하루 예약 → 정원 → 공지 → (오늘이면) 수납 금액을
다시 읽어 ccc 사본(DB)에 덮어쓴다. KOS 읽기가 실패해도 오류를 주지 않고 사본으로 응답하며, 실패 내용은 `sync.lastError` 에 싣는다.
서버에 KOS 설정이 없으면 사본만 쓴다(`sync.lastError` = `KOS 설정이 비어 있어요`).

**부작용**: KOS 쓰기 없음 · SSE 없음 · event_log 없음. DB 사본(예약 · 고객 · 슬롯 · 공지 · 조회 상태) 갱신만.

{FAKE_GET} 가짜 값은 날짜와 상관없이 같은 예약을 그 날짜에 놓는다.""",
    responses=errors(UNAUTHORIZED, (400, "invalid_request", "`date` 가 `YYYY-MM-DD`(10자) 꼴이 아닐 때")),
)
async def board(c: Ctr, _: Actor, date: Annotated[str | None, Query(
        description="보는 날짜 `YYYY-MM-DD`(KST). 생략 · 빈 값 = 오늘(KST)")] = None) -> ReservationBoard:
    if c.settings.proc_fake_board:
        return fake.board(c.clock.now(), date)
    return await c.resv.board(date)


@router.get(
    "/reservations/form", response_model=ReservationForm, tags=[T_RESV],
    summary="예약 등록 모달 목록",
    description=f"""예약 등록 모달에 필요한 목록 — 담당자 · 상담사 · 유입 코드 · 구역(고를 수 있는지) · 기본값 · SNS 종류.

{WHO}

- `groupId` 를 주면 `zones[].available` = 그 그룹에서 켜진 구역인지. `groupId` 와 `start` 를 같이 주면 그 줄 정원이 찼는지도 본다
  (이때만 `date` 날짜(생략 = 오늘) 사본을 KOS 에서 다시 읽는다 — 실패해도 오류 없이 사본으로).
- `date` 는 형식 검사와 위 다시 읽기 날짜에만 쓰인다. 정원 판정은 `start` 의 KST 날짜 사본으로 하므로, `date` 와 `start` 의 날짜가
  다르면 `start` 날짜는 다시 읽지 않은 사본(낡았을 수 있음)으로 판정한다.

**부작용**: KOS 쓰기 없음 · SSE 없음 · event_log 없음.

{FAKE_GET} 가짜 모드에서는 없는 `groupId` 도 400 이 아니다(구역 모두 available).""",
    responses=errors(UNAUTHORIZED, INVALID,
                     (400, "invalid_request", "`date` 가 `YYYY-MM-DD` 꼴이 아님 · `groupId` 가 없는 예약 그룹 · "
                                              "`groupId` 와 같이 준 `start` 가 ISO 시각이 아님")),
)
async def form(c: Ctr, _: Actor,
               date: Annotated[str | None, Query(description="날짜 `YYYY-MM-DD`(KST) — 형식 검사 · groupId+start 때 다시 읽을 "
                                                     "날짜. 생략 = 오늘")] = None,
               groupId: Annotated[int | None, Query(  # noqa: N803 — 계약 이름
                   description="ccc 예약 그룹 id — 주면 그 그룹에서 켜진 구역만 available")] = None,
               start: Annotated[str | None, Query(
                   description="줄 시작 ISO-8601(오프셋 없으면 KST) — groupId 와 같이 주면 "
                               "그 줄 정원이 찬 구역은 available=false")] = None,
               ) -> ReservationForm:
    if c.settings.proc_fake_board:
        return fake.form(c.clock.now(), date, groupId, start)
    return await c.resv.form(date, groupId, start)


@router.get(
    "/reservations/{reservation_id}", response_model=ReservationDetail, tags=[T_RESV],
    summary="예약 상세",
    description=f"""예약 하나의 상세 — 고객(KOS 개인 정보 · 신분 확인 · 특이사항 · 유입 채널) · 예약 정보 · 건강 정보(문진) ·
이전 방문 · 내원 현황 · 정산 · 고를 방 · 상담사 · 버튼 켜짐(`can`) · 띄우기 요청.

{WHO}

**동작**:
1. 오늘 · 그 예약 날짜 사본이 낡았으면 KOS 에서 다시 읽는다(실패해도 오류 없음).
2. KOS 설정이 있으면 그 일정 하나를 캐시 없이 KOS 에서 바로 다시 읽어 사본에 덮어쓴다 — KOS 가 404 면 404 `reservation_gone`
   (사본은 지우지 않는다). 그 밖의 실패는 무시하고 사본으로.
3. KOS 고객 · 문진 양식 · 문진 제출본 · 이전 일정(· 귀가면 수납 요약)을 동시에 읽는다. 하나가 실패해도 응답은 오고 그 칸만
   비거나(`personal` = null · `personalError`) `health.state` = `error` 가 된다.

**부작용**: KOS 쓰기 없음 · SSE 없음 · event_log 없음. DB 사본 갱신 · KOS 문진 제출본의 제출 시각이 마지막으로 저장한 문진 이력의
시각과 다르면 문진 이력 1줄 추가(ccc 고객 웹 제출본을 보일 때는 추가 안 함) · 기한 지난 띄우기 요청을 `expired` 로 바꿈.

{FAKE_GET} 가짜 모드는 예약 id 1 ~ 17 만 있고(그 밖 404) `displays` · `funnelCodes` 는 [] 다.""",
    responses=errors(UNAUTHORIZED, INVALID, NOT_FOUND_RESV,
                     (404, "reservation_gone", "그 일정을 KOS 에서 다시 읽었더니 KOS 가 404(KOS 에서 지워진 예약)")),
)
async def detail(reservation_id: ResvId, c: Ctr, _: Actor) -> ReservationDetail:
    if c.settings.proc_fake_board:
        return fake.detail(c.clock.now(), reservation_id)
    return await c.resv.detail(reservation_id)


@router.get(
    "/customers/search", response_model=CustomerSearch, tags=[T_CUSTOMER],
    summary="고객 검색(KOS)",
    description=f"""KOS 고객 검색(내부 get-visitors) — 한 페이지 20명 · KOS 최근 방문 순. 조건을 모두 비우면
최근 방문 순 전체 목록.

{WHO}

- 각 조건은 앞뒤 공백을 지우고 비면 조건 없음. 조건 뜻(부분 일치 등)은 KOS 가 정한다.
- 결과 고객은 ccc 고객 사본에 넣고(있으면 덮어씀) 그 ccc id 를 `customerId` 로 준다.
- KOS 실패는 4xx 도 모두 502 `kos_unavailable`(이 경로는 `kos_rejected` 를 주지 않는다).

**부작용**: KOS 쓰기 없음 · SSE 없음 · event_log 없음. DB 고객 사본 갱신.

{FAKE_GET} 가짜 모드는 이름(부분 · 대소문자 무시) · 차트 · 생년월일(같음)만 거르고 `phone` 은 무시하며
`birth` 꼴 검사도 하지 않는다.""",
    responses=errors(UNAUTHORIZED, INVALID,
                     (400, "invalid_request", "`page` < 1 · `birth` 를 Python `date.fromisoformat` 이 못 읽음"
                                              "(`YYYY-MM-DD` 외에 `20240101` 같은 꼴도 통과)"),
                     (502, "kos_unavailable", "서버에 KOS 설정이 없음 · KOS 검색 호출이 실패(어떤 오류든)")),
)
async def search(c: Ctr, _: Actor,
                 name: Annotated[str | None, Query(description="고객 이름 조건(KOS visitorName)")] = None,
                 phone: Annotated[str | None, Query(description="전화번호 조건(KOS phoneNumber)")] = None,
                 birth: Annotated[str | None, Query(description="생년월일 조건 `YYYY-MM-DD` — `date.fromisoformat` "
                                                       "으로 검사만 하고 받은 글자 그대로 KOS 에 보낸다"
                                                       "(`20240101` 같은 꼴도 통과)")] = None,
                 chart: Annotated[str | None, Query(description="차트 번호 조건(KOS chartNumber)")] = None,
                 page: Annotated[int, Query(description="페이지(1부터 · 한 페이지 20명)")] = 1) -> CustomerSearch:
    if c.settings.proc_fake_board:
        return fake.search(name, phone, birth, chart, page)
    return await c.resv.search(name, phone, birth, chart, page)


# ------------------------------------------------------------------ 조작(§7.5)
@router.post(
    "/reservations", response_model=CreateReservationResponse, dependencies=write, tags=[T_RESV],
    summary="예약 등록",
    description=f"""새 예약을 KOS 에 만든다(내부 reserve). 고객은 기존 고객(`{{customerId}}`) 또는 새 고객(`{{new: {{...}}}}`).

**주의**: 502 `kos_unavailable` 중 「KOS 응답에 일정 id 가 없음」 · 「KOS 응답에 고객 id 가 없음」은 KOS reserve ·
create-visitor 쓰기가 **이미 된 뒤** 응답 모양 검사에서 난다. 이 502 를 받고 그대로 다시 보내면 KOS 에 예약 · 고객이 중복될 수
있으니, 먼저 스케줄 표 · 고객 검색으로 이미 만들어졌는지 확인한다.

{WHO}

**검사 순서**: 400(형식 · 그룹 · 구역 · 유입 · 담당자 · 상담사 · 희망 귀가 · 생년월일) → 404(기존 고객 없음) →
409 `not_identifiable`(새 고객) → 409 `slot_full`(사본 정원) → KOS 호출.

**KOS 호출**:
- 새 고객: find-duplicated-visitor → 같은 고객이 있으면 그 고객을 ccc 사본에 넣고 409 `duplicated_visitor` + `candidate`
  (KOS 고객은 만들지 않음). 없으면 create-visitor 로 KOS 고객을 만들고 ccc 사본에 넣는다.
- reserve(끝 = 시작 + 그룹 간격 · 의사 없음 · 담당자 기본 = 시스템 계정 · 상담사 · 메모 · 희망 귀가 · 유입은 줄 때만) →
  그 일정을 KOS 에서 다시 읽어 사본에 넣는다(다시 읽기가 실패하면 최소 행만 만든다).

**부작용**: event_log `resv_create` 1줄 · 그 날짜 캐시 비움(다음 조회가 KOS 를 다시 읽음). SSE 없음.
새 고객을 만든 뒤 reserve 가 실패해도 KOS 고객은 남는다(되돌리지 않음).

**멱등 아님**: 다시 보내면 예약이 하나 더 생긴다(위 **주의**의 502 뒤 재시도도 같다).

{WRITE_COMMON}""",
    responses=errors(
        UNAUTHORIZED, FAKE_BOARD, INVALID,
        (400, "invalid_request", "`start` 가 ISO 시각이 아님 · 없는 `groupId` · 그 그룹에 켜진 구역 없음 · "
                                 "`zoneId` 가 그 그룹에서 꺼짐 · "
                                 "없거나 닫힌 `funnelId` · 없는 `assigneeStaffId` · 상담사 목록에 없는 `counselorStaffId` · "
                                 "`desiredDischargeTime` 이 `정수:정수` 꼴이 아님 · 새 고객 `dateOfBirth` 를 "
                                 "`date.fromisoformat` 이 못 읽음 · 모르는 키"),
        (404, "not_found", "기존 고객 `customerId` 가 ccc 사본에 없음"),
        (409, "not_identifiable", "새 고객에 이름 + (전화(국가번호+번호) · SNS(종류+id) · 이메일 · "
                                  "여권번호 · 생년월일 중 하나)가 없음"),
        (409, "slot_full", "고른 구역의 그 시작 시각 슬롯이 사본상 꽉 참"),
        (409, "duplicated_visitor", "KOS 에 같은 고객이 이미 있음 — "
                                    "본문 `error.candidate` 에 그 고객(ccc id · 이름 · 차트 · 생년월일)"),
        KOS_REJECTED,
        (502, "kos_unavailable", "KOS 실패(네트워크 · 5xx · 401) · 서버에 KOS 설정 없음 · "
                                 "KOS 응답에 일정 id 또는 새 고객 id 가 없음 — 이 마지막 둘은 KOS 쓰기가 이미 된 뒤라 "
                                 "재시도하면 중복될 수 있음(먼저 조회로 확인)"),
    ),
)
async def create(body: CreateReservationRequest, c: Ctr, actor: Actor) -> CreateReservationResponse:
    return await c.resv.create(actor, body)


@router.put(
    "/reservations/notice", response_model=NoticeResponse, dependencies=write, tags=[T_RESV],
    summary="그 날 공지 저장(고치기 · 새로 쓰기 · 지우기)",
    description=f"""그 날짜 공지 하나를 저장한다. 저장 직전 KOS 에서 그 날 공지를 다시 읽어(캐시 없이) 대상을 정한다.

{WHO}

**대상**: `noticeId` 의 ccc 행이 다시 읽은 목록에 있으면 그것 · 아니면 KOS 응답 첫 공지 · 없으면 대상 없음.
이 KOS get-notices 읽기는 어떤 경우든 먼저 하며, 실패하면 event_log `kos_rejected` 1줄 + 409 `kos_rejected` / 502
`kos_unavailable`.

| 대상 | `content`(앞뒤 공백 뺀 값) | KOS 쓰기 호출 |
|---|---|---|
| 없음 | 빈 값 | 쓰기 호출 없음(읽기만) · `notice_save` 기록 없음 · `notice: null` |
| 없음 | 있음 | create-notice(공백 뺀 값 · 게시 = 그 날 00:00 KST) |
| 있음 | 있음 | change-content(공백을 빼지 않은 원래 값) |
| 있음 | 빈 값 | delete-notice(지우기) → `notice: null` |

**부작용**: event_log `notice_save`(op · 저장 뒤 ccc noticeId · 요청 noticeId · 길이) · 그 날짜 캐시 비우고 KOS 에서 다시 읽음.
SSE 없음. 저장 뒤 다시 읽은 사본에서 그 공지를 못 찾으면(다시 읽기 실패 등) 저장은 됐어도 `notice: null`.

**반복**: 같은 글로 다시 보내면 다시 change-content 를 보낸다(같은 값 비교 없음).

{WRITE_COMMON}""",
    responses=errors(
        UNAUTHORIZED, FAKE_BOARD, INVALID,
        (400, "invalid_request", "`date` 가 비었거나 `YYYY-MM-DD` 꼴이 아님 · `content` 앞뒤 공백 뺀 길이 > 2000 · 모르는 키"),
        (409, "notice_past_date", "`date` 가 오늘(KST)보다 앞"),
        KOS_REJECTED, KOS_UNAVAILABLE,
    ),
)
async def notice(body: NoticeRequest, c: Ctr, actor: Actor) -> NoticeResponse:
    return await c.resv.notice(actor, body)


@router.post(
    "/reservations/{reservation_id}/move", response_model=OkResponse, dependencies=write, tags=[T_RESV],
    summary="예약 묶음 옮기기",
    description=f"""예약 묶음 하나를 다른 칸(그룹) · 시각으로 옮긴다(KOS 내부 update-reservation). 같은 날짜 안 · 구역은 그대로 ·
길이는 원래 묶음 그대로.

{WHO}

- 다른 묶음은 그대로 함께 다시 보낸다.
- 제자리(같은 그룹 · 같은 시작)면 정원 검사를 건너뛰고 그대로 KOS 에 보낸다.

**부작용**: event_log `resv_move`(from · to) · 옛 날짜 · 새 날짜 캐시 비움. SSE 없음.

**반복**: 같은 요청을 다시 보내면 다시 KOS 에 보낸다.

{WRITE_COMMON}""",
    responses=errors(
        UNAUTHORIZED, FAKE_BOARD, INVALID,
        (400, "invalid_request", "`start` 가 ISO 시각이 아님 · `resourceIndex` 범위 밖 · 없는 `groupId` · "
                                 "원래 묶음과 다른 날짜 · 그 칸 간격 경계가 아님 · 그 묶음 구역이 새 그룹에서 꺼짐 · 모르는 키"),
        NOT_FOUND_RESV,
        (409, "slot_full", "옮겨 갈 슬롯이 사본상 꽉 참(제자리면 검사 안 함)"),
        KOS_REJECTED, KOS_UNAVAILABLE,
    ),
)
async def move(reservation_id: ResvId, body: MoveRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.move(actor, reservation_id, body)
    return OkResponse()


@router.post(
    "/reservations/{reservation_id}/cancel", response_model=OkResponse, dependencies=write, tags=[T_RESV],
    summary="예약 취소 · 부도",
    description=f"""접수 전(주 상태 reserved) 예약을 취소 또는 부도로 바꾼다(KOS 공개 cancel-reservation · reason 그대로).

{WHO}

상태 판정은 ccc 사본 기준이다.

**부작용**: event_log `resv_cancel`(reason · 이전 status) · 그 날짜 캐시 비움. SSE 없음.

**반복**: 사본이 다시 읽히기 전이면 다시 KOS 에 보낸다(KOS 가 거절하면 409 `kos_rejected`) · 다시 읽힌 뒤면 409 `not_cancelable`.

{WRITE_COMMON}""",
    responses=errors(UNAUTHORIZED, FAKE_BOARD, INVALID, NOT_FOUND_RESV,
                     (409, "not_cancelable", "주 상태가 reserved 가 아님(접수 뒤 · 이미 취소 · 부도)"),
                     KOS_REJECTED, KOS_UNAVAILABLE),
)
async def cancel(reservation_id: ResvId, body: CancelRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.cancel(actor, reservation_id, body.reason)
    return OkResponse()


@router.put(
    "/reservations/{reservation_id}/memo", response_model=OkResponse, dependencies=write, tags=[T_RESV],
    summary="예약 메모 저장",
    description=f"""예약 메모를 바꾼다(KOS 공개 change-reservation-memo). 빈 문자열 = 비움.

{WHO}

**멱등**: 사본의 지금 메모와 같으면 KOS 를 부르지 않고 바로 `{{ok:true}}`(자동 저장용 · 이때는 KOS 설정이 없어도 성공).

**부작용**: event_log `resv_memo` · 그 날짜 캐시 비움. SSE 없음.

{WRITE_COMMON}""",
    responses=errors(UNAUTHORIZED, FAKE_BOARD, INVALID, NOT_FOUND_RESV,
                     (409, "reservation_closed", "취소된 예약 · KOS 단계 COMPLETED(귀가 완료) 예약(부도는 고칠 수 있음)"),
                     KOS_REJECTED, KOS_UNAVAILABLE),
)
async def memo(reservation_id: ResvId, body: MemoRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.memo(actor, reservation_id, body.memo)
    return OkResponse()


@router.post(
    "/reservations/{reservation_id}/reception", response_model=ReceptionResponse, dependencies=write, tags=[T_RESV],
    summary="[접수 완료] 묶음 실행",
    description=f"""접수 → 「방 배정」 작업 → 방 지정 → 끝 단계를 차례로 KOS 에 보낸다. 지금 KOS 단계 · 작업을 먼저 읽어 남은
단계만 간다(이어 하기).

**주의**: 성공 직후 사본에 끝 단계를 먼저 싣지만, 5초 동안 KOS 의 이전 단계로 되돌리지 않는 것은 **예약 상세 GET 의 단건 다시
읽기뿐**이다. 약 3초 뒤 배경 다시 읽기 · 스케줄 표의 하루 일괄 다시 읽기는 KOS 값으로 덮어쓰므로, KOS 반영이 늦으면 표 · 상세에
이전 단계가 잠깐 다시 보일 수 있다.

{WHO}

**단계**(`step` = 실패 때 오류 본문 `error.step` 값):
0. KOS 일정 다시 읽기(실패 때 `step` 없음). 취소 · 접수 불가 단계면 409. KOS 단계가 이미 끝 단계 이후(상담 대기 ~ 귀가 완료)면
   아무것도 보내지 않고 그 단계를 `flowStep` 으로 성공 응답(반영 지연 · 두 번 누름).
1. `recept` — KOS 단계 RESERVED 면 접수(recept) → 반영될 때까지 0.5초 간격 최대 10번 다시 읽기.
2. `add_task` — 안 취소된 「방 배정」 기타 작업이 없으면 추가(add-flow-tasks) → `read_sequence` — 그 작업이 보일 때까지 다시 읽기.
3. `assign_room` — 그 작업에 방이 없으면 방 지정(change-tasks-room) → 보일 때까지 다시 읽기.
4. `flow_step` — 끝 단계 보내기(내부 change-flow-step): `route=consultation` → CONSULTATION_WAITING · `direct` →
   PROCEDURE_WAITING.

실패하면 거기서 멈추고 되돌리지 않는다 — 다시 누르면 남은 단계부터 이어 간다. 방이 이미 붙어 있으면 그 방만 고를 수 있다.
접수 단계(RESERVED)의 부도(NO_SHOW) 예약도 접수할 수 있다.

**부작용**: event_log `reception`(방 · 끝 단계 · 보낸 단계들 — 1 ~ 4단계 진행 중 실패하고 **이미 보낸 단계가 있으면**
끝 단계 null 로 1줄 · 첫 단계에서 실패하면 행 없음) · 성공하면 사본에 끝 단계를 먼저 싣고
(위 **주의** — 상세 GET 단건 다시 읽기만 5초 지킴) 바로 응답 ·
약 3초 뒤 뒤에서 KOS 일정을 다시 읽고(KOS 값으로 덮음) 그 날짜 캐시를 비우고
시술 현황 조회 1회(바뀌었으면 SSE `board` 발행). 1 ~ 4단계 진행 중 실패(409 · 502)면 그 날짜 캐시를 비운다 — 0단계 읽기 실패 ·
`not_receivable` · `room_task_missing` · `room_locked` · `room_busy` · 400 · 404 때는 비우지 않는다.

{WRITE_COMMON} 이 경로의 409 `kos_rejected` · 409 `kos_slow` · 502 `kos_unavailable` 에는 그 단계 이름 `error.step` 이
실린다(0단계 읽기 · KOS 설정 없음은 제외).""",
    responses=errors(
        UNAUTHORIZED, FAKE_BOARD, INVALID,
        (400, "invalid_request", "방이 아직 안 붙었는데 `roomId` 가 그 예약 구역의 방이 아님 · 모르는 키"),
        NOT_FOUND_RESV,
        (404, "not_found", "없는 방 id(`roomId` 가 ccc 방 사본에 없음)"),
        (409, "not_receivable", "KOS 예약 status 가 CANCELED · KOS 단계가 RESERVED · RECEPTION · 끝 단계 이후 어느 것도 아님"),
        (409, "room_task_missing", "「방 배정」 기타 작업 정의를 찾지 못함"
                                  "(env `KOS_ROOM_TASK_ID` 없음 + 사본에 그 제목의 기타 작업 없음)"),
        (409, "room_locked", "「방 배정」 작업에 이미 다른 방이 붙어 있음 — message 에 그 방 이름"),
        (409, "room_busy", "고른 방이 오늘 같은 구역의 다른 진행 중 예약에 쓰이는 중"),
        (409, "kos_slow", "KOS 반영 대기(0.5초 × 10번) 안에 보낸 단계가 보이지 않음 — `error.step` 있음 · "
                          "잠시 뒤 다시 누르면 이어 간다"),
        (409, "kos_rejected", "KOS 가 4xx(401 제외)로 거절 — 쓰기 단계면 `error.step` 있음"),
        (502, "kos_unavailable", "KOS 네트워크 오류 · 5xx · 401 · 일정 응답 형식이 틀림 · 서버에 KOS 설정 없음 — "
                                 "단계 중이면 `error.step` 있음"),
    ),
)
async def reception(reservation_id: ResvId, body: ReceptionRequest, c: Ctr, actor: Actor) -> ReceptionResponse:
    return ReceptionResponse(flowStep=await c.reception.run(actor, reservation_id, body.roomId, body.route))


@router.post(
    "/reservations/{reservation_id}/counselor-call", response_model=OkResponse, dependencies=write, tags=[T_RESV],
    summary="[실장 호출] 상담사 지정 · 호출",
    description=f"""상담 단계 예약의 담당 상담사를 KOS 에 지정하고(내부 update-reservation counselor) 그 상담사에게 알린다.

{WHO}

상태 판정은 ccc 사본 기준이다(KOS 단계 CONSULTATION_WAITING · CONSULTATION · 취소 · 부도 아님).

**부작용**: event_log `counselor_call` · KOS 200 뒤 그 상담사 직원에 연결된 활성 counselor 계정마다 알림 행 +
SSE `notification`(안 읽은 수) + iOS 푸시(제목 「상담사 호출」 · 본문 「<방> · 상담 대기」, 사본에 방이 없으면 「상담 대기」) ·
그 날짜 캐시 비움.

**멱등 아님**: 누를 때마다 KOS 에 다시 보내고 알림 · 푸시도 다시 간다.

{WRITE_COMMON}""",
    responses=errors(
        UNAUTHORIZED, FAKE_BOARD, INVALID, NOT_FOUND_RESV,
        (404, "not_found", "없는 직원 id(`staffId` 가 ccc 직원 사본에 없음)"),
        (409, "not_consultation", "KOS 단계가 CONSULTATION_WAITING · CONSULTATION 이 아니거나 취소 · 부도"),
        (409, "not_counselor", "그 직원이 상담사 목록(역할 태그 COUNSELOR · 활성 · 시스템 계정 · 제외 목록 아님)에 없음"),
        KOS_REJECTED, KOS_UNAVAILABLE,
    ),
)
async def counselor_call(reservation_id: ResvId, body: CounselorCallRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.reception.counselor_call(actor, reservation_id, body.staffId)
    return OkResponse()


@router.post(
    "/reservations/{reservation_id}/consultation-add", response_model=OkResponse, dependencies=write, tags=[T_RESV],
    summary="[+ 상담 추가] 상담 대기로 되돌리기",
    description=f"""상담 뒤(시술 대기 · 시술 중 · 귀가 대기) 고객을 상담 대기로 되돌린다(KOS 공개 change-flow-step
CONSULTATION_WAITING). 본문 없음.

**주의**: 사본에 CONSULTATION_WAITING 을 먼저 싣지만, 5초 동안 KOS 의 이전 단계로 되돌리지 않는 것은 **예약 상세 GET 의 단건 다시
읽기뿐**이다. 약 3초 뒤 배경 다시 읽기 · 스케줄 표의 하루 일괄 다시 읽기는 KOS 값으로 덮어쓰므로 이전 단계가 잠깐
다시 보일 수 있다.

{WHO}

지금 단계는 KOS 일정을 다시 읽어 정한다. KOS 상담 기록은 만들지 않는다.

**부작용**: event_log `consultation_add`(이전 단계) · 사본에 CONSULTATION_WAITING 을 먼저 싣고
(상세 GET 단건 다시 읽기만 5초 지킴) 바로 응답 · 약 3초 뒤 뒤에서 KOS 일정 다시 읽기(KOS 값으로 덮음) ·
그 날짜 캐시 비움 · 시술 현황 조회 1회(바뀌었으면 SSE `board`).

**반복**: KOS 가 상담 대기를 반영한 뒤 다시 보내면 409 `not_consultation_addable`.

{WRITE_COMMON}""",
    responses=errors(
        UNAUTHORIZED, FAKE_BOARD, INVALID, NOT_FOUND_RESV,
        (409, "not_consultation_addable", "KOS 단계가 PROCEDURE_WAITING · PROCEDURE · PROCEDURE_DONE 이 아니거나 취소 · 부도"),
        KOS_REJECTED,
        (502, "kos_unavailable", "KOS 네트워크 오류 · 5xx · 401 · 일정 응답 형식이 틀림 · 서버에 KOS 설정 없음"),
    ),
)
async def consultation_add(reservation_id: ResvId, c: Ctr, actor: Actor) -> OkResponse:
    await c.reception.consultation_add(actor, reservation_id)
    return OkResponse()


@router.post(
    "/reservations/{reservation_id}/discharge", response_model=OkResponse, dependencies=write, tags=[T_RESV],
    summary="[귀가 완료]",
    description=f"""귀가 대기(KOS 단계 PROCEDURE_DONE) 예약을 귀가 완료로 바꾼다(KOS 공개 change-flow-step COMPLETED). 본문 없음.

{WHO}

상태 · 수납 필요 판정은 ccc 사본 기준이다. 수납 필요가 1 이상이면 보내지 않는다.

**부작용**: event_log `discharge` · 그 날짜 캐시 비움 · 응답 전에 시술 현황 조회 1회(바뀌었으면 SSE `board` · 실패해도 성공 응답).

**반복**: 사본이 다시 읽히기 전이면 다시 KOS 에 보낸다 · 다시 읽힌 뒤면 409 `not_home_waiting`.

{WRITE_COMMON}""",
    responses=errors(
        UNAUTHORIZED, FAKE_BOARD, INVALID, NOT_FOUND_RESV,
        (409, "not_home_waiting", "KOS 단계가 PROCEDURE_DONE 이 아니거나 취소 · 부도"),
        (409, "payment_required", "수납 필요 작업이 1개 이상 남아 있음"),
        KOS_REJECTED, KOS_UNAVAILABLE,
    ),
)
async def discharge(reservation_id: ResvId, c: Ctr, actor: Actor) -> OkResponse:
    await c.reception.discharge(actor, reservation_id)
    return OkResponse()


@router.put(
    "/customers/{customer_id}/personal", response_model=OkResponse, dependencies=write, tags=[T_CUSTOMER],
    summary="고객 개인 정보 고치기",
    description=f"""KOS 고객 개인 정보를 고친다. 보낸 키만 바꾼다(안 보낸 키는 그대로).

{WHO}

**동작**: 날짜 꼴 검사(400) → KOS get-visitor 로 지금 값을 다시 읽음 → 다시 읽은 개인 정보 키들(읽은 값에 있는 것만) 그대로 +
바꾼 키를 덮어 update-visitor-personal-information.
- 문자열 키: 앞뒤 공백을 지워 보낸다 · null/빈 값 = 빈 문자열(비움).
- `phone` · `additionalPhone` · `sns` · `address`: null 을 보내면 바꾸지 않는다 · 객체 안 null = 빈 문자열.

**멱등**: 바꾼 키가 모두 다시 읽은 값과 같으면 update 를 보내지 않고 성공(get-visitor 읽기는 한다).

**부작용**: ccc 고객 사본의 이름 · 발음 이름 · 국적 · 성별(보낸 것만) 갱신 · event_log `visitor_personal`(보낸 키 이름들) ·
그 고객의 예약이 있는 모든 날짜 캐시 비움. SSE 없음.

{WRITE_COMMON}""",
    responses=errors(
        UNAUTHORIZED, FAKE_BOARD, INVALID, NOT_FOUND_CUST,
        (400, "invalid_request", "`dateOfBirth` · `passportExpiryDate` 를 `date.fromisoformat` 이 못 읽음 · 모르는 키"),
        KOS_REJECTED,
        (502, "kos_unavailable", "KOS 네트워크 오류 · 5xx · 401 · 고객 응답 형식이 틀림 · 서버에 KOS 설정 없음"),
    ),
)
async def personal(customer_id: CustId, body: PersonalRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.personal(actor, customer_id, body.personal)
    return OkResponse()


@router.put(
    "/customers/{customer_id}/remark", response_model=OkResponse, dependencies=write, tags=[T_CUSTOMER],
    summary="고객 특이사항 저장",
    description=f"""KOS 고객 특이사항(관리 정보 `memo`)을 바꾼다. 빈 문자열 = 비움.

{WHO}

**동작**: KOS get-visitor 로 다시 읽음 → 관리 정보 묶음 그대로(빈 배열 키는 뺌) + `memo` 만 바꿔
update-visitor-management-information.

**멱등**: 다시 읽은 KOS memo 와 같으면 update 를 보내지 않고 성공(읽기는 한다).

**부작용**: event_log `visitor_remark`. 캐시 비움 없음 · SSE 없음.

{WRITE_COMMON}""",
    responses=errors(
        UNAUTHORIZED, FAKE_BOARD, INVALID, NOT_FOUND_CUST, KOS_REJECTED,
        (502, "kos_unavailable", "KOS 네트워크 오류 · 5xx · 401 · 고객 응답 형식이 틀림 · 서버에 KOS 설정 없음"),
    ),
)
async def remark(customer_id: CustId, body: RemarkRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.remark(actor, customer_id, body.memo)
    return OkResponse()


@router.put(
    "/customers/{customer_id}/identity", response_model=OkResponse, dependencies=write, tags=[T_CUSTOMER],
    summary="신분 확인 표시",
    description=f"""고객의 신분 확인 표시(ccc 기록)를 남긴다 — KOS 호출 없음.

{WHO}

- `unconfirmed` 는 지금 confirmed 이고 그 고객의 오늘 예약 중 접수 뒤 단계(취소 · 부도 · 예약 아님)가 있으면 409
  `identity_locked`.
- 기록 방법(`method`)은 `web_manual`.

**부작용**: event_log `identity` · 신분 확인 기록 1줄(가장 최근 기록이 상세 `identity.status` 가 된다). SSE 없음.

**반복**: 같은 값이어도 보낼 때마다 기록이 1줄씩 쌓인다(결과 상태는 같음).

서버 env `PROC_FAKE_BOARD` 가 켜져 있으면 403 `fake_board`.""",
    responses=errors(UNAUTHORIZED, FAKE_BOARD, INVALID, NOT_FOUND_CUST,
                     (409, "identity_locked", "미확인으로 되돌리려는데 그 고객의 오늘 예약이 이미 접수 뒤")),
)
async def identity(customer_id: CustId, body: IdentityRequest, c: Ctr, actor: Actor) -> OkResponse:
    c.resv.identity(actor, customer_id, body.status)
    return OkResponse()


@router.put(
    "/customers/{customer_id}/funnel", response_model=OkResponse, dependencies=write, tags=[T_CUSTOMER],
    summary="고객 유입 채널 저장",
    description=f"""KOS 고객 유입 채널(관리 정보 `visitorFunnel`)을 바꾼다.

{WHO}

- `funnelId` = ccc 유입 코드 id(null = 비움) · `funnelDetail` 은 키를 보낼 때만 바꾼다(안 보내면 지금 값). `funnelCategoryId` 는
  읽은 값 그대로.
- **동작**: KOS get-visitor 로 다시 읽음 → 관리 정보 묶음 그대로(빈 배열 키는 뺌) + `visitorFunnel` 만 바꿔
  update-visitor-management-information.

**멱등**: 다시 읽은 값과 같으면 update 를 보내지 않고 성공(읽기는 한다).

**부작용**: event_log `visitor_funnel`. 캐시 비움 없음 · SSE 없음.

{WRITE_COMMON}""",
    responses=errors(
        UNAUTHORIZED, FAKE_BOARD, INVALID, NOT_FOUND_CUST,
        (400, "invalid_request", "`funnelId` 가 없거나 닫힌 유입 코드 · `funnelId` 키 없음 · 모르는 키"),
        KOS_REJECTED,
        (502, "kos_unavailable", "KOS 네트워크 오류 · 5xx · 401 · 고객 응답 형식이 틀림 · 서버에 KOS 설정 없음"),
    ),
)
async def funnel(customer_id: CustId, body: FunnelRequest, c: Ctr, actor: Actor) -> OkResponse:
    """KOS 고객 유입 채널(E2E batch 3 #2) — 같은 값이면 KOS 안 부름."""
    await c.resv.funnel(actor, customer_id, body.funnelId, body.funnelDetail, "funnelDetail" in body.model_fields_set)
    return OkResponse()
