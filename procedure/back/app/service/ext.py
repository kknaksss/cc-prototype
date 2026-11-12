"""외부 연동 API(SPEC-008 · DEC-010) — 연동처 키 · 호출 제한 · 호출 기록 · 메뉴 · 고객 조회(이름 + 이메일) · 예약.

- 키 = env `PROC_EXT_KEY_<연동처>` · 상수 시간 비교 · 빈 env 연동처와는 견주지 않는다(§7.1)
- 제한 = 키당 최근 60초 60번 · 연동처가 정해지지 않은 오류 응답이 IP 당 최근 60초 10번이면 그 IP 를 막는다(§7.3 · 보정 1 N1)
- 기록 = `ext_call` 1줄(연동처 · 경로 틀 · 상태 · 결과) — 이름 · 이메일 · 키 · IP · 고객 · 예약 id 없음(§3.4 · §7.4)
- 고객 조회와 예약은 같은 함수(`find`)로 고객을 정한다(§5)
- 예약은 지금 `ReservationService.create()` 를 다시 쓴다 — 행위자 = `"ext:<연동처>"` 문자열(§3.5)
"""

import hmac
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from app.config import Settings
from app.domain.clock import KST, Clock, iso, parse
from app.domain.errors import BadGateway, BadRequest, Conflict, NotFound, ServiceUnavailable
from app.domain.models import ResvGroup, Zone
from app.domain.reservation_rules import (
    PREV_RESULT,
    ROOM_TASK_TITLE,
    day_range,
    is_full,
    kst_min,
    open_spans,
    parse_day,
    schedule_start,
    state_of,
    to_min,
)
from app.kos.reservation_sync import resources_of, upsert_customer
from app.repository.repo import Repository
from app.schemas.ext import ExtCustomerReservations, ExtVisits
from app.schemas.reservations import CreateReservationRequest, ExistingCustomerRef, NewCustomer, NewCustomerRef
from app.service import kos_errors
from app.service.questionnaire import WINDOW_SEC, RateLimiter
from app.service.reservations import PATH_BY_VISITOR, PATH_VISITORS, ReservationService, ResvContext

log = logging.getLogger("procedure.ext")

CLIENTS = ("linky", "charty")  # 연동처(코드에 고정 · §7.1)
LIMIT_KEY = 60  # 키당 최근 60초(D-34)
LIMIT_BAD_IP = 10  # 연동처 없는 오류 응답 IP 당 최근 60초(§7.3 — 문진 웹 값 그대로)
PAGE = 1000  # 이름 검색 한 페이지(D-16)
PATH_TICKETS = "ticket/open/v1/queries/get-ticket-bundles"
NOT_FOUND = "일치하는 고객이 없어요"
AMBIGUOUS = "고객을 특정할 수 없어요"
RATE = "잠시 뒤 다시 시도해 주세요"
UNAUTHORIZED = "API 키가 없거나 맞지 않아요"
NOT_CONFIGURED = "외부 예약 설정이 비어 있어요"
DAYS_AHEAD = 90  # 가능 시간대 날짜 범위 — 오늘(KST) ~ 오늘 + 90일(DEC-011 D-08)
VISITS_MAX = 50  # 과거 시술 최근 몇 건(DEC-011 D-10)
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _norm_name(v: Any) -> str:
    """이름 대조(§5 3단계) — 공백을 전부 지우고 소문자."""
    return "".join(v.split()).lower() if isinstance(v, str) else ""


def _norm_email(v: Any) -> str:
    return v.strip().lower() if isinstance(v, str) else ""


def _kst_date(v: Any) -> str | None:
    at = parse(v) if isinstance(v, str) else None
    return at.astimezone(KST).date().isoformat() if at else None


