"""예약 현황 service(SPEC-005 §4 · §5 · §7) — 사본 조회 조립 · 조작(§8 KOS 호출 순서).

KOS 는 `KosRuntime` 을 통해서만 부른다(env 가 비면 없음 — 조회는 사본만 · 조작은 502). 조작은 동기(§4.4).
"""

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from app.config import Settings
from app.domain.clock import KST, Clock, iso, kos_utc, parse
from app.domain.errors import BadGateway, BadRequest, Conflict, NotFound
from app.domain.models import Account, Reservation, ResvGroup, Zone
from app.domain.reservation_rules import (
    BUSY_FLOWS,
    CLOSED_MAINS,
    IN_CLINIC_FLOWS,
    MAINS,
    PREV_RESULT,
    age_on,
    at_hhmm,
    axis,
    blank,
    can,
    day_range,
    draggable,
    flow_rank,
    health_items,
    identifiable,
    identity_fields,
    is_full,
    kst_min,
    lines,
    open_spans,
    parse_at,
    parse_day,
    payment_required_count,
    plus_allowed,
    purchase_amount,
    receive_mode,
    reception_room_task,
    schedule_start,
    state_of,
    sum_amounts,
)
from app.kos.client import KosError
from app.kos.reservation_sync import PATH_DETAIL, PATH_PURCHASES, apply_schedule, upsert_customer
from app.repository.repo import Repository, Tx
from app.schemas.reservations import (
    SNS_TYPES,
    CreateReservationRequest,
    CreateReservationResponse,
    CustomerSearch,
    ExistingCustomerRef,
    MoveRequest,
    NewCustomer,
    NewCustomerRef,
    PersonalIn,
    ReservationBoard,
    ReservationDetail,
    ReservationForm,
)
from app.service import kos_errors

log = logging.getLogger("procedure.resv")

GONE = "KOS 에서 사라진 예약이에요"
PIN_SEC = 5  # 먼저 실은 단계를 지키는 창(KOS 반영 0 ~ 3초 · r2 W1)
PATH_VISITORS = "visitor/v2/queries/get-visitors"
PATH_VISITOR = "visitor/v2/queries/get-visitor"
PATH_Q_FORM = "visitor/open/v1/queries/get-visitor-questionnaire"
PATH_Q_SUBMIT = "visitor/open/v1/queries/get-questionnaire-submit"
PATH_BY_VISITOR = "schedule/open/v1/queries/get-schedules-by-visitor"
PATH_RESERVE = "schedule/reservation/v2/commands/reserve"
PATH_UPDATE = "schedule/reservation/v2/commands/update-reservation"
PATH_CANCEL = "schedule/open/v1/commands/cancel-reservation"
PATH_MEMO = "schedule/open/v1/commands/change-reservation-memo"
PATH_DUPLICATED = "visitor/v1/queries/find-duplicated-visitor"
PATH_CREATE_VISITOR = "v1/visitor/commands/create-visitor"
PATH_PERSONAL = "visitor/v2/commands/update-visitor-personal-information"
PATH_MANAGEMENT = "visitor/v2/commands/update-visitor-management-information"
NO_KOS = "KOS 설정이 비어 있어요"


def _at(day: date, minutes: int) -> datetime:
    return day_range(day)[0] + timedelta(minutes=minutes)


def _parse_req(value: str) -> datetime:
    return parse_at(value)


def _date10(v: Any) -> str | None:
    return str(v)[:10] if isinstance(v, str) and len(v) >= 10 else None


def _counselors(staff, system_kos: str | None, exclude: set[str]):
    """상담사 목록(D-36) = role_tags 에 COUNSELOR · 활성 · 시스템 계정 · 제외 목록(`KOS_EXCLUDE_ACCOUNT_IDS`) 뺌.

    시술 현황 원장 목록(`set_doctor_flags`)과 같은 규칙 — 마취용 등은 제외 목록으로 뺀다(E2E b2 #5).
    """
    return [x for x in staff if "COUNSELOR" in x.role_tags and x.active and x.kos_id != system_kos
            and x.kos_id not in exclude]



def _unique(items) -> list:
    out = []
    for x in items:
        if x and x not in out:
            out.append(x)
    return out


def busy_rooms(today: list[Reservation], zone_kos_id: str | None, exclude_id: int | None = None) -> set[str]:
    """§5.7 「사용 중」 — 오늘 그 구역 · 접수 ~ 시술 진행 · 취소 · 부도 아님 · 안 취소된 작업에 붙은 방(type 무관)."""
    out: set[str] = set()
    for r in today:
        if r.id == exclude_id or r.zone_kos_id != zone_kos_id or r.flow_step not in BUSY_FLOWS:
            continue
        if state_of(r.status, r.flow_step)[0] in CLOSED_MAINS:
            continue
        out |= {t["roomKosId"] for t in r.tasks if t.get("roomKosId") and t.get("status") != "CANCELED"}
    return out


def counselor_busy_room(today: list[Reservation], counselor_kos_id: str) -> str | None:
    """§5.8 — 오늘(두 구역) CONSULTATION 이고 그 상담사인 일정 중 flow_step_at 가장 늦은 것의 카드 방. 없으면 None(비어있음)."""
    far = datetime.min.replace(tzinfo=KST)
    mine = [r for r in today if r.flow_step == "CONSULTATION" and (r.counselor or {}).get("id") == counselor_kos_id
            and state_of(r.status, r.flow_step)[0] not in CLOSED_MAINS]
    if not mine:
        return None
    r = max(mine, key=lambda x: x.flow_step_at or far)
    return r.room_title or "-"


def personal_of(v: dict[str, Any] | None) -> dict[str, Any] | None:
    """KOS get-visitor → §7.3 personal(빈 칸 키 없음 = None)."""
    if v is None:
        return None

    def phone(p):
        return {"countryCode": p.get("countryCode"), "number": p.get("phoneNumber")} if isinstance(p, dict) else None

    sns, addr = v.get("snsInfo"), v.get("address")
    return {
        "name": v.get("name"), "phoneticName": v.get("phoneticName"), "gender": v.get("gender"),
        "dateOfBirth": _date10(v.get("dateOfBirth")), "registrationNumber": v.get("registrationNumber"),
        "passportNumber": v.get("passportNumber"), "passportSurname": v.get("passportSurname"),
        "passportGivenNames": v.get("passportGivenNames"), "passportExpiryDate": _date10(v.get("passportExpiryDate")),
        "foreignRegistrationNumber": v.get("foreignRegistrationNumber"), "nationality": v.get("nationality"),
        "language": v.get("language"), "phone": phone(v.get("phoneNumber")),
        "additionalPhone": phone(v.get("additionalPhoneNumber")),
        "email": v.get("email"),
        "sns": {"type": sns.get("snsType"), "accountId": sns.get("accountId")} if isinstance(sns, dict) else None,
        "address": {"address": addr.get("address"), "detailed": addr.get("detailedAddress"), "zipCode": addr.get("zipCode")}
        if isinstance(addr, dict) else None,
    }


