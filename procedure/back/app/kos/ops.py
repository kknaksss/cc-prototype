"""KOS 반영 — 대기열 · 보내기 · 확인 · 재전송 · 실패(SPEC-003 §4.4).

- 같은 visit 의 op 은 seq 순서대로 — 앞 op 이 2xx(sent)면 confirmed 를 기다리지 않고 바로 다음을 보낸다(E2E-6).
  앞 op 이 오류(pending 으로 돌아옴)면 그 visit 은 거기서 멈춘다
- 보내기: pending → 호출 → 2xx 면 sent. 오류(KosError 아닌 예외 포함)면 attempts+1 · pending(다음 조회 주기에 다시)
- 확인: 다음 일정 조회에서 expect 가 맞으면 confirmed. 보냈다가 거절된 pending 도 KOS 값이 이미 맞으면 confirmed
  (예: 같은 단계 change-flow-step 은 KOS 가 400 — 이미 그 단계면 확인으로 본다)
- 재전송: sent 인데 조회 2번 동안 expect 가 안 맞으면 attempts+1 · pending
- 실패: attempts 가 3 에 닿으면 failed + event_log(kos_failed). 그때 대기 중이던 같은 visit 의 뒤 op 은 보내지 않고
  함께 failed(막힘 — 담당자 지정이 실패하면 호출을 보내지 않는다, D-24 · 리뷰 W2). 그 뒤 새로 생긴 op 은 평소대로 보낸다
- failed 뒤 KOS 기준 필드는 KOS 값을 따른다(대기 중 보호가 풀림 — 리뷰 W1). 카드의 「KOS 반영 실패」는 그 visit 의
  뒤 op 이 confirmed 될 때까지 남는다(board_service)
"""

import logging
from datetime import datetime
from typing import Any

from app.domain.clock import Clock
from app.domain.kos_ops import resolve
from app.domain.models import KosOp
from app.kos.client import KosClient, KosError
from app.repository.repo import Repository, Tx

log = logging.getLogger("procedure.kos")

MAX_ATTEMPTS = 3
MISS_LIMIT = 2
BLOCKED = "앞 op 실패로 보내지 않음"


def expect_met(expect: dict[str, Any], schedule: dict[str, Any] | None) -> bool:
    """확인 조건(§8 「확인」 칸)이 KOS 일정 값과 맞나. `$SYSTEM` 은 이미 바꿔 둔 값."""
    if schedule is None:
        return False
    if "flowStep" in expect and schedule.get("flowStep") != expect["flowStep"]:
        return False
    if "tasks" in expect:
        by_seq = {t.get("sequence"): t for t in schedule.get("tasks") or [] if isinstance(t, dict)}
        for seq in expect["tasks"]:
            t = by_seq.get(seq)
            if t is None:
                return False
            if "status" in expect and t.get("status") != expect["status"]:
                return False
            if "statusNot" in expect and t.get("status") == expect["statusNot"]:
                return False
            if "roomId" in expect and str((t.get("room") or {}).get("id")) != expect["roomId"]:
                return False
            for key, field in (("assigneesContain", "assignees"), ("doctorsContain", "doctors")):
                if key in expect and expect[key] not in {str(x.get("id")) for x in t.get(field) or []}:
                    return False
    return True


def _fail_or_retry(tx: Tx, op: KosOp, now: datetime, error: str) -> str:
    attempts = op.attempts + 1
    if attempts >= MAX_ATTEMPTS:
        tx.update_op(op.id, now, status="failed", attempts=attempts, checks=0, last_error=error)
        blocked = tx.block_ops_after(op.visit_id, op.seq, now, BLOCKED)
        tx.add_event(now, "system", "kos_failed", op.visit_id,
                     {"opId": op.id, "path": op.path, "error": error, "blockedOpIds": blocked})
        log.warning("KOS 반영 실패 op=%d %s: %s (막힌 뒤 op %d)", op.id, op.path.rsplit("/", 1)[-1], error, len(blocked))
        return "failed"
    tx.update_op(op.id, now, status="pending", attempts=attempts, checks=0, last_error=error)
    return "pending"


# 같은 필드를 바꾸는 확인 키 묶음 — status 와 statusNot(되돌리기)은 같은 작업 status 필드(SPEC-003 §8 대체 규칙)
SUPERSEDABLE = (("flowStep",), ("status", "statusNot"))


