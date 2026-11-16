"""외부 연동 API(SPEC-008 §6 · §7) — 링키 · 차티 같은 연동처용. 헤더 `X-Api-Key` 로만 연다.

- `Authorization` 을 보지 않는다(`require_login` · `Actor` 를 쓰지 않음 — 직원 토큰이 실려도 직원 권한이 되지 않는다)
- 이름 · 이메일은 POST 본문으로만 받는다(경로 · 질의 → 접근 로그) · 로그 · `ext_call` 에 이름 · 이메일 · 키 · IP 0
- 미들웨어(`ext_middleware`): IP 차단(키 검사 전 429) → 응답 → 연동처 없는 오류면 IP 카운트 → `ext_call` 1줄 → `no-store`
"""

import json
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import JSONResponse, Response

from app.api.deps import Ctr, get_container
from app.api.docs import T_EXT, errors
from app.api.public_questionnaire import client_ip
from app.domain.errors import BadRequest, TooManyRequests, Unauthorized
from app.schemas.ext import (
    ExtAvailability,
    ExtBoard,
    ExtClinic,
    ExtConsultationMemoRequest,
    ExtCustomerRequest,
    ExtCustomerReservations,
    ExtLanguageRequest,
    ExtLookupRequest,
    ExtLookupResponse,
    ExtMenu,
    ExtOk,
    ExtOrderMemoRequest,
    ExtReservationDetail,
    ExtReservationRequest,
    ExtReservationResponse,
    ExtStaffList,
    ExtVisits,
)
from app.service.ext import RATE, UNAUTHORIZED

PREFIX = "/api/ext"
INTERNAL = "서버 오류가 났어요"
log = logging.getLogger("procedure.ext")
KEY_DESC = "연동처 API 키(링키 · 차티 각각 다름). 직원 로그인 토큰(`Authorization: Bearer`)과 다르다 — 그 헤더는 보지 않는다"


async def require_ext_key(request: Request, x_api_key: str | None = Header(default=None, alias="X-Api-Key",
                                                                     description=KEY_DESC)) -> str:
    """`X-Api-Key` → 연동처 이름(401 ext_unauthorized) → 키당 최근 60초 60번(429). 칸 검증(400)보다 먼저 돈다.

    `async def` — 안에 막히는 I/O 가 없다(키 비교 · 메모리 카운터). 카운터는 미들웨어와 같은 이벤트 루프 스레드에서만 만진다.
    """
    ext = get_container(request).ext
    client = ext.match_key(x_api_key)
    if client is None:
        raise Unauthorized("ext_unauthorized", UNAUTHORIZED)
    request.state.ext_client = client  # ext_call.client — 미들웨어는 키를 다시 견주지 않는다
    if not ext.take_key(client):
        raise TooManyRequests("too_many_requests", RATE)
    return client


ExtClient = Annotated[str, Depends(require_ext_key)]

# ------------------------------------------------------------------ 열람 헤더(SPEC-008 §6.10 · DEC-012 D-18 · D-37)
STAFF_HEADER = "X-Ext-Staff-Id"
STAFF_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
STAFF_BASE = ("연동처 직원 id(선택) — **연동처가 신고한 값이고 CC 가 검증하지 않는다**. 열람 기록(`event_log` `ext_view`) · "
              "쓰기 행위자(`ext:<연동처>:<직원 id>`)에 그대로 적는다(호출 기록 `ext_call` · 로그 · 응답에는 남기지 않는다). "
              "앞뒤 공백을 지우고, 비면 없는 것으로 본다. 꼴 = 영문 · 숫자 · `.` `_` `-` 1 ~ 64자")
STAFF_LENIENT_DESC = STAFF_BASE + ". **꼴이 틀리면 없는 것으로 본다**(400 없음)"
STAFF_STRICT_DESC = STAFF_BASE + ". **꼴이 틀리면 `400 invalid_request`**(message `header.X-Ext-Staff-Id: …`)"
STAFF_BAD = f"header.{STAFF_HEADER}: 영문 · 숫자 · . _ - 로 1 ~ 64자여야 해요"


def staff_id_of(raw: str | None) -> tuple[str | None, bool]:
    """꼴 검사 하나(두 의존성이 같이 쓴다) → (직원 id 또는 None, 꼴이 맞았나). 비면 (None, True)."""
    v = (raw or "").strip()
    if not v:
        return None, True
    return (v, True) if STAFF_RE.fullmatch(v) else (None, False)


async def lenient_staff(x_ext_staff_id: str | None = Header(default=None, alias=STAFF_HEADER,
                                                            description=STAFF_LENIENT_DESC)) -> str | None:
    """lookup(기존 경로) — 틀린 꼴은 없는 것으로(DEC-012 D-37 ②)."""
    return staff_id_of(x_ext_staff_id)[0]


async def strict_staff(x_ext_staff_id: str | None = Header(default=None, alias=STAFF_HEADER,
                                                           description=STAFF_STRICT_DESC)) -> str | None:
    """새 경로 넷(상세 · 쓰기 셋) — 틀린 꼴은 400(DEC-012 D-37 ③)."""
    staff, ok = staff_id_of(x_ext_staff_id)
    if not ok:
        raise BadRequest("invalid_request", STAFF_BAD)
    return staff


LenientStaff = Annotated[str | None, Depends(lenient_staff)]
StrictStaff = Annotated[str | None, Depends(strict_staff)]
router = APIRouter(prefix=PREFIX, tags=[T_EXT])


