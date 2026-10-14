"""현황판 칸 — 시안 `LAYOUT` · `capOf` · `isSleep` · `roomName` 이식(SPEC-001 0.2.0: 라운지 → 접수대기실 `reception`,
수면실 → 수면시술실) + KOS 방 대응표(D-13, 참고용 — 0.2.0 시드는 쓰지 않는다)."""

import re

RECEPTION = "reception"  # 접수대기실 — 고객 location 값과 같다
TRACK = {1: 1, 2: 2, 3: 4, 4: 5, 5: 6, 6: 8}


def _rm(rid: str, name: str, col: int, row: int, cs: int = 1) -> dict:
    return {"id": rid, "name": name, "col": col, "row": TRACK[row], "cs": cs}


def _care(n: int, col: int, row: int) -> dict:
    return _rm(f"c{n:02d}", f"관리실 {n:02d}", col, row)


LAYOUT: list[dict] = [
    _rm("t02", "2인관리실 02", 3, 1, 2), _rm("t03", "2인관리실 03", 5, 1, 2),
    _care(11, 3, 2), _care(12, 4, 2), _care(13, 5, 2), _care(14, 6, 2), _care(15, 7, 2), _care(16, 8, 2),
    _rm("desk", "데스크", 1, 3), _rm(RECEPTION, "접수대기실", 2, 3, 2), _rm("info2", "인포 2", 7, 3),
    _rm("s02", "수면시술실 02", 8, 3),
    _rm("consult", "상담실", 2, 4), _care(4, 6, 4), _rm("s03", "수면시술실 03", 8, 4),
    _care(1, 1, 5), _care(2, 2, 5), _care(3, 3, 5), _rm("info1", "인포 1", 4, 5), _rm("s01", "수면시술실 01", 8, 5),
    _care(5, 1, 6), _care(6, 2, 6), _care(7, 3, 6), _care(8, 4, 6), _care(9, 5, 6), _care(10, 6, 6),
    _rm("t01", "2인관리실 01", 7, 6, 2),
]
CORRIDORS = [{"row": 3}, {"row": 7}]
ROOM_IDS = {r["id"] for r in LAYOUT}

# KOS `tasks[].room.title` → 현황판 칸 id (orchestration/work/sts-prototype/room-map-provisional.md 그대로)
KOS_ROOM_MAP: dict[str, str] = {
    **{f"A_룸{n}": f"c{n:02d}" for n in range(1, 10)},
    "A_트윈1-1": "t01",
    "A_트윈1-2": "t01",
    "A_시술실1": "s01",
    "A_시술실2": "s02",
    "A_레이저실": "c10",
}


def map_kos_room(title: str | None) -> str | None:
    return KOS_ROOM_MAP.get((title or "").strip())


def room_name(rid: str | None) -> str:
    if rid == "office":
        return "원장실"
    for r in LAYOUT:
        if r["id"] == rid:
            return r["name"]
    return rid or ""


def cap_of(rid: str | None) -> int:
    rid = rid or ""
    if re.match(r"^t\d", rid):
        return 2
    if re.match(r"^(c\d|s\d)", rid):
        return 1
    return 0


def is_sleep(rid: str | None) -> bool:
    return bool(re.match(r"^s\d", rid or ""))


def is_treatment_room(rid: str | None) -> bool:
    """접수대기실에서 고객을 넣을 수 있는 칸 — 관리실 · 2인관리실(시안 freeRooms)."""
    return bool(re.match(r"^(c\d|t\d)", rid or ""))


def rooms_payload() -> list[dict]:
    return [{**r, "cap": cap_of(r["id"])} for r in LAYOUT]
