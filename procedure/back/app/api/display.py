"""띄우기 요청(SPEC-004 §5-3) — 다섯 역할 모두. pending · claim 은 부른 기기 · 계정 것만(남의 기기 = 404 device_not_found)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.deps import Actor, Ctr
from app.api.docs import INVALID, T_DEVICE, T_DISPLAY, UNAUTHORIZED, errors
from app.schemas.actions import (
    ClaimDisplayRequest,
    CloseDisplayRequest,
    CreateDisplayRequest,
    CreateDisplayResponse,
    DisplayPending,
    DisplayRequestItem,
    DisplayTarget,
    OkResponse,
)

router = APIRouter(prefix="/api")

DEVICE_404 = (404, "device_not_found", "`deviceId` 가 없는 기기이거나 다른 계정의 기기일 때")
DISPLAY_404 = (404, "display_not_found", "띄우기 요청을 찾을 수 없을 때")
STATUS = """
상태: `pending`(만듦 · 아직 안 엶) → `opened`(스캔 = 기기가 받아감 / 문진 = 고객이 링크를 엶) → `done` · `canceled` ·
`expired`. 여는 시한(만든 뒤 env `PROC_DISPLAY_TTL_MIN` · 기본 10분)이 지난 pending 은 expired, 문진 종류 opened 는 연 뒤
env `PROC_QWEB_FILL_MIN`(기본 60분)이 지나면 expired. 만료는 따로 도는 작업이 없고 pending 조회 · claim · 닫기 · 예약 상세 ·
공개 문진 API 를 부를 때 먼저 반영한다(기기 목록 · 만들기는 반영하지 않는다 — 만들기는 같은 예약 · 종류의 열린 요청을 시한과
상관없이 `canceled` 로 닫으므로, 시한이 지났는데 아직 pending 인 요청도 expired 가 아니라 canceled 가 된다).
"""


@router.get(
    "/devices/targets", response_model=list[DisplayTarget], tags=[T_DEVICE, T_DISPLAY],
    summary="띄우기 대상 기기 목록 — 코디 기기",
    description="""
띄우기(문진 · 여권 스캔)를 보낼 수 있는 기기 — **active `coordinator` 계정**의 기기 중 `lastSeenAt` 이 24시간 안인 것.
다섯 역할 모두 부를 수 있다. 읽기만 한다.

- 순서 = `lastSeenAt` 최근 순. 같은 계정 · 같은 `installId` 는 가장 최근 1개만. installId 있는 행이 생긴 계정의 옛
  (installId 없는) 같은 종류 행은 뺀다.
- `online` = 지금 그 기기로 연 SSE 연결이 있나(서버 메모리 — 끊긴 연결은 다음 ping 전까지 online 으로 보일 수 있다).
""",
    responses=errors(UNAUTHORIZED),
)
def targets(c: Ctr, _: Actor) -> list[DisplayTarget]:
    """코디 계정 기기 중 last_seen_at 24시간 안 · 최근 순 · online = 지금 SSE 열림."""
    return [DisplayTarget.model_validate(x) for x in c.display.targets()]


@router.post(
    "/display-requests", response_model=CreateDisplayResponse, tags=[T_DISPLAY],
    summary="띄우기 요청 만들기 — 문진 · 여권 스캔을 기기에",
    description="""
예약 하나의 문진(`questionnaire`) 또는 여권 스캔(`scan`)을 기기에 띄우라고 요청한다. 다섯 역할 모두.
`PROC_FAKE_BOARD` 와 상관없이 동작한다.

- 같은 예약 · 같은 종류의 열린 요청을 먼저 `canceled` 로 닫는다(스캔 = pending 만 · 문진 = pending · opened 둘 다 — 옛 링크 무효).
- 새 요청 = pending · 여는 시한 `expiresAt`. event_log `display_request`.
- **스캔**: 응답 `qrToken`(1회용 · QR 로 다른 기기가 `POST /api/display-requests/claim`) · `qrUrl` = null.
- **문진**: 응답 `qrUrl` = 고객 문진 웹 링크(`{PROC_FRONT_ORIGIN}/q#<토큰>` — 고객이 자기 폰으로 연다 · 공개 문진 API 의
  `X-Questionnaire-Token` 이 이 토큰) · `qrToken` = null.
- `deviceId` 를 주면: 그 기기 SSE 가 열려 있으면 그 기기 연결에만 `event: display`
  `{requestId, deviceId, kind, reservationId, qrUrl?}` + **늘** 그 기기로 APNs 푸시(제목 「고객 입력 요청」/「여권 스캔 요청」 ·
  본문 「데스크에서 보냈어요」 · 소리 없음 · 알림 목록에 안 들어감 · APNs 설정이 없으면 기록만). 기기는 계정을 가리지 않는다
  (있는 기기면 된다).
