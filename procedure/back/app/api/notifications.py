"""알림 목록 · 읽음 · 설정(SPEC-004 §5-4) — 다섯 역할 모두 · 자기 계정 것만."""

from fastapi import APIRouter

from app.api.deps import Actor, Ctr
from app.schemas.actions import (
    NotificationList,
    NotificationReadRequest,
    NotificationReadResponse,
    NotificationSettingRequest,
    NotificationSettings,
)

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/notifications", response_model=NotificationList)
def notifications(c: Ctr, actor: Actor) -> NotificationList:
    """그 계정 · 오늘(KST) · 최근 50 · 새것 위."""
    return NotificationList.model_validate(c.notifications.listing(actor))


@router.post("/notifications/read", response_model=NotificationReadResponse)
def read(body: NotificationReadRequest, c: Ctr, actor: Actor) -> NotificationReadResponse:
    return NotificationReadResponse(read=c.notifications.read(actor, body.ids, body.callId, body.reservationId))


@router.get("/me/notification-settings", response_model=NotificationSettings)
def settings(c: Ctr, actor: Actor) -> NotificationSettings:
    """그 역할이 받는 종류만 — doctor · admin = doctor_call / counselor = counselor_call / 그 밖 = 빈 목록."""
    return NotificationSettings.model_validate({"items": c.notifications.settings(actor)})


@router.put("/me/notification-settings", response_model=NotificationSettings)
def put_setting(body: NotificationSettingRequest, c: Ctr, actor: Actor) -> NotificationSettings:
    """받지 않는 종류 = 400 setting_not_allowed. 끄면 서버가 그 계정에 보내지 않는다."""
    return NotificationSettings.model_validate({"items": c.notifications.put_setting(actor, body.kind, body.enabled)})
