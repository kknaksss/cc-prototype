"""푸시(SPEC-004 §5-1.2 · §5-2 · §5-3) — 커밋 뒤 비동기로 보낸다. 조작 응답 · SSE 를 기다리게 하지 않는다.

원장 호출(doctor_call): 전체 호출 = active 의사 전원 + 관리자 · 지정 호출 = 지정 원장의 의사 계정 + 관리자 · 간호사 · 코디 ·
상담사 = 없음. 누른 계정이 의사면 그 의사 자신은 뺀다(관리자는 빼지 않는다 — 간호 스테이션 · 의국이 같이 쓴다).
상담사 호출(counselor_call): 그 상담사 계정(active)만 — 관리자 · 코디 · 의사 안 받음.
알림 목록(§5-4): 받는 계정마다 notification 1행(기기가 없어도) · 설정을 끈 계정은 notification · push_log 둘 다 안 씀.
발송 내역은 push_log 에 받는 기기마다 1행 쌓는다(sent · failed · skipped_no_key · token_removed · kind).
내용에 고객 이름 · 국적 · 시술 이름을 넣지 않는다(잠금 화면). 실패는 로그만(상태 · reason · 토큰 끝 6자리).
의사 수신자 알림에만 `aps.category = "CALL"` — 알림(워치 포함)에서 바로 수락. 의사 수신자는 늘 그 호출을 수락할 수 있는
원장이다(전체 호출 = 전원 · 지정 = 그 원장). 관리자 알림은 category 없음(앱을 열어 원장을 고른다).
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.domain.clock import Clock
from app.domain.models import Account
from app.push.apns import ApnsClient, ApnsResult
from app.repository.repo import Repository, Tx
from app.service.chat import PREVIEW, room_name
from app.service.notifications import NotificationService

log = logging.getLogger("procedure.push")

RETRY = (429,)  # + 5xx · 네트워크 오류 → 1회 재시도
# 이 기기 토큰은 다시 쓸 수 없다 → device 행 삭제 · push_log token_removed. 410 은 늘, 400 은 이 reason 일 때만
# (DeviceTokenNotForTopic = 번들 id 바꾸기 전에 등록된 옛 토큰 — 2026-10-21 실 APNs). 그 밖 400 은 failed
DEAD_400 = ("BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered")
CHAT_TTL_SEC = 86400  # 채팅 apns-expiration = 보낼 때 + 1일(D9-31) — 호출 · 띄우기는 0 그대로


def chat_body(kind: str, text: str | None) -> str:
    """채팅 푸시 본문(SPEC-007 §8) — 텍스트 앞 100자(넘으면 「…」 · 줄바꿈 = 공백) ·
    사진 = 「사진」 · 동영상 = 「동영상」(잠금 화면에 보인다)."""
    # 법적 검토 필요: 직원 채팅 — 고객 정보가 메시지 · 사진으로 오갈 수 있음(보존 기간 없음 · 열람 로그 없음 · 잠금 화면에 본문 앞부분)  # noqa: E501
    if kind == "photo":
        return "사진"
    if kind == "video":
        return "동영상"
    flat = " ".join((text or "").splitlines())
    return flat[:PREVIEW] + ("…" if len(flat) > PREVIEW else "")


@dataclass(frozen=True)
class Delivery:
    """받는 사람 기기 하나에 보낼 것."""

    call_id: int | None
    visit_id: int | None
    account_id: int
    role: str
    device_id: int
    token: str
    category: str | None
    payload: dict[str, Any]
    kind: str = "doctor_call"  # doctor_call | counselor_call | display | chat
    reservation_id: int | None = None
    notification_id: int | None = None
    display_request_id: int | None = None
    chat_message_id: int | None = None
    expiration: int = 0  # apns-expiration — 채팅만 보낼 때 + 1일(SPEC-007 §8 · D9-31)


def _tail(token: str) -> str:
    return f"…{token[-6:]}"


class PushService:
    def __init__(self, repo: Repository, settings: Settings, client: ApnsClient | None = None, clock: Clock | None = None,
                 notifications: NotificationService | None = None):
        self.repo = repo
        self.s = settings
        self.clock = clock or Clock()
        self.notifications = notifications or NotificationService(repo, self.clock)
        self.enabled = settings.apns_enabled
        self.client = client if client is not None else (ApnsClient(settings) if self.enabled else None)
        self.tasks: set[asyncio.Task] = set()
        if not self.enabled:
            log.warning("APNS_* 가 비어 원장 호출 푸시를 끈다(조작은 그대로)")
        elif self.client is not None:
            self.check_key()

    def check_key(self) -> bool:
        """서버 시작 때 JWT 를 한 번 서명해 본다 — 키 파일 · 형식 확인. 로그에 값 없음(env · 결과만)."""
        try:
            self.client.sign()  # type: ignore[union-attr]
        except Exception as e:
            log.error("APNs JWT 서명 실패(%s) — 키 파일 경로 · 형식 확인 · 발송은 실패로 기록", type(e).__name__)
            return False
        log.info("APNs JWT 서명 OK(env=%s)", self.s.apns_env)
        return True

    # ------------------------------------------------------------------ 받는 사람 · 내용
    def _rows(self, tx: Tx, to: list[Account], kind: str, title: str, body: str, **target: int | None) -> dict[int, int]:
        """설정이 켜진 계정마다 notification 1행 → {계정 id: notification id}. 끈 계정은 빠진다(발송도 없음)."""
        out = {}
        for a in to:
            if self.notifications.enabled(tx, a.id, kind):
                out[a.id] = self.notifications.add(tx, a.id, kind, title, body, **target)
        return out

    def message(self, call_id: int, actor_login: str) -> list[Delivery] | None:
        """원장 호출 — 받는 계정마다 notification 1행 쓰고, 받는 기기마다 Delivery 하나. 호출이 없으면 None."""
        with self.repo.tx() as tx:
            w = tx.world()
            call = w.calls.get(call_id)
            if call is None:
                return None
            accounts = [a for a in tx.accounts() if a.active]
            actor = tx.account(actor_login)
            to: list[Account] = [a for a in accounts if a.role == "admin"]
            if call.kind == "one":
                to += [a for a in accounts if a.role == "doctor" and a.staff_id == call.target_staff_id]
            else:
                to += [a for a in accounts if a.role == "doctor"]
            if actor is not None and actor.role == "doctor":
                to = [a for a in to if a.id != actor.id]
            v = w.visits.get(call.visit_id)
            room = w.rooms.get(v.room_id) if v is not None and v.room_id is not None else None
            kind = "전체 호출" if call.kind == "all" else "지정 호출"
            body = f"{room.title if room else '방'} · 시술 {len(call.procedure_ids)}건 · {kind}"
            notes = self._rows(tx, to, "doctor_call", "원장 호출", body, call_id=call.id, visit_id=call.visit_id)
            role_of = {a.id: a.role for a in to if a.id in notes}
            devices = tx.devices_of(list(role_of))
        self.notifications.announce(list(notes))
        aps = {"alert": {"title": "원장 호출", "body": body}, "sound": "default"}
        out = []
        for device_id, account_id, token in devices:
            category = "CALL" if role_of[account_id] == "doctor" else None  # 의사만 알림에서 바로 수락
            a = {**aps, "category": category} if category else aps
            out.append(Delivery(call.id, call.visit_id, account_id, role_of[account_id], device_id, token, category,
                                {"aps": a, "kind": "doctor_call", "visitId": call.visit_id, "callId": call.id},
                                notification_id=notes[account_id]))
        return out

    def counselor_message(self, reservation_id: int, counselor_staff_id: int) -> list[Delivery]:
        """상담사 호출(§5-2) — 그 상담사 계정(active)만 · 본문 「<방> · 상담 대기」(방 없으면 「상담 대기」)."""
        with self.repo.tx() as tx:
            r = tx.reservation(reservation_id)
            to = [a for a in tx.accounts() if a.active and a.role == "counselor" and a.staff_id == counselor_staff_id]
            body = f"{r.room_title} · 상담 대기" if r is not None and r.room_title else "상담 대기"
            notes = self._rows(tx, to, "counselor_call", "상담사 호출", body, reservation_id=reservation_id)
            devices = tx.devices_of(list(notes))
        self.notifications.announce(list(notes))
        payload = {"aps": {"alert": {"title": "상담사 호출", "body": body}, "sound": "default"},
                   "kind": "counselor_call", "reservationId": reservation_id}
        return [Delivery(None, None, account_id, "counselor", device_id, token, None, payload, kind="counselor_call",
                         reservation_id=reservation_id, notification_id=notes[account_id])
                for device_id, account_id, token in devices]

    def display_message(self, request_id: int) -> list[Delivery]:
        """띄우기 푸시(§5-3 ②) — 그 기기 하나 · 보이는 알림 · 소리 없음 · 고객 이름 없음 · 알림 목록 · 설정 밖(D7-67)."""
        with self.repo.tx() as tx:
            d = tx.display(request_id)
            dev = tx.device(d.device_id) if d is not None and d.device_id is not None else None
            owner = next((a for a in tx.accounts() if dev is not None and a.id == dev.account_id), None)
        if d is None or dev is None or owner is None:
            return []
        title = "고객 입력 요청" if d.kind == "questionnaire" else "여권 스캔 요청"
        payload = {"aps": {"alert": {"title": title, "body": "데스크에서 보냈어요"}}, "kind": "display", "requestId": d.id}
        return [Delivery(None, None, owner.id, owner.role, dev.id, dev.token, None, payload, kind="display",
                         reservation_id=d.reservation_id, display_request_id=d.id)]

    def chat_message(self, message_id: int) -> list[Delivery]:
        """채팅 새 메시지(SPEC-007 §8) — 받는 사람 = 지금 멤버 − 보낸 사람 − 알림 끈 사람 − 비활성 → 기기 전부.

        숨긴 1:1 멤버도 받는다. 시스템 줄 · 지운 것 = 없음. notification 행을 쓰지 않는다(알림 목록 · 종 배지 밖 · D9-30).
        제목 = 1:1 은 보낸 사람 · 그룹은 「보낸 사람 · 방 이름」(이름 없는 그룹 = 받는 사람 기준 나열).
        """
        with self.repo.tx() as tx:
            m = tx.chat_message(message_id)
            room = tx.chat_room(m["room_id"]) if m else None
            if m is None or room is None or m["kind"] == "system" or m["deleted_at"] is not None:
                return []
            accounts = {a.id: a for a in tx.accounts()}
            members = tx.chat_members(room["id"])
            ids = [r["account_id"] for r in members]
            to = [r["account_id"] for r in members if r["account_id"] != m["account_id"] and not r["muted"]
                  and r["account_id"] in accounts and accounts[r["account_id"]].active]
            devices = tx.devices_of(to)
        sender = accounts.get(m["account_id"])
        sender_name = sender.name if sender else ""
        body = chat_body(m["kind"], m["body"])
        expiration = int(self.clock.now().timestamp()) + CHAT_TTL_SEC
        out = []
        for device_id, account_id, token in devices:
            to_acc = accounts[account_id]
            title = sender_name if room["kind"] == "direct" else f"{sender_name} · {room_name(room, ids, accounts, account_id)}"
            payload = {"aps": {"alert": {"title": title, "body": body}, "sound": "default", "thread-id": f"chat-{room['id']}"},
                       "kind": "chat", "roomId": room["id"], "messageId": m["id"]}
            out.append(Delivery(None, None, account_id, to_acc.role, device_id, token, None, payload, kind="chat",
                                chat_message_id=m["id"], expiration=expiration))
        return out

    def _log(self, d: "Delivery", status: str, created_at, res: ApnsResult | None = None, attempts: int = 0) -> None:
        with self.repo.tx() as tx:
            tx.add_push_log(call_id=d.call_id, visit_id=d.visit_id, account_id=d.account_id, role=d.role,
                            device_id=d.device_id, token_tail=d.token[-6:], category=d.category, status=status,
                            apns_status=res.status if res else None, apns_reason=res.reason if res else None,
                            apns_id=res.apns_id if res else None, attempts=attempts, created_at=created_at,
                            sent_at=self.clock.now() if res is not None and res.status == 200 else None,
                            kind=d.kind, reservation_id=d.reservation_id, notification_id=d.notification_id,
                            display_request_id=d.display_request_id, chat_message_id=d.chat_message_id)

    # ------------------------------------------------------------------ 발송
    def schedule(self, call_id: int, actor_login: str) -> None:
        """원장 호출 — 커밋 뒤 부른다."""
        self._dispatch(lambda: self.message(call_id, actor_login) or [], f"원장 호출 call={call_id}")

    def schedule_counselor(self, reservation_id: int, counselor_staff_id: int) -> None:
        """상담사 호출 — KOS 200 + event_log 커밋 뒤 부른다(§5-2)."""
        self._dispatch(lambda: self.counselor_message(reservation_id, counselor_staff_id),
                       f"상담사 호출 reservation={reservation_id}")

    def schedule_display(self, request_id: int) -> None:
        """띄우기 — 그 기기 SSE 가 닫혀 있을 때(§5-3 ②)."""
        self._dispatch(lambda: self.display_message(request_id), f"띄우기 request={request_id}")

    def schedule_chat(self, message_id: int) -> None:
        """채팅 새 메시지 — 보내기 커밋 뒤(같은 clientId 다시 · 시스템 줄은 부르지 않는다). what 에 id 만(§6.1)."""
        self._dispatch(lambda: self.chat_message(message_id), f"채팅 message={message_id}")

    async def notify_chat(self, message_id: int) -> dict[str, int]:
        return await self._notify(lambda: self.chat_message(message_id), f"채팅 message={message_id}")

    def _dispatch(self, prepare, what: str) -> None:
        """돌고 있는 이벤트 루프에 태스크로 띄운다. 키가 없으면 받는 기기마다 skipped_no_key 로 쌓기만(알림 행은 쓴다)."""
        if not self.enabled:
            self._skip(prepare, what)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning("%s 푸시 건너뜀(이벤트 루프 없음)", what)
            return
        task = loop.create_task(self._notify(prepare, what))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def skip(self, call_id: int, actor_login: str) -> int:
        return self._skip(lambda: self.message(call_id, actor_login) or [], f"원장 호출 call={call_id}")

    def _skip(self, prepare, what: str) -> int:
        try:
            msg = prepare()
            now = self.clock.now()
            for d in msg:
                self._log(d, "skipped_no_key", now)
        except Exception as e:
            log.error("%s 푸시 내역 오류: %s", what, type(e).__name__)
            return 0
        log.info("%s 푸시 건너뜀(APNS_* 없음) 받는 기기 %d", what, len(msg))
        return len(msg)

    async def notify(self, call_id: int, actor_login: str) -> dict[str, int]:
        return await self._notify(lambda: self.message(call_id, actor_login) or [], f"원장 호출 call={call_id}")

    async def notify_counselor(self, reservation_id: int, counselor_staff_id: int) -> dict[str, int]:
        return await self._notify(lambda: self.counselor_message(reservation_id, counselor_staff_id),
                                  f"상담사 호출 reservation={reservation_id}")

    async def notify_display(self, request_id: int) -> dict[str, int]:
        return await self._notify(lambda: self.display_message(request_id), f"띄우기 request={request_id}")

    async def _notify(self, prepare, what: str) -> dict[str, int]:
        if not self.enabled or self.client is None:
            return {"sent": 0, "failed": 0, "removed": 0}
        try:
            msg = prepare()
        except Exception as e:  # 발송 준비 실패로 조작에 영향 주지 않는다
            log.error("%s 푸시 준비 오류: %s", what, type(e).__name__)
            return {"sent": 0, "failed": 0, "removed": 0}
        return await self.deliver(msg, what)

    async def deliver(self, msg: list[Delivery], what: str) -> dict[str, int]:
        out = {"sent": 0, "failed": 0, "removed": 0}
        if not msg or self.client is None:
            return out
        created = self.clock.now()
        for d in msg:
            res, attempts = await self._send_with_retry(d.token, d.payload, d.expiration)
            if res.status == 200:
                out["sent"] += 1
                self._log(d, "sent", created, res, attempts)
                continue
            out["failed"] += 1
            log.warning("%s 푸시 실패 token=%s status=%s reason=%s", what, _tail(d.token), res.status, res.reason)
            if res.status == 410 or (res.status == 400 and res.reason in DEAD_400):  # 죽은 토큰 — 그 기기 행 삭제
                with self.repo.tx() as tx:
                    tx.delete_device(d.token)
                out["removed"] += 1
                self._log(d, "token_removed", created, res, attempts)
            else:
                self._log(d, "failed", created, res, attempts)
        log.info("%s 푸시 보냄 %d · 실패 %d", what, out["sent"], out["failed"])
        return out

    async def _send_with_retry(self, token: str, payload: dict[str, Any], expiration: int = 0) -> tuple[ApnsResult, int]:
        assert self.client is not None
        res = await self._send(token, payload, expiration)
        if res.status is None or res.status >= 500 or res.status in RETRY:  # 네트워크 · 5xx · 429 → 1회만 다시
            return await self._send(token, payload, expiration), 2
        return res, 1

    async def _send(self, token: str, payload: dict[str, Any], expiration: int = 0) -> ApnsResult:
        assert self.client is not None
        try:
            return await self.client.send(token, payload, expiration)
        except Exception as e:  # 키 파일 · 서명 오류 등 — 메시지에 키가 섞일 수 있어 클래스 이름만
            return ApnsResult(None, type(e).__name__)
