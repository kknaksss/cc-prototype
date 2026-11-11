"""외부 연동 API(SPEC-008 §6 · §7) — 링키 · 차티 같은 연동처용. 헤더 `X-Api-Key` 로만 연다.

- `Authorization` 을 보지 않는다(`require_login` · `Actor` 를 쓰지 않음 — 직원 토큰이 실려도 직원 권한이 되지 않는다)
- 이름 · 이메일은 POST 본문으로만 받는다(경로 · 질의 → 접근 로그) · 로그 · `ext_call` 에 이름 · 이메일 · 키 · IP 0
- 미들웨어(`ext_middleware`): IP 차단(키 검사 전 429) → 응답 → 연동처 없는 오류면 IP 카운트 → `ext_call` 1줄 → `no-store`
"""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response

from app.api.deps import Ctr, get_container
from app.api.docs import T_EXT, errors
from app.api.public_questionnaire import client_ip
from app.domain.errors import TooManyRequests, Unauthorized
from app.schemas.ext import (
    ExtLookupRequest,
    ExtLookupResponse,
    ExtMenu,
    ExtReservationRequest,
    ExtReservationResponse,
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
            "그 키로 최근 60초 안에 60번을 이미 불렀을 때(세 엔드포인트 합산) · 그 IP 의 연동처 없는 오류 응답이 최근 60초 안에 "
            "10번 이상일 때(키 검사 전에 막는다)")
LOOKUP_INVALID = (400, "invalid_request",
                  "본문이 JSON 이 아님(키 검사보다 먼저) · 필수 칸 없음 · 타입 · 모르는 키 · "
                  "앞뒤 공백을 지우면 빈 `name` · `email`. message = `<위치>: <이유>`")
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
1명이 맞으면 그 고객과 **남은 시술권**(KOS 공개 `getTicketBundlesQuery` 1번 · 매번 KOS 에서 읽음 · 저장 안 함)을 준다.

- 고객 칸 = ccc `customerId` · 이름 · 신규 여부 · 최근 방문일만. 전화 · 생년월일 · 국적 · 여권 · 차트번호 · 이메일 · KOS id 없음.
- 시술권은 KOS 값 그대로다: **`bundlePrice` 는 고객이 낸 돈이 아니다** — 산 시점 값에서 출발하지만 GROUP 에서 한 세트를 다
  쓰면 그 세트가 빠져 `totalCount` 와 함께 줄 수 있다 · 부가세 포함 여부는 표기하지 않는다. `AVAILABLE` 이 0장인 묶음은 KOS 가
  주지 않는다. `remainingCount` 는 `AVAILABLE` 만 센다 — `IN_USE`(쓰는 중)는 넣지 않는다.
- 남은 시술권이 없으면 `tickets: []`(고객은 있음). 시술권 조회가 실패하면 빈 배열이 아니라 `502`.
- 부작용: 찾은 고객을 ccc 고객 사본에 덮어쓴다(이메일은 저장하지 않음). KOS 쓰기 없음.
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


@router.post("/customers/lookup", response_model=ExtLookupResponse,
             summary="고객 조회 — 이름 + 이메일 → 고객 + 남은 시술권", description=LOOKUP_DOC,
             responses=errors(*COMMON, LOOKUP_INVALID, NOT_FOUND_ROW, AMBIGUOUS_ROW,
                              (502, "kos_unavailable", "KOS 이름 검색 · 시술권 조회가 실패했을 때(네트워크 · 5xx · 4xx · KOS "
                                                       "인증 실패 · 응답 모양 오류). message 「KOS 에 연결하지 못했어요」")))
async def lookup(body: ExtLookupRequest, c: Ctr, _: ExtClient) -> ExtLookupResponse:
    return ExtLookupResponse.model_validate(await c.ext.lookup(body.name, body.email))


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

