"""알림 목록 · 설정 · 종 배지(SPEC-004 §5-4) — 종류는 doctor_call · counselor_call 둘뿐(display 는 목록 밖).

발송 1회 × 받는 계정 1 = notification 1행(기기가 없어도 쓴다 · D7-69). 설정을 끈 계정엔 쓰지 않는다(push_log 도 — D7-42).
새 행이 생기면 그 계정 스트림에만 SSE `notification {unread}`.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.domain.clock import Clock, iso, parse, today_range_kst
from app.domain.errors import BadRequest
from app.domain.models import Account
from app.repository.repo import Repository, Tx

KINDS = ("doctor_call", "counselor_call")
LIST_MAX = 50
KINDS_BY_ROLE = {"admin": ("doctor_call",), "doctor": ("doctor_call",), "counselor": ("counselor_call",)}


def kinds_for(role: str) -> tuple[str, ...]:
    """그 역할이 받는 종류 — coordinator · nurse = 없음."""
    return KINDS_BY_ROLE.get(role, ())


class NotificationService:
    def __init__(self, repo: Repository, clock: Clock):
        self.repo = repo
        self.clock = clock
        self.on_new: Callable[[int, int], None] = lambda account_id, unread: None  # (계정, 안 읽은 수) → SSE

    def _since(self) -> datetime:
        return today_range_kst(self.clock.now())[0]

    # ------------------------------------------------------------------ 쓰기(발송 쪽)
    @staticmethod
    def enabled(tx: Tx, account_id: int, kind: str) -> bool:
        return tx.notification_settings(account_id).get(kind, True)

    def add(self, tx: Tx, account_id: int, kind: str, title: str, body: str, *, call_id: int | None = None,
            visit_id: int | None = None, reservation_id: int | None = None) -> int:
        return tx.add_notification(account_id=account_id, kind=kind, call_id=call_id, visit_id=visit_id,
                                   reservation_id=reservation_id, title=title, body=body, created_at=self.clock.now())

    def announce(self, account_ids: list[int]) -> None:
        """커밋 뒤 — 그 계정 스트림에 안 읽은 수."""
        since = self._since()
        with self.repo.tx() as tx:
            counts = {a: tx.unread_count(a, since) for a in set(account_ids)}
        for a, n in counts.items():
            self.on_new(a, n)

    # ------------------------------------------------------------------ 읽기 · 읽음
    def listing(self, actor: Account) -> dict[str, Any]:
        since = self._since()
        with self.repo.tx() as tx:
            rows = tx.notifications(actor.id, since, LIST_MAX)
            unread = tx.unread_count(actor.id, since)
        items = [{"id": r["id"], "kind": r["kind"], "title": r["title"], "body": r["body"],
                  "createdAt": iso(parse(r["created_at"])), "readAt": iso(parse(r["read_at"])),
                  "target": {k: v for k, v in (("visitId", r["visit_id"]), ("callId", r["call_id"]),
                                               ("reservationId", r["reservation_id"])) if v is not None}}
                 for r in rows]
        return {"unread": unread, "items": items}

    def read(self, actor: Account, ids: list[int] | None, call_id: int | None = None,
             reservation_id: int | None = None) -> int:
        with self.repo.tx() as tx:
            return tx.mark_read(actor.id, self.clock.now(), ids=ids, call_id=call_id, reservation_id=reservation_id)

    # ------------------------------------------------------------------ 설정
    def settings(self, actor: Account) -> list[dict[str, Any]]:
        with self.repo.tx() as tx:
            saved = tx.notification_settings(actor.id)
        return [{"kind": k, "enabled": saved.get(k, True)} for k in kinds_for(actor.role)]

    def put_setting(self, actor: Account, kind: str, enabled: bool) -> list[dict[str, Any]]:
        if kind not in kinds_for(actor.role):
            raise BadRequest("setting_not_allowed", "이 계정이 받지 않는 알림이에요")
        with self.repo.tx() as tx:
            tx.put_notification_setting(actor.id, kind, enabled, self.clock.now())
        return self.settings(actor)
