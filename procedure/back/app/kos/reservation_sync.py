"""KOS 예약 조회 → 사본(SPEC-005 §4.2 · §4.3).

- 1시간 목록(서버 시작 1회 포함 · `KosRuntime.master_once` 에 이어 붙임): 구역 · 예약 그룹 · 다른 구역 방 · 유입 코드 · 기타 작업
- 날짜별(화면이 볼 때 · `KOS_RESV_CACHE_SEC` 캐시 · 날짜 잠금): 하루 예약 → 칸 정원 → 공지 → (오늘만) 금액
- 조회 시간(09:00 ~ 21:00)은 걸지 않는다 · 실패는 그 날짜 `sync_state("resv:<날짜>")` 에 이름만
"""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from app.config import Settings
from app.domain.clock import KST, Clock, kos_utc, parse, to_db
from app.domain.reservation_rules import WEEKDAYS, day_range, purchase_amount
from app.kos.client import KosClient, KosError
from app.kos.sync import PATH_ROOMS, _card_room_task
from app.repository.repo import Repository, Tx

log = logging.getLogger("procedure.kos")

PATH_ZONES = "schedule/open/zone/v1/queries/get-zones"
PATH_GROUPS = "schedule/group/v1/queries/get-reservation-groups"
PATH_CODES = "meta/codes/v1/queries/get-codes"
PATH_ETC = "schedule/etcetera-tasks/v1/queries/get-etcetera-tasks"
PATH_DAY = "schedule/v2/queries/get-schedules-for-reservation"
PATH_SLOTS = "schedule/open/v2/queries/get-reservation-slots-by-groups"
PATH_NOTICES = "meta/notice/v1/queries/get-notices"
PATH_PURCHASES = "purchase/open/v1/queries/get-purchase-summaries"
PATH_DETAIL = "schedule/v1/queries/get-schedule-detail"


def _err(e: Exception) -> str:
    return str(e) if isinstance(e, KosError) else type(e).__name__


def _data_list(resp: dict[str, Any], what: str) -> list[dict[str, Any]]:
    data = resp.get("data")
    if not isinstance(data, list):  # 2xx 인데 data 가 배열 아님 = 실패(SPEC-003 §4.2 와 같은 규칙)
        raise KosError(f"{what} 응답 형식")
    return [x for x in data if isinstance(x, dict)]


def _kst_hhmm(value: Any) -> str | None:
    """날짜 붙은 UTC 문자열(`2026-08-10T01:00:00Z`) → KST `HH:MM`(시 · 분만 — TA§2)."""
    at = parse(value) if isinstance(value, str) else None
    return at.astimezone(KST).strftime("%H:%M") if at else None


def timetable_of(group: dict[str, Any]) -> dict[str, dict[str, Any]]:
    table = group.get("operationTimetable") or {}
    out = {}
    for day in WEEKDAYS:
        t = table.get(day) if isinstance(table, dict) else None
        t = t if isinstance(t, dict) else {}
        brk = t.get("breaktime") if isinstance(t.get("breaktime"), dict) else {}
        start, end = _kst_hhmm(t.get("startTime")), _kst_hhmm(t.get("endTime"))
        out[day] = {"enabled": bool(t.get("enabled")) and bool(start and end), "start": start, "end": end,
                    "breakStart": _kst_hhmm(brk.get("startTime")), "breakEnd": _kst_hhmm(brk.get("endTime"))}
    return out


def capacities_of(group: dict[str, Any]) -> list[dict[str, Any]]:
    """`intervalCapacities[]` 중 enabled 인 것만 → [{zoneKosId, capacity}](D-44)."""
    out = []
    for c in group.get("intervalCapacities") or []:
        if isinstance(c, dict) and c.get("enabled") and c.get("zoneId"):
            out.append({"zoneKosId": str(c["zoneId"]), "capacity": int(c.get("intervalCapacity") or 0)})
    return out


def _person(p: Any) -> dict[str, str] | None:
    if isinstance(p, dict) and p.get("id"):
        return {"id": str(p["id"]), "name": p.get("name") or ""}
    return None


def resources_of(sch: dict[str, Any]) -> list[dict[str, Any]]:
    """`occupiedResources[]` → 묶음(그룹 id 원천 = 묶음 · 없으면 reservation.reservationGroupId — OQ-702)."""
    resv = sch.get("reservation") or {}
    out = []
    for r in sch.get("occupiedResources") or []:
        if not isinstance(r, dict):
            continue
        rt = r.get("reservationTime") or {}
        rg = r.get("reservationGroup") or {}
        start, end = parse(rt.get("startDateTimeUtc")), parse(rt.get("endDateTimeUtc"))
        if start is None or end is None:
            continue
        group = rg.get("reservationGroupId") or resv.get("reservationGroupId")
        out.append({"kosId": str(r.get("id") or ""), "type": r.get("type") or "RESERVATION_GROUP",
                    "groupKosId": str(group) if group else None,
                    "zoneKosId": str(rg.get("zoneId") or resv.get("zoneId") or (sch.get("zone") or {}).get("id") or "") or None,
                    "startAt": to_db(start), "endAt": to_db(end),
                    "doctors": [p for p in (_person(d) for d in rg.get("doctors") or []) if p]})
    return sorted(out, key=lambda x: x["startAt"])


