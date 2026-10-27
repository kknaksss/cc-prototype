"""띄우기 요청(SPEC-004 §5-3) — 웹 · 앱 예약 상세에서 「이 예약의 문진 / 여권 스캔을 저 기기에 띄워라」.

- 만들기: 같은 예약 · 같은 종류의 pending 은 canceled 로 닫고 새로 · 유효 PROC_DISPLAY_TTL_MIN(10분) · 지나면 expired
- 닿기: 그 기기 SSE 가 열려 있으면 `event: display`(그 기기 스트림에만) · 아니면 띄우기 푸시(보이는 알림 · 소리 없음 · 목록 밖)
- QR: 무작위 32바이트 토큰 · DB 엔 sha256 만 · claim 1회 · 유효 10분
- pending: 그 기기의 pending + 이미 열린 것(오래된 것 먼저) — 돌려주며 opened 로(코디 결정 2026-10-27)
"""

import hashlib
import secrets
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from app.config import Settings
from app.domain.clock import Clock, iso, today_range_kst
from app.domain.errors import BadRequest, Conflict, NotFound
from app.domain.models import Account, DisplayRequest
from app.repository.repo import Repository, Tx
from app.service.devices import DeviceNotFound, DeviceService

KINDS = ("questionnaire", "scan")
TARGET_ROLE = "coordinator"  # 기기 목록 = 코디 계정 기기(D7-43)
TARGET_HOURS = 24
OPEN = ("pending", "opened")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class DisplayNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("띄우기 요청을 찾을 수 없어요", "display_not_found")


def item(d: DisplayRequest) -> dict[str, Any]:
    """pending · claim 항목 — SSE `display` 와 같은 키 + 상태 · 만료(코디 결정 2026-10-27)."""
    return {"requestId": d.id, "kind": d.kind, "reservationId": d.reservation_id, "customerId": d.customer_id,
            "deviceId": d.device_id, "status": d.status, "expiresAt": iso(d.expires_at)}


