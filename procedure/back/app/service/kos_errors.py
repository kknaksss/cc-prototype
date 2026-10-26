"""KOS 실패 → 도메인 예외(SPEC-005 §4.4) — 4xx = 409 kos_rejected · 네트워크 · 5xx · 401 = 502 kos_unavailable."""

from app.domain.errors import BadGateway, Conflict
from app.kos.client import KosError

UNAVAILABLE = "KOS 에 연결하지 못했어요"


def rejected_message(e: KosError) -> str:
    """문구 = `errorProperties` 의 key · reason 먼저, 없으면 className(§4.4 표)."""
    for p in e.error_properties:
        key, reason = p.get("key") or "", p.get("reason") or ""
        if key == "startDateTime" and reason == "NotAvailable":
            return "같은 고객의 예약이 그 시간에 있어요"
        if key.startswith("occupiedResources") and key.endswith("startDateTimeUtc") and reason == "NotAvailable":
            return "묶음 날짜가 서로 달라요"
        if reason == "ReservationCapacityExceeded":
            return "그 시간은 정원이 찼어요"
        if reason == "ReservationNotAllowedByPolicy":
            return "예약 정책상 바꿀 수 없어요"
        if key == "status" and reason == "NotAvailable":
            return "지금 상태에서는 취소할 수 없어요"
    if e.name == "ReservationCapacityExceeded":
        return "그 시간은 정원이 찼어요"
    if e.name == "ReservationNotAllowedByPolicy":
        return "예약 정책상 바꿀 수 없어요"
    return f"KOS 가 거절했어요 ({e.name or str(e)})"


def is_rejection(e: Exception) -> bool:
    return isinstance(e, KosError) and e.status is not None and 400 <= e.status < 500 and e.status != 401


def to_domain(e: Exception, step: str | None = None) -> Conflict | BadGateway:
    if is_rejection(e):
        return Conflict("kos_rejected", rejected_message(e), step=step)  # type: ignore[arg-type]
    return BadGateway("kos_unavailable", UNAVAILABLE, step=step)


def describe(e: Exception) -> str:
    """event_log · 로그용 — 상태 · 이름만(본문 · 값 없음)."""
    return str(e) if isinstance(e, KosError) else type(e).__name__
