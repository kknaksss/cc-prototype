"""KOS 조회 → ccc DB(SPEC-003 §4.2 · §4.3).

- 일정: 내부 `get-schedules-grouped-by-zone` · 오늘(KST) · 4층 · 10초
- 직원: 공개 `get-accounts` · 방: 내부 `get-rooms` · 1시간 + 서버 시작
- 조회 시간(KST 09:00 ~ 21:00) 밖에서는 조회하지 않는다
- 반영 순서: ① 직원 · 방 ② 일정 → customer · visit · procedure(덮어쓰기 규칙) ③ kos_op 확인 ④ sync_state
"""

import logging
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.domain.clock import Clock, in_window, kos_utc, parse, today_range_kst
from app.domain.kos_ops import touched_sequences, touches_flow_step
from app.kos.client import KosClient, KosError
from app.kos.ops import confirm_ops
from app.repository.repo import Repository, Tx

log = logging.getLogger("procedure.kos")

PATH_SCHEDULES = "schedule/v2/queries/get-schedules-grouped-by-zone"
PATH_ROOMS = "schedule/zone/room/v1/queries/get-rooms"
PATH_ACCOUNTS = "account/open/v1/queries/get-accounts"


def flatten_schedules(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """`data[].schedules[]`(구역별 묶음) → 일정 목록. 묶음이 아니면 data 그대로."""
    out: list[dict[str, Any]] = []
    for item in resp.get("data") or []:
        if isinstance(item, dict) and "schedules" in item:
            out.extend(s for s in item.get("schedules") or [] if isinstance(s, dict))
        elif isinstance(item, dict):
            out.append(item)
    return out


def _room_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """방 = ETCETERA 이고 room 있는 작업 — 여럿이면 roomAssignedDateTimeUtc 가 가장 늦은 것(OQ-511)."""
    cands = [t for t in tasks if t.get("type") == "ETCETERA" and isinstance(t.get("room"), dict) and t["room"].get("id")]
    if not cands:
        return None
    floor = datetime.min.replace(tzinfo=UTC)
    return max(cands, key=lambda t: parse(t.get("roomAssignedDateTimeUtc")) or floor)


def _ids(people: Any) -> list[str]:
    return [str(p["id"]) for p in people or [] if isinstance(p, dict) and p.get("id")]


class ScheduleApplier:
    """조회 결과 한 번을 트랜잭션 하나로 반영한다(덮어쓰기 규칙 §4.3)."""

    def __init__(self, tx: Tx, now: datetime):
        self.tx = tx
        self.now = now
        self.staff = {k: s.id for k, s in tx.staff_by_kos().items()}

    def staff_ids(self, people: Any) -> list[int]:
        out = []
        for p in people or []:
            if not isinstance(p, dict) or not p.get("id"):
                continue
            kid = str(p["id"])
            if kid not in self.staff:  # 직원 목록에 아직 없는 계정 — 이름만 둔다(원장 목록엔 안 들어간다)
                self.staff[kid] = self.tx.upsert("staff", kid, {"name": p.get("name") or "", "role_tags": [], "active": False,
                                                                "is_doctor": False, "synced_at": self.now})
            out.append(self.staff[kid])
        return out

    def apply(self, schedules: list[dict[str, Any]]) -> set[int]:
        """→ 이번 조회에 있던 visit id."""
        tx, now = self.tx, self.now
        known = tx.visit_by_kos()
        busy: dict[str, list[dict[str, Any]]] = {}
        for op in tx.ops(("pending", "sent")):
            busy.setdefault(str(op.visit_id), []).append({"path": op.path, "body": op.body})
        seen: set[int] = set()
        for sch in schedules:
            if not sch.get("id") or sch.get("deleted"):
                continue
            kos_id = str(sch["id"])
            visitor = sch.get("visitor") or {}
            cust_id = None
            if visitor.get("id"):
                cust_id = tx.upsert("customer", str(visitor["id"]), {
                    "name": visitor.get("name") or "", "phonetic_name": visitor.get("phoneticName"),
                    "nationality": visitor.get("nationality"), "is_new": bool(visitor.get("isNew")),
                    "chart_number": visitor.get("chartNumber"), "synced_at": now})
            tasks = [t for t in sch.get("tasks") or [] if isinstance(t, dict)]
            rt = _room_task(tasks)
            room_id = None
            if rt:
                r = rt["room"]
                room_id = tx.upsert("room", str(r["id"]), {"zone_kos_id": r.get("zoneId"), "title": r.get("title") or "",
                                                           "order": r.get("order") or 0})
            prev = known.get(kos_id)
            pending = busy.get(str(prev.id), []) if prev else []
            fields: dict[str, Any] = {
                "customer_id": cust_id, "zone_kos_id": (sch.get("zone") or {}).get("id"),
                "order_memo": sch.get("orderMemo"), "room_id": room_id,
                "room_assigned_at": parse(rt.get("roomAssignedDateTimeUtc")) if rt else None,
                "kos_updated_at": parse(sch.get("updatedDateTimeUtc")), "synced_at": now, "present": True,
            }
            if not any(touches_flow_step(o["path"]) for o in pending):  # 반영 대기 중 changeFlowStep 이 있으면 안 덮는다
                fields["flow_step"] = sch.get("flowStep")
                fields["flow_step_at"] = parse(sch.get("flowStepUpdatedDateTimeUtc"))
            if prev is None:
                fields["seen_at"] = now
            fields["open_task_seqs"] = sorted(int(t["sequence"]) for t in tasks if t.get("sequence") is not None
                                              and t.get("status") not in ("DONE", "CANCELED"))
            vid = tx.upsert("visit", kos_id, fields)
            seen.add(vid)

            guarded: set[int] = set()
            for o in pending:
                guarded |= touched_sequences(o["body"])
            keep: set[int] = set()
            for t in tasks:
                if t.get("type") not in ("PROCEDURE", "ETCETERA") or t.get("sequence") is None:
                    continue
                seq = int(t["sequence"])
                keep.add(seq)
                pf: dict[str, Any] = {"kind": "procedure" if t.get("type") == "PROCEDURE" else "etc",
                                      "kos_order": t.get("order"), "title": t.get("title") or "",
                                      "payment_required": bool(t.get("paymentRequired")), "synced_at": now, "present": True}
                if seq not in guarded:  # 반영 대기 중 호출 · 수락 · 완료가 있으면 그 작업은 안 덮는다
                    pf.update({
                        "kos_status": t.get("status"),
                        "doctor_staff_ids": self.staff_ids(t.get("doctors")),
                        "assignee_staff_ids": self.staff_ids(t.get("assignees")),
                        "doctor_assigned_at": parse(t.get("doctorAssignedDateTimeUtc")),
                        "doctor_call_at": parse(t.get("doctorCallDateTime")),
                        "completed_at": parse(t.get("completedDateTimeUtc")),
                        "room_kos_id": str((t.get("room") or {}).get("id") or "") or None,
                    })
                tx.upsert_procedure(vid, seq, pf)
            tx.mark_absent_procedures(vid, keep)  # KOS 에서 빠진 작업은 목록에서 뺀다(행은 남김)
        tx.mark_absent_visits(seen)
        return seen


class KosSync:
    def __init__(self, settings: Settings, repo: Repository, client: KosClient, clock: Clock):
        self.s = settings
        self.repo = repo
        self.client = client
        self.clock = clock

    def in_window(self) -> bool:
        return in_window(self.clock.now(), self.s.poll_window)

    async def sync_master(self, force: bool = False) -> bool:
        """직원 · 방(1시간). 조회 시간 밖이면 건너뛴다 — 서버 시작 1회(force)만 시간과 상관없이(리뷰 W8) → 했나."""
        if not force and not self.in_window():
            return False
        try:
            return await self._sync_master()
        except Exception as e:  # KosError 아닌 예외(응답 모양 등)도 남긴다(리뷰 W6) — 메시지는 상태 · 클래스만
            error = str(e) if isinstance(e, KosError) else type(e).__name__
            log.warning("KOS 직원 · 방 조회 실패: %s", error)
            with self.repo.tx() as tx:
                tx.set_sync("master", None, error)
            return False

    async def _sync_master(self) -> bool:
        now = self.clock.now()
        accounts = await self.client.open(PATH_ACCOUNTS, {})
        rooms = await self.client.internal(PATH_ROOMS, {"zoneId": self.s.kos_zone_id})
        system_id = self.client.system_kos_id()
        with self.repo.tx() as tx:
            for a in accounts.get("data") or []:
                if isinstance(a, dict) and a.get("id"):
                    tx.upsert("staff", str(a["id"]), {"name": a.get("name") or "", "role_tags": a.get("roleTags") or [],
                                                      "active": bool(a.get("activate")), "synced_at": now})
            for r in rooms.get("data") or []:
                if isinstance(r, dict) and r.get("id"):
                    tx.upsert("room", str(r["id"]), {"zone_kos_id": r.get("zoneId"), "title": r.get("title") or "",
                                                     "order": r.get("order") or 0, "synced_at": now})
            tx.set_doctor_flags(system_id, self.s.exclude_account_ids)
            tx.set_sync("master", now, None)
        log.info("KOS 직원 %d · 방 %d", len(accounts.get("data") or []), len(rooms.get("data") or []))
        return True

    async def sync_schedules(self) -> dict[str, int] | None:
        """일정(10초). 조회 시간 밖이면 None. 실패면 sync_state 에 남기고 화면은 마지막 값 그대로."""
        if not self.in_window():
            return None
        try:
            return await self._sync_schedules()
        except Exception as e:  # KosError 아닌 예외도 「동기화 실패」로(리뷰 W6) — 반영은 트랜잭션째 되돌아간다
            error = str(e) if isinstance(e, KosError) else type(e).__name__
            log.warning("KOS 일정 조회 실패: %s", error)
            with self.repo.tx() as tx:
                tx.set_sync("schedules", None, error)
            return {"error": 1}

    async def _sync_schedules(self) -> dict[str, int]:
        now = self.clock.now()
        start, end = today_range_kst(now)
        body = {"zoneIds": [self.s.kos_zone_id], "startDateTimeUtc": kos_utc(start), "endDateTimeUtc": kos_utc(end)}
        resp = await self.client.internal(PATH_SCHEDULES, body)
        if not isinstance(resp.get("data"), list):
            # 2xx 인데 JSON 이 아니거나 data 가 없으면 「일정 0건」이 아니라 동기화 실패 — 카드(present)를 건드리지 않는다
            raise KosError("일정 응답 형식")
        schedules = flatten_schedules(resp)
        system_id = self.client.system_kos_id()
        with self.repo.tx() as tx:
            ScheduleApplier(tx, now).apply(schedules)
            result = confirm_ops(tx, {str(s.get("id")): s for s in schedules}, system_id, now)
            tx.set_sync("schedules", now, None)
        return {"schedules": len(schedules), **result}