- 반복 호출 = 앞 요청을 닫고 새로 만든다(멱등 아님). KOS 쓰기 없음.
""" + STATUS,
    responses=errors(
        INVALID, UNAUTHORIZED,
        (404, "not_found", "`reservationId` 예약이 없을 때"),
        (404, "device_not_found", "`deviceId` 기기가 없을 때"),
    ),
)
async def create(body: CreateDisplayRequest, c: Ctr, actor: Actor) -> CreateDisplayResponse:
    """async — 띄우기 푸시를 이벤트 루프에 태스크로 띄운다(sync 면 스레드라 루프가 없어 건너뜀 · 리뷰 r1 FAIL-1)."""
    return CreateDisplayResponse.model_validate(c.display.create(actor, body.reservationId, body.kind, body.deviceId))


@router.get(
    "/display-requests/pending", response_model=DisplayPending, tags=[T_DISPLAY],
    summary="내 기기에 온 띄우기 요청 — pending · opened",
    description="""
그 기기(자기 계정 기기여야)에 온 열린 요청(pending · opened)을 만든 순으로 돌려준다. 앱이 SSE · 푸시를 놓쳤을 때 메우는 길.
다섯 역할 모두.

- `deviceId` 필수(없으면 `400 invalid_request`). 그 기기의 `lastSeenAt` = 지금.
- 부작용: **스캔 종류 pending 은 돌려주면서 `opened` 로 바꾼다**(응답에도 opened). 문진 종류는 그대로(opened = 고객이 엶).
- `qrUrl` 은 문진 종류 · pending 일 때만.
""" + STATUS,
    responses=errors(
        (400, "invalid_request", "`deviceId` 가 없거나 정수가 아닐 때"),
        UNAUTHORIZED, DEVICE_404,
    ),
)
def pending(c: Ctr, actor: Actor,
            deviceId: Annotated[int | None, Query(description="자기 계정 기기 id(필수 — 없으면 400)")] = None,  # noqa: N803 — 계약 이름
            ) -> DisplayPending:
    """deviceId 필수(없으면 400) — 그 기기 pending(+ 열린 것) · 돌려주며 opened."""
    return DisplayPending.model_validate({"items": c.display.pending(actor, deviceId)})


@router.post(
    "/display-requests/claim", response_model=DisplayRequestItem, tags=[T_DISPLAY],
    summary="QR 로 띄우기 요청 받기 — 스캔 종류",
    description="""
QR 에서 읽은 `qrToken`(스캔 종류)으로 요청을 받아 `opened` 로 바꾼다. **1회** —
이미 받은(pending 아닌) 요청은 `409 display_closed`.
다섯 역할 모두.

- `deviceId` 를 주면 자기 계정 기기여야 하고(`lastSeenAt` = 지금), 그 요청을 이 기기 것으로 바꾼다(다른 기기로 보낸 요청이어도).
- 문진 종류 토큰은 이 길이 아니다(`404 display_not_found`).
- 만료는 먼저 따로 저장한다(뒤에서 409 가 나도 expired 는 남음). KOS 쓰기 · SSE · 푸시 없음.
""" + STATUS,
    responses=errors(
        INVALID, UNAUTHORIZED, DEVICE_404,
        (404, "display_not_found", "토큰에 맞는 요청이 없거나 문진 종류일 때"),
        (409, "display_expired", "여는 시한이 지났을 때"),
        (409, "display_closed", "이미 받았거나(opened) 닫힌(done · canceled) 요청일 때"),
    ),
)
def claim(body: ClaimDisplayRequest, c: Ctr, actor: Actor) -> DisplayRequestItem:
    """QR(ccc://display?t=) — 1회 · 유효 10분 · deviceId 가 있으면 그 기기 요청으로 묶음."""
    return DisplayRequestItem.model_validate(c.display.claim(actor, body.qrToken, body.deviceId))


@router.post(
    "/display-requests/{request_id}/close", response_model=OkResponse, tags=[T_DISPLAY],
    summary="띄우기 요청 닫기 — done · canceled",
    description="""
열린(pending · opened) 요청을 `done` 또는 `canceled` 로 닫는다. 다섯 역할 모두 · 요청을 만든 계정 · 기기와 상관없이 닫을 수 있다.
event_log `display_close`. KOS 쓰기 · SSE · 푸시 없음.

반복: 이미 닫혔으면 `409 display_closed`(expired 면 `409 display_expired`). 서버가 대신 done 으로 닫는 경우: 공개 문진 제출이
성공하면 그 링크의 요청 · 여권 스캔 저장이 성공하고 본문에 `displayRequestId` 를 보냈으면 그 id 의 요청(종류 · 예약 검사 없이 ·
이미 닫혔거나 없으면 그대로). `displayRequestId` 없이 스캔을 저장하면 요청은 열린 채로 남는다.
""" + STATUS,
    responses=errors(
        INVALID, UNAUTHORIZED, DISPLAY_404,
        (409, "display_expired", "이미 만료된 요청일 때"),
        (409, "display_closed", "이미 done · canceled 로 닫힌 요청일 때"),
    ),
)
def close(request_id: Annotated[int, Path(description="띄우기 요청 id(만들기 응답 `id` · `requestId`)")],
          body: CloseDisplayRequest, c: Ctr, actor: Actor) -> OkResponse:
    c.display.close(actor, request_id, body.status)
    return OkResponse()