def _endpoint(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path_format", None) or getattr(route, "path", None)
    return f"{request.method} {path}" if path else f"{request.method} (unknown)"


async def ext_middleware(request: Request, call_next):
    """`/api/ext` — IP 차단 · 기록 · no-store(오류 응답 포함). 그 밖 경로는 그대로 넘긴다."""
    if not request.url.path.startswith(PREFIX):
        return await call_next(request)
    ext = get_container(request).ext
    ip = client_ip(request)  # 메모리 카운터 키로만 — 표 · 로그에 남기지 않는다
    if ext.ip_blocked(ip):  # 키 검사 전 · 막힌 요청은 세지 않는다
        ext.record(ip, None, _endpoint(request), 429, "too_many_requests")
        return JSONResponse(status_code=429, content={"error": {"code": "too_many_requests", "message": RATE}},
                            headers={"Cache-Control": "no-store"})
    try:
        resp = await call_next(request)
        body = b"".join([chunk async for chunk in resp.body_iterator])
    except Exception as e:  # 처리하지 못한 예외 — 기록 · no-store 는 그대로(본문 · 로그에 예외 문구 없음 · 종류만)
        log.error("외부 처리 오류: %s", type(e).__name__)
        client = getattr(request.state, "ext_client", None)
        ext.record(ip, client, _endpoint(request), 500, "internal_error")
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": INTERNAL}},
                            headers={"Cache-Control": "no-store"})
    client = getattr(request.state, "ext_client", None)
    outcome = "ok"
    if resp.status_code >= 400:
        try:
            outcome = str(json.loads(body)["error"]["code"])
        except (ValueError, KeyError, TypeError):
            outcome = "http_error"
        if client is None:  # 연동처가 정해지지 않은 오류 응답 = 키 맞히기 · 기록 쌓기 카운터(보정 1 N1)
            ext.count_bad(ip)
    ext.record(ip, client, _endpoint(request), resp.status_code, outcome)
    headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
    headers["Cache-Control"] = "no-store"
    return Response(content=body, status_code=resp.status_code, headers=headers, media_type=resp.media_type,
                    background=resp.background)


# ------------------------------------------------------------------ 응답 표(SPEC-008 §6.2 공통)
EXT_UNAUTHORIZED = (401, "ext_unauthorized",
                    "직원 로그인이 아니라 `X-Api-Key` 헤더의 연동처 키가 없거나 · 비었거나 · 어느 연동처 키와도 같지 않거나 · "
                    "그 연동처 키 env 가 비어 꺼졌을 때. 직원 `Authorization: Bearer` 토큰만 실린 경우도 같다")
EXT_RATE = (429, "too_many_requests",
            "그 키로 최근 60초 안에 60번을 이미 불렀을 때(외부 경로 전부 합산) · "
            "그 IP 의 연동처 없는 오류 응답이 최근 60초 안에 10번 이상일 때(키 검사 전에 막는다)")
LOOKUP_INVALID = (400, "invalid_request",
                  "본문이 JSON 이 아님(키 검사보다 먼저) · 타입 · 모르는 키 · 앞뒤 공백을 지우면 빈 `name` · `email` · "
                  "`customerId` 가 1 이상 정수가 아님(문자열 포함) · **두 갈래가 섞이거나(`customerId` + `name` 등) · 한쪽만"
                  "(`name` 만 · `email` 만) · 빈 요청 `{}`**(이 갈래 오류의 message 는 `body: …` 로 시작). "
                  "그 밖 message = `<위치>: <이유>`")
RESERVE_INVALID = (400, "invalid_request",
                   "본문이 JSON 이 아님(키 검사보다 먼저) · 필수 칸 없음 · 타입 · 모르는 키 · "
                   "앞뒤 공백을 지우면 빈 `name` · `email` · ISO 가 아닌 `start`. message = `<위치>: <이유>`")
EXT_405 = (405, "http_error", "외부 경로에 허용하지 않는 메서드로 불렀을 때(예: `GET /api/ext/customers/lookup`)")
EXT_500 = (500, "internal_error",
           "서버가 처리하지 못한 예외 — 본문에 예외 문구 없음(message 「서버 오류가 났어요」) · 호출 기록 1줄 · IP 카운트 안 함")
COMMON = (EXT_UNAUTHORIZED, EXT_RATE, EXT_405, EXT_500)
NOT_FOUND_ROW = (404, "customer_not_found",
                 "일치하는 고객이 없을 때 — 이름이 틀림(부분 일치만 맞음 포함) · 이메일이 틀림 · 고객 없음 · KOS 에 그 고객 "
                 "email 이 비어 있음 · 이름 검색 결과가 1000명을 넘음. **모두 같은 응답**(code · message 같음 · 어느 쪽이 "
                 "틀렸는지 알 수 없다). message 「일치하는 고객이 없어요」")
AMBIGUOUS_ROW = (409, "customer_ambiguous", "이름 · 이메일이 맞는 고객이 2명 이상일 때(아무도 돌려주지 않음 · 후보 수 · 이름 · "
                 "id 없음). message 「고객을 특정할 수 없어요」")

SHARED = """
**인증**: 헤더 `X-Api-Key: <연동처 키>`. 직원 `Authorization: Bearer` 는 보지 않는다(Bearer 만 실리면 `401 ext_unauthorized`).
**검사 순서**: 키(`401`) → 호출 제한(`429`) → 칸 검증(`400`) → 엔드포인트 규칙. 단 IP 차단 `429` 가 무엇보다 먼저 ·
JSON 이 아닌 본문 `400` 은 키보다 먼저 · 없는 경로 `404 not_found` 는 키 없이 난다.
응답(오류 포함)마다 `Cache-Control: no-store`. 호출마다 `ext_call` 에 연동처 · 경로 틀 · 상태 · 결과 code 만 남는다.
"""

NAME_RULE = """
**이름 · 이메일 대조**(조회 · 예약 같은 규칙): KOS 내부 이름 검색을 **한 번**(한 페이지 1000명) 부른다 — 보낼 때는 앞뒤 공백만
지운다. KOS 검색은 가운데 공백을 그대로 견주므로 **이름은 KOS 에 등록된 띄어쓰기 그대로 보내야 한다**. 받은 고객 중 이름
(또는 발음 이름)이 입력과 **정확히 같은** 고객(대소문자 무시)만 남기고, 그중 email 이 입력과 같은(앞뒤 공백 · 대소문자 무시)
고객만 남긴다. 이름이 일부만 겹치는 고객은 빠진다. KOS 에 email 이 빈 고객은 찾지 못한다. 검색 결과가 1000명을 넘으면 「없음」.
"""