def tasks_of(sch: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for t in sch.get("tasks") or []:
        if not isinstance(t, dict) or t.get("sequence") is None:
            continue
        room = t.get("room") if isinstance(t.get("room"), dict) else {}
        room_id = str(room.get("id") or "") or None  # 방 없음 = room.id 빈 값(WP-KOS 주의 3)
        out.append({"type": t.get("type"), "sequence": int(t["sequence"]), "title": t.get("title") or "",
                    "status": t.get("status"), "paymentRequired": bool(t.get("paymentRequired")),
                    "roomKosId": room_id, "roomTitle": (room.get("title") or None) if room_id else None,
                    "roomZoneKosId": str(room.get("zoneId") or "") or None if room_id else None,
                    "roomAssignedAt": to_db(parse(t.get("roomAssignedDateTimeUtc"))),
                    "doctors": [p["name"] for p in (_person(d) for d in t.get("doctors") or []) if p]})
    return out


def reservation_fields(sch: dict[str, Any], now: datetime, fallback_day: str | None) -> dict[str, Any]:
    """일정 1건 → reservation 열(§3.3). customer_id 는 부르는 쪽이 넣는다."""
    resv = sch.get("reservation") or {}
    resources = resources_of(sch)
    first = parse(resources[0]["startAt"]) if resources else parse(resv.get("startDateTime"))
    tasks = tasks_of(sch)
    rt = _card_room_task([{**t, "room": {"id": t["roomKosId"]}, "roomAssignedDateTimeUtc": t["roomAssignedAt"]}
                          for t in tasks if t["roomKosId"]])
    return {
        "day": first.astimezone(KST).date().isoformat() if first else fallback_day,
        "zone_kos_id": str((sch.get("zone") or {}).get("id") or resv.get("zoneId") or "") or None,
        "status": resv.get("status"), "flow_step": sch.get("flowStep"),
        "flow_step_at": parse(sch.get("flowStepUpdatedDateTimeUtc")), "reception_at": parse(sch.get("receptionDateTimeUtc")),
        "resources": resources, "consultation_required": bool(resv.get("consultationRequired")),
        "sedation_required": bool(resv.get("sedationRequired")), "counselor": _person(resv.get("counselor")),
        "assignee": _person(resv.get("reservationAssignee")), "memo": resv.get("reservationMemo"),
        "funnel": resv.get("funnel") if isinstance(resv.get("funnel"), dict) else None,
        "connected_channel": resv.get("connectedChannel") if isinstance(resv.get("connectedChannel"), str) else None,
        "desired_discharge_at": parse(resv.get("desiredDischargeDateTimeUtc")),
        "purchase_ids": [str(x) for x in sch.get("purchaseIds") or []],
        "prescription_ids": [str(x) for x in sch.get("prescriptionIds") or []],
        "tasks": tasks, "room_kos_id": rt["roomKosId"] if rt else None, "room_title": rt["roomTitle"] if rt else None,
        "kos_updated_at": parse(sch.get("updatedDateTimeUtc")), "present": True, "synced_at": now,
    }


def upsert_customer(tx: Tx, visitor: dict[str, Any], now: datetime) -> int | None:
    if not isinstance(visitor, dict) or not visitor.get("id"):
        return None
    fields = {"name": visitor.get("name") or "", "phonetic_name": visitor.get("phoneticName"),
              "nationality": visitor.get("nationality"), "is_new": bool(visitor.get("isNew")),
              "chart_number": visitor.get("chartNumber"), "synced_at": now}
    if "gender" in visitor:
        fields["gender"] = visitor.get("gender")
    return tx.upsert("customer", str(visitor["id"]), fields)


def apply_schedule(tx: Tx, sch: dict[str, Any], now: datetime, fallback_day: str | None = None) -> int | None:
    """일정 1건을 사본에 덮어쓴다 → reservation id."""
    if not sch.get("id") or sch.get("deleted"):
        return None
    fields = reservation_fields(sch, now, fallback_day)
    fields["customer_id"] = upsert_customer(tx, sch.get("visitor") or {}, now)
    return tx.upsert("reservation", str(sch["id"]), fields)


class ReservationSync:
    def __init__(self, settings: Settings, repo: Repository, client: KosClient, clock: Clock,
                 mono: Callable[[], float] = time.monotonic):
        self.s = settings
        self.repo = repo
        self.client = client
        self.clock = clock
        self.mono = mono
        self._fetched: dict[date, float] = {}
        self._locks: dict[date, asyncio.Lock] = {}
        self._master_lock = asyncio.Lock()
        self.amounts: dict[str, dict[str, Any]] = {}  # purchaseId → {total, paid, currency} — 저장하지 않음(D-46)

    # ------------------------------------------------------------------ 1시간 목록
    async def master(self) -> bool:
        async with self._master_lock:
            errors = []
            now = self.clock.now()
            for name, fn in (("zones", self._zones), ("groups", self._groups), ("rooms", self._rooms),
                             ("funnels", self._funnels), ("etc", self._etc)):
                try:
                    await fn(now)
                except Exception as e:  # 하나가 실패해도 나머지는 받는다
                    errors.append(f"{name}: {_err(e)}")
                    log.warning("KOS 예약 목록(%s) 조회 실패: %s", name, _err(e))
            with self.repo.tx() as tx:
                tx.set_sync("resv_master", None if errors else now, "; ".join(errors) or None)
            return not errors

    async def _zones(self, now: datetime) -> None:
        rows = _data_list(await self.client.open(PATH_ZONES, {}), "구역")
        with self.repo.tx() as tx:
            keep = set()
            for z in rows:
                if not z.get("id"):
                    continue
                keep.add(str(z["id"]))
                tx.upsert("zone", str(z["id"]), {"title": z.get("title") or "", "order": z.get("order") or 0,
                                                 "is_default": bool(z.get("isDefault")), "present": True, "synced_at": now})
            tx.mark_absent_kos("zone", keep)

    def zone_kos_ids(self) -> list[str]:
        with self.repo.tx() as tx:
            ids = [z.kos_id for z in tx.zones()]
        return ids or ([self.s.kos_zone_id] if self.s.kos_zone_id else [])

    async def _groups(self, now: datetime) -> None:
        body = {"deleted": False, "zoneIds": self.zone_kos_ids()}
        rows = _data_list(await self.client.internal(PATH_GROUPS, body), "예약 그룹")
        with self.repo.tx() as tx:
            keep = set()
            for g in rows:
                if not g.get("id") or g.get("deleted"):
                    continue
                keep.add(str(g["id"]))
                tx.upsert("reservation_group", str(g["id"]), {
                    "title": g.get("title") or "", "order": g.get("order") or 0,
                    "interval_minutes": int(g.get("intervalMinutes") or 30), "capacities": capacities_of(g),
                    "timetable": timetable_of(g), "close_buffer_min": g.get("sameDayCloseBufferMinutes"),
                    "present": True, "synced_at": now})
            tx.mark_absent_kos("reservation_group", keep)

    async def _rooms(self, now: datetime) -> None:
        """다른 구역 방 — KOS_ZONE_ID 밖 구역마다 1번(4층은 시술 현황 직원 · 방 조회가 읽는다)."""
        for zid in self.zone_kos_ids():
            if zid == self.s.kos_zone_id:
                continue
            rows = _data_list(await self.client.internal(PATH_ROOMS, {"zoneId": zid}), "방")
            with self.repo.tx() as tx:
                for r in rows:
                    if r.get("id"):
                        tx.upsert("room", str(r["id"]), {"zone_kos_id": str(r.get("zoneId") or zid),
                                                         "title": r.get("title") or "", "order": r.get("order") or 0,
                                                         "synced_at": now})

    async def _funnels(self, now: datetime) -> None:
        rows = _data_list(await self.client.internal(PATH_CODES, {"category": "FUNNEL"}), "유입 코드")
        with self.repo.tx() as tx:
            for f in rows:
                if f.get("id"):
                    tx.upsert("funnel_code", str(f["id"]), {"name": f.get("name") or "", "order": f.get("order") or 0,
                                                            "closed": bool(f.get("closed")), "is_default": bool(f.get("default")),
                                                            "synced_at": now})

    async def _etc(self, now: datetime) -> None:
        rows = _data_list(await self.client.internal(PATH_ETC, {}), "기타 작업")
        with self.repo.tx() as tx:
            for t in rows:
                if t.get("id"):
                    tx.upsert("etc_task_def", str(t["id"]), {"title": t.get("title") or "", "deleted": bool(t.get("deleted")),
                                                             "synced_at": now})

    # ------------------------------------------------------------------ 날짜별
    def invalidate(self, day: date | str | None = None) -> None:
        """조작 성공 뒤 — 그 날짜 캐시 비움(다음 GET 이 KOS 를 다시 읽는다 · §4.3). None = 전부."""
        if day is None:
            self._fetched.clear()
            return
        self._fetched.pop(date.fromisoformat(day) if isinstance(day, str) else day, None)

    def fresh(self, day: date) -> bool:
        at = self._fetched.get(day)
        return at is not None and self.mono() - at < self.s.kos_resv_cache_sec

    async def ensure(self, day: date) -> None:
        """캐시가 낡았으면 그 날짜를 다시 읽는다 — 같은 날짜는 동시에 한 번만(날짜 잠금)."""
        if self.fresh(day):
            return
        lock = self._locks.setdefault(day, asyncio.Lock())
        async with lock:
            if self.fresh(day):
                return
            await self.fetch_day(day)
            self._fetched[day] = self.mono()

    async def fetch_day(self, day: date) -> None:
        now = self.clock.now()
        start, end = day_range(day)
        key = f"resv:{day.isoformat()}"
        with self.repo.tx() as tx:
            groups = [g.kos_id for g in tx.resv_groups()]
        if not groups:  # 서버 시작 목록 조회가 실패했으면 한 번 더
            await self.master()
            with self.repo.tx() as tx:
                groups = [g.kos_id for g in tx.resv_groups()]
        zones = self.zone_kos_ids()
        try:
            resp = await self.client.internal(PATH_DAY, {"baseDateUtc": kos_utc(start), "reservationGroupIds": groups,
                                                         "zoneIds": zones})
            schedules = _data_list(resp, "예약")
        except Exception as e:
            log.warning("KOS 하루 예약 조회 실패: %s", _err(e))
            with self.repo.tx() as tx:
                tx.set_sync(key, None, _err(e))
            return
        with self.repo.tx() as tx:
            seen = set()
            for sch in schedules:
                rid = apply_schedule(tx, sch, now, day.isoformat())
                if rid is not None:
                    seen.add(rid)
            tx.mark_absent_reservations(day.isoformat(), seen)
        errors = []
        try:
            await self._slots(groups, start, end, now)
        except Exception as e:  # 슬롯 · 공지 · 금액이 실패해도 예약은 보인다(§4.2)
            errors.append(f"정원: {_err(e)}")
        try:
            await self._notices(start, end, now)
        except Exception as e:
            errors.append(f"공지: {_err(e)}")
        if day == now.astimezone(KST).date():
            try:
                await self._amounts(day)
            except Exception as e:
                errors.append(f"금액: {_err(e)}")
        with self.repo.tx() as tx:
            tx.set_sync(key, now, "; ".join(errors) or None)

    async def _slots(self, groups: list[str], start: datetime, end: datetime, now: datetime) -> None:
        if not groups:
            return
        rows = _data_list(await self.client.open(PATH_SLOTS, {"reservationGroupIds": groups, "startDateTimeUtc": kos_utc(start),
                                                              "endDateTimeUtc": kos_utc(end)}), "정원")
        out = []
        for item in rows:
            for sl in item.get("slots") or []:
                if not isinstance(sl, dict):
                    continue
                s_at, e_at = parse(sl.get("startDateTimeUtc")), parse(sl.get("endDateTimeUtc"))
                group = sl.get("reservationGroupId") or item.get("reservationGroupId")
                zone = (sl.get("zone") or {}).get("id") if isinstance(sl.get("zone"), dict) else None
                zone = zone or item.get("zoneId")
                if s_at is None or not group or not zone:
                    continue
                out.append({"group": str(group), "zone": str(zone), "start": s_at, "end": e_at,
                            "capacity": sl.get("capacity"), "count": sl.get("reservationCount")})
        with self.repo.tx() as tx:
            tx.replace_slots(start, end, out, now)

    async def _notices(self, start: datetime, end: datetime, now: datetime) -> None:
        rows = _data_list(await self.client.internal(PATH_NOTICES, {"startDateTimeUtc": kos_utc(start),
                                                                    "endDateTimeUtc": kos_utc(end), "deleted": False}), "공지")
        out = [{"kos_id": str(n["id"]), "content": n.get("content") or "", "released_at": parse(n.get("releaseDateTimeUtc"))}
               for n in rows if n.get("id") and not n.get("deleted")]
        with self.repo.tx() as tx:
            tx.replace_notices(start, end, [n for n in out if n["released_at"] and start <= n["released_at"] < end], now)

    async def _amounts(self, day: date) -> None:
        """오늘 원내 일정들의 수납 금액(§4.2 · §5.9) — 메모리에만."""
        from app.domain.reservation_rules import IN_CLINIC_FLOWS

        with self.repo.tx() as tx:
            ids = sorted({p for r in tx.reservations(day.isoformat()) if r.flow_step in IN_CLINIC_FLOWS for p in r.purchase_ids})
        if ids:
            self.amounts.update(await self.purchase_amounts(ids))

    async def purchase_amounts(self, purchase_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not purchase_ids:
            return {}
        rows = _data_list(await self.client.open(PATH_PURCHASES, {"purchaseIds": purchase_ids}), "수납")
        return {str(p.get("id")): purchase_amount([p]) for p in rows if p.get("id")}
