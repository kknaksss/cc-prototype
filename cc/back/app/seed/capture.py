"""KOS 시각 값 다루기(UTC 문자열 ↔ epoch ms · KST). 0.2.1 부터 캡처는 직접 읽지 않는다(시나리오 파일)."""

from datetime import UTC, date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def parse_ts(s: str | None) -> int | None:
    """KOS UTC 문자열 → epoch ms."""
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    if "." in s:  # 나노초 자리는 마이크로초로 자른다
        head, _, rest = s.partition(".")
        frac = "".join(ch for ch in rest if ch.isdigit())
        tz = rest[len(frac):]
        s = f"{head}.{frac[:6]}{tz}"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def kst_date(ms: int) -> date:
    return datetime.fromtimestamp(ms / 1000, KST).date()


def hhmm(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%H:%M") if ms is not None else None