MENU_DOC = SHARED + """
우리 DB 의 메뉴 사본(KOS 시술 · 상품 메뉴를 1시간마다 · 서버 시작 때 동기화)을 트리로 준다 — 카테고리 → 상품 → 옵션 → (GROUP 이면)
구성. KOS 를 부르지 않는다. 질의 칸 없음.

- **지금 있는 것만**: KOS 동기화 결과에서 빠졌거나 KOS 가 숨김 · 닫힘 · 삭제로 표시한 카테고리 · 상품 · 옵션은 나오지 않는다.
  위 층이 빠지면 아래 층도 빠진다. 보이는 카테고리에 하나도 걸리지 않은 상품은 나오지 않는다.
- 순서: 카테고리 `order` 오름차순 → id · 상품 · 옵션 · 구성은 KOS 배열 순서.
- 가격 칸 `listPriceExVat` = KOS 정가 · **부가세 별도**. 진료항목 · 기기 · 약물 · 공급가 · 부가세 · 특별가 · 프로모션은
  내지 않는다.
- **`syncedAt`** = 메뉴 동기화가 마지막으로 전부 성공한 시각(그 뒤 작업 하나가 실패해도 그대로) — 언제 받은 메뉴인지 알 수 있다.
  메뉴가 비었으면(첫 동기화 전) `200` 에 `categories: []` · `syncedAt: null`.
"""

LOOKUP_DOC = SHARED + NAME_RULE + """
**요청 두 갈래 — 정확히 하나만**: ① `{"name", "email"}` 둘 다(위 대조 규칙) ② `{"customerId"}` 하나만(ccc 고객 id —
**이름 + 이메일 없이 열린다** · 사본에서 KOS 고객을 찾아 KOS 고객 읽기 1번).
섞이거나 한쪽만 · 빈 요청이면 `400`(message `body: …`).
1명이 맞으면 그 고객 · **남은 시술권**(KOS 내부 시술권 조회 1번) · **선불카드**(KOS 공개 선불카드 요약 1번 · 시술권과
동시)를 준다.
매번 KOS 에서 읽고 저장하지 않는다.

- 고객 칸 = ccc `customerId` · 이름 · 신규 여부 · 최근 방문일만. 전화 · 생년월일 · 국적 · 여권 · 차트번호 · 이메일 · KOS id 없음.
- 시술권은 KOS 값 그대로다: **`bundlePrice` 는 고객이 낸 돈이 아니다** — 산 시점 값에서 출발하지만 GROUP 에서 한 세트를 다
  쓰면 그 세트가 빠져 `totalCount` 와 함께 줄 수 있다 · 부가세 포함 여부는 표기하지 않는다. `remainingCount` 는 `AVAILABLE` 만
  센다 — `IN_USE`(사용 중)는 넣지 않고 `inUseCount` 로 따로 준다. 시술권 만료일 칸은 없다(KOS 에 없음).
- **(0.4.0 행동 변화) 사용 중 장만 남은 묶음도 나온다** — 사용 가능 또는 사용 중 장이 1장 이상인 묶음을 내고, 다 쓴 · 다
  취소된 묶음은 뺀다. `totalCount` 는 뜻 그대로(상태 무관)이고 **사용 중 장도 센다**(그만큼 커질 수 있다).
- 남은 시술권이 없으면 `tickets: []`(고객은 있음). 시술권 조회가 실패하면 빈 배열이 아니라 `502`.
- 선불카드 = 만료되지 않았고 잔액이 남은 카드 · 칸 = 이름 · 발급일 · 만료 일시 · 현금 잔액 · 포인트 잔액(`{remaining, total}` —
  금액 꼴 `{value, currency}`). 없으면 `[]`. **(0.4.1 행동 변화) 선불카드 조회가 실패해도 `200` — `prepaidCards: null` ·
  `partialErrors: ["prepaidCards"]`**(「카드 없음」 `[]` 과 다르다).
- **(0.4.1 행동 변화)** 요청 스키마의 `name` · `email` 은 `required` 가 아니다(갈래 검사로 옮김). 갈래 오류의 `400` message 는
  `body: …` 꼴이다(code 는 그대로 `invalid_request`).
- 선택 헤더 `X-Ext-Staff-Id` — 꼴이 틀리면 없는 것으로 본다(400 없음). `200` 이면 열람 기록 1줄(`event_log` `ext_view`).
- 부작용: 찾은 고객을 ccc 고객 사본에 덮어쓴다(이메일은 저장하지 않음). KOS 쓰기 없음.
- **KOS 호출**: 이름 갈래 = 이름 검색 1 + 시술권 1 + 선불카드 1 = 3 · `customerId` 갈래 = 고객 읽기 1 + 시술권 1 + 선불카드 1 = 3
  (`404` · `409` 이면 1 · `customerId` 가 사본에 없으면 0).
"""

RESERVE_DOC = SHARED + NAME_RULE + """
이름 + 이메일로 고객을 정해 서버 기본 예약 그룹(env `KOS_EXT_RESERVATION_GROUP_ID`)에 예약을 만든다. 그룹 · 구역 · 담당자 칸은
받지 않는다(보내면 모르는 키라 `400`). 구역 = 서버 기본 구역 규칙 · 담당자 = KOS 시스템 계정 · 끝 = 시작 + 그룹 간격.

- **1명** → 그 고객으로 예약. **0명** → 이름 + 이메일로 KOS 에 새 고객을 만들고 예약(다음 조회부터 그 이메일로 찾힌다).
  **2명 이상** → `409 customer_ambiguous`(예약 안 함).
- 0명 갈래에서 KOS 중복 검사에 걸리면(같은 이메일 · 이름 등의 고객이 이미 있음) `409 customer_ambiguous` 로 막고 예약하지 않는다.
- **주의(이메일 존재 노출)**: 0명 갈래에서 KOS 중복 검사에 걸리면 409, 아니면 200 이라 그 이메일이 KOS 에 있는지가 드러난다.
  이 위험은 받아들인다(키를 가진 연동처만 · 호출 제한 · 호출 기록).
- 설정(기본 그룹 env 가 빔 · 그 그룹이 KOS 에서 사라짐 · 그 그룹에 켜진 구역 0)이 맞지 않으면 KOS 를 부르기 전에 `503`.
- 부작용: KOS 고객 생성(0명 갈래) · KOS 예약 생성 · event_log `resv_create`(실패면 `kos_rejected`) — 행위자 `ext:<연동처>`.
"""


