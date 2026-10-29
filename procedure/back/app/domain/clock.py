"""시각 — 저장 · KOS 는 UTC, 화면 · 조회 시간 판정은 KST(SPEC-003 §2.3)."""

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


class Clock:
    """지금 시각. 시험은 `set()` 으로 고정한다."""

    def __init__(self, fn: Callable[[], datetime] | None = None):
        self._fn = fn or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        return self._fn()

    def set(self, at: datetime) -> None:
        self._fn = lambda: at


def iso(at: datetime | None) -> str | None:
    """화면용 ISO(KST 오프셋)."""
    return at.astimezone(KST).isoformat(timespec="seconds") if at else None


def to_db(at: datetime | None) -> str | None:
    """DB 저장용 ISO(UTC)."""
    return at.astimezone(UTC).isoformat(timespec="seconds") if at else None


def iso_ms(at: datetime | None) -> str | None:
    """채팅 API 시각(SPEC-007 §6.1) — KST 오프셋 · 밀리초. `iso` 는 초라 채팅 `since` 경계에 쓰지 않는다."""
    return at.astimezone(KST).isoformat(timespec="milliseconds") if at else None


def to_db_ms(at: datetime | None) -> str | None:
    """채팅 표 시각(SPEC-007 §3) — UTC · 밀리초 · 늘 같은 폭(`…T…:…:….mmm+00:00`)이라 SQL 문자열 비교 = 시간 순."""
    return at.astimezone(UTC).isoformat(timespec="milliseconds") if at else None


def parse(value: str | None) -> datetime | None:
    """KOS · DB 의 ISO 문자열 → aware datetime(오프셋 없으면 UTC 로 본다)."""
    if not value:
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def kos_utc(at: datetime) -> str:
    """KOS 요청용 UTC 문자열(`…Z`)."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def today_range_kst(now: datetime) -> tuple[datetime, datetime]:
    """오늘(KST) 00:00 ~ 다음날 00:00 — aware."""
    local = now.astimezone(KST)
    start = datetime.combine(local.date(), time(0), tzinfo=KST)
    return start, start + timedelta(days=1)


def kst_day(now: datetime) -> str:
    """오늘(KST) 날짜 `YYYY-MM-DD` — 카드 순서(board_order)의 하루 단위."""
    return now.astimezone(KST).date().isoformat()


def in_window(now: datetime, window: tuple[time, time]) -> bool:
    """조회 시간(KST) 안인가 — 시작 포함 · 끝 제외(D-08)."""
    t = now.astimezone(KST).time()
    start, end = window
    return start <= t < end


def minutes_between(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)