class ExtService:
    def __init__(self, settings: Settings, repo: Repository, clock: Clock, resv: ReservationService):
        self.s = settings
        self.repo = repo
        self.clock = clock
        self.resv = resv
        self.rate = RateLimiter()  # 메모리 카운터(파드 1개 가정 · 재시작하면 지워짐)
        self._logged: dict[tuple[str, str], float] = {}  # (IP, 결과) → 마지막 ext_call(연동처 없는 오류 1분에 1줄)

    # ------------------------------------------------------------------ 키 · 제한(§7.1 · §7.3)
    def match_key(self, key: str | None) -> str | None:
        """들어온 키 → 연동처 이름. 빈 env 연동처와는 견주지 않는다 · 모든 연동처와 다 견준다(상수 시간)."""
        if not key:
            return None
        found = None
        for name, k in (("linky", self.s.proc_ext_key_linky), ("charty", self.s.proc_ext_key_charty)):
            if k and hmac.compare_digest(k.encode(), key.encode()):
                found = name
        return found

    def take_key(self, client: str) -> bool:
        """키당 한 번 쓰기 — 최근 60초 60번에 닿아 있으면 False(세지 않음)."""
        return self.rate.take(("ext_key", client), LIMIT_KEY)

    def ip_blocked(self, ip: str) -> bool:
        return self.rate.full(("ext_bad", ip), LIMIT_BAD_IP)

    def count_bad(self, ip: str) -> None:
        self.rate.add(("ext_bad", ip))

    # ------------------------------------------------------------------ 기록(§3.4 · §7.4)
    def record(self, ip: str, client: str | None, endpoint: str, status: int, outcome: str) -> None:
        """ext_call 1줄 — 연동처 없는 오류 응답은 같은 IP · 같은 결과면 1분에 1줄. 실패해도 응답은 그대로."""
        if client is None and status >= 400:
            now = self.rate.now_mono()
            last = self._logged.get((ip, outcome))
            if last is not None and now - last < WINDOW_SEC:
                return
            self._logged[(ip, outcome)] = now
        try:
            with self.repo.tx() as tx:
                tx.add_ext_call(self.clock.now(), client, endpoint, status, outcome)
        except Exception as e:
            log.warning("ext_call 기록 실패: %s", type(e).__name__)
        log.info("외부 호출 %s %s %s", client or "-", endpoint, status)

    # ------------------------------------------------------------------ 메뉴(§6.3)
    def menu(self) -> dict[str, Any]:
        with self.repo.tx() as tx:
            cats = tx.menu_rows("menu_category")
            products = tx.menu_rows("menu_product")
            options = tx.menu_rows("menu_option")
            comps = tx.menu_rows("menu_composition")
            services = {r["kos_id"]: r for r in tx.menu_rows("menu_medical_service")}
            ok_at, _ = tx.sync_state("menu")
        live_opts: dict[str, list[dict]] = {}
        for o in sorted(options, key=lambda r: r["seq"]):
            if not o["deleted"]:
                live_opts.setdefault(o["product_kos_id"], []).append(o)
        live_comps: dict[str, list[dict]] = {}
        for x in sorted(comps, key=lambda r: r["seq"]):
            live_comps.setdefault(x["option_kos_id"], []).append(x)
        live_products = [p for p in sorted(products, key=lambda r: r["seq"]) if not p["closed"] and not p["deleted"]]
        out = []
        for cat in sorted(cats, key=lambda r: (r["order"], r["kos_id"])):
            if not cat["opened"] or cat["deleted"]:
                continue
            raw = json.loads(cat["raw"])
            items = [self._product(p, live_opts, live_comps, services) for p in live_products
                     if cat["kos_id"] in json.loads(p["category_kos_ids"] or "[]")]
            out.append({"id": cat["kos_id"], "name": cat["name"], "order": cat["order"],
                        "translsMap": raw.get("translsMap") or {}, "products": items})
        return {"syncedAt": iso(ok_at), "categories": out}

    def _product(self, p: dict, opts: dict, comps: dict, services: dict) -> dict[str, Any]:
        raw = json.loads(p["raw"])
        return {"id": p["kos_id"], "title": p["title"], "description": raw.get("description") or "",
                "isEvent": bool(p["is_event"]), "translsMap": raw.get("translsMap") or {},
                "options": [self._option(o, comps, services) for o in opts.get(p["kos_id"], [])]}

    @staticmethod
    def _money(value: int | None, currency: str | None) -> dict[str, Any] | None:
        return None if value is None else {"value": value, "currency": currency or ""}

    @staticmethod
    def _proc(raw: dict) -> dict[str, Any] | None:
        p = raw.get("procedure")
        return {"id": str(p["id"]), "name": p.get("name") or ""} if isinstance(p, dict) and p.get("id") else None

    def _option(self, o: dict, comps: dict, services: dict) -> dict[str, Any]:
        raw = json.loads(o["raw"])
        single, group = o["type"] == "SINGLE", o["type"] == "GROUP"
        unit = None
        ms = services.get(o["medical_service_kos_id"]) if single and o["medical_service_kos_id"] else None
        if ms and ms["unit_type"]:
            unit = {"type": ms["unit_type"], "value": ms["unit_value"]}
        rows = comps.get(o["kos_id"], []) if group else []
        return {"id": o["kos_id"], "type": o["type"], "title": o["title"], "description": raw.get("description") or "",
                "translsMap": raw.get("translsMap") or {},
                "listPriceExVat": self._money(o["list_price"], o["currency"]) if o["type"] != "CONSULTATION" else None,
                "count": o["count"] if single else None, "unit": unit,
                "procedure": self._proc(raw) if single else None,
                "compositions": [self._composition(x) for x in rows]}

    def _composition(self, x: dict) -> dict[str, Any]:
        raw = json.loads(x["raw"])
        return {"title": x["title"], "count": x["count"],
                "unit": {"type": x["unit_type"], "value": x["unit_value"]} if x["unit_type"] else None,
                "listPriceExVat": self._money(x["list_price"], x["currency"]), "procedure": self._proc(raw)}

    # ------------------------------------------------------------------ 고객 정하기(§4.2 · §5)
    async def find(self, name: str, email: str) -> tuple[str, dict[str, Any] | None]:
        """→ ("none" | "one" | "many", 1명이면 KOS 고객). KOS 이름 검색 1번 · 실패 = 502."""
        body = {"indexOfPage": 0, "countInPage": PAGE, "visitorName": name.strip(), "phoneNumber": "", "chartNumber": "",
                "sort": {"by": "lastVisitedDateTimeUtc", "order": "DESC"}}
        try:
            resp = await self.resv.client().internal(PATH_VISITORS, body)
        except Exception as e:
            log.warning("KOS 외부 고객 검색 실패: %s", kos_errors.describe(e))
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE) from None
        data = resp.get("data")
        if not isinstance(data, list):  # 2xx 인데 data 가 없거나 배열 아님 = 실패(「없음」과 섞지 않는다 · D-14)
            log.warning("KOS 외부 고객 검색 응답 형식")
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        count = resp.get("count")
        if isinstance(count, int) and not isinstance(count, bool) and count > PAGE:
            return "none", None  # 상한 — 거르지 않고 「없음」(D-16)
        seen, uniq = set(), []
        for v in data:
            if isinstance(v, dict) and v.get("id") and str(v["id"]) not in seen:
                seen.add(str(v["id"]))
                uniq.append(v)
        want_name, want_email = _norm_name(name), _norm_email(email)
        hits = [v for v in uniq
                if want_name in {n for n in (_norm_name(v.get("name")), _norm_name(v.get("phoneticName"))) if n}
                and _norm_email(v.get("email")) and _norm_email(v.get("email")) == want_email]
        if not hits:
            return "none", None
        return ("one", hits[0]) if len(hits) == 1 else ("many", None)

    def _keep(self, visitor: dict[str, Any]) -> int:
        """찾은 고객 → customer 사본 덮어쓰기(email 은 저장 안 함) → ccc id."""
        with self.repo.tx() as tx:
            return int(upsert_customer(tx, visitor, self.clock.now()) or 0)

    # ------------------------------------------------------------------ 고객 조회(§6.4)
    async def lookup(self, name: str, email: str) -> dict[str, Any]:
        kind, v = await self.find(name, email)
        if kind == "none":
            raise NotFound(NOT_FOUND, "customer_not_found")
        if kind == "many" or v is None:
            raise Conflict("customer_ambiguous", AMBIGUOUS)
        cid = self._keep(v)
        try:
            resp = await self.resv.client().open(PATH_TICKETS, {"visitorId": str(v["id"])})
        except Exception as e:
            log.warning("KOS 시술권 조회 실패: %s", kos_errors.describe(e))
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE) from None
        data = resp.get("data", [])
        if not isinstance(data, list):
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        tickets = [self._ticket(b) for b in data if isinstance(b, dict)]
        return {"customer": {"customerId": cid, "name": v.get("name") or "", "isNew": bool(v.get("isNew")),
                             "lastVisitDate": _kst_date(v.get("lastVisitedDateTimeUtc"))},
                "tickets": tickets}

    @staticmethod
    def _ticket(b: dict[str, Any]) -> dict[str, Any]:
        conf = b.get("optionConfiguration") if isinstance(b.get("optionConfiguration"), dict) else {}
        tickets = [t for s in b.get("ticketSets") or [] if isinstance(s, dict)
                   for t in s.get("tickets") or [] if isinstance(t, dict)]
        made = [at for at in (parse(t.get("createdDateTimeUtc")) if isinstance(t.get("createdDateTimeUtc"), str) else None
                              for t in tickets) if at]
        price = b.get("price") if isinstance(b.get("price"), dict) else {}
        value = price.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):  # KOS 필수 칸 — 없으면 응답 모양 오류
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        return {"optionId": str(conf.get("optionId") or ""), "optionTitle": conf.get("optionTitle") or "",
                "remainingCount": sum(1 for t in tickets if t.get("status") == "AVAILABLE"), "totalCount": len(tickets),
                "purchasedDate": min(made).astimezone(KST).date().isoformat() if made else None,
                "bundlePrice": {"value": int(value), "currency": price.get("currency") or ""}}

    # ------------------------------------------------------------------ 기본 예약 그룹(§6.5 1단계 · §6.6 2단계)
    def _ext_group(self) -> tuple[ResvGroup, list[tuple[Zone, int]]]:
        """외부 예약 기본 그룹 + 켜진 구역 — env 빔 · 사본에 그 그룹 없음 · 켜진 구역 0 = 503.

        KOS 를 부르기 전이다(D-33 · DEC-011 D-09). 예약 · 가능 시간대가 같이 쓴다.
        """
        gid = self.s.kos_ext_reservation_group_id.strip()
        with self.repo.tx() as tx:
            ctx = ResvContext(tx)
            g = ctx.group_by_kos.get(gid) if gid else None
            enabled = ctx.enabled_zones(g) if g is not None else []
        if g is None or not enabled:
            raise ServiceUnavailable("ext_not_configured", NOT_CONFIGURED)
        return g, enabled

    # ------------------------------------------------------------------ 예약(§6.5)
    async def reserve(self, client: str, name: str, email: str, start: str, memo: str | None) -> dict[str, int]:
        g, _ = self._ext_group()
        kind, v = await self.find(name, email)
        if kind == "many":
            raise Conflict("customer_ambiguous", AMBIGUOUS)
        if kind == "one" and v is not None:
            customer: ExistingCustomerRef | NewCustomerRef = ExistingCustomerRef(customerId=self._keep(v))
        else:
            customer = NewCustomerRef(new=NewCustomer(name=name.strip(), email=email.strip()))
        req = CreateReservationRequest(groupId=g.id, start=start, customer=customer,
                                       memo=memo if memo and memo.strip() else None)
        try:
            out = await self.resv.create(f"ext:{client}", req)
        except Conflict as e:
            if e.code == "duplicated_visitor":  # KOS 중복 검사 — candidate 를 싣지 않는다(코디 Q1)
                raise Conflict("customer_ambiguous", AMBIGUOUS) from None
            raise
        return {"reservationId": out.reservationId, "customerId": out.customerId}

    # ------------------------------------------------------------------ 예약 가능 시간대(§6.6)
    def _day(self, value: str, now: datetime) -> date:
        """`YYYY-MM-DD` · 오늘(KST) ~ 오늘 + 90일 — 그 밖 400(빈 값을 오늘로 보지 않는다)."""
        if not DAY_RE.fullmatch(value or ""):
            raise BadRequest("invalid_request", "date: YYYY-MM-DD 꼴이어야 해요")
        day = parse_day(value, now)
        today = now.astimezone(KST).date()
        if not today <= day <= today + timedelta(days=DAYS_AHEAD):
            raise BadRequest("invalid_request", f"date: 오늘(KST)부터 {DAYS_AHEAD}일 뒤까지만 볼 수 있어요")
        return day

    async def availability(self, date_value: str) -> dict[str, Any]:
        now = self.clock.now()
        day = self._day(date_value, now)
        g, enabled = self._ext_group()
        sync = self.resv.sync
        if sync is None:
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        try:  # 요청마다 1번 — 공유 사본을 바꿔 바로 뒤 예약 생성이 같은 값을 본다(DEC-011 D-12)
            await sync.refresh_slots(day)
        except Exception as e:
            log.warning("KOS 외부 가능 시간대 정원 조회 실패: %s", kos_errors.describe(e))
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE) from None
        d0, d1 = day_range(day)
        with self.repo.tx() as tx:
            slots = {(sl.group_kos_id, sl.zone_kos_id, kst_min(sl.start_at, day)): sl for sl in tx.slots(d0, d1)}
        iv = g.interval_minutes
        out = []
        for span_start, span_end in open_spans(g.timetable, day):
            a, b = to_min(span_start), to_min(span_end)
            m = a + (-a % iv)  # 자정 기준 간격 경계(`lines()` 와 같은 경계)
            while iv > 0 and m + iv <= b:
                at = d0 + timedelta(minutes=m)
                seats = self._seats(g, enabled, slots, m)
                if at > now and seats > 0:
                    out.append({"start": iso(at), "remainingSeats": seats})
                m += iv
        return {"date": day.isoformat(), "intervalMinutes": iv, "slots": out}

    @staticmethod
    def _seats(g: ResvGroup, enabled: list[tuple[Zone, int]], slots: dict, m: int) -> int:
        """켜진 구역별 남은 자리 합 — 예약 생성의 정원 검사(`is_full`)와 같은 사본 행 · 같은 규칙.

        행이 없거나 capacity 가 null 인 구역은 넣지 않는다(자리 수를 모름 · DEC-011 D-11). 「참」인 구역 = 0.
        """
        total = 0
        for z, _ in enabled:
            sl = slots.get((g.kos_id, z.kos_id, m))
            if sl is None or sl.capacity is None or is_full(sl.capacity, sl.reservation_count):
                continue
            total += max(0, sl.capacity - (sl.reservation_count or 0))
        return total

    # ------------------------------------------------------------------ 과거 시술 · 예약 내역(§6.7 · §6.8)
    async def _schedules(self, name: str, email: str) -> list[dict[str, Any]]:
        """고객 정하기(조회와 같은 함수 · 사본에 쓰지 않음) → 고객 일정 전부(KOS 공개 1번)."""
        kind, v = await self.find(name, email)
        if kind == "none":
            raise NotFound(NOT_FOUND, "customer_not_found")
        if kind == "many" or v is None:
            raise Conflict("customer_ambiguous", AMBIGUOUS)
        try:
            resp = await self.resv.client().open(PATH_BY_VISITOR, {"visitorId": str(v["id"])})
        except Exception as e:
            log.warning("KOS 고객 일정 조회 실패: %s", kos_errors.describe(e))
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE) from None
        data = resp.get("data", [])  # 키 없음(`{}`) · `[]` = 일정 없음(§4.3 과 같은 규칙)
        if not isinstance(data, list):  # 있으면서 배열 아님 = 실패(빈 목록이 아니다)
            log.warning("KOS 고객 일정 응답 형식")
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        return [x for x in data if isinstance(x, dict) and not x.get("deleted")]  # 지운 일정은 두 목록 다 뺀다(사본 쓰기와 같음)

    @staticmethod
    def _shape_error(e: Exception) -> BadGateway:
        """일정 원소 모양이 깨져 처리 중 예외 = KOS 응답 모양 오류 → 502(1차 W1 과 같은 분류 · 원문 · 문구 없이 종류만)."""
        log.warning("KOS 고객 일정 원소 형식: %s", type(e).__name__)
        return BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)

    async def visits(self, name: str, email: str) -> dict[str, Any]:
        schedules = await self._schedules(name, email)
        now = self.clock.now()
        try:
            rows = []
            for sch in schedules:
                start = schedule_start(sch)
                if start is None or start >= now:
                    continue
                status = (sch.get("reservation") or {}).get("status")
                procs = [t.get("title") or "" for t in sch.get("tasks") or [] if isinstance(t, dict)
                         and not (t.get("type") == "ETCETERA" and (t.get("title") or "").strip() == ROOM_TASK_TITLE)]
                rows.append((start, {"date": start.astimezone(KST).date().isoformat(), "start": iso(start),
                                     "result": PREV_RESULT.get(status or "", "other"), "procedures": procs}))
            rows.sort(key=lambda x: x[0], reverse=True)
            out = {"visits": [x[1] for x in rows[:VISITS_MAX]]}
            return ExtVisits.model_validate(out).model_dump()  # 칸 타입까지 여기서 — 응답 모델 오류도 502(N1)
        except (AttributeError, TypeError, ValueError, KeyError) as e:  # pydantic ValidationError ⊂ ValueError
            raise self._shape_error(e) from None

    async def reservations(self, name: str, email: str) -> dict[str, Any]:
        schedules = await self._schedules(name, email)
        today0 = day_range(self.clock.now().astimezone(KST).date())[0]
        try:
            rows = []
            with self.repo.tx() as tx:
                for sch in schedules:
                    start = schedule_start(sch)
                    if start is None or start < today0:
                        continue
                    resv = sch.get("reservation") or {}
                    res = resources_of(sch)
                    rid = tx.reservation_id_of(str(sch["id"])) if sch.get("id") else None  # 일정 KOS id 로만 · 새로 쓰지 않음
                    rows.append((start, {"reservationId": rid, "date": start.astimezone(KST).date().isoformat(),
                                         "start": iso(start), "end": iso(parse(res[0]["endAt"])) if res else None,
                                         "state": state_of(resv.get("status"), sch.get("flowStep"))[0]}))
            rows.sort(key=lambda x: x[0])
            return ExtCustomerReservations.model_validate({"reservations": [x[1] for x in rows]}).model_dump()
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            raise self._shape_error(e) from None