@router.get("/menu", response_model=ExtMenu, summary="시술 · 상품 메뉴 — 카테고리 · 상품 · 옵션 · 구성", description=MENU_DOC,
            responses=errors(*COMMON))
async def menu(c: Ctr, _: ExtClient) -> ExtMenu:
    return ExtMenu.model_validate(c.ext.menu())


LOOKUP_NOT_FOUND = (404, "customer_not_found",
                    NOT_FOUND_ROW[2] + ". `customerId` 갈래 — 그 id 가 ccc 사본에 없음 · KOS 가 그 고객을 없다고 줌(같은 응답)")
LOOKUP_PATH = "POST /api/ext/customers/lookup"


@router.post("/customers/lookup", response_model=ExtLookupResponse,
             summary="고객 조회 — 이름 + 이메일 또는 customerId → 고객 + 남은 시술권 + 선불카드", description=LOOKUP_DOC,
             responses=errors(*COMMON, LOOKUP_INVALID, LOOKUP_NOT_FOUND, AMBIGUOUS_ROW,
                              (502, "kos_unavailable", "KOS 이름 검색 · 고객 읽기(`customerId` 갈래) · 시술권 조회가 실패했을 때"
                                                       "(네트워크 · 5xx · 4xx · KOS 인증 실패 · 응답 모양 오류). 선불카드만 "
                                                       "실패하면 502 가 아니라 200 + `partialErrors`. "
                                                       "message 「KOS 에 연결하지 못했어요」")))
async def lookup(body: ExtLookupRequest, c: Ctr, client: ExtClient, staff: LenientStaff) -> ExtLookupResponse:
    out = ExtLookupResponse.model_validate(await c.ext.lookup(body.name, body.email, body.customerId))
    c.ext.view(client, staff, LOOKUP_PATH, out.customer.customerId)
    return out


@router.post("/reservations", response_model=ExtReservationResponse,
             summary="예약 — 이름 + 이메일 + 시작 시각", description=RESERVE_DOC,
             responses=errors(*COMMON, RESERVE_INVALID,
                              (409, "customer_ambiguous", "이름 · 이메일이 맞는 고객이 2명 이상 · 0명 갈래에서 KOS 중복 검사에 "
                                                          "걸림(예약 안 함 · 후보 정보 없음)"),
                              (409, "slot_full", "그 시간 칸의 정원이 찼을 때(사본 기준 · KOS 쓰기 직전)"),
                              (409, "kos_rejected", "KOS 가 4xx(401 제외)로 거절했을 때 — 중복 검사 · 고객 만들기 · "
                                                    "예약 쓰기 단계. message = 거절 이유를 옮긴 한국어 문구"),
                              (502, "kos_unavailable", "KOS 네트워크 · 5xx · 401 · 응답 형식(예약 쓰기 · 고객 만들기 · "
                                                       "중복 검사) · 이름 검색은 4xx 도 502 · 예약 응답에 일정 id 없음. "
                                                       "message 「KOS 에 연결하지 못했어요」"),
                              (503, "ext_not_configured", "기본 예약 그룹 env 가 비었거나 · 그 그룹이 KOS 에서 사라졌거나 · "
                                                          "그 그룹에 켜진 구역이 0 일 때(KOS 를 부르기 전)")))
async def reserve(body: ExtReservationRequest, c: Ctr, client: ExtClient) -> ExtReservationResponse:
    return ExtReservationResponse.model_validate(await c.ext.reserve(client, body.name, body.email, body.start, body.memo))



# ------------------------------------------------------------------ 0.3.0(add1) — SPEC-008 §6.6 ~ §6.9
AVAIL_INVALID = (400, "invalid_request",
                 "질의 `date` 없음(message `query.date: …`) · 빈 문자열 · `YYYY-MM-DD` 꼴 아님 · 오늘(KST) 앞 · "
                 "오늘 + 90일 뒤(message `date: <이유>`)")
CUSTOMER_INVALID = (400, "invalid_request",
                    "본문이 JSON 이 아님(키 검사보다 먼저) · 필수 칸 없음 · 타입 · 모르는 키 · "
                    "앞뒤 공백을 지우면 빈 `name` · `email`. message = `<위치>: <이유>`")
HISTORY_502 = (502, "kos_unavailable", "KOS 이름 검색 · 고객 일정 읽기가 실패했을 때(네트워크 · 5xx · 4xx · KOS 인증 실패 · "
                                       "응답 모양 오류 — 빈 목록이 아니다). message 「KOS 에 연결하지 못했어요」")
OVERLAP = "**오늘 겹침**: 오늘 이미 시작한 일정은 과거 시술과 예약 내역 둘 다에 나온다(과거 = 지금 앞 · 내역 = 오늘 0시 이후)."