def funnel_of(f: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(f, dict):
        return None
    code = f.get("funnel") if isinstance(f.get("funnel"), dict) else {}
    name, detail = code.get("name") or None, f.get("funnelDetail") or None
    return {"name": name, "detail": detail} if (name or detail) else None


def previous_visits(schedules: list[dict[str, Any]], day: date, ctx: "ResvContext") -> list[dict[str, Any]]:
    """§5.13 — 그 예약 날짜(KST)와 같은 날 일정은 뺀다 · 최신 순."""
    from app.kos.reservation_sync import resources_of

    rows = []
    for sch in schedules:
        start = schedule_start(sch)
        if start is None or start.astimezone(KST).date() == day:
            continue
        resv = sch.get("reservation") or {}
        status = resv.get("status")
        res = resources_of(sch)
        g = ctx.groups_all.get(res[0]["groupKosId"] or "") if res else None
        rows.append((start, {
            "date": start.astimezone(KST).date().isoformat(), "start": iso(start),
            "result": PREV_RESULT.get(status or "", "other"), "resultRaw": status,
            "zoneTitle": (sch.get("zone") or {}).get("title"), "groupTitle": g.title if g else None,
            "reservationMemo": resv.get("reservationMemo") or None,
            "consultationMemo": ((sch.get("consultation") or {}).get("consultationMemo") or None)
            if isinstance(sch.get("consultation"), dict) else None,
            "procedures": [{"title": t.get("title") or "", "status": t.get("status"),
                            "doctors": [d.get("name") or "" for d in t.get("doctors") or [] if isinstance(d, dict)]}
                           for t in sch.get("tasks") or [] if isinstance(t, dict)
                           and not (t.get("type") == "ETCETERA" and (t.get("title") or "").strip() == "방 배정")],
        }))
    rows.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in rows]


class ResvContext:
    """조립에 쓰는 사본 한 벌(한 트랜잭션에서 읽음)."""

    def __init__(self, tx: Tx):
        self.zones_all = tx.zones(present_only=False)
        self.zones = [z for z in self.zones_all if z.present]
        self.zone_by_kos: dict[str, Zone] = {z.kos_id: z for z in self.zones_all}
        self.groups = tx.resv_groups()
        self.group_by_kos: dict[str, ResvGroup] = {g.kos_id: g for g in self.groups}
        self.groups_all = {g.kos_id: g for g in tx.resv_groups(present_only=False)}
        self.called = tx.called_sequences()
        self.customers = tx.customers()

    def zone_id(self, kos_id: str | None) -> int | None:
        z = self.zone_by_kos.get(kos_id or "")
        return z.id if z else None

    def called_of(self, r: Reservation) -> set[int]:
        return self.called.get(r.kos_id, set())

    def payment(self, r: Reservation) -> int:
        return payment_required_count(r.tasks, self.called_of(r))

    def enabled_zones(self, g: ResvGroup) -> list[tuple[Zone, int]]:
        """켜진 구역(사본에 있는 것) · 구역 order 순."""
        out = [(self.zone_by_kos[c["zoneKosId"]], int(c["capacity"])) for c in g.capacities if c["zoneKosId"] in self.zone_by_kos]
        return sorted(out, key=lambda x: (x[0].order, x[0].id))


