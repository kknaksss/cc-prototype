"""OpenAPI 문서 — 앱 설명(공통 규칙) · 태그 설명 · 문서에만 싣는 Bearer 보안 표시. 요청 처리에는 관여하지 않는다.

`decorate(app)` 는 `app.openapi` 를 감싸 **만들어진 스키마 dict 만** 고친다(라우트 · 의존성 · 처리기는 그대로).
"""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi import routing as fastapi_routing
from fastapi.dependencies.models import Dependant
from fastapi.openapi import utils as openapi_utils

from app.api import docs as d
from app.api.deps import require_login

TITLE = "CCC procedure API"

DESCRIPTION = """
시술 현황판 · 예약 현황 · 직원 앱 · 고객 문진 웹이 쓰는 ccc procedure 백엔드 API.

## 호스트 · 문서
- 운영 호스트: `https://ccc.medisolveai.xyz` — 모든 API 경로는 `/api` 로 시작한다.
- 이 문서: Swagger UI `/api/docs` · ReDoc `/api/redoc` · OpenAPI JSON `/api/openapi.json`(로그인 없이 열린다).

## 인증
1. `POST /api/auth/login` 에 `{"id": "<아이디>", "password": "<비밀번호>"}` → 응답 `token` · `expiresAt`.
2. 그 뒤 요청마다 헤더 `Authorization: Bearer <token>`. Swagger 오른쪽 위 **Authorize** 에 토큰만 넣으면 된다.
- 토큰 수명 = 서버 env `PROC_SESSION_HOURS`(기본 12시간). 만료 시각은 로그인 응답 `expiresAt`. 갱신 · 로그아웃 API 는 없다 —
  만료되면 `401 unauthorized` 이고, 다시 로그인한다.
- 서버는 요청마다 DB 의 지금 계정 값을 다시 본다. 계정이 비활성이 되거나 역할 · staffId 가 토큰 발급 뒤 바뀌면 그 토큰은 바로
  `401 unauthorized` 다.
- 같은 아이디로 로그인이 5번 잇달아 실패하면 60초 동안 `429 too_many_attempts`(서버 메모리 기준 · 재시작하면 지워진다).
- 예외 — 로그인이 필요 없는 곳: `POST /api/auth/login` · `GET /api/health` · 공개 문진(`/api/public/*`).
  SSE(`GET /api/board/stream`)와 통역 WebSocket 은 헤더 대신 `?token=` 을 받는다(아래).

## 역할
계정 역할은 다섯 — `admin`(관리자) · `doctor`(원장) · `nurse`(간호사) · `coordinator`(코디) · `counselor`(상담사).
대부분의 API 는 로그인만 보고 역할을 가리지 않는다. 역할에 따라 `403` 이 나는 곳(예: 원장 호출 수락)은 그 엔드포인트 설명과
응답 표에 허용 역할 · 오류 코드를 적었다. 검사 순서는 `401`(로그인) → `403 fake_board` → 역할 `403` → `404` → `409` 다.

## 가짜 스냅샷 모드
서버 env `PROC_FAKE_BOARD` 가 켜져 있으면 조회 일부(현황판 · 예약 현황)는 지어낸 값을 주고, 쓰기(조작) API 는
`403 fake_board` 로 막힌다. 해당 엔드포인트마다 응답 표에 적었다.

## 오류 형식
오류는 모두 JSON `{"error": {"code": "<코드>", "message": "<한국어 문구>", ...}}` 다. 분기는 `code` 로 한다.
- 요청 검증 오류(타입 · 필수 값 · 범위)는 FastAPI 기본 422 가 아니라 **`400 invalid_request`** 이다.
  `message` = `<위치>: <이유>`(첫 오류 하나만, 예: `body.id: Field required`).
- 없는 경로 = `404 not_found`. 그 밖의 HTTP 오류(예: 허용하지 않는 메서드 405)는 코드 `http_error`.
- 일부 오류는 키를 더 싣는다 — `step`(접수 단계) · `candidate`(같은 고객). `ErrorResponse` 스키마 참고.
- KOS 연동 실패는 `409 kos_rejected`(KOS 가 4xx 로 거절) · `502 kos_unavailable`(네트워크 · 5xx · KOS 인증 실패)로 온다.

## 형식
- 요청 · 응답 본문은 JSON(필드 이름 camelCase). 예외:
  - **업로드** = `multipart/form-data` — 여권 스캔(`POST /api/customers/{customer_id}/passport-scan`) ·
    채팅 사진(`POST /api/chat/photos`) · 채팅 동영상(`POST /api/chat/videos`). 칸은 각 엔드포인트 참고.
  - **다운로드** = 바이너리 본문(`image/jpeg` · `video/mp4`) — 신분증 사진 · 채팅 사진 · 동영상 · 썸네일.
    `Authorization` 헤더로만 열린다(`?token=` · 쿠키 없음) · `Cache-Control: no-store`.
- 시각: 서버가 만드는 시각은 ISO 8601 · 한국 시간 오프셋(`+09:00`) · 초 단위(예: `2026-01-01T09:30:00+09:00`).
  채팅 API 의 시각은 밀리초까지(예: `2026-01-01T09:30:00.123+09:00`). 날짜는 `YYYY-MM-DD`(한국 날짜).
  필드마다 다른 형식은 그 필드 설명을 따른다. 「오늘」은 한국 시간(Asia/Seoul) 기준이다.

## 공개 문진(고객 웹)
`/api/public/*` 는 로그인 없이 헤더 **`X-Questionnaire-Token`**(문진 링크의 토큰)으로만 연다. `Authorization` 은 보지 않는다
(직원 토큰이 실려도 직원 권한이 되지 않는다). 응답(오류 포함)에 `Cache-Control: no-store` · `Referrer-Policy: no-referrer`.

## 실시간 — SSE
`GET /api/board/stream?token=<토큰>` (선택 `&deviceId=<기기 id>`) — 브라우저 `EventSource` 는 헤더를 못 실어서 쿼리로 받는다.
이벤트 종류 · 본문은 그 엔드포인트 설명 참고.

## 통역 WebSocket — `WS /api/interpret`
OpenAPI 는 WebSocket 을 싣지 못해 여기 적는다. 한국어 ↔ 고른 언어 양방향 실시간 통역 중계(자막 + 번역 음성).
- **연결**: `wss://ccc.medisolveai.xyz/api/interpret`. 토큰 = 핸드셰이크 헤더 `Authorization: Bearer <토큰>`(앱) 또는
  `?token=<토큰>`(브라우저). 다섯 역할 모두.
  - `Origin` 헤더가 있으면 서버 env `PROC_INTERPRET_ORIGIN`(비면 `PROC_FRONT_ORIGIN`)과 같아야 한다. 없으면(앱) 토큰만 본다.
  - 출처가 다르거나 토큰이 없음 · 틀림 · 만료 · 비활성이면 연결을 받지 않고 코드 1008 로 닫는다(핸드셰이크 거절).
- **클라이언트 → 서버**
  - 첫 프레임(연결 뒤 10초 안 · 텍스트): `{"type": "start", "lang": "zh", "traditional": false}`
    - `lang`(필수) = 상대 언어 — `zh` · `en` · `ja` · `th` · `fr` · `es` · `tl` · `hi` 중 하나.
    - `traditional`(선택 · 기본 false) = true 면 중국어 자막을 번체로 바꿔 보낸다.
    - `scheduleId`(선택) — 서버가 읽기만 하고 쓰지 않는다.
  - 바이너리 프레임 = 마이크 음성 PCM(s16le · 16kHz · mono).
  - 텍스트 `{"type": "pause"}`(말하던 것을 확정해 내보내고 음성 무시) · `{"type": "resume"}` · `{"type": "stop"}`(남은 자막을
    최대 3초 기다려 보내고 끝냄).
- **서버 → 클라이언트**
  - `{"type": "ready"}` — 통역 준비 끝. 이 뒤로 음성을 보낸다.
  - `{"type": "caption", "id": "u1", "side": "me", "original": "…", "translation": "…", "final": false}` — 자막.
    같은 `id` 가 `final: false` 로 여러 번 갱신되다가 `final: true` 로 한 번 확정된다. `side` = `me`(한국어로 말함) ·
    `them`(상대 언어로 말함). `original` = 들은 말 · `translation` = 번역.
  - `{"type": "audio_start", "id": "u1", "sampleRate": 24000}` → 바이너리 프레임들(번역 음성 PCM s16le · 24kHz) →
    `{"type": "audio_end", "id": "u1"}` — 확정된 자막의 번역을 읽은 음성.
  - `{"type": "error", "code": "…", "message": "…"}` — `bad_request`(start 형식 · 언어 · 알 수 없는 프레임) ·
    `no_api_key`(서버에 통역 키 없음) · `soniox_unavailable`(통역 서버 연결 실패 · 끊김). `bad_request` 중 알 수 없는 프레임은
    연결을 유지하고, 나머지는 보낸 뒤 연결을 닫는다.
"""

