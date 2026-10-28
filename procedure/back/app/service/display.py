"""띄우기 요청(SPEC-004 §5-3) — 웹 · 앱 예약 상세에서 「이 예약의 문진 / 여권 스캔을 저 기기에 띄워라」.

- 만들기: 같은 예약 · 같은 종류의 pending 은 canceled 로 닫고 새로 · 유효 PROC_DISPLAY_TTL_MIN(10분) · 지나면 expired
- 닿기: 그 기기 SSE 가 열려 있으면 `event: display`(그 기기 스트림에만) + 늘 띄우기 푸시
  (보이는 알림 · 소리 없음 · 목록 밖 · E2E batch 2)
- QR(스캔 종류): 무작위 32바이트 토큰 · DB 엔 sha256 만 · claim 1회 · 유효 10분
- 문진 종류(SPEC-006 §3 · §6.6): 고객 웹 링크 `{PROC_FRONT_ORIGIN}/q#<token>` · token = HMAC(PROC_SESSION_SECRET,
  "q|{id}|{nonce}") — DB 엔 nonce · sha256(token) 만 · 로그인한 직원 응답에만 qrUrl · 새 요청이 pending · opened 둘 다 닫음 ·
  열린 뒤 쓰는 시한(PROC_QWEB_FILL_MIN) · claim 길 아님(404)
- pending: 그 기기의 pending + 이미 열린 것(오래된 것 먼저) — 스캔 종류만 돌려주며 opened 로(문진 opened = 고객이 엶)
"""

import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from app.config import Settings
from app.domain.clock import Clock, iso, today_range_kst
from app.domain.errors import BadRequest, Conflict, NotFound
from app.domain.models import Account, DisplayRequest
from app.repository.repo import Repository, Tx, live_devices
from app.service.devices import DeviceNotFound, DeviceService