AVAIL_DOC = SHARED + """
그날(`date` · KST) **서버 기본 예약 그룹 하나**(env `KOS_EXT_RESERVATION_GROUP_ID` — 외부 예약이 들어가는 그 그룹)의 예약 가능한
칸을 준다. 칸마다 시작 시각과 남은 자리 수만 준다(그룹 · 구역 이름 · 구역별 정원 · 예약 수 없음).

- **날짜 범위**: 오늘(KST) ~ 오늘 + 90일. 지난 날짜 · 범위 밖 · `YYYY-MM-DD` 가 아닌 값은 `400`.
- **후보 시각**: 그 그룹 시간표의 그날 운영 구간(쉬는 시간 뺌) 안에서 자정 기준 그룹 간격 경계마다(시작 + 간격 ≤ 구간 끝).
  휴무 요일이면 `slots: []`.
- **남은 자리** = 그 그룹의 켜진 구역마다 `max(0, 정원 − 예약 수)` 를 더한 값. **0 인 칸 · (오늘이면) 시작이 지금과 같거나
  지난 칸 · 자리 수를 모르는 칸(KOS 가 정원을 주지 않음)은 나오지 않는다 — 목록에 없어도 예약이 될 수 있다.**
- **예약과 같은 규칙**: 요청마다 KOS 칸 정원을 새로 읽어 서버 사본을 바꾸고, 예약(`POST /api/ext/reservations`)의 정원 검사도
  그 사본을 본다. 그래서 **이 목록의 `start` 로 예약하면 정원 때문에 거절되지 않는다 — 그 사이 다른 예약이 끼면
  `409 slot_full`** 이다. 운영 시간 밖 시각의 예약을 이 목록이 막지는 않는다.
- 설정(기본 그룹 env 가 빔 · 그 그룹이 KOS 에서 사라짐 · 켜진 구역 0)이 맞지 않으면 KOS 를 부르기 전에 `503`.
- **KOS 호출**: 요청 1번 = KOS 공개 칸 정원 조회 1번(`400` · `503` 이면 0번). 부작용: 서버 칸 정원 사본(직원 예약 현황도 보는
  값)을 새로 바꾼다. KOS 쓰기 없음.
"""

VISITS_DOC = SHARED + NAME_RULE + """
1명이 맞으면 그 고객의 **과거 시술**(지금보다 앞선 KOS 일정)을 **최신 순 · 최근 50건까지** 준다. 고객 찾기는 조회
(`POST /api/ext/customers/lookup`)와 같은 함수 · 같은 응답이다(「없음」 `404` 는 조회 `404` 와 바이트까지 같다).

- 칸 = 날짜 · 시작 · 결과(`completed` · `noshow` · `canceled` · `other`) · 시술 이름 목록. **예약 메모 · 상담 메모 · 의사 이름은
  내지 않는다.** 취소 · 부도 일정도 결과 칸으로 나온다.
- 지난 일정이 없으면 `visits: []`(고객은 있음). 일정 읽기가 실패하면 빈 배열이 아니라 `502`.
- """ + OVERLAP + """
- **KOS 호출**: 이름 검색 1번 + 고객 일정 1번 = 2번(`404` · `409` 이면 1번). 서버 사본에 쓰지 않는다 · KOS 쓰기 없음.
"""

CUSTOMER_RESV_DOC = SHARED + NAME_RULE + """
1명이 맞으면 그 고객의 **예약 내역**(오늘(KST) 0시 이후 KOS 일정)을 **시작 오름차순**으로 준다(개수 상한 없음 · **취소 · 부도
포함**). 고객 찾기는 조회와 같은 함수 · 같은 응답이다(「없음」 `404` 는 조회 `404` 와 바이트까지 같다).
지난 일정은 과거 시술에서 본다.

- 칸 = `reservationId` · 날짜 · 시작 · 끝(첫 묶음) · 상태(직원 예약 현황의 주 상태 그대로). 그룹 · 구역 이름 · 메모 · 담당자 ·
  상담사는 내지 않는다.
- **`reservationId`** = ccc 예약 id(예약 응답과 같은 체계). ccc 서버 사본에 그 일정이 없으면(KOS 에서 직접 만든 예약을 서버가
  아직 읽지 않음) **null** 이다. 외부 예약 API 로 만든 예약은 늘 id 가 있다.
- 오늘 이후 일정이 없으면 `reservations: []`. 일정 읽기가 실패하면 빈 배열이 아니라 `502`.
- """ + OVERLAP + """
- **KOS 호출**: 이름 검색 1번 + 고객 일정 1번 = 2번(`404` · `409` 이면 1번). 서버 사본에 쓰지 않는다 · KOS 쓰기 없음.
"""


@router.get("/availability", response_model=ExtAvailability, summary="예약 가능 시간대 — 날짜 → 칸 · 남은 자리",
            description=AVAIL_DOC,
            responses=errors(*COMMON, AVAIL_INVALID,
                             (502, "kos_unavailable", "KOS 칸 정원 조회가 실패했을 때(네트워크 · 5xx · 4xx · KOS 인증 실패 · "
                                                      "응답 모양 오류 · KOS 설정 없음 — 사본은 그대로). "
                                                      "message 「KOS 에 연결하지 못했어요」"),
                             (503, "ext_not_configured", "기본 예약 그룹 env 가 비었거나 · 그 그룹이 KOS 에서 사라졌거나 · "
                                                         "그 그룹에 켜진 구역이 0 일 때(KOS 를 부르기 전)")))
async def availability(c: Ctr, _: ExtClient,
                       date: str = Query(description="볼 날짜 `YYYY-MM-DD`(KST) — 오늘 ~ 오늘 + 90일",
                                         examples=["2026-11-20"])) -> ExtAvailability:
    return ExtAvailability.model_validate(await c.ext.availability(date))


@router.post("/customers/visits", response_model=ExtVisits, summary="고객 과거 시술 — 이름 + 이메일 → 지난 일정(최신 50)",
             description=VISITS_DOC, responses=errors(*COMMON, CUSTOMER_INVALID, NOT_FOUND_ROW, AMBIGUOUS_ROW, HISTORY_502))
async def visits(body: ExtCustomerRequest, c: Ctr, _: ExtClient) -> ExtVisits:
    return ExtVisits.model_validate(await c.ext.visits(body.name, body.email))


@router.post("/customers/reservations", response_model=ExtCustomerReservations,
             summary="고객 예약 내역 — 이름 + 이메일 → 오늘 이후 예약", description=CUSTOMER_RESV_DOC,
             responses=errors(*COMMON, CUSTOMER_INVALID, NOT_FOUND_ROW, AMBIGUOUS_ROW, HISTORY_502))
async def customer_reservations(body: ExtCustomerRequest, c: Ctr, _: ExtClient) -> ExtCustomerReservations:
    return ExtCustomerReservations.model_validate(await c.ext.reservations(body.name, body.email))