_TAG_TEXT = {
    d.T_AUTH: "로그인 · 내 계정. 로그인 응답 토큰을 `Authorization: Bearer` 에 싣는다.",
    d.T_BOARD: "시술 현황판 — 오늘 고객 카드 스냅샷 · 카드 순서 · 실시간 SSE 스트림.",
    d.T_ACTIONS: ("현황판 조작 — 마취 · 원장 호출 · 수락 · 시술 시작/종료 · 되돌리기 · 귀가. "
                  "응답은 짧고, 화면은 뒤따르는 SSE `board` 이벤트로 바뀐다."),
    d.T_RESV: ("예약 현황 — 날짜별 예약판 · 예약 상세 · 예약 만들기 · 옮기기 · 취소 · 메모 · 공지 · "
               "접수 · 상담 호출 · 상담 추가 · 귀가."),
    d.T_CUSTOMER: "고객 — 검색 · 개인 정보 · 특이사항 · 신분 확인 · 유입 채널.",
    d.T_NOTI: "내 알림 목록 · 읽음 · 알림 종류별 켜기/끄기.",
    d.T_DEVICE: "앱 기기(푸시 토큰) 등록 · 해제.",
    d.T_DISPLAY: ("띄우기 요청 — 예약 상세에서 「이 예약의 문진(questionnaire) / 여권 스캔(scan)을 "
                  "코디 기기에 띄워라」. QR claim · 기기별 pending 조회 · 닫기."),
    d.T_PUBLIC: "고객 문진 웹 — 로그인 없이 `X-Questionnaire-Token` 헤더로 연다.",
    d.T_PHOTO: "여권 스캔 · 신분증 사진 열람 · KOS 재전송 · 삭제.",
    d.T_CHAT: "직원 채팅 — 사람 · 방 · 메시지 · 읽음 · 사진 · 동영상. 다섯 역할 모두 · 가짜 스냅샷 모드에서도 된다.",
    d.T_HEALTH: "서버 상태 확인(로그인 없음).",
}
TAGS: list[dict[str, str]] = [{"name": k, "description": v} for k, v in _TAG_TEXT.items()]


