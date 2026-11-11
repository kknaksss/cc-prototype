"""알림 목록 · 읽음 · 설정(SPEC-004 §5-4) — 다섯 역할 모두 · 자기 계정 것만."""

from fastapi import APIRouter

from app.api.deps import Actor, Ctr
from app.api.docs import INVALID, T_NOTI, UNAUTHORIZED, errors
from app.schemas.actions import (
    NotificationList,
    NotificationReadRequest,
    NotificationReadResponse,
    NotificationSettingRequest,
    NotificationSettings,
)

router = APIRouter(prefix="/api", tags=[T_NOTI])

KINDS = """
알림 종류는 둘 — `doctor_call`(원장 호출 · 받는 역할 `admin` · `doctor`) · `counselor_call`(상담사 호출 · 받는 역할 `counselor`).
알림 행은 호출 푸시를 보낼 때 받는 계정마다 1행 생긴다(기기가 없어도). 띄우기 · 채팅 푸시는 알림 목록에 들어가지 않는다.
"""


@router.get(
    "/notifications", response_model=NotificationList,
    summary="내 알림 목록 — 오늘 · 최근 50",
    description="""
지금 계정의 오늘(KST 00:00 이후) 알림 — 새것 먼저 · 최대 50건 + 오늘 안 읽은 수. 다섯 역할 모두 · 자기 계정 것만.
읽기만 한다(읽음 처리 안 함).
""" + KINDS,
    responses=errors(UNAUTHORIZED),
)
def notifications(c: Ctr, actor: Actor) -> NotificationList:
    """그 계정 · 오늘(KST) · 최근 50 · 새것 위."""
    return NotificationList.model_validate(c.notifications.listing(actor))


@router.post(
    "/notifications/read", response_model=NotificationReadResponse,
    summary="알림 읽음 처리",
    description="""
지금 계정의 **안 읽은** 알림을 읽음(지금 시각)으로 바꾼다. 다섯 역할 모두 · 자기 계정 것만(남의 id 는 무시).

- 고르기: `ids` · `callId` · `reservationId` 중 보낸 조건을 모두 만족하는 것(AND). 셋 다 없으면 그 계정의 안 읽은 알림 **전부**
  (오늘 것만이 아님). `ids: []` = 아무것도 안 바꿈.
- 푸시를 눌러 열 때는 푸시 payload 의 `callId`(원장 호출) · `reservationId`(상담사 호출)로 보낸다.
- 응답 `read` = 이번에 바뀐 수. 반복 = 두 번째부터 0(멱등). SSE `notification` 은 보내지 않는다.
""",
    responses=errors(INVALID, UNAUTHORIZED),
)
def read(body: NotificationReadRequest, c: Ctr, actor: Actor) -> NotificationReadResponse:
    return NotificationReadResponse(read=c.notifications.read(actor, body.ids, body.callId, body.reservationId))


@router.get(
    "/me/notification-settings", response_model=NotificationSettings,
    summary="내 알림 설정 보기",
    description="""
지금 계정 역할이 받는 알림 종류의 켜짐 여부. `doctor` · `admin` = `doctor_call` · `counselor` = `counselor_call` ·
`nurse` · `coordinator` = 빈 목록. 저장한 적 없으면 켜짐(true). 다섯 역할 모두.
""",
    responses=errors(UNAUTHORIZED),
)
def settings(c: Ctr, actor: Actor) -> NotificationSettings:
    """그 역할이 받는 종류만 — doctor · admin = doctor_call / counselor = counselor_call / 그 밖 = 빈 목록."""
    return NotificationSettings.model_validate({"items": c.notifications.settings(actor)})


@router.put(
    "/me/notification-settings", response_model=NotificationSettings,
    summary="내 알림 설정 바꾸기",
    description="""
알림 종류 하나를 켜거나 끈다. 응답 = 바꾼 뒤 전체 설정(GET 과 같은 모양). 다섯 역할 모두(받는 종류가 없는 `nurse` ·
`coordinator` 는 늘 400).

- 끄면 서버가 그 계정에 그 종류의 알림 행 · 푸시를 만들지 않는다(다른 계정에는 영향 없음).
- 역할이 받지 않는 종류 = `400 setting_not_allowed`. 같은 값 반복 = 같은 결과(멱등).
""",
    responses=errors(
        INVALID, UNAUTHORIZED,
        (400, "setting_not_allowed", "그 역할이 받지 않는 알림 종류일 때(모르는 값 포함)"),
    ),
)
def put_setting(body: NotificationSettingRequest, c: Ctr, actor: Actor) -> NotificationSettings:
    """받지 않는 종류 = 400 setting_not_allowed. 끄면 서버가 그 계정에 보내지 않는다."""
    return NotificationSettings.model_validate({"items": c.notifications.put_setting(actor, body.kind, body.enabled)})