class ReservationService:
    def __init__(self, settings: Settings, repo: Repository, clock: Clock, kos: Callable[[], Any]):
        self.s = settings
        self.repo = repo
        self.clock = clock
        self._kos = kos  # () → KosRuntime | None(시험이 런타임을 바꿔 끼워도 따라간다)
        self._gone_logged: set[str] = set()  # 404 를 이미 로그에 남긴 일정
        self._pins: dict[str, tuple[str, datetime, datetime]] = {}  # kos_id → (단계, 실은 시각, 풀 시각) — 반영 지연 창

    # ------------------------------------------------------------------ KOS
    @property
    def runtime(self):
        return self._kos()

    @property
    def sync(self):
        rt = self.runtime
        return rt.resv if rt is not None else None

    def client(self):
        rt = self.runtime
        if rt is None:
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        return rt.client

    async def ensure_day(self, day: date) -> None:
        if self.sync is not None:
            await self.sync.ensure(day)

    async def ensure_today(self) -> None:
        """오늘 사본이 쓰이는 계산 전 — 오늘 캐시가 낡았으면 오늘 날짜 조회 1번(§4.2 W7)."""
        await self.ensure_day(self.clock.now().astimezone(KST).date())

    # ------------------------------------------------------------------ §7.2 스케줄 표
    async def board(self, date_value: str | None) -> ReservationBoard:
        now = self.clock.now()
        day = parse_day(date_value, now)
        await self.ensure_day(day)
        start, end = day_range(day)
        with self.repo.tx() as tx:
            ctx = ResvContext(tx)
            resvs = tx.reservations(day.isoformat())
            slots = {(sl.group_kos_id, sl.zone_kos_id, kst_min(sl.start_at, day)): sl for sl in tx.slots(start, end)}
            notices = tx.notices(start, end)
            ok_at, error = tx.sync_state(f"resv:{day.isoformat()}")
        if self.runtime is None:
            error = error or NO_KOS
        today = now.astimezone(KST).date()

        # 카드 = 묶음당 한 장(§5.2)
        cards, spans, lost_count = [], [], 0
        col_count: dict[str | None, int] = {}
        for r in resvs:
            main, sub = state_of(r.status, r.flow_step)
            cust = ctx.customers.get(r.customer_id) if r.customer_id else None
            pay = ctx.payment(r)
            groups_here: set[str | None] = set()
            for i, res in enumerate(r.resources):
                g = ctx.group_by_kos.get(res.get("groupKosId") or "")
                s_at, e_at = parse(res["startAt"]), parse(res["endAt"])
                spans.append((kst_min(s_at, day), kst_min(e_at, day)))
                groups_here.add(g.kos_id if g else None)
                cards.append({
                    "reservationId": r.id, "resourceIndex": i, "groupId": g.id if g else None,
                    "zoneId": ctx.zone_id(res.get("zoneKosId") or r.zone_kos_id), "start": iso(s_at), "end": iso(e_at),
                    "customer": {"customerId": cust.id if cust else None, "name": cust.name if cust else "",
                                 "phoneticName": cust.phonetic_name if cust else None, "gender": cust.gender if cust else None,
                                 "nationality": cust.nationality if cust else None, "isNew": bool(cust and cust.is_new)},
                    "state": {"main": main, "sub": sub}, "paymentRequiredCount": pay, "draggable": draggable(main),
                    "_order": g.order if g else 1 << 30, "_start": s_at})
            if main not in CLOSED_MAINS:
                for k in groups_here:
                    col_count[k] = col_count.get(k, 0) + 1
            if None in groups_here:
                lost_count += 1
        cards.sort(key=lambda c: (c["_order"], c["_start"], c["reservationId"], c["resourceIndex"]))
        for c in cards:
            del c["_order"], c["_start"]

        ax = axis(spans)
        columns, slot_rows, rows = [], [], []
        for g in ctx.groups:
            zones = ctx.enabled_zones(g)
            columns.append({"groupId": g.id, "title": g.title, "order": g.order, "intervalMinutes": g.interval_minutes,
                            "count": col_count.get(g.kos_id, 0),
                            "capacities": [{"zoneId": z.id, "capacity": cap} for z, cap in zones],
                            "open": [{"start": a, "end": b} for a, b in open_spans(g.timetable, day)]})
            for m in lines(ax, g.interval_minutes):
                fulls = []
                for z, _ in zones:
                    sl = slots.get((g.kos_id, z.kos_id, m))
                    full = is_full(sl.capacity, sl.reservation_count) if sl else False
                    fulls.append(full)
                    slot_rows.append({"groupId": g.id, "zoneId": z.id, "start": iso(_at(day, m)),
                                      "end": iso(_at(day, m + g.interval_minutes)),
                                      "capacity": sl.capacity if sl else None, "count": sl.reservation_count if sl else None,
                                      "full": full})
                rows.append({"groupId": g.id, "start": iso(_at(day, m)), "plusAllowed": plus_allowed(fulls)})
        if any(c["groupId"] is None for c in cards):  # 「그룹 없음」 칸(§5.2)
            columns.append({"groupId": None, "title": "그룹 없음", "order": (max((g.order for g in ctx.groups), default=0) + 1),
                            "intervalMinutes": 30, "count": col_count.get(None, 0), "capacities": [], "open": []})

        counts = dict.fromkeys(MAINS, 0)
        for r in resvs:
            counts[state_of(r.status, r.flow_step)[0]] += 1
        counts["total"] = sum(v for k, v in counts.items() if k not in CLOSED_MAINS)

        return ReservationBoard.model_validate({
            "date": day.isoformat(), "isToday": day == today, "now": iso(now),
            "sync": {"lastOkAt": iso(ok_at), "lastError": error},
            "axis": {"start": ax[0], "end": ax[1]},
            "zones": [{"zoneId": z.id, "title": z.title, "order": z.order, "isDefault": z.is_default} for z in ctx.zones],
            "columns": columns, "cards": cards, "slots": slot_rows, "rows": rows, "counts": counts,
            "notices": [{"id": n.id, "content": n.content, "releasedAt": iso(n.released_at)} for n in notices],
            "requests": [], "clinic": self._clinic(ctx, resvs) if day == today else None,
        })

    def _clinic(self, ctx: ResvContext, resvs: list[Reservation]) -> dict[str, Any]:
        """원내 현황(§6.4) — 오늘 · 두 구역 · 접수 ~ 귀가 대기 · 구역 order → 접수 시각."""
        amounts = self.sync.amounts if self.sync is not None else {}
        items = [r for r in resvs if r.flow_step in IN_CLINIC_FLOWS and state_of(r.status, r.flow_step)[0] not in CLOSED_MAINS]
        far = datetime.max.replace(tzinfo=KST)

        def key(r: Reservation):
            z = ctx.zone_by_kos.get(r.zone_kos_id or "")
            return (z.order if z else 1 << 30, r.reception_at or far, r.id)

        items.sort(key=key)
        counts = {"all": len(items), "reception": 0, "consultation": 0, "procedure": 0, "home": 0}
        out = []
        for r in items:
            main, sub = state_of(r.status, r.flow_step)
            counts[main] += 1
            cust = ctx.customers.get(r.customer_id) if r.customer_id else None
            out.append({"reservationId": r.id, "zoneId": ctx.zone_id(r.zone_kos_id),
                        "customer": {"name": cust.name if cust else "", "phoneticName": cust.phonetic_name if cust else None,
                                     "nationality": cust.nationality if cust else None},
                        "state": {"main": main, "sub": sub}, "receptionAt": iso(r.reception_at),
                        "paymentRequiredCount": ctx.payment(r),
                        "amount": sum_amounts([amounts.get(p) for p in r.purchase_ids]) if r.purchase_ids else None})
        return {"counts": counts, "items": out}

    # ------------------------------------------------------------------ §7.4 등록 모달
    async def form(self, date_value: str | None, group_id: int | None, start: str | None) -> ReservationForm:
        now = self.clock.now()
        day = parse_day(date_value, now)
        if group_id is not None and start is not None:
            await self.ensure_day(day)
        with self.repo.tx() as tx:
            ctx = ResvContext(tx)
            staff = tx.staff()
            system = tx.token("internal")
            funnels = [f for f in tx.funnel_codes() if not f.closed]
            g = next((x for x in ctx.groups if x.id == group_id), None) if group_id is not None else None
            if group_id is not None and g is None:
                raise BadRequest("invalid_request", "groupId: 없는 예약 그룹이에요")
            slots = {}
            if g is not None and start is not None:
                s_at = _parse_req(start)
                d0, d1 = day_range(s_at.astimezone(KST).date())
                slots = {(sl.group_kos_id, sl.zone_kos_id): sl for sl in tx.slots(d0, d1) if sl.start_at == s_at}
        system_kos = system[2] if system else None
        exclude = self.s.exclude_account_ids
        active = [x for x in staff if x.active and x.kos_id not in exclude]
        sys_staff = next((x for x in staff if x.kos_id == system_kos), None)
        enabled = {z.id: z for z, _ in ctx.enabled_zones(g)} if g is not None else None
        zones = []
        for z in ctx.zones:
            available = True
            if enabled is not None:
                available = z.id in enabled
                sl = slots.get((g.kos_id, z.kos_id)) if g is not None else None
                if available and sl is not None:
                    available = not is_full(sl.capacity, sl.reservation_count)
            zones.append({"zoneId": z.id, "title": z.title, "available": available})
        default = next((x["zoneId"] for x in zones if x["available"] and ctx.zone_by_kos.get(self.s.kos_zone_id)
                        and x["zoneId"] == ctx.zone_by_kos[self.s.kos_zone_id].id), None)
        default = default or next((x["zoneId"] for x in zones if x["available"]), None)
        return ReservationForm.model_validate({
            "staff": [{"staffId": x.id, "name": x.name} for x in active],
            "defaultAssigneeStaffId": sys_staff.id if sys_staff else None,
            "counselors": [{"staffId": x.id, "name": x.name} for x in _counselors(staff, system_kos, exclude)],
            "funnels": [{"funnelId": f.id, "name": f.name} for f in funnels],
            "zones": zones, "defaultZoneId": default, "snsTypes": list(SNS_TYPES)})

    # ------------------------------------------------------------------ §7.4 고객 검색
    async def search(self, name: str | None, phone: str | None, birth: str | None, chart: str | None,
                     page: int) -> CustomerSearch:
        name, phone, birth, chart = (v.strip() if isinstance(v, str) and v.strip() else None for v in (name, phone, birth, chart))
        # 조건 없음 = 최근 방문 순 목록(내부 get-visitors 빈 조건 · 10-27 E2E #1)
        if page < 1:
            raise BadRequest("invalid_request", "page: 1 이상이어야 해요")
        if birth is not None:
            try:
                date.fromisoformat(birth)
            except ValueError:
                raise BadRequest("invalid_request", "birth: YYYY-MM-DD 꼴이어야 해요") from None
        body: dict[str, Any] = {"indexOfPage": page - 1, "countInPage": 20, "visitorName": name or "",
                                "phoneNumber": phone or "", "chartNumber": chart or "",
                                "sort": {"by": "lastVisitedDateTimeUtc", "order": "DESC"}}
        if birth is not None:
            body["dateOfBirth"] = f"{birth} 00:00:00.000Z"
        client = self.client()
        try:
            resp = await client.internal(PATH_VISITORS, body)
        except Exception as e:
            log.warning("KOS 고객 검색 실패: %s", kos_errors.describe(e))
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE) from None
        data = [v for v in resp.get("data") or [] if isinstance(v, dict) and v.get("id")]
        now = self.clock.now()
        items = []
        with self.repo.tx() as tx:
            for v in data:
                cid = upsert_customer(tx, v, now)
                items.append({"customerId": cid, "chartNumber": v.get("chartNumber"), "name": v.get("name") or "",
                              "phoneticName": v.get("phoneticName"), "dateOfBirth": _date10(v.get("dateOfBirth")),
                              "nationality": v.get("nationality"), "isNew": bool(v.get("isNew"))})
        total = resp.get("count") if isinstance(resp.get("count"), int) else len(items)
        return CustomerSearch.model_validate({"items": items, "total": total, "page": page, "pageSize": 20})

    # ------------------------------------------------------------------ 공통
    def _reservation(self, tx: Tx, reservation_id: int) -> Reservation:
        r = tx.reservation(reservation_id)
        if r is None:
            raise NotFound("없는 예약이에요")
        return r

    def _event(self, tx: Tx, actor: Account, type_: str, payload: dict[str, Any]) -> int:
        return tx.add_event(self.clock.now(), actor.login_id, type_, None, payload)


    # ------------------------------------------------------------------ §7.3 예약 상세
    async def detail(self, reservation_id: int) -> ReservationDetail:
        with self.repo.tx() as tx:
            self._reservation(tx, reservation_id)  # 404 먼저
        await self.ensure_today()  # 방 「사용 중」 · 상담사 상태 = 오늘 사본(§4.2 W7)
        now = self.clock.now()
        with self.repo.tx() as tx:
            r = self._reservation(tx, reservation_id)
            cust = tx.customer(r.customer_id) if r.customer_id else None
        if r.day:
            await self.ensure_day(date.fromisoformat(r.day))
        if self.runtime is not None:  # 그 일정만 KOS 에서 바로(캐시 없이) — 열린 모달 폴링이 수납 · 단계를 곧바로 본다(10-27 #17)
            await self.refresh_schedule(r.kos_id, r.day, gone=True)
        with self.repo.tx() as tx:
            r = self._reservation(tx, reservation_id)
        main, sub = state_of(r.status, r.flow_step)
        reads = await self._detail_reads(r, cust, main)
        visitor, visitor_err = reads["visitor"]
        today = now.astimezone(KST).date().isoformat()
        with self.repo.tx() as tx:
            ctx = ResvContext(tx)
            cust = tx.customer(r.customer_id) if r.customer_id else None
            check = tx.last_identity_check(cust.id) if cust else None
            accounts = {a.login_id: a.name for a in tx.accounts()}
            events = [e for e in tx.events() if e["payload"].get("reservationId") == r.id]
            today_resvs = tx.reservations(today)
            staff = tx.staff()
            rooms_all = tx.rooms()
            system = tx.token("internal")
            health = self._health(tx, r, cust, reads)
        staff_by_kos = {x.kos_id: x for x in staff}
        kind, fields, complete = identity_fields(visitor)
        confirmed = bool(check and check.status == "confirmed")
        mode = receive_mode(main, r.flow_step)
        room_task = reception_room_task(r.tasks) if mode == "resume" else None
        locked_room = room_task.get("roomKosId") if room_task else None
        pay = ctx.payment(r)
        rooms = []
        if mode is not None:
            busy = busy_rooms(today_resvs, r.zone_kos_id, exclude_id=r.id)
            rooms = [{"roomId": x.id, "title": x.title, "busy": x.kos_id in busy and x.kos_id != locked_room,
                      "selected": bool(locked_room) and x.kos_id == locked_room}
                     for x in rooms_all if x.zone_kos_id == r.zone_kos_id]
        after = main not in ("reserved", "canceled", "noshow")
        flow = self._flow(r, after, events, accounts, staff_by_kos) if after else None
        counselors = []
        if flow is not None and flow["consultation"] is not None:
            counselors = [{"staffId": x.id, "name": x.name, "busyRoom": counselor_busy_room(today_resvs, x.kos_id)}
                          for x in _counselors(staff, system[2] if system else None, self.s.exclude_account_ids)]
        settlement = None
        if main == "home":
            settlement = {"paymentRequiredCount": pay, "amount": reads["amount"], "prescriptionCount": len(r.prescription_ids),
                          "links": self._links(r, cust)}
        g0 = ctx.groups_all.get((r.resources[0].get("groupKosId") or "") if r.resources else "")
        zone = ctx.zone_by_kos.get(r.zone_kos_id or "")
        day = date.fromisoformat(r.day) if r.day else now.astimezone(KST).date()
        personal = personal_of(visitor)
        return ReservationDetail.model_validate({
            "reservationId": r.id, "day": day.isoformat(),
            "start": iso(parse(r.resources[0]["startAt"])) if r.resources else None,
            "end": iso(max(parse(x["endAt"]) for x in r.resources)) if r.resources else None,
            "groupTitle": g0.title if g0 else None, "zoneId": zone.id if zone else None,
            "zoneTitle": zone.title if zone else None,
            "state": {"main": main, "sub": sub},
            "customer": {
                "customerId": cust.id if cust else 0, "name": cust.name if cust else "",
                "phoneticName": cust.phonetic_name if cust else None, "gender": cust.gender if cust else None,
                "nationality": cust.nationality if cust else None, "isNew": bool(cust and cust.is_new),
                "chartNumber": cust.chart_number if cust else None,
                "age": age_on((visitor or {}).get("dateOfBirth"), day), "personal": personal,
                "personalError": visitor_err, "remark": (visitor or {}).get("memo"),
                "identity": {"status": "confirmed" if confirmed else "unconfirmed",
                             "checkedAt": iso(check.checked_at) if check else None,
                             "checkedBy": accounts.get(check.actor, check.actor) if check else None,
                             "method": check.method if check else None, "kind": kind, "fields": fields, "complete": complete}},
            "reservation": {
                "sedationRequired": r.sedation_required, "memo": r.memo,
                "funnel": funnel_of(r.funnel), "connectedChannel": r.connected_channel or None,
                "counselor": self._staff_ref(r.counselor, staff_by_kos),
                "assignee": {"name": r.assignee["name"]} if r.assignee else None,
                "doctors": [{"name": n} for n in _unique(d["name"] for x in r.resources for d in x.get("doctors") or [])],
                "desiredDischargeAt": iso(r.desired_discharge_at)},
            "health": health, "previousVisits": previous_visits(reads["previous"], day, ctx), "flow": flow,
            "settlement": settlement, "rooms": rooms, "roomLocked": bool(locked_room), "receiveMode": mode,
            "counselors": counselors,
            "can": can(main, r.flow_step, payment_required=pay, identity_confirmed=confirmed,
                       identity_locked=identity_locked(today_resvs, cust.id if cust else None)),
        })

    async def _detail_reads(self, r: Reservation, cust, main: str) -> dict[str, Any]:
        """상세 KOS 읽기 — 하나가 실패해도 나머지는 쓴다(§7.3 · OQ-757)."""
        out: dict[str, Any] = {"visitor": (None, "고객 정보 없음"), "form": None, "submit": None, "submit_err": None,
                               "form_err": None, "previous": [], "amount": None}
        rt = self.runtime
        if rt is None or cust is None:
            if rt is None:
                out["visitor"] = (None, NO_KOS)
                out["form_err"] = NO_KOS
            return out
        client = rt.client
        vid = cust.kos_id
        calls = [client.internal(PATH_VISITOR, {"id": vid}), client.open(PATH_Q_FORM, {"visitorId": vid}),
                 client.open(PATH_Q_SUBMIT, {"visitorId": vid}), client.open(PATH_BY_VISITOR, {"visitorId": vid})]
        want_amount = main == "home" and bool(r.purchase_ids)
        if want_amount:
            calls.append(client.open(PATH_PURCHASES, {"purchaseIds": r.purchase_ids}))
        got = await asyncio.gather(*calls, return_exceptions=True)
        visitor, form, submit, prev = got[:4]
        if isinstance(visitor, BaseException):
            out["visitor"] = (None, kos_errors.describe(visitor))
        else:
            data = visitor.get("data")
            out["visitor"] = (data, None) if isinstance(data, dict) else (None, "고객 응답 형식")
        if isinstance(form, BaseException):
            out["form_err"] = kos_errors.describe(form)
        else:
            out["form"] = form
        if isinstance(submit, KosError) and submit.has("visitorId", "NotFound"):
            out["submit"] = None  # 제출본 없음 — 오류 아님(WP-KOS 주의 2)
        elif isinstance(submit, BaseException):
            out["submit_err"] = kos_errors.describe(submit)
        else:
            out["submit"] = submit
        if not isinstance(prev, BaseException):
            out["previous"] = [x for x in prev.get("data") or [] if isinstance(x, dict)]
        if want_amount and not isinstance(got[4], BaseException):
            out["amount"] = purchase_amount([p for p in got[4].get("data") or [] if isinstance(p, dict)])
        return out

    def _health(self, tx: Tx, r: Reservation, cust, reads: dict[str, Any]) -> dict[str, Any]:
        """§5.11 — 「건강 정보」 질문 × 제출본 · 확인 필요 · 제출본이 새로우면 이력 한 줄."""
        if reads["form_err"] or reads["submit_err"]:
            return {"state": "error", "submittedAt": None, "needCount": 0, "items": []}
        submit = reads["submit"]
        items = health_items(reads["form"], submit)
        if submit is None:
            return {"state": "none", "submittedAt": None, "needCount": 0, "items": items}
        submitted = submit.get("createdDateTimeUtc")
        if cust is not None and isinstance(submitted, str) and submitted and tx.last_questionnaire_at(cust.id) != submitted:
            tx.add_questionnaire(cust.id, r.id, submitted, submit.get("answers") or [], self.clock.now())
        return {"state": "ok", "submittedAt": iso(parse(submitted)), "needCount": sum(1 for i in items if i["needsCheck"]),
                "items": items}

    def _flow(self, r: Reservation, after: bool, events: list[dict], accounts: dict[str, str], staff_by_kos) -> dict:
        reception = [e for e in events if e["type"] == "reception"]
        calls = [e for e in events if e["type"] == "counselor_call"]
        cons = None
        # 상담 거침 = 지금 상담 단계 · ccc 접수가 상담 대기로 끝남 · [+ 상담 추가](KOS consultationRequired 는 안 읽는다 · 10-27)
        routed = any(e["type"] == "reception" and e["payload"].get("endStep") == "CONSULTATION_WAITING" for e in events) \
            or any(e["type"] == "consultation_add" for e in events)
        if r.flow_step in ("CONSULTATION_WAITING", "CONSULTATION") or routed:
            states = {"CONSULTATION_WAITING": "waiting", "CONSULTATION": "doing", "RECEPTION": "none"}
            state = states.get(r.flow_step or "", "done")
            last = calls[-1] if calls else None
            cons = {"state": state, "counselor": self._staff_ref(r.counselor, staff_by_kos),
                    "since": iso(r.flow_step_at) if state == "doing" else None,
                    "calledAt": iso(parse(last["at"])) if last else None,
                    "calledBy": accounts.get(last["actor"], last["actor"]) if last else None}
        proc = {"PROCEDURE_WAITING": "waiting", "PROCEDURE": "doing", "PROCEDURE_DONE": "done", "COMPLETED": "done"}
        home = {"PROCEDURE_DONE": "waiting", "COMPLETED": "done"}
        return {"receptionAt": iso(r.reception_at), "roomTitle": r.room_title,
                "receptionBy": accounts.get(reception[-1]["actor"], reception[-1]["actor"]) if reception else None,
                "consultation": cons,
                "stages": {"procedure": proc.get(r.flow_step or "", "none"), "home": home.get(r.flow_step or "", "none")}}

    @staticmethod
    def _staff_ref(person: dict | None, staff_by_kos) -> dict | None:
        if not person or not person.get("id"):
            return None
        st = staff_by_kos.get(person["id"])
        return {"staffId": st.id if st else None, "name": person.get("name") or (st.name if st else "")}

    def _links(self, r: Reservation, cust) -> dict | None:
        base = self.s.kos_web_base.rstrip("/")
        if not base or cust is None:
            return None
        url = f"{base}/{self.s.kos_tenant_id}/reservation/schedule/?visitorId={cust.kos_id}&scheduleId={r.kos_id}"
        return {"purchase": f"{url}&tab=purchase", "prescription": f"{url}&tab=etceteraWork"}

    # ------------------------------------------------------------------ §5.12 ② 신분 확인 표시(KOS 호출 없음)
    def identity(self, actor: Account, customer_id: int, status: str) -> None:
        now = self.clock.now()
        today = now.astimezone(KST).date().isoformat()
        with self.repo.tx() as tx:
            if tx.customer(customer_id) is None:
                raise NotFound("없는 고객이에요")
            last = tx.last_identity_check(customer_id)
            if status == "unconfirmed" and last is not None and last.status == "confirmed":
                if identity_locked(tx.reservations(today), customer_id):  # [미확인으로]는 접수 전만(§5.14)
                    raise Conflict("identity_locked", "접수 뒤에는 미확인으로 바꿀 수 없어요")
            ev = self._event(tx, actor, "identity", {"customerId": customer_id, "status": status})
            tx.add_identity_check(customer_id, status, now, actor.login_id, ev)

    # ------------------------------------------------------------------ KOS 쓰기 공통(§4.4 — 동기)
    async def kos_write(self, actor: Account, op: str, call, *, reservation_id: int | None = None,
                        customer_id: int | None = None, step: str | None = None) -> dict[str, Any]:
        """KOS 쓰기 1번 — 실패면 event_log(kos_rejected) 1줄 + 409 kos_rejected / 502 kos_unavailable."""
        try:
            return await call
        except Exception as err:
            payload = {k: v for k, v in (("reservationId", reservation_id), ("customerId", customer_id)) if v is not None}
            with self.repo.tx() as tx:
                self._event(tx, actor, "kos_rejected", {**payload, "op": op, "httpStatus": getattr(err, "status", None),
                                                        "kosError": kos_errors.describe(err)})
            log.warning("KOS %s 실패: %s", op, kos_errors.describe(err))
            raise kos_errors.to_domain(err, step) from None

    def after_write(self, *days: str | None) -> None:
        """성공 뒤 — 그 날짜 캐시 비움(§4.3)."""
        if self.sync is not None:
            for d in days:
                if d:
                    self.sync.invalidate(d)

    async def refresh_schedule(self, kos_id: str, fallback_day: str | None = None, *, gone: bool = False) -> int | None:
        """일정 1건을 KOS 에서 다시 읽어 사본에 덮어쓴다(내부 get-schedule-detail) → reservation id. 실패는 None.

        gone = KOS 404 면 404 `reservation_gone`(상세 · E2E b2 #2). 로그는 일정마다 한 번만(폴링 반복 막기).
        등록 직후 다시 읽기는 gone=False — 만든 직후 잠깐 404 가 온다(§3 데모 시험).
        사본은 건드리지 않는다(만든 직후 404 일 수 있음 · 날짜 조회가 목록으로 맞춘다).
        """
        try:
            resp = await self.client().internal(PATH_DETAIL, {"scheduleId": kos_id})
        except Exception as e:
            if gone and isinstance(e, KosError) and e.status == 404:
                if kos_id not in self._gone_logged:
                    self._gone_logged.add(kos_id)
                    log.info("KOS 에 없는 일정(404) — 상세는 reservation_gone")
                raise NotFound(GONE, code="reservation_gone") from None
            log.warning("KOS 일정 다시 읽기 실패: %s", kos_errors.describe(e))
            return None
        self._gone_logged.discard(kos_id)
        data = resp.get("data")
        if not isinstance(data, dict):
            return None
        now = self.clock.now()
        with self.repo.tx() as tx:
            rid = apply_schedule(tx, data, now, fallback_day)
            pin = self._pins.get(kos_id)
            if pin is not None:
                step, at, until = pin
                if now >= until or flow_rank(data.get("flowStep")) >= flow_rank(step):
                    del self._pins[kos_id]  # 창이 지났거나 KOS 가 따라왔다 — 정상 덮어쓰기
                else:  # KOS 가 아직 이전 단계 — 먼저 실은 단계를 지킨다(r2 W1)
                    tx.upsert("reservation", kos_id, {"flow_step": step, "flow_step_at": at})
            return rid

    def pin_step(self, kos_id: str, step: str) -> None:
        """조작이 단계를 사본에 먼저 실었다 — PIN_SEC 동안 상세 다시 읽기가 KOS 의 이전 단계로 되돌리지 않게."""
        now = self.clock.now()
        with self.repo.tx() as tx:
            tx.upsert("reservation", kos_id, {"flow_step": step, "flow_step_at": now})
        self._pins[kos_id] = (step, now, now + timedelta(seconds=PIN_SEC))

    # ------------------------------------------------------------------ §5.5 예약 등록
    async def create(self, actor: Account, body: CreateReservationRequest) -> CreateReservationResponse:
        start = parse_at(body.start)
        day = start.astimezone(KST).date()
        with self.repo.tx() as tx:
            ctx = ResvContext(tx)
            g = next((x for x in ctx.groups if x.id == body.groupId), None)
            if g is None:
                raise BadRequest("invalid_request", "groupId: 없는 예약 그룹이에요")
            enabled = ctx.enabled_zones(g)
            d0, d1 = day_range(day)
            slots = {(sl.group_kos_id, sl.zone_kos_id): sl for sl in tx.slots(d0, d1) if sl.start_at == start}
            zone = self._pick_zone(ctx, g, enabled, slots, body.zoneId)
            sl = slots.get((g.kos_id, zone.kos_id))
            staff = {x.id: x for x in tx.staff()}
            system = tx.token("internal")
            existing = tx.customer(body.customer.customerId) if isinstance(body.customer, ExistingCustomerRef) else None
            funnel = None
            if body.funnelId is not None:
                f = next((x for x in tx.funnel_codes() if x.id == body.funnelId and not x.closed), None)
                if f is None:
                    raise BadRequest("invalid_request", "funnelId: 없는 유입 코드예요")
                funnel = {"funnel": {"id": f.kos_id, "category": "FUNNEL", "name": f.name, "order": f.order,
                                     "closed": f.closed, "default": f.is_default},
                          "funnelDetail": body.funnelDetail or ""}
        assignee = self._assignee(staff, body.assigneeStaffId, system[2] if system else None)
        counselor = None
        if body.counselorStaffId is not None:
            st = staff.get(body.counselorStaffId)
            if st is None or st not in _counselors(list(staff.values()), system[2] if system else None,
                                                                  self.s.exclude_account_ids):
                raise BadRequest("invalid_request", "counselorStaffId: 상담사 목록에 없는 직원이에요")
            counselor = {"id": st.kos_id, "name": st.name}
        discharge = None
        if body.desiredDischargeTime:
            try:
                discharge = kos_utc(at_hhmm(day, body.desiredDischargeTime))
            except ValueError:
                raise BadRequest("invalid_request", "desiredDischargeTime: HH:MM 꼴이어야 해요") from None
        new = body.customer.new if isinstance(body.customer, NewCustomerRef) else None
        birth = _birth(new) if new is not None else None  # 400 끝
        if new is None and existing is None:  # 404
            raise NotFound("없는 고객이에요")
        if new is not None:  # 409 — KOS 를 부르기 전
            self._check_identifiable(new)
        if sl is not None and is_full(sl.capacity, sl.reservation_count):  # 409 — 정원은 KOS 쓰기 직전(r1 W3)
            raise Conflict("slot_full", "그 시간은 정원이 찼어요")

        client = self.client()
        new_customer = existing is None
        if existing is None:
            visitor_kos, cust_id = await self._new_visitor(actor, new, birth)  # type: ignore[arg-type]
        else:
            visitor_kos, cust_id = existing.kos_id, existing.id
        end = start + timedelta(minutes=g.interval_minutes)
        req: dict[str, Any] = {
            "visitorId": visitor_kos, "zoneId": zone.kos_id,
            "occupiedResources": [{"id": str(uuid.uuid4()), "type": "RESERVATION_GROUP",
                                   "reservationTime": {"startDateTimeUtc": kos_utc(start), "endDateTimeUtc": kos_utc(end)},
                                   "reservationGroup": {"reservationGroupId": g.kos_id, "zoneId": zone.kos_id,
                                                        "doctors": []}}],  # 당일 지정 의사 없음(KOS 화면 빈 값과 같음)
            "reservationAssignee": assignee}  # 상담 필요 · 수면마취는 보내지 않는다(10-27 · KOS 기본 false)
        if counselor:
            req["counselor"] = counselor
        if body.memo:
            req["reservationMemo"] = body.memo
        if discharge:
            req["desiredDischargeDateTimeUtc"] = discharge
        if funnel:
            req["funnel"] = funnel
        resp = await self.kos_write(actor, "reserve", client.internal(PATH_RESERVE, req), customer_id=cust_id)
        schedule_id = str(resp.get("scheduleId") or (resp.get("data") or {}).get("scheduleId") or "")
        if not schedule_id:
            raise BadGateway("kos_unavailable", "KOS 응답에 일정 id 가 없어요")
        rid = await self.refresh_schedule(schedule_id, day.isoformat())
        with self.repo.tx() as tx:
            if rid is None:
                rid = tx.upsert("reservation", schedule_id, {"customer_id": cust_id, "day": day.isoformat(), "present": True,
                                                             "status": "RESERVED", "flow_step": "RESERVED"})
            self._event(tx, actor, "resv_create", {"reservationId": rid, "customerId": cust_id, "newCustomer": new_customer,
                                                   "groupId": g.id, "start": iso(start), "end": iso(end)})
        self.after_write(day.isoformat())
        return CreateReservationResponse(reservationId=rid, customerId=cust_id)

    def _pick_zone(self, ctx: "ResvContext", g: ResvGroup, enabled, slots, zone_id: int | None) -> Zone:
        """§5.5 구역 — 고른 구역은 그 그룹에서 켜져 있어야(400) · 생략 = KOS_ZONE_ID(켜짐 · 자리) → order 첫 자리 있는 구역."""
        if not enabled:
            raise BadRequest("invalid_request", "그 그룹에 켜진 구역이 없어요")
        if zone_id is not None:
            z = next((z for z, _ in enabled if z.id == zone_id), None)
            if z is None:
                raise BadRequest("invalid_request", "zoneId: 그 그룹에서 꺼진 구역이에요")
            return z

        def has_room(z: Zone) -> bool:
            sl = slots.get((g.kos_id, z.kos_id))
            return not (sl is not None and is_full(sl.capacity, sl.reservation_count))

        default = next((z for z, _ in enabled if z.kos_id == self.s.kos_zone_id and has_room(z)), None)
        return default or next((z for z, _ in enabled if has_room(z)), enabled[0][0])

    @staticmethod
    def _assignee(staff, staff_id: int | None, system_kos: str | None) -> dict[str, str]:
        if staff_id is not None:
            st = staff.get(staff_id)
            if st is None:
                raise BadRequest("invalid_request", "assigneeStaffId: 없는 직원이에요")
            return {"id": st.kos_id, "name": st.name}
        sys = next((x for x in staff.values() if x.kos_id == system_kos), None)
        return {"id": system_kos or "", "name": sys.name if sys else ""}  # 기본 = 시스템 계정(OQ-710)

    @staticmethod
    def _check_identifiable(new: NewCustomer) -> None:
        phone = new.phone.model_dump() if new.phone else None
        sns = new.sns.model_dump() if new.sns else None
        if not identifiable(new.name, phone=phone, sns=sns, email=new.email, passport=new.passportNumber, birth=new.dateOfBirth):
            raise Conflict("not_identifiable", "고객을 구분할 수 있는 정보가 부족합니다")

    async def _new_visitor(self, actor: Account, new: NewCustomer, birth: date | None) -> tuple[str, int]:
        """(검사 끝난) 신규 고객 → find-duplicated-visitor → create-visitor(§5.5 · §8)."""
        phone = new.phone.model_dump() if new.phone else None
        sns = new.sns.model_dump() if new.sns else None
        name = new.name.strip()
        kos_phone = {"countryCode": phone["countryCode"], "phoneNumber": phone["number"]} if phone else None
        kos_sns = {"snsType": sns["type"], "accountId": sns["accountId"]} if sns else None
        dup: dict[str, Any] = {"name": name}
        for k, v in (("phone", kos_phone), ("passportNumber", new.passportNumber), ("snsInfo", kos_sns), ("email", new.email)):
            if v and not (isinstance(v, str) and blank(v)):
                dup[k] = v
        if birth:
            dup["birthDateUtc"] = kos_utc(day_range(birth)[0])
        client = self.client()
        found = await self.kos_write(actor, "find-duplicated-visitor", client.internal(PATH_DUPLICATED, dup))
        cand = found.get("data") if isinstance(found.get("data"), dict) else None
        now = self.clock.now()
        if cand and cand.get("id"):
            with self.repo.tx() as tx:
                cid = upsert_customer(tx, cand, now)
            raise Conflict("duplicated_visitor", "KOS 에 같은 고객이 있어요",
                           candidate={"customerId": cid, "name": cand.get("name") or "", "chartNumber": cand.get("chartNumber"),
                                      "dateOfBirth": _date10(cand.get("dateOfBirth"))})
        create: dict[str, Any] = {"name": name}
        for k, v in (("phoneticName", new.phoneticName), ("gender", new.gender), ("nationality", new.nationality),
                     ("email", new.email), ("passportNumber", new.passportNumber)):
            if not blank(v):
                create[k] = v.strip()  # type: ignore[union-attr]
        if birth:
            create["dateOfBirth"] = f"{birth.isoformat()} 00:00:00.000Z"
        if kos_phone:
            create["phoneNumber"] = kos_phone
        if kos_sns:
            create["snsInfo"] = kos_sns
        made = await self.kos_write(actor, "create-visitor", client.internal(PATH_CREATE_VISITOR, create))
        vid = str((made.get("data") or {}).get("id") or "")
        if not vid:
            raise BadGateway("kos_unavailable", "KOS 응답에 고객 id 가 없어요")
        with self.repo.tx() as tx:
            cid = upsert_customer(tx, {"id": vid, "name": name, "phoneticName": create.get("phoneticName"),
                                       "nationality": create.get("nationality"), "isNew": True, "chartNumber": None,
                                       "gender": create.get("gender")}, now)
        return vid, cid  # type: ignore[return-value]

    # ------------------------------------------------------------------ §5.4 이동
    async def move(self, actor: Account, reservation_id: int, body: MoveRequest) -> None:
        start = parse_at(body.start)
        with self.repo.tx() as tx:
            r = self._reservation(tx, reservation_id)
            ctx = ResvContext(tx)
            if not 0 <= body.resourceIndex < len(r.resources):
                raise BadRequest("invalid_request", "resourceIndex: 없는 묶음이에요")
            g = next((x for x in ctx.groups if x.id == body.groupId), None)
            if g is None:
                raise BadRequest("invalid_request", "groupId: 없는 예약 그룹이에요")
            res = r.resources[body.resourceIndex]
            old_start, old_end = parse(res["startAt"]), parse(res["endAt"])
            zone_kos = res.get("zoneKosId") or r.zone_kos_id
            day = old_start.astimezone(KST).date()
            if start.astimezone(KST).date() != day:
                raise BadRequest("invalid_request", "start: 같은 날짜 안에서만 옮길 수 있어요")
            if kst_min(start, day) % g.interval_minutes or start.second or start.microsecond:
                raise BadRequest("invalid_request", "start: 그 칸 간격 경계가 아니에요")
            if zone_kos not in {z.kos_id for z, _ in ctx.enabled_zones(g)}:  # 추가 지시 1 W2 — 이동은 구역을 바꾸지 않는다
                raise BadRequest("invalid_request", "그 칸에서 꺼진 구역의 예약이에요")
            main = state_of(r.status, r.flow_step)[0]
            if not draggable(main):
                raise Conflict("not_movable", "옮길 수 없는 예약이에요")
            same = res.get("groupKosId") == g.kos_id and old_start == start  # 제자리
            d0, d1 = day_range(day)
            sl = next((x for x in tx.slots(d0, d1) if x.group_kos_id == g.kos_id and x.zone_kos_id == zone_kos
                       and x.start_at == start), None)
            if not same and sl is not None and is_full(sl.capacity, sl.reservation_count):
                raise Conflict("slot_full", "그 시간은 정원이 찼어요")
            old_group = ctx.groups_all.get(res.get("groupKosId") or "")
        end = start + (old_end - old_start)  # 길이 그대로(D-20)
        items = []
        for i, x in enumerate(r.resources):
            moved = i == body.resourceIndex
            s_at, e_at = (start, end) if moved else (parse(x["startAt"]), parse(x["endAt"]))
            items.append({"id": x["kosId"], "type": x.get("type") or "RESERVATION_GROUP",
                          "reservationTime": {"startDateTimeUtc": kos_utc(s_at), "endDateTimeUtc": kos_utc(e_at)},
                          "reservationGroup": {"reservationGroupId": g.kos_id if moved else x.get("groupKosId"),
                                               "zoneId": x.get("zoneKosId") or r.zone_kos_id,
                                               "doctors": x.get("doctors") or []}})
        await self.kos_write(actor, "update-reservation", self.client().internal(
            PATH_UPDATE, {"scheduleId": r.kos_id, "occupiedResources": {"items": items}}), reservation_id=r.id)
        with self.repo.tx() as tx:
            self._event(tx, actor, "resv_move", {
                "reservationId": r.id, "resourceIndex": body.resourceIndex,
                "from": {"groupId": old_group.id if old_group else None, "start": iso(old_start), "end": iso(old_end)},
                "to": {"groupId": g.id, "start": iso(start), "end": iso(end)}})
        self.after_write(r.day, day.isoformat())

    # ------------------------------------------------------------------ 취소 · 메모
    async def cancel(self, actor: Account, reservation_id: int, reason: str) -> None:
        with self.repo.tx() as tx:
            r = self._reservation(tx, reservation_id)
        if state_of(r.status, r.flow_step)[0] != "reserved":
            raise Conflict("not_cancelable", "접수 전 예약만 취소할 수 있어요")
        await self.kos_write(actor, "cancel-reservation", self.client().open(
            PATH_CANCEL, {"scheduleId": r.kos_id, "reason": reason}), reservation_id=r.id)
        with self.repo.tx() as tx:
            self._event(tx, actor, "resv_cancel", {"reservationId": r.id, "reason": reason, "prevStatus": r.status})
        self.after_write(r.day)

    async def memo(self, actor: Account, reservation_id: int, memo: str) -> None:
        with self.repo.tx() as tx:
            r = self._reservation(tx, reservation_id)
        if state_of(r.status, r.flow_step)[0] == "canceled" or r.flow_step == "COMPLETED":  # §5.14 · r1 W1
            raise Conflict("reservation_closed", "끝난 예약이에요")
        await self.kos_write(actor, "change-reservation-memo", self.client().open(
            PATH_MEMO, {"scheduleId": r.kos_id, "memo": memo}), reservation_id=r.id)
        with self.repo.tx() as tx:
            self._event(tx, actor, "resv_memo", {"reservationId": r.id})
        self.after_write(r.day)

    # ------------------------------------------------------------------ §5.13 고객 정보 · 특이사항
    async def personal(self, actor: Account, customer_id: int, personal: PersonalIn) -> None:
        with self.repo.tx() as tx:
            cust = tx.customer(customer_id)
            if cust is None:
                raise NotFound("없는 고객이에요")
        changes = personal_changes(personal)  # 400 은 KOS 를 부르기 전에
        client = self.client()
        read = await self.kos_write(actor, "get-visitor", client.internal(PATH_VISITOR, {"id": cust.kos_id}),
                                    customer_id=cust.id)
        current = read.get("data") if isinstance(read.get("data"), dict) else None
        if current is None:
            raise BadGateway("kos_unavailable", "KOS 고객 응답 형식")
        body: dict[str, Any] = {"id": cust.kos_id}
        for k in PERSONAL_KEYS:  # 다시 읽은 묶음 전체 — 없던 키는 보내지 않는다(K7)
            if k in current:
                body[k] = current[k]
        body.update(changes)
        await self.kos_write(actor, "update-visitor-personal-information", client.internal(PATH_PERSONAL, body),
                             customer_id=cust.id)
        with self.repo.tx() as tx:
            mirror = {"name": "name", "phoneticName": "phonetic_name", "nationality": "nationality", "gender": "gender"}
            fields = {col: body[k] or None for k, col in mirror.items() if k in changes}
            if fields:
                tx.upsert("customer", cust.kos_id, fields)
            self._event(tx, actor, "visitor_personal", {"customerId": cust.id, "fields": sorted(personal.model_fields_set)})
        self.after_write(*self._days_of(cust.id))

    async def remark(self, actor: Account, customer_id: int, memo: str) -> None:
        with self.repo.tx() as tx:
            cust = tx.customer(customer_id)
            if cust is None:
                raise NotFound("없는 고객이에요")
        client = self.client()
        read = await self.kos_write(actor, "get-visitor", client.internal(PATH_VISITOR, {"id": cust.kos_id}),
                                    customer_id=cust.id)
        current = read.get("data") if isinstance(read.get("data"), dict) else None
        if current is None:
            raise BadGateway("kos_unavailable", "KOS 고객 응답 형식")
        body: dict[str, Any] = {"id": cust.kos_id}
        for k in MANAGEMENT_KEYS:  # 관리 묶음 그대로 + memo 만 바꿈 · 빈 배열은 뺀다(§8 · MT§4)
            if k in current and current[k] != []:
                body[k] = current[k]
        body["memo"] = memo
        await self.kos_write(actor, "update-visitor-management-information", client.internal(PATH_MANAGEMENT, body),
                             customer_id=cust.id)
        with self.repo.tx() as tx:
            self._event(tx, actor, "visitor_remark", {"customerId": cust.id})

    def _days_of(self, customer_id: int) -> list[str]:
        with self.repo.tx() as tx:
            return sorted({r.day for r in tx.reservations() if r.customer_id == customer_id and r.day})