def superseded(op: KosOp, later: list[KosOp]) -> bool:
    """같은 visit 의 뒤 op(sent · confirmed)이 같은 값을 다시 바꿨나 — 그러면 앞 op 의 확인 조건은 더는 맞을 수 없다.

    앞 op 이 2xx 면 확인을 기다리지 않고 다음을 보내므로(E2E-6) 예: change-flow-step PROCEDURE 뒤 PROCEDURE_DONE,
    호출(WAITING) 뒤 수락(READY). 이걸 「안 맞음」으로 세면 앞 op 을 재전송해 KOS 를 되돌린다 → 확인으로 본다.
    """
    for o in later:
        if o.seq <= op.seq or o.status not in ("sent", "confirmed"):
            continue
        for keys in SUPERSEDABLE:
            if any(k in op.expect for k in keys) and any(k in o.expect for k in keys):
                if keys == ("flowStep",) or set(op.expect.get("tasks", [])) & set(o.expect.get("tasks", [])):
                    return True
    return False


def confirm_ops(tx: Tx, schedules: dict[str, dict[str, Any]], system_kos_id: str | None, now: datetime) -> dict[str, int]:
    """일정 조회 뒤 sent op(+ 한 번 이상 보냈다 거절된 pending) 확인 → {"confirmed", "resend", "failed"} 수."""
    out = {"confirmed": 0, "resend": 0, "failed": 0}
    visits = {v.id: v.kos_id for v in tx.visit_by_kos().values()}
    every = tx.ops()
    for op in tx.ops(("sent", "pending")):
        if op.status == "pending" and op.attempts == 0:
            continue
        sch = schedules.get(visits.get(op.visit_id, ""))
        same_visit = [o for o in every if o.visit_id == op.visit_id]
        if superseded(op, same_visit) or expect_met(resolve(op.expect, system_kos_id), sch):
            tx.update_op(op.id, now, status="confirmed", checks=0, last_error=None)
            out["confirmed"] += 1
        elif op.status == "pending":
            continue  # 거절된 것 — 보내기 쪽이 다음 주기에 다시 보낸다
        elif op.checks + 1 >= MISS_LIMIT:
            state = _fail_or_retry(tx, op, now, "KOS 값이 바뀌지 않음")
            out["failed" if state == "failed" else "resend"] += 1
        else:
            tx.update_op(op.id, now, checks=op.checks + 1)
    return out


class OpSender:
    def __init__(self, repo: Repository, client: KosClient, clock: Clock):
        self.repo = repo
        self.client = client
        self.clock = clock

    async def send_heads(self, fresh_only: bool = False) -> dict[str, int]:
        """visit 마다 대기열을 seq 순으로 — sent 는 건너뛰고 pending 을 이어서 보낸다. 오류가 나면 그 visit 은 멈춘다.

        fresh_only = 조작 직후 깨울 때 — 재전송 대기(attempts > 0)를 만나면 그 visit 은 멈춘다(다음 조회 주기 몫).
        """
        with self.repo.tx() as tx:
            queued = tx.ops(("pending", "sent"))
        by_visit: dict[int, list[KosOp]] = {}
        for o in queued:
            by_visit.setdefault(o.visit_id, []).append(o)
        out = {"sent": 0, "retry": 0, "failed": 0}
        if not any(o.status == "pending" for o in queued):
            return out
        system_id = self.client.system_kos_id()
        if system_id is None:
            try:
                await self.client.internal_token()
                system_id = self.client.system_kos_id()
            except KosError:
                pass
        for ops in by_visit.values():
            for op in sorted(ops, key=lambda o: o.seq):
                if op.status == "sent":
                    continue
                if fresh_only and op.attempts > 0:
                    break
                if not await self._send_one(op, system_id, out):
                    break  # 오류 — 뒤 op 은 보내지 않는다(재전송 · 3회 실패 규칙)
        return out

    async def _send_one(self, op: KosOp, system_id: str | None, out: dict[str, int]) -> bool:
        now = self.clock.now()
        try:
            if system_id is None:
                raise KosError("시스템 계정 id 없음(sign-in 실패)")
            await self.client.send(op.api, op.path, resolve(op.body, system_id))
        except Exception as e:  # KosError 아닌 예외도 실패 경로로(리뷰 W6) — 메시지는 상태 · 클래스만
            error = str(e) if isinstance(e, KosError) else type(e).__name__
            with self.repo.tx() as tx:
                state = _fail_or_retry(tx, op, now, error)
            out["failed" if state == "failed" else "retry"] += 1
            return False
        with self.repo.tx() as tx:
            tx.update_op(op.id, now, status="sent", checks=0, last_error=None)
        out["sent"] += 1
        log.info("KOS 반영 보냄 op=%d %s", op.id, op.path.rsplit("/", 1)[-1])
        return True
