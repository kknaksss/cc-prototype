"""예약관리 데모 서비스 — 읽기 · 데모 요청 · KOS 등록/수정 · 변경 요청(SPEC-002 §3.2).

상태 전이 규칙은 이 파일의 `TRANSITIONS` 한 곳. 맞지 않는 전이 = Conflict(409).
조작 성공 → 1차와 같은 version(+1) · SSE. KOS 는 부르지 않는다 — `kos api 연동 필요` 주석만.
"""

from app.domain.errors import BadRequest, Conflict, NotFound
from app.repository.reservation_repo import ReservationRepository
from app.service import resv_demo as D
from app.service.board_service import BoardService, now_ms
from app.service.events import EventBus

REQUESTED, CONFIRMED, CHANGE_REQUESTED = "requested", "confirmed", "change_requested"
MODIFY_REQUESTED, MODIFIED, SUPERSEDED = "modify_requested", "modified", "superseded"
OPEN = (REQUESTED, MODIFY_REQUESTED)  # 확인 필요 — 병원이 KOS 등록/수정 · 변경 요청할 수 있는 줄
DONE = (CONFIRMED, MODIFIED)

# 조작 → {지금 상태: 다음 상태}. 표에 없는 상태에서의 조작 = 409.
# 수정 등록(modify_requested → modified) 때 같은 묶음의 나머지 유효 줄은 superseded 로 간다(`register`).
TRANSITIONS = {
    "register": {REQUESTED: CONFIRMED, MODIFY_REQUESTED: MODIFIED},
    "change_request": {REQUESTED: CHANGE_REQUESTED, MODIFY_REQUESTED: CHANGE_REQUESTED},
}


def _next_status(action: str, row: dict) -> str:
    to = TRANSITIONS[action].get(row["status"])
    if to is None:
        raise Conflict("invalid_status", f"이 줄은 지금 상태({row['status']})에서 할 수 없는 조작이에요")
    return to