def _birth(new: NewCustomer) -> date | None:
    if blank(new.dateOfBirth):
        return None
    try:
        return date.fromisoformat(new.dateOfBirth.strip())  # type: ignore[union-attr]
    except ValueError:
        raise BadRequest("invalid_request", "dateOfBirth: YYYY-MM-DD 꼴이어야 해요") from None


def identity_locked(today: list[Reservation], customer_id: int | None) -> bool:
    """[미확인으로] 잠김(§5.14 · r1 W4) — 고객 단위: 그 고객의 오늘 예약 중 접수 뒤 단계가 있으면."""
    return customer_id is not None and any(
        r.customer_id == customer_id and state_of(r.status, r.flow_step)[0] not in ("reserved", "noshow", "canceled")
        for r in today)


# ------------------------------------------------------------------ 고객 정보 본문(§8 · K7)
PERSONAL_KEYS = ("name", "phoneticName", "phoneNumber", "additionalPhoneNumber", "email", "dateOfBirth", "gender",
                 "registrationNumber", "foreignRegistrationNumber", "passportNumber", "passportSurname", "passportGivenNames",
                 "passportExpiryDate", "address", "nationality", "language", "snsInfo")
MANAGEMENT_KEYS = ("memo", "visitorFunnel", "visitor", "account", "unregistered", "visitorType", "visitorCategories", "doctor",
                   "counselor", "aggrementPersonalInformation", "aggrementAdvertisements", "agreementInformationalNotification",
                   "customAttributes")