# ------------------------------------------------------------------ 0.4.0(charty 1차) — SPEC-008 §6.10 ~ §6.17
STAFF_400 = ("열람 헤더 `X-Ext-Staff-Id` 꼴이 틀림(영문 · 숫자 · `.` `_` `-` 1 ~ 64자가 아님 · message "
             "`header.X-Ext-Staff-Id: …`)")
RESV_NOT_FOUND_ROW = (404, "reservation_not_found", "ccc 사본에 그 예약이 없을 때(KOS 를 부르지 않는다). 없는 경로의 "
                      "`not_found` 와 다르다. message 「없는 예약이에요」")
NO_KOS_502 = (502, "kos_unavailable", "서버에 KOS 설정이 없을 때. message 「KOS 에 연결하지 못했어요」")
STAFF_NOTE = ("- 선택 헤더 `X-Ext-Staff-Id`(연동처 직원 id) — **연동처가 신고한 값이고 CC 가 검증하지 않는다**. "
              "**꼴이 틀리면 `400`**.\n")

DETAIL_DOC = SHARED + """
ccc 예약 id(접수 목록 `reservationId`)로 예약 하나의 상세를 준다 — 고객 기본 정보 · 나이 · 언어 · 고객 유입 · 예약 메모 ·
귀가 희망 · 예약 유입 · 희망 상담사 · 희망 의사 · 희망 시술 · 지금 오더 메모 · 지금 상담 메모 · 문진 · 이전 방문.

- **`reservation.counselor` = KOS 희망 상담사**(예약에 지정한 사람 — 실제 상담자가 아니다). 실제 상담자는 이전 방문
  `counselors[]` 에 있다.
- **지금 오더 메모 · 상담 메모**(`reservation.orderMemo` · `consultationMemo`) — 오더 메모 · 상담 메모 쓰기가 **통째로 바꾸는**
  칸이다. 쓰기 전에 여기서 읽는다. 예약 메모(`reservation.memo`)와 다른 칸이다. 상담 메모 = 차트 메모.
- **이전 방문**은 예약 메모 · 상담 메모 · 의사 이름 · 상담자를 준다 — **과거 시술 경로(`POST /api/ext/customers/visits`)와
  다르다**(그 경로는 메모 · 의사를 내지 않는다). 그 예약 날짜와 같은 날 일정은 뺀다.
- 「상담 여부」 · 「처음 상담 대기 시각」은 여기 없다 — 접수 목록(`GET /api/ext/reservations/board`)에 있다.
- **부분 실패**: KOS 읽기 하나가 실패해도 `200` 이고 그 칸이 null(문진은 `health.state = error`)이며 `partialErrors` 에 이름이
  든다 — `schedule`(희망 시술 · 희망 의사 · 지금 메모 둘) · `visitor`(나이 · 언어 · 고객 유입) · `questionnaire` ·
  `previousVisits`(null — 빈 배열이 아니다).
- 전화 · 이메일 · 여권 · 주소 · 고객 특이사항 · 정산 · KOS id 는 내지 않는다.
""" + STAFF_NOTE + """- `200` 이면 열람 기록 1줄(`event_log` `ext_view` · 행위자 `ext:<연동처>[:<직원 id>]`).
- **예약을 만든 직후**에는 KOS 반영이 늦어 `404 reservation_gone` 이 잠깐 날 수 있다 — 다시 부르면 된다.
- 부작용: KOS 일정을 다시 읽어 서버 예약 사본을 덮어쓴다(직원 상세와 같다). KOS 쓰기 없음.
- **KOS 호출**: 일정 상세 1 + 고객 읽기 1 + 문진 2 + 고객 일정 1 = 5(사본에 없으면 0 · `reservation_gone` 이면 1).
"""
DETAIL_PATH = "GET /api/ext/reservations/{reservationId}"


BOARD_DOC = SHARED + """
**오늘(KST)** 접수 목록 — **예약 1건 = 1줄**(직원 화면 카드는 묶음마다 한 장이지만 여기는 예약 단위). 상태로 거르지 않는다(취소 ·
부도 · 귀가 포함). 질의 칸 없음. 차례 = 첫 묶음 시작 → `reservationId`.

- **사본**: 직원 예약 현황과 같은 **10초 날짜 사본**에서 읽는다(낡았으면 KOS 날짜 조회 후). KOS 가 실패하면 낡은 사본 그대로
  `200` 이고 `sync.lastError` 에 문구가 든다 — `lastError` 가 있으면 낡은 목록일 수 있다. 이 경로는 `502` 를 내지 않는다.
- **`counselor` = KOS 희망 상담사**(예약에 지정한 사람 — 실제 상담자가 아니다).
- **`roomTitle`** = 작업에 붙은 방 중 가장 늦게 배정된 방.
- **`consultation`** = CC 판정(접수 뒤 · 지금 상담 대기 · 상담 / CC 접수가 상담 대기로 끝남 / CC 「상담 추가」). 취소 · 부도 ·
  접수 전은 `false`.
- **`firstConsultationWaitingAt`** = KOS 단계 변경 이력에서 찾은 처음 상담 대기 시각. **`consultation` 과 따로 정한다** —
  `consultation = false` 여도 시각이 있을 수 있다(KOS 웹에서만 상담 대기를 지나간 일정).
  찾은 값은 서버에 저장해 다시 부르지 않는다.
  **아직 못 찾은 시각은 일정의 단계가 바뀔 때(상담 대기에 들어감 · 귀가) 다시 확인한다 — 화면을 자주 불러도 확인 호출은 늘지
  않는다.** 조회 실패는 5분 뒤 다시(일정마다 하루 3번까지). null = 접수 전 · 취소 · 부도 · 아직 못 찾음.
- **`partialErrors`** = `["consultationHistory"]` — 아직 확인하지 못한 시각이 있다(조회 실패 · 요청당 상한으로 미룸 · 다른 요청이
  확인 중). 못 찾음(이력에 없음)만은 넣지 않는다.
- 직원 화면의 열 · 칸 정원 · 공지 · 금액 · 담당자는 내지 않는다.
- **KOS 호출**: 사본이 신선하면 0 · 낡았으면 날짜 조회 3 ~ 4. 여기에 이력 조회가 **많아야 10**
  (사건이 있는 일정만 · 동시에 한 바퀴).
"""