def _groups(rows: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in sorted(rows, key=lambda r: r["id"]):
        out.setdefault(r["groupId"], []).append(r)
    return out


def modify_target(rows: list[dict]) -> dict | None:
    """수정 요청을 붙일 줄 — 묶음마다 마지막 줄을 보고, `change_requested` 가 있으면 그중 가장 최근,
    없으면 `confirmed`/`modified` 중 가장 최근. 마지막 줄이 확인 중인 묶음은 대상이 아니다."""
    lasts = [g[-1] for g in _groups(rows).values()]
    changed = [r for r in lasts if r["status"] == CHANGE_REQUESTED]
    if changed:
        return max(changed, key=lambda r: (r["changeAt"] or 0, r["id"]))
    done = [r for r in lasts if r["status"] in DONE]
    return max(done, key=lambda r: (r["registeredAt"] or 0, r["id"])) if done else None


def _row(rid: int, group_id: int, kind: str, now: int, base: dict, **extra) -> dict:
    return {"id": rid, "groupId": group_id, "kind": kind, "modifyReason": None, "receivedAt": now,
            "customer": base["customer"], "date": base["date"], "time": base["time"],
            "proc": base["proc"], "lang": base["lang"], "before": None, "status": REQUESTED,
            "changeReason": None, "changeAt": None, "registeredAt": None, "snapshot": None, **extra}


class ReservationService:
    def __init__(self, repo: ReservationRepository, board: BoardService, bus: EventBus, clock=now_ms):
        self.repo = repo
        self.board = board  # version · 잠금은 1차 현황판과 하나
        self.bus = bus
        self.clock = clock

    # ── 읽기 ──
    def read(self) -> dict:
        with self.board.lock:
            rows = self.repo.all()
            version = self.board.version()
        groups = sorted(_groups(rows).items(), key=lambda kv: kv[0], reverse=True)  # 최신 묶음이 위
        return {
            "rows": [r for _, g in groups for r in g],  # 묶음 안은 오래된 줄이 위
            "counts": {
                "needCheck": sum(r["status"] in OPEN for r in rows),
                "changeRequested": sum(r["status"] == CHANGE_REQUESTED for r in rows),
                "confirmed": sum(r["status"] in DONE for r in rows),
                "total": len(groups),
            },
            "version": version,
        }

    # ── 쓰기 공통: 읽기 → 바꿀 줄 → 저장 + version+1 → SSE ──
    def _run(self, change) -> dict:
        with self.board.lock:
            rows = self.repo.all()
            changed = change(rows, self.clock())
            version = self.board.version() + 1
            self.repo.save(changed, version)
        self.bus.publish(version)
        return {"version": version}

    @staticmethod
    def _find(rows: list[dict], rid: int) -> dict:
        row = next((r for r in rows if r["id"] == rid), None)
        if row is None:
            raise NotFound("reservation_not_found", f"예약 줄 {rid} 이 없어요")
        return row

    # ── 데모 전용(링키 연동 자리) ──
    def demo_request(self) -> dict:
        def change(rows: list[dict], now: int) -> list[dict]:
            rid = max((r["id"] for r in rows), default=0) + 1
            n = len({r["groupId"] for r in rows})  # 묶음 수 = 지금까지 받은 예약 요청 수
            return [_row(rid, rid, "request", now, D.sample(n, now))]

        return self._run(change)

    def demo_modify(self) -> dict:
        def change(rows: list[dict], now: int) -> list[dict]:
            target = modify_target(rows)
            if target is None:
                raise Conflict("no_modify_target", "확정 또는 변경 요청된 예약이 있어야 해요")
            reason = "change_request" if target["status"] == CHANGE_REQUESTED else "customer"
            rid = max(r["id"] for r in rows) + 1
            new_time = D.modify_time(reason, target["time"])
            return [_row(rid, target["groupId"], "modify", now, target, modifyReason=reason, time=new_time,
                         before={"time": target["time"]}, status=MODIFY_REQUESTED)]

        return self._run(change)

    # ── 병원 조작 ──
    def register(self, rid: int) -> dict:
        def change(rows: list[dict], now: int) -> list[dict]:
            row = self._find(rows, rid)
            to = _next_status("register", row)
            if row["kind"] == "request":
                ## ============kos api 연동 필요 ========================
                ## 공식: 예약 생성(공개 스펙 「예약 생성」 command — operationId 는 1차 HAR 범위 밖, 확인 필요)
                ## ======================================================
                pass
            else:
                ## ============kos api 연동 필요 ========================
                ## 공식: 예약 변경(공개 스펙 「예약 변경」 command — operationId 는 1차 HAR 범위 밖, 확인 필요)
                ## ======================================================
                pass
            done = {**row, "status": to, "registeredAt": now, "snapshot": D.snapshot(row, now)}
            if to != MODIFIED:
                return [done]
            older = [{**r, "status": SUPERSEDED} for r in rows
                     if r["groupId"] == row["groupId"] and r["id"] != rid and r["status"] != SUPERSEDED]
            return [*older, done]

        return self._run(change)

    def change_request(self, rid: int, reason: str) -> dict:
        reason = reason.strip()
        if not reason:
            raise BadRequest("empty_reason", "변경 요청 사유를 적어 주세요")

        def change(rows: list[dict], now: int) -> list[dict]:
            row = self._find(rows, rid)
            return [{**row, "status": _next_status("change_request", row), "changeReason": reason, "changeAt": now}]

        return self._run(change)

    # ── 초기화 — 데모 처음 상태 = 빈 테이블 ──
    def reset(self) -> dict:
        """1차 초기화(시드로) + 예약 줄 비우기. 시드가 없으면 1차처럼 404 이고 예약 줄은 그대로."""
        with self.board.lock:
            out = self.board.reset()
            self.repo.clear()
        return out