_PLAIN = ("name", "phoneticName", "gender", "registrationNumber", "passportNumber", "passportSurname", "passportGivenNames",
          "foreignRegistrationNumber", "nationality", "language", "email")


def personal_changes(p: PersonalIn) -> dict[str, Any]:
    """§7.5 personal(보낸 키만) → KOS 키 · 꼴. 빈 칸으로 고치면 빈 문자열(U§2.2). 날짜 꼴이 틀리면 400."""
    out: dict[str, Any] = {}
    sent = p.model_fields_set
    for k in _PLAIN:
        if k in sent:
            v = getattr(p, k)
            out[k] = (v or "").strip()
    if "dateOfBirth" in sent:
        out["dateOfBirth"] = _kos_date(p.dateOfBirth, "dateOfBirth", suffix=" 00:00:00.000Z")
    if "passportExpiryDate" in sent:
        out["passportExpiryDate"] = _kos_date(p.passportExpiryDate, "passportExpiryDate")
    for k, kos in (("phone", "phoneNumber"), ("additionalPhone", "additionalPhoneNumber")):
        if k in sent and getattr(p, k) is not None:
            v = getattr(p, k)
            out[kos] = {"countryCode": v.countryCode or "", "phoneNumber": v.number or ""}
    if "sns" in sent and p.sns is not None:
        out["snsInfo"] = {"snsType": p.sns.type or "", "accountId": p.sns.accountId or ""}
    if "address" in sent and p.address is not None:
        out["address"] = {"address": p.address.address or "", "detailedAddress": p.address.detailed or "",
                          "zipCode": p.address.zipCode or ""}
    return out


def _kos_date(v: str | None, what: str, suffix: str = "") -> str:
    if blank(v):
        return ""
    try:
        return date.fromisoformat(v.strip()).isoformat() + suffix  # type: ignore[union-attr]
    except ValueError:
        raise BadRequest("invalid_request", f"{what}: YYYY-MM-DD 꼴이어야 해요") from None