@router.get("/reservations/board", response_model=ExtBoard,
            summary="오늘 접수 목록 — 예약 단위 · 상담 거침 · 처음 상담 대기 시각",
            description=BOARD_DOC, responses=errors(*COMMON))
async def board(c: Ctr, _: ExtClient) -> ExtBoard:
    return ExtBoard.model_validate(await c.ext.board())


# 경로 차례: board(§6.11)를 이 경로보다 먼저 둔다 — `board` 가 정수 경로 칸 검증(400)에 걸리지 않게
@router.get("/reservations/{reservationId}", response_model=ExtReservationDetail,
            summary="예약 상세 — 고객 · 희망 시술 · 지금 메모 · 문진 · 이전 방문", description=DETAIL_DOC,
            responses=errors(*COMMON, (400, "invalid_request", "`reservationId` 가 정수가 아님 · " + STAFF_400),
                             RESV_NOT_FOUND_ROW,
                             (404, "reservation_gone", "KOS 에서 그 일정이 지워졌을 때(KOS 가 404). 예약을 만든 직후 "
                                                       "KOS 반영이 늦을 때도 잠깐 난다(다시 부르면 된다). "
                                                       "message 「KOS 에서 사라진 예약이에요」"),
                             NO_KOS_502))
async def reservation_detail(c: Ctr, client: ExtClient, staff: StrictStaff,
                             reservationId: int = Path(description="ccc 예약 id(접수 목록 `reservationId`)")
                             ) -> ExtReservationDetail:
    out = ExtReservationDetail.model_validate(await c.ext.detail(reservationId))
    c.ext.view(client, staff, DETAIL_PATH, out.customer.customerId, reservationId)
    return out


WRITE_RULE = """
- **KOS 먼저**: KOS 에 쓴 뒤에만 서버 사본 · 기록을 바꾼다. **KOS 가 실패하면 그 오류 그대로**(`409 kos_rejected` · `502
  kos_unavailable`) 내고 성공 기록 · 사본 변경은 없다(실패 기록 `kos_rejected` 1줄).
- 행위자 = `ext:<연동처>:<직원 id>`(헤더 없으면 `ext:<연동처>`) — 서버 기록 `event_log` 에 남는다.
""" + STAFF_NOTE
WRITE_ERRORS = ((409, "kos_rejected", "KOS 가 4xx(401 제외)로 거절했을 때 — message = 거절 이유를 옮긴 한국어 문구"),
                (502, "kos_unavailable", "KOS 네트워크 · 5xx · 401 · 응답 형식 · 서버에 KOS 설정 없음. "
                                         "message 「KOS 에 연결하지 못했어요」"))
LANG_DOC = SHARED + """
고객 언어 하나를 바꾼다. 직원 화면의 고객 개인 정보 저장과 **같은 코드**를 탄다 — KOS 고객을 다시 읽고, 읽은 값과 같으면 KOS 에
쓰지 않고 `200` 이다. 다르면 다시 읽은 개인 정보 묶음 전체(있는 키)에 `language` 만 바꿔 KOS 에 보낸다.

- **덮어쓰기 위험**: 다시 읽기와 쓰기 사이에 KOS 웹에서 다른 개인 정보 칸을 고치면 그 변경이 덮일 수 있다(묶음 전체를 다시 보냄).
- 빈 문자열 = 비움 · 값 꼴은 검사하지 않고 KOS 에 그대로 보낸다.
""" + WRITE_RULE + """- 기록: `event_log` `visitor_personal`(`fields: ["language"]`) · 그 고객 날짜 캐시 비움.
- **KOS 호출**: 고객 읽기 1 + 개인 정보 쓰기 1 = 2(같은 값이면 1 · 사본에 없으면 0).
"""
ORDER_DOC = SHARED + """
예약(KOS 일정) 하나의 **오더 메모**를 글 전체로 **통째로 바꾼다**. 지금 값은 예약 상세 `reservation.orderMemo` 로 읽는다.
**예약 메모(`reservation.memo`)와 다른 칸**이다. 예약 상태로 막지 않는다(KOS 가 거르면 `409 kos_rejected`).
""" + WRITE_RULE + """- 기록: `event_log` `order_memo`(글 길이만 · 원문 없음) ·
  시술 현황 사본에 그 일정이 있으면 그 오더 메모만 고침 ·
  날짜 캐시 비움. 같은 글을 다시 보내도 늘 KOS 에 쓴다.
- **KOS 호출**: 내부 오더 메모 쓰기 1(사본에 없으면 0).
"""
CONSULT_DOC = SHARED + """
예약(KOS 일정) 하나의 **상담 메모**를 글 전체로 **통째로 바꾼다**. **「차트 메모」 = 이 상담 메모**다. 지금 값은 예약 상세
`reservation.consultationMemo` 로 읽는다. 예약 메모 · 오더 메모와 다른 칸이다.
- **비울 수 없다** — KOS 가 상담 메모를 비우지 못한다(빈 값을 보내면 200 인데 그대로 남는다). 그래서 앞뒤 공백을 지우면 비는
  값은 KOS 를 부르지 않고 `400 invalid_request`(message `body.consultationMemo: KOS 는 상담 메모를 비울 수 없어요`). 오더 메모는
  빈 값으로 비울 수 있다.
- 상담 전(예약 상태) 일정에도 쓸 수 있다. 쓴 뒤 같은 일정의 상담사 · 의사 칸은 그대로다.
""" + WRITE_RULE + """- 기록: `event_log` `consultation_memo`(글 길이만 · 원문 없음) · 날짜 캐시 비움.
- **KOS 호출**: 공개 상담 정보 쓰기 1(사본에 없으면 0).
"""
WRITE_400 = (400, "invalid_request", "경로 id 가 정수가 아님 · 본문 칸 없음 · 타입(null 포함) · 모르는 키 · " + STAFF_400)
CONSULT_400 = (400, "invalid_request", "경로 id 가 정수가 아님 · 본문 칸 없음 · 타입(null 포함) · 모르는 키 · "
               "**앞뒤 공백을 지우면 빈 `consultationMemo`**(KOS 가 비우지 못함 · "
               "message `body.consultationMemo: KOS 는 상담 메모를 비울 수 없어요`) · "
               + STAFF_400)
