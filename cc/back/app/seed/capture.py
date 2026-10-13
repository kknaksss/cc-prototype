"""KOS 캡처 읽기(읽기만 — SPEC-001 §3). KOS API 는 부르지 않는다."""

import json
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

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


class Capture:
    def __init__(self, root: Path):
        if not (root / "raw" / "getScheduleDetail").is_dir():
            raise FileNotFoundError(f"CC_CAPTURE_DIR 에 raw/getScheduleDetail 이 없어요: {root}")
        self.root = root
        manifest = json.loads((root / "manifest.json").read_text())
        self.by_visitor: dict[str, dict[str, Path]] = {}
        for r in manifest.get("requests", []):
            vid = (r.get("request") or {}).get("visitorId")
            if vid and r.get("file"):
                self.by_visitor.setdefault(r["operationId"], {})[vid] = root / r["file"]

    def _rows(self, op: str) -> list:
        out: list = []
        for f in sorted((self.root / "raw" / op).glob("*.json")):
            data = json.loads(f.read_text()).get("data")
            out.extend(data if isinstance(data, list) else [data])
        return out

    def schedules(self) -> list[dict]:
        return self._rows("getScheduleDetail")

    def schedule_statistics(self) -> dict[str, dict]:
        return {r["scheduleId"]: r for r in self._rows("getScheduleStatistics")}

    def purchase_items(self) -> list[dict]:
        return self._rows("getPurchaseItemStatistics")

    def reservation_groups(self) -> dict[str, str]:
        return {g["id"]: g.get("title", "") for g in self._rows("getReservationGroups")}

    def per_visitor(self, op: str, visitor_id: str):
        f = self.by_visitor.get(op, {}).get(visitor_id)
        return json.loads(f.read_text()).get("data") if f else None