class DisplayService:
    def __init__(self, repo: Repository, clock: Clock, settings: Settings, devices: DeviceService):
        self.repo = repo
        self.clock = clock
        self.s = settings
        self.devices = devices
        # 컨테이너가 끼운다 — 기기 SSE 열림 여부 · 그 기기 스트림에 보내기 · 띄우기 푸시
        self.online: Callable[[int], bool] = lambda device_id: False
        self.send: Callable[[int, dict[str, Any]], int] = lambda device_id, data: 0
        self.push: Callable[[int], None] = lambda request_id: None

    # ------------------------------------------------------------------ 기기 목록
    def targets(self) -> list[dict[str, Any]]:
        since = self.clock.now() - timedelta(hours=TARGET_HOURS)
        with self.repo.tx() as tx:
            coord = {a.id for a in tx.accounts() if a.active and a.role == TARGET_ROLE}
            devs = [d for d in tx.devices() if d.account_id in coord and d.last_seen_at and d.last_seen_at >= since]
        devs.sort(key=lambda d: d.last_seen_at, reverse=True)  # type: ignore[arg-type, return-value]
        return [{"deviceId": d.id, "name": d.name or "iPhone", "kind": d.kind, "lastSeenAt": iso(d.last_seen_at),
                 "online": self.online(d.id)} for d in devs]

    # ------------------------------------------------------------------ 만들기 · 닿기
    def create(self, actor: Account, reservation_id: int, kind: str, device_id: int | None) -> dict[str, Any]:
        if kind not in KINDS:
            raise BadRequest("invalid_request", "kind: questionnaire 또는 scan 이어야 해요")
        now = self.clock.now()
        token = secrets.token_urlsafe(32)
        with self.repo.tx() as tx:
            r = tx.reservation(reservation_id)
            if r is None:
                raise NotFound("없는 예약이에요")
            if device_id is not None and tx.device(device_id) is None:
                raise DeviceNotFound()
            for old in tx.displays(reservation_id=reservation_id, kind=kind, statuses=("pending",)):
                tx.update_display(old.id, status="canceled", closed_at=now)
            expires = now + timedelta(minutes=self.s.proc_display_ttl_min)
            rid = tx.add_display(reservation_id=reservation_id, customer_id=r.customer_id, kind=kind, device_id=device_id,
                                 qr_token_hash=token_hash(token), status="pending", created_by=actor.login_id,
                                 created_at=now, expires_at=expires)
            tx.add_event(now, actor.login_id, "display_request", None,
                         {"reservationId": reservation_id, "requestId": rid, "kind": kind, "deviceId": device_id})
        if device_id is not None:
            self.reach(rid, device_id, kind, reservation_id)
        return {"id": rid, "qrToken": token, "expiresAt": iso(expires)}

    def reach(self, request_id: int, device_id: int, kind: str, reservation_id: int) -> str:
        """SSE 가 열려 있으면 그 기기 스트림 · 아니면 띄우기 푸시."""
        data = {"requestId": request_id, "deviceId": device_id, "kind": kind, "reservationId": reservation_id}
        if self.online(device_id) and self.send(device_id, data):
            return "sse"
        self.push(request_id)
        return "push"

    # ------------------------------------------------------------------ 기기 쪽 — pending · claim
    def pending(self, actor: Account, device_id: int | None) -> list[dict[str, Any]]:
        if device_id is None:
            raise BadRequest("invalid_request", "deviceId: 필요해요")
        self.devices.check(actor, device_id)  # 남의 계정 · 없는 기기 = 404 · last_seen_at 갱신
        now = self.clock.now()
        with self.repo.tx() as tx:
            tx.expire_displays(now)
            rows = tx.displays(device_id=device_id, statuses=OPEN)
            for d in rows:
                if d.status == "pending":
                    tx.update_display(d.id, status="opened", opened_at=now)
                    d.status, d.opened_at = "opened", now
        return [item(d) for d in rows]

    def claim(self, actor: Account, qr_token: str, device_id: int | None) -> dict[str, Any]:
        self.devices.check(actor, device_id)
        now = self.expire()
        with self.repo.tx() as tx:
            d = tx.display_by_hash(token_hash(qr_token))
            if d is None:
                raise DisplayNotFound()
            if d.status == "expired":
                raise Conflict("display_expired", "QR 유효 시간이 지났어요")
            if d.status != "pending":
                raise Conflict("display_closed", "이미 쓴 QR 이에요")  # 1회
            fields: dict[str, Any] = {"status": "opened", "opened_at": now}
            if device_id is not None:  # 그 기기 요청으로 묶음(다른 기기로 보낸 요청이면 바꿈)
                fields["device_id"] = device_id
            tx.update_display(d.id, **fields)
            d = tx.display(d.id)
        assert d is not None
        return item(d)

    def expire(self):
        """만료를 먼저 따로 커밋한다 — 뒤에서 409 를 던져도 expired 가 남게."""
        now = self.clock.now()
        with self.repo.tx() as tx:
            tx.expire_displays(now)
        return now

    # ------------------------------------------------------------------ 닫기
    def close(self, actor: Account, request_id: int, status: str) -> None:
        if status not in ("done", "canceled"):
            raise BadRequest("invalid_request", "status: done 또는 canceled 여야 해요")
        self.expire()
        with self.repo.tx() as tx:
            self._close(tx, actor, request_id, status, strict=True)

    def finish(self, tx: Tx, actor: Account, request_id: int | None) -> None:
        """문진 제출 · 스캔 저장 성공 — 그 API 가 대신 done 으로(이미 닫혔으면 그대로)."""
        if request_id is not None:
            self._close(tx, actor, request_id, "done", strict=False)

    def _close(self, tx: Tx, actor: Account, request_id: int, status: str, *, strict: bool) -> None:
        now = self.clock.now()
        tx.expire_displays(now)
        d = tx.display(request_id)
        if d is None:
            if strict:
                raise DisplayNotFound()
            return
        if d.status not in OPEN:
            if strict:
                raise Conflict("display_expired" if d.status == "expired" else "display_closed", "이미 닫힌 요청이에요")
            return
        tx.update_display(d.id, status=status, closed_at=now)
        tx.add_event(now, actor.login_id, "display_close", None,
                     {"reservationId": d.reservation_id, "requestId": d.id, "status": status})

    # ------------------------------------------------------------------ 상세 응답(§5-3 「닫기」)
    def of_reservation(self, tx: Tx, reservation_id: int) -> list[dict[str, Any]]:
        now = self.clock.now()
        tx.expire_displays(now)
        names = {d.id: d.name for d in tx.devices()}
        since = today_range_kst(now)[0]
        return [{"id": d.id, "kind": d.kind, "status": d.status, "deviceName": names.get(d.device_id or 0),
                 "createdAt": iso(d.created_at), "closedAt": iso(d.closed_at)}
                for d in tx.displays(reservation_id=reservation_id, since=since)]