LANG_404 = (404, "customer_not_found", "ccc 사본에 그 고객이 없을 때(KOS 를 부르지 않는다) — 조회 `404` 와 같은 응답. "
            "message 「일치하는 고객이 없어요」")


@router.put("/customers/{customerId}/language", response_model=ExtOk, summary="고객 언어 바꾸기",
            description=LANG_DOC, responses=errors(*COMMON, WRITE_400, LANG_404, *WRITE_ERRORS))
async def customer_language(body: ExtLanguageRequest, c: Ctr, client: ExtClient, staff: StrictStaff,
                            customerId: int = Path(description="ccc 고객 id(조회 · 예약 상세의 `customerId`)")) -> ExtOk:
    await c.ext.language(client, staff, customerId, body.language)
    return ExtOk(ok=True)


@router.put("/reservations/{reservationId}/order-memo", response_model=ExtOk, summary="오더 메모 바꾸기(통째로)",
            description=ORDER_DOC, responses=errors(*COMMON, WRITE_400, RESV_NOT_FOUND_ROW, *WRITE_ERRORS))
async def order_memo(body: ExtOrderMemoRequest, c: Ctr, client: ExtClient, staff: StrictStaff,
                     reservationId: int = Path(description="ccc 예약 id(접수 목록 `reservationId`)")) -> ExtOk:
    await c.ext.order_memo(client, staff, reservationId, body.orderMemo)
    return ExtOk(ok=True)


@router.put("/reservations/{reservationId}/consultation-memo", response_model=ExtOk,
            summary="상담 메모(= 차트 메모) 바꾸기(통째로)", description=CONSULT_DOC,
            responses=errors(*COMMON, CONSULT_400, RESV_NOT_FOUND_ROW, *WRITE_ERRORS))
async def consultation_memo(body: ExtConsultationMemoRequest, c: Ctr, client: ExtClient, staff: StrictStaff,
                            reservationId: int = Path(description="ccc 예약 id(접수 목록 `reservationId`)")) -> ExtOk:
    await c.ext.consultation_memo(client, staff, reservationId, body.consultationMemo)
    return ExtOk(ok=True)


CLINIC_DOC = SHARED + """
이 CC 서버가 붙은 **KOS 병원 하나**의 정보 — 이름 · 전화 · 주소 · 운영 시간 · 휴무 · `clinicId` 만 준다.

- **`clinicId` = 1** — CC 서버 하나 = KOS 병원 하나라 늘 1 이다. 직원 목록 경로에 쓴다. **전역 유일하지 않다**(CC 서버 여럿을
  모으면 겹친다).
- **운영 시간 = 병원 기본 운영 시간**(요일마다 KST `HH:MM` · 예약 그룹별 시간표가 아니다).
- 휴무 = 병원 기본 휴무(오늘 ~ 오늘 + 90일) · 원소 = `{startDate, endDate}`(KST 날짜 · 하루 휴무면 둘이 같다).
- KOS 가 빈 칸을 빈 문자열로 주면 null 로 준다. 전화는 KOS 값 그대로(국가 번호를 붙이지 않는다).
- 매번 KOS 에서 읽는다(저장 · 캐시 없음). 셋 중 하나라도 실패하면 `502`(부분 응답 없음).
- **KOS 호출**: 병원 1 + 운영 시간 1 + 휴무 1 = 3(동시).
"""
STAFF_DOC = SHARED + """
병원(`clinicId`)의 직원 목록 — `staffId` · 이름 · 역할 이름 · 역할 태그 · 활성. 비활성 직원도 싣는다 · KOS 차례.

- **외주 직원은 역할 이름(`roleName`)으로 구분한다**(예 「CS팀(콜센터)」). `roleTags` 에 `CALL_COUNSELOR` 가 있다고
  외주가 아니다 — 코디 · 관리자에게도 붙는다.
- `staffId` = ccc 직원 사본 id(접수 목록 · 예약 상세의 `counselor.staffId` 와 같다). 사본에 아직 없는 새 계정(1시간 동기화 전)은
  `staffId = null` · `roleTags = []`.
- KOS 시스템 계정 · 서버 제외 목록 계정은 뺀다. 이메일 · 실명 · KOS id 는 내지 않는다.
- **KOS 호출**: 내부 계정 목록 1(`clinicId` 가 다르면 0).
"""
NO_KOS_OR_FAIL = (502, "kos_unavailable", "KOS 조회가 실패했을 때(네트워크 · 5xx · 4xx · KOS 인증 실패 · 응답 모양 오류) · "
                  "서버에 KOS 설정 없음. message 「KOS 에 연결하지 못했어요」")


@router.get("/clinic", response_model=ExtClinic, summary="병원 정보 — 이름 · 전화 · 주소 · 운영 시간 · 휴무",
            description=CLINIC_DOC, responses=errors(*COMMON, NO_KOS_OR_FAIL))
async def clinic(c: Ctr, _: ExtClient) -> ExtClinic:
    return ExtClinic.model_validate(await c.ext.clinic())


@router.get("/clinics/{clinicId}/staff", response_model=ExtStaffList, summary="직원 목록 — 역할 이름 · 태그 · 활성",
            description=STAFF_DOC,
            responses=errors(*COMMON, (400, "invalid_request", "`clinicId` 가 정수가 아님"),
                             (404, "clinic_not_found", "`clinicId` 가 병원 정보의 `clinicId` 가 아닐 때(KOS 를 부르지 않는다). "
                                                       "message 「없는 병원이에요」"), NO_KOS_OR_FAIL))
async def clinic_staff(c: Ctr, _: ExtClient,
                       clinicId: int = Path(description="병원 id — 병원 정보(`GET /api/ext/clinic`)의 `clinicId`(지금은 1)")
                       ) -> ExtStaffList:
    return ExtStaffList.model_validate(await c.ext.staff(clinicId))