KINDS = ("questionnaire", "scan")
TARGET_ROLE = "coordinator"  # 기기 목록 = 코디 계정 기기(D7-43)
TARGET_HOURS = 24
OPEN = ("pending", "opened")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def qweb_token(secret: str, request_id: int, nonce: str) -> str:
    """고객 문진 웹 토큰(SPEC-006 §3.1) — base64url(HMAC-SHA256(secret, "q|{id}|{nonce}")) 43자. 로그 · DB 에 원문 0."""
    mac = hmac.new(secret.encode(), f"q|{request_id}|{nonce}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


class DisplayNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("띄우기 요청을 찾을 수 없어요", "display_not_found")


def item(d: DisplayRequest, qr_url: str | None = None) -> dict[str, Any]:
    """pending · claim 항목 — SSE `display` 와 같은 키 + 상태 · 만료(코디 결정 2026-10-27) + qrUrl(문진 · pending 만)."""
    return {"requestId": d.id, "kind": d.kind, "reservationId": d.reservation_id, "customerId": d.customer_id,
            "deviceId": d.device_id, "status": d.status, "expiresAt": iso(d.expires_at), "qrUrl": qr_url}


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

    # ------------------------------------------------------------------ 고객 문진 웹 링크(SPEC-006 §3.1 · §6.6)
    def token_of(self, d: DisplayRequest) -> str | None:
        if d.kind != "questionnaire" or not d.qr_nonce:
            return None
        return qweb_token(self.s.proc_session_secret, d.id, d.qr_nonce)

    def qr_url(self, d: DisplayRequest, *, pending_only: bool = True) -> str | None:
        """로그인한 직원 응답에만 싣는다 — 문진 종류 · (pending_only 면) pending 일 때만."""
        token = self.token_of(d)
        if token is None or (pending_only and d.status != "pending"):
            return None
        return f"{self.s.proc_front_origin.rstrip('/')}/q#{token}"

    def _expire(self, tx: Tx, now) -> None:
        tx.expire_displays(now, self.s.proc_qweb_fill_min)

    # ------------------------------------------------------------------ 기기 목록
    def targets(self) -> list[dict[str, Any]]:
        since = self.clock.now() - timedelta(hours=TARGET_HOURS)
        with self.repo.tx() as tx:
            coord = {a.id for a in tx.accounts() if a.active and a.role == TARGET_ROLE}
            devs = [d for d in live_devices(tx.devices())
                    if d.account_id in coord and d.last_seen_at and d.last_seen_at >= since]
        devs.sort(key=lambda d: d.last_seen_at, reverse=True)  # type: ignore[arg-type, return-value]
        seen: set[tuple] = set()  # 계정 · installId 당 하나(가장 최근 · 없으면 행마다 · E2E batch 1 #1)
        uniq = []
        for d in devs:
            key = (d.account_id, d.install_id) if d.install_id else ("row", d.id)
            if key not in seen:
                seen.add(key)
                uniq.append(d)
        devs = uniq
        return [{"deviceId": d.id, "name": d.name or "iPhone", "kind": d.kind, "lastSeenAt": iso(d.last_seen_at),
                 "online": self.online(d.id)} for d in devs]

    # ------------------------------------------------------------------ 만들기 · 닿기
    def create(self, actor: Account, reservation_id: int, kind: str, device_id: int | None) -> dict[str, Any]:
        if kind not in KINDS:
            raise BadRequest("invalid_request", "kind: questionnaire 또는 scan 이어야 해요")
        now = self.clock.now()
        questionnaire = kind == "questionnaire"
        token = secrets.token_urlsafe(32)  # 스캔 = 이 값 · 문진 = 행 id 를 안 뒤 HMAC 으로 바꿔 씀
        with self.repo.tx() as tx:
            r = tx.reservation(reservation_id)
            if r is None:
                raise NotFound("없는 예약이에요")
            if device_id is not None and tx.device(device_id) is None:
                raise DeviceNotFound()
            closing = ("pending", "opened") if questionnaire else ("pending",)  # 문진 = 옛 링크(열린 것도) 닫음(§3.3)
            for old in tx.displays(reservation_id=reservation_id, kind=kind, statuses=closing):
                tx.update_display(old.id, status="canceled", closed_at=now)
            expires = now + timedelta(minutes=self.s.proc_display_ttl_min)
            nonce = secrets.token_hex(16) if questionnaire else None
            rid = tx.add_display(reservation_id=reservation_id, customer_id=r.customer_id, kind=kind, device_id=device_id,
                                 qr_token_hash=token_hash(token), qr_nonce=nonce, status="pending",
                                 created_by=actor.login_id, created_at=now, expires_at=expires)
            if questionnaire:
                token = qweb_token(self.s.proc_session_secret, rid, nonce)  # type: ignore[arg-type]
                tx.update_display(rid, qr_token_hash=token_hash(token))
            tx.add_event(now, actor.login_id, "display_request", None,
                         {"reservationId": reservation_id, "requestId": rid, "kind": kind, "deviceId": device_id})
            d = tx.display(rid)
        assert d is not None
        qr_url = self.qr_url(d)
        if device_id is not None:
            self.reach(rid, device_id, kind, reservation_id, qr_url)
        return {"id": rid, "qrToken": None if questionnaire else token, "qrUrl": qr_url, "expiresAt": iso(expires)}

    def reach(self, request_id: int, device_id: int, kind: str, reservation_id: int, qr_url: str | None = None) -> str:
        """SSE(그 기기 스트림이 열려 있으면) **와** 띄우기 푸시를 둘 다 보낸다(E2E batch 2) — 허브는 죽은 연결을 ping 전까지
        online 으로 보므로 잠긴 · 뒤 폰을 놓칠 수 있다. 앱은 requestId 로 한 번만 연다(batch 1 W1).
        문진 종류는 SSE 에 qrUrl(그 기기 스트림 · 로그인 연결에만) · 푸시 payload 는 그대로(링크를 Apple 로 안 보냄)."""
        data = {"requestId": request_id, "deviceId": device_id, "kind": kind, "reservationId": reservation_id}
        if qr_url:
            data["qrUrl"] = qr_url
        sse = self.online(device_id) and self.send(device_id, data) > 0
        self.push(request_id)
        return "sse+push" if sse else "push"

    # ------------------------------------------------------------------ 기기 쪽 — pending · claim
    def pending(self, actor: Account, device_id: int | None) -> list[dict[str, Any]]:
        if device_id is None:
            raise BadRequest("invalid_request", "deviceId: 필요해요")
        self.devices.check(actor, device_id)  # 남의 계정 · 없는 기기 = 404 · last_seen_at 갱신
        now = self.clock.now()
        with self.repo.tx() as tx:
            self._expire(tx, now)
            rows = tx.displays(device_id=device_id, statuses=OPEN)
            out = []
            for d in rows:
                url = self.qr_url(d)  # 문진 · pending 만(돌려줘도 pending 그대로 — opened = 고객이 엶 · SPEC-006 §6.6)
                if d.kind != "questionnaire" and d.status == "pending":
                    tx.update_display(d.id, status="opened", opened_at=now)
                    d.status, d.opened_at = "opened", now
                out.append(item(d, url))
        return out

    def claim(self, actor: Account, qr_token: str, device_id: int | None) -> dict[str, Any]:
        self.devices.check(actor, device_id)
        now = self.expire()
        with self.repo.tx() as tx:
            d = tx.display_by_hash(token_hash(qr_token))
            if d is None or d.kind == "questionnaire":  # 문진 QR 은 claim 길이 아니다(SPEC-006 §6.6)
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
            self._expire(tx, now)
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
        self._expire(tx, now)
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
        self._expire(tx, now)
        names = {d.id: d.name for d in tx.devices()}
        since = today_range_kst(now)[0]
        return [{"id": d.id, "kind": d.kind, "status": d.status, "deviceName": names.get(d.device_id or 0),
                 "createdAt": iso(d.created_at), "openedAt": iso(d.opened_at), "closedAt": iso(d.closed_at),
                 "qrUrl": self.qr_url(d)}
                for d in tx.displays(reservation_id=reservation_id, since=since)]
