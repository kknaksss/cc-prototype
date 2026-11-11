"""OpenAPI 문서 전용 — 오류 응답 모델 · `responses=` 를 만드는 도우미. 요청 처리에는 쓰이지 않는다.

여기 모델은 `responses={...: {"model": ...}}` 로만 싣는다(`response_model` 이 아니라 응답 거르기 · 직렬화를 바꾸지 않는다).
"""

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DuplicateCandidate(BaseModel):
    """`duplicated_visitor`(409) 오류에만 실리는 KOS 쪽 같은 고객."""

    customerId: int = Field(description="ccc 고객 id — KOS 고객을 ccc 사본에 넣은(또는 이미 있던) 행의 id")
    name: str = Field(description="KOS 고객 이름. KOS 가 이름을 안 주면 빈 문자열")
    chartNumber: str | None = Field(description="KOS 차트 번호. KOS 가 안 주면 null")
    dateOfBirth: str | None = Field(description="생년월일 `YYYY-MM-DD`(KOS 값의 앞 10자). KOS 가 안 주면 null")


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str = Field(description=(
        "오류 코드(영문 snake_case). 클라이언트는 이 값으로 분기한다. 값과 뜻은 각 엔드포인트의 응답 설명 참고"))
    message: str = Field(description=(
        "사람이 읽는 한국어 문구. 화면에 그대로 보여 줄 수 있다. 문구는 바뀔 수 있으니 분기에 쓰지 않는다"))
    step: str | None = Field(default=None, description=(
        "접수(`POST /api/reservations/{reservation_id}/reception`)에서 KOS 쓰기 · 다시 읽기가 실패했을 때만 실린다 — "
        "실패한 단계 이름 `recept` · `add_task` · `read_sequence` · `assign_room` · `flow_step`. 그 밖의 오류에는 키가 없다"))
    candidate: DuplicateCandidate | None = Field(default=None, description=(
        "`duplicated_visitor`(409 · 예약 생성의 새 고객)에만 실린다 — KOS 에 이미 있는 같은 고객. 그 밖의 오류에는 키가 없다"))


class ErrorResponse(BaseModel):
    """모든 오류 응답의 모양 — `{"error": {"code", "message", ...}}`."""

    error: ErrorDetail = Field(description="오류 내용. `step` · `candidate` 는 해당 오류에만 있다")


# 태그 이름 — 라우터 `tags=` 와 main 의 openapi_tags 가 이 값을 같이 쓴다
T_AUTH, T_BOARD, T_ACTIONS, T_RESV, T_CUSTOMER = "인증", "현황판", "조작", "예약", "고객"
T_NOTI, T_DEVICE, T_DISPLAY, T_PUBLIC, T_PHOTO, T_CHAT, T_HEALTH = (
    "알림", "기기", "표시 요청", "공개 문진", "신분증 사진", "채팅", "상태")
T_EXT = "외부 연동"

STATUS_TEXT = {400: "요청이 잘못됨", 401: "로그인 필요", 403: "권한 없음", 404: "없음", 409: "지금 상태와 충돌",
               405: "허용하지 않는 메서드",
               410: "만료 · 무효", 413: "파일이 너무 큼", 429: "요청이 너무 많음", 500: "서버 오류",
               502: "KOS 연결 실패", 503: "지금 쓸 수 없음"}

# 자주 쓰는 오류 — (상태, 코드, 언제)
INVALID = (400, "invalid_request",
           "요청 본문 · 경로 · 쿼리 · 헤더 형식이 맞지 않을 때(타입 · 필수 · 범위). message = `<위치>: <이유>`")
UNAUTHORIZED = (401, "unauthorized",
                "`Authorization: Bearer` 토큰이 없거나 · 서명이 틀리거나 · 만료됐거나 · 계정이 비활성 · 삭제됐거나 · "
                "역할 · staffId 가 토큰 발급 뒤 바뀌었을 때. 서버에 서명 키(env `PROC_SESSION_SECRET`)가 없어도 늘 401")
FAKE_BOARD = (403, "fake_board", "서버가 가짜 스냅샷 모드(env `PROC_FAKE_BOARD`)일 때 — 조작(쓰기)을 막는다")
KOS_REJECTED = (409, "kos_rejected", "KOS 가 4xx(401 제외)로 거절했을 때. message = 거절 이유를 옮긴 한국어 문구")
KOS_UNAVAILABLE = (502, "kos_unavailable", "KOS 네트워크 오류 · 5xx · 401 · 응답 형식이 맞지 않을 때")

Err = tuple[int, str, str]


def errors(*items: Err) -> dict[int | str, dict[str, Any]]:
    """`responses=` 값 — 상태별로 묶어 `- code — 언제` 목록을 설명에 쓴다. 모두 같은 ErrorResponse 모양."""
    by: dict[int, list[str]] = defaultdict(list)
    for status, code, when in items:
        by[status].append(f"- `{code}` — {when}")
    return {s: {"model": ErrorResponse, "description": f"{STATUS_TEXT.get(s, '오류')}\n\n" + "\n".join(lines)}
            for s, lines in sorted(by.items())}


def binary(media_type: str, description: str) -> dict[int | str, dict[str, Any]]:
    """바이너리 200 응답(이미지 · 동영상) — 본문 스키마 = 바이트."""
    return {200: {"description": description,
                  "content": {media_type: {"schema": {"type": "string", "format": "binary"}}}}}