BEARER = "BearerAuth"


def _needs_login(dep: Dependant) -> bool:
    return dep.call is require_login or any(_needs_login(x) for x in dep.dependencies)


def _api_routes(routes: list[Any]) -> list[Any]:
    """OpenAPI 를 만드는 FastAPI 와 같은 길로 라우트를 편다 — 0.15x 는 include_router 를 펼치지 않고 감싸 둔다(_IncludedRouter).

    돌려받는 값은 라우터 dependencies 까지 합친 유효 라우트(path_format · methods · dependant)."""
    out = []
    for ctx in fastapi_routing.iter_route_contexts(routes):
        r = openapi_utils._get_api_route_for_openapi(ctx)
        if r is not None:
            out.append(r)
    return out


def _refs(node: Any) -> set[str]:
    if isinstance(node, dict):
        out = {node["$ref"]} if isinstance(node.get("$ref"), str) else set()
        for v in node.values():
            out |= _refs(v)
        return out
    if isinstance(node, list):
        return set().union(*(_refs(v) for v in node)) if node else set()
    return set()


def _patch(schema: dict[str, Any], routes: list[Any]) -> None:
    comps = schema.setdefault("components", {})
    comps["securitySchemes"] = {BEARER: {
        "type": "http", "scheme": "bearer",
        "description": "`POST /api/auth/login` 응답의 `token`. 헤더 `Authorization: Bearer <token>` 으로 보낸다."}}
    paths = schema.get("paths", {})
    for r in _api_routes(routes):
        if r.include_in_schema and _needs_login(r.dependant):
            for m in r.methods or ():
                op = paths.get(r.path_format, {}).get(m.lower())
                if op is not None:
                    op["security"] = [{BEARER: []}]
    # FastAPI 기본 422 는 이 서버가 내지 않는다(검증 오류 = 400 invalid_request · main 의 처리기) — 문서에서 뺀다
    for item in paths.values():
        for op in item.values():
            if isinstance(op, dict):
                op.get("responses", {}).pop("422", None)
    schemas = comps.get("schemas", {})
    used = _refs(paths) | _refs({k: v for k, v in schemas.items() if k not in ("HTTPValidationError", "ValidationError")})
    for name in ("HTTPValidationError", "ValidationError"):
        if f"#/components/schemas/{name}" not in used:
            schemas.pop(name, None)


def decorate(app: FastAPI) -> None:
    """`app.openapi` 를 감싼다 — 처음 만들 때 한 번만 스키마를 고치고, 그 뒤는 FastAPI 캐시(app.openapi_schema)를 그대로."""
    original: Callable[[], dict[str, Any]] = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = original()
        _patch(schema, app.routes)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
