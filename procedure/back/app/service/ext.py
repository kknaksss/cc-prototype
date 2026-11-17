"""외부 연동 API(SPEC-008 · DEC-010) — 연동처 키 · 호출 제한 · 호출 기록 · 메뉴 · 고객 조회(이름 + 이메일) · 예약.

- 키 = env `PROC_EXT_KEY_<연동처>` · 상수 시간 비교 · 빈 env 연동처와는 견주지 않는다(§7.1)
- 제한 = 키당 최근 60초 60번 · 연동처가 정해지지 않은 오류 응답이 IP 당 최근 60초 10번이면 그 IP 를 막는다(§7.3 · 보정 1 N1)
- 기록 = `ext_call` 1줄(연동처 · 경로 틀 · 상태 · 결과) — 이름 · 이메일 · 키 · IP · 고객 · 예약 id 없음(§3.4 · §7.4)
- 고객 조회와 예약은 같은 함수(`find`)로 고객을 정한다(§5)
- 예약은 지금 `ReservationService.create()` 를 다시 쓴다 — 행위자 = `"ext:<연동처>"` 문자열(§3.5)
"""

import asyncio
import hmac
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from app.config import Settings
from app.domain.clock import KST, Clock, iso, kos_utc, parse, to_db
from app.domain.errors import BadGateway, BadRequest, Conflict, NotFound, ServiceUnavailable
from app.domain.models import ResvGroup, Zone
from app.domain.reservation_rules import (
    PREV_RESULT,
    ROOM_TASK_TITLE,
    age_on,
    consultation_passed,
    day_range,
    is_after,
    is_full,
    kst_min,
    open_spans,
    parse_day,
    schedule_start,
    state_of,
    to_min,
)
from app.kos.client import KosError
from app.kos.reservation_sync import resources_of, timetable_of, upsert_customer
from app.repository.repo import Repository
from app.schemas.ext import ExtCustomerReservations, ExtVisits
from app.schemas.reservations import (
    CreateReservationRequest,
    ExistingCustomerRef,
    NewCustomer,
    NewCustomerRef,
    PersonalIn,
)
from app.service import kos_errors
from app.service.questionnaire import WINDOW_SEC, RateLimiter
from app.service.reservations import (
    NO_KOS,
    PATH_BY_VISITOR,
    PATH_VISITOR,
    PATH_VISITORS,
    ReservationService,
    ResvContext,
    funnel_of,
    previous_visits,
    visitor_funnel_of,
)

log = logging.getLogger("procedure.ext")

CLIENTS = ("linky", "charty")  # 연동처(코드에 고정 · §7.1)
LIMIT_KEY = 60  # 키당 최근 60초(D-34)
LIMIT_BAD_IP = 10  # 연동처 없는 오류 응답 IP 당 최근 60초(§7.3 — 문진 웹 값 그대로)
PAGE = 1000  # 이름 검색 한 페이지(D-16)
PATH_TICKETS = "ticket/v1/queries/get-ticket-bundles"  # 내부(0.4.0 · DEC-012 D-08 ②) — 공개 → 내부
TICKET_SORT = {"by": "ticket.createdDateTimeUtc", "order": 2}  # KOS 웹 요청 모양 그대로
PATH_PREPAID = "purchase/open/prepaid-card/v1/queries/get-prepaid-card-summaries"  # 공개(§4.4)
LIVE_TICKETS = ("AVAILABLE", "IN_USE")  # 이 상태가 1장 이상인 묶음만 낸다(§4.3 거르기)
NOT_FOUND = "일치하는 고객이 없어요"
RESV_NOT_FOUND = "없는 예약이에요"
PATH_EVENT_LOGS = "schedule/v1/queries/get-schedule-event-logs"  # 내부 읽기(DEC-012 D-16 · D-42)
FLOW_STEP_CHANGED = "FlowStepChanged"  # eventType 의 마지막 `.` 뒤 조각(실물 = protos.schedule.event.FlowStepChanged)
CONSULT_WAITING = "CONSULTATION_WAITING"
HISTORY_CAP = 10  # 요청 1번당 이력 호출 상한 = 동시 한 바퀴(DEC-012 D-38 ③ · SPEC-008 §6.11 4)
RETRY_AFTER = timedelta(minutes=5)  # 실패 재시도 간격(D-38 ② ⓓ)
RETRY_MAX = 3  # 일정마다 실패 재시도 상한
CLINIC_ID = 1  # CC 서버 하나 = KOS 병원 하나(DEC-012 D-20 · D-24)
CLINIC_NOT_FOUND = "없는 병원이에요"
PATH_HOSPITAL = "v1/hospital/queries/get-hospital"
PATH_OP_TIME = "schedule/default-operation-time/v1/queries/get-default-operation-timetable"
PATH_DAYS_OFF = "schedule/default-operation-time/v1/queries/get-default-days-off"
PATH_ACCOUNTS_INTERNAL = "account/v2/queries/get-accounts"
DAYS_OFF_AHEAD = 90  # 휴무 기간 = 오늘(KST) 0시 ~ 오늘 + 90일 끝(DEC-012 D-27)
PATH_ORDER_MEMO = "schedule/v1/commands/change-order-memo"  # 내부 쓰기(DEC-012 D-12)
PATH_CONSULT_MEMO = "schedule/open/v1/commands/update-schedule-consultation-info"  # 공개 쓰기(DEC-012 D-13)
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


class _Shape(Exception):
    """KOS 응답 원소 모양 오류(원문 없이 종류만)."""


def ext_actor(client: str, staff_id: str | None) -> str:
    """행위자 문자열 — `ext:<연동처>[:<직원 id>]`(SPEC-008 §3.5 · §6.10 · DEC-012 D-19 · D-37 ⑤)."""
    return f"ext:{client}:{staff_id}" if staff_id else f"ext:{client}"


def _money_or_none(x: Any) -> dict[str, Any] | None:
    if x is None:
        return None
    if not isinstance(x, dict) or not isinstance(x.get("value"), (int, float)) or isinstance(x.get("value"), bool):
        raise _Shape("money")
    return {"value": int(x["value"]), "currency": x.get("currency") or ""}


def _balance(x: Any) -> dict[str, Any]:
    if x is None:
        return {"remaining": None, "total": None}
    if not isinstance(x, dict):
        raise _Shape("balance")
    return {"remaining": _money_or_none(x.get("balance")), "total": _money_or_none(x.get("total"))}


def prepaid_card(c: Any) -> dict[str, Any]:
    """공개 선불카드 요약 원소 → 응답 한 줄(§4.4) — id · ownerId · description 은 내지 않는다."""
    if not isinstance(c, dict) or not isinstance(c.get("title", ""), str):
        raise _Shape("card")
    exp = c.get("expirationDateTimeUtc")
    return {"title": c.get("title") or "", "issuedDate": _kst_date(c.get("createdDateTimeUtc")),
            "expiresAt": iso(parse(exp)) if isinstance(exp, str) else None,
            "balance": _balance(c.get("remainingBalance")), "point": _balance(c.get("remainingPoint"))}


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

    # ------------------------------------------------------------------ 열람 기록(§3.5 · §6.10)
    def view(self, client: str, staff_id: str | None, path: str, customer_id: int | None,
             reservation_id: int | None = None) -> None:
        """200 응답 뒤 `event_log` `ext_view` 1줄 — 직원 id 는 신고값 그대로(검증 안 함 · DEC-012 D-18)."""
        with self.repo.tx() as tx:
            tx.add_event(self.clock.now(), ext_actor(client, staff_id), "ext_view", None,
                         {"client": client, "staffId": staff_id, "path": path, "customerId": customer_id,
                          "reservationId": reservation_id})

    # ------------------------------------------------------------------ 고객 조회(§6.4)
    async def lookup(self, name: str | None, email: str | None, customer_id: int | None = None) -> dict[str, Any]:
        """두 갈래 — 이름 + 이메일(§5) · `customerId`(사본 → 내부 get-visitor). 그 뒤 시술권 + 선불카드(동시)."""
        if customer_id is not None:
            cid, v = await self._by_customer_id(customer_id)
        else:
            kind, v = await self.find(name or "", email or "")
            if kind == "none":
                raise NotFound(NOT_FOUND, "customer_not_found")
            if kind == "many" or v is None:
                raise Conflict("customer_ambiguous", AMBIGUOUS)
            cid = self._keep(v)
        client = self.resv.client()
        vid = str(v["id"])
        got = await asyncio.gather(client.internal(PATH_TICKETS, {"visitorId": vid, "sort": dict(TICKET_SORT)}),
                                   client.open(PATH_PREPAID, {"visitorId": vid, "available": True}),
                                   return_exceptions=True)
        tickets_resp, cards_resp = got
        if isinstance(tickets_resp, BaseException):  # 시술권 실패 = 502 그대로(D-14 · DEC-012 D-36)
            log.warning("KOS 시술권 조회 실패: %s", kos_errors.describe(tickets_resp))
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        data = tickets_resp.get("data", [])
        if not isinstance(data, list):
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        # 거르기 먼저(e2e 1) — 산 묶음만 모양 검사 · 칸 만들기. 걸러진(다 쓴 · 다 취소된) 묶음의 모양은 보지 않는다
        tickets = [self._ticket(b) for b in data if isinstance(b, dict) and self._live_bundle(b)]
        partial: list[str] = []
        cards: list[dict[str, Any]] | None
        try:
            if isinstance(cards_resp, BaseException):
                raise cards_resp
            cdata = cards_resp.get("data", [])
            if not isinstance(cdata, list):
                raise _Shape("data")
            cards = [prepaid_card(x) for x in cdata]
        except Exception as e:  # 선불카드만 실패 = 200 + null + partialErrors(DEC-012 D-36)
            log.warning("KOS 선불카드 조회 실패: %s", kos_errors.describe(e))
            cards, partial = None, ["prepaidCards"]
        return {"customer": {"customerId": cid, "name": v.get("name") or "", "isNew": bool(v.get("isNew")),
                             "lastVisitDate": _kst_date(v.get("lastVisitedDateTimeUtc"))},
                "tickets": tickets, "prepaidCards": cards, "partialErrors": partial}

    async def _by_customer_id(self, customer_id: int) -> tuple[int, dict[str, Any]]:
        """사본 `customer.id` → `kos_id` → 내부 get-visitor 1번 → 사본 덮어쓰기(§6.4 · DEC-012 D-02 · D-32)."""
        with self.repo.tx() as tx:
            cust = tx.customer(customer_id)
        if cust is None:  # 이름 갈래 404 와 같은 본문 · KOS 0
            raise NotFound(NOT_FOUND, "customer_not_found")
        try:
            resp = await self.resv.client().internal(PATH_VISITOR, {"id": cust.kos_id})
        except KosError as e:
            if e.status == 404 or (e.status == 400 and e.has("id", "NotFound")):  # KOS 에 그 고객 없음
                raise NotFound(NOT_FOUND, "customer_not_found") from None
            log.warning("KOS 외부 고객 읽기 실패: %s", kos_errors.describe(e))
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE) from None
        except Exception as e:
            log.warning("KOS 외부 고객 읽기 실패: %s", kos_errors.describe(e))
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE) from None
        data = resp.get("data")
        if not isinstance(data, dict):
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        v = {**data, "id": cust.kos_id}
        return self._keep(v) or cust.id, v

    @staticmethod
    def _bundle_tickets(b: dict[str, Any]) -> list[dict[str, Any]]:
        return [t for s in b.get("ticketSets") or [] if isinstance(s, dict)
                for t in s.get("tickets") or [] if isinstance(t, dict)]

    @classmethod
    def _live_bundle(cls, b: dict[str, Any]) -> bool:
        """`AVAILABLE` 또는 `IN_USE` 가 1장 이상인 묶음만 낸다(§4.3 거르기)."""
        return any(t.get("status") in LIVE_TICKETS for t in cls._bundle_tickets(b))

    @classmethod
    def _ticket(cls, b: dict[str, Any]) -> dict[str, Any]:
        conf = b.get("optionConfiguration") if isinstance(b.get("optionConfiguration"), dict) else {}
        tickets = cls._bundle_tickets(b)
        made = [at for at in (parse(t.get("createdDateTimeUtc")) if isinstance(t.get("createdDateTimeUtc"), str) else None
                              for t in tickets) if at]
        price = b.get("price")
        if not isinstance(price, dict):  # KOS 필수 칸 — 없거나 객체가 아니면 응답 모양 오류
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        value = price.get("value", 0)  # 내부 원천(protobuf JSON)은 0 을 빼고 보낸다 → `value` 없음 = 0(e2e 1)
        if not isinstance(value, (int, float)) or isinstance(value, bool):  # 다른 꼴(문자열 · null 등) = 모양 오류
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        return {"optionId": str(conf.get("optionId") or ""), "optionTitle": conf.get("optionTitle") or "",
                "remainingCount": sum(1 for t in tickets if t.get("status") == "AVAILABLE"),
                "inUseCount": sum(1 for t in tickets if t.get("status") == "IN_USE"), "totalCount": len(tickets),
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

    # ------------------------------------------------------------------ 0.4.0 예약 상세(§6.12)
    def _reservation_or_404(self, reservation_id: int):
        with self.repo.tx() as tx:
            r = tx.reservation(reservation_id)
        if r is None:  # 없는 경로의 not_found 와 가른다 · KOS 0
            raise NotFound(RESV_NOT_FOUND, "reservation_not_found")
        return r

    @staticmethod
    def _staff(person: Any, staff_by_kos: dict) -> dict[str, Any] | None:
        return ReservationService._staff_ref(person if isinstance(person, dict) else None, staff_by_kos)

    @staticmethod
    def _requested(raw_resv: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for x in raw_resv.get("requestedProcedures") or []:
            if not isinstance(x, dict):
                continue
            o = x.get("optionConfiguration") if isinstance(x.get("optionConfiguration"), dict) else None
            t = x.get("ticketConfiguration") if isinstance(x.get("ticketConfiguration"), dict) else None
            is_opt, is_tk = x.get("type") == "OPTION", x.get("type") == "TICKET"
            out.append({"type": str(x.get("type") or ""),
                        "optionId": str(o.get("optionId")) if is_opt and o and o.get("optionId") else None,
                        "optionTitle": (o.get("optionTitle") or None) if is_opt and o else None,
                        "productTitle": (o.get("productTitle") or None) if is_opt and o else None,
                        "ticketId": str(t.get("ticketId")) if is_tk and t and t.get("ticketId") else None,
                        "ticketTitle": (t.get("ticketTitle") or None) if is_tk and t else None})
        return out

    def _visit_counselors(self, sch: dict[str, Any], staff_by_kos: dict) -> list[dict[str, Any]]:
        """그 방문 상담자 — `consultations[].counselors[]`(나온 차례 · 같은 KOS id 한 번) · 비면 `consultation.counselor`."""
        seen, out = set(), []
        for cons in sch.get("consultations") or []:
            for p in (cons.get("counselors") or []) if isinstance(cons, dict) else []:
                ref = self._staff(p, staff_by_kos)
                if ref is not None and p["id"] not in seen:
                    seen.add(p["id"])
                    out.append(ref)
        if not out:
            one = self._staff((sch.get("consultation") or {}).get("counselor")
                              if isinstance(sch.get("consultation"), dict) else None, staff_by_kos)
            out = [one] if one else []
        return out

    async def detail(self, reservation_id: int) -> dict[str, Any]:
        r = self._reservation_or_404(reservation_id)
        if self.resv.runtime is None:
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        raw: dict[str, Any] = {}  # 직원 상세와 같은 다시 읽기(캐시 없음 · 성공하면 사본 덮어씀)
        await self.resv.refresh_schedule(r.kos_id, r.day, gone=True, sink=raw)
        partial: list[str] = [] if raw else ["schedule"]
        r = self._reservation_or_404(reservation_id)
        with self.repo.tx() as tx:
            cust = tx.customer(r.customer_id) if r.customer_id else None
        main, sub = state_of(r.status, r.flow_step)
        reads = await self.resv._detail_reads(r, cust, main, amount=False)  # 수납 금액 0(정산 칸 없음)
        visitor, visitor_err = reads["visitor"]
        day = date.fromisoformat(r.day) if r.day else self.clock.now().astimezone(KST).date()
        with self.repo.tx() as tx:
            ctx = ResvContext(tx)
            cust = tx.customer(r.customer_id) if r.customer_id else None
            staff_by_kos = {x.kos_id: x for x in tx.staff()}
            funnel_codes = tx.funnel_codes()
            if cust is None:
                health = {"state": "error", "submittedAt": None, "needCount": 0, "items": []}
            else:
                health = self.resv._health(tx, r, cust, reads)
        if cust is None or visitor_err:
            partial.append("visitor")
            visitor = None
        if health["state"] == "error":
            partial.append("questionnaire")
        prev: list[dict[str, Any]] | None = None
        if cust is None or reads["previous_err"]:
            partial.append("previousVisits")
        else:
            rows = []
            for sch in reads["previous"]:
                one = previous_visits([sch], day, ctx)  # 직원 함수 그대로(같은 날 뺌) + 상담자
                if one:
                    rows.append((schedule_start(sch), {**one[0], "counselors": self._visit_counselors(sch, staff_by_kos)}))
            rows.sort(key=lambda x: x[0], reverse=True)
            prev = [x[1] for x in rows]
        rraw = raw.get("reservation") if isinstance(raw.get("reservation"), dict) else {}
        cons = raw.get("consultation") if isinstance(raw.get("consultation"), dict) else None
        vf = visitor_funnel_of(visitor, funnel_codes)
        order_memo = raw.get("orderMemo") if isinstance(raw.get("orderMemo"), str) else None
        cons_memo = cons.get("consultationMemo") if cons and isinstance(cons.get("consultationMemo"), str) else None
        return {
            "reservationId": r.id, "day": day.isoformat(),
            "start": iso(parse(r.resources[0]["startAt"])) if r.resources else None,
            "end": iso(max(parse(x["endAt"]) for x in r.resources)) if r.resources else None,
            "state": {"main": main, "sub": sub},
            "customer": {
                "customerId": cust.id if cust else None, "name": cust.name if cust else "",
                "phoneticName": cust.phonetic_name if cust else None, "gender": cust.gender if cust else None,
                "nationality": cust.nationality if cust else None, "isNew": bool(cust and cust.is_new),
                "chartNumber": cust.chart_number if cust else None,
                "age": age_on((visitor or {}).get("dateOfBirth"), day) if visitor else None,
                "language": (visitor or {}).get("language") or None,
                "funnel": {"name": vf["name"], "detail": vf["detail"]} if vf else None},
            "reservation": {
                "memo": r.memo, "desiredDischargeAt": iso(r.desired_discharge_at), "funnel": funnel_of(r.funnel),
                "counselor": self._staff(r.counselor, staff_by_kos),
                "orderMemo": order_memo if raw else None, "consultationMemo": cons_memo if raw else None,
                "requestedDoctor": self._staff(rraw.get("doctor"), staff_by_kos) if raw else None,
                "requestedProcedures": self._requested(rraw) if raw else None},
            "health": health, "previousVisits": prev, "partialErrors": partial,
        }

    # ------------------------------------------------------------------ 0.4.0 쓰기 셋(§6.13 ~ §6.15) — KOS 먼저(D-04)
    async def language(self, client: str, staff_id: str | None, customer_id: int, language: str) -> None:
        """직원 `personal()` 을 그대로 부른다(다시 읽기 → 같으면 0 · 묶음 전체 + language 쓰기 · visitor_personal)."""
        try:
            await self.resv.personal(ext_actor(client, staff_id), customer_id, PersonalIn(language=language))
        except NotFound as e:
            if e.code == "not_found":  # 직원 「없는 고객이에요」 → lookup 404 와 같은 본문
                raise NotFound(NOT_FOUND, "customer_not_found") from None
            raise

    async def _memo(self, client: str, staff_id: str | None, reservation_id: int, op: str, call_of, type_: str,
                    text: str, mirror: bool) -> None:
        r = self._reservation_or_404(reservation_id)  # KOS 0
        actor = ext_actor(client, staff_id)
        await self.resv.kos_write(actor, op, call_of(self.resv.client(), r.kos_id), reservation_id=r.id)
        with self.repo.tx() as tx:  # KOS 성공 뒤에만
            self.resv._event(tx, actor, type_, {"reservationId": r.id, "length": len(text)})  # 글 원문은 싣지 않는다
            if mirror:
                tx.set_visit_order_memo(r.kos_id, text)  # visit 행이 있을 때만(upsert 아님)
        self.resv.after_write(r.day)

    async def order_memo(self, client: str, staff_id: str | None, reservation_id: int, memo: str) -> None:
        await self._memo(client, staff_id, reservation_id, "change-order-memo",
                         lambda k, sid: k.internal(PATH_ORDER_MEMO, {"scheduleId": sid, "orderMemo": memo}),
                         "order_memo", memo, mirror=True)

    async def consultation_memo(self, client: str, staff_id: str | None, reservation_id: int, memo: str) -> None:
        await self._memo(client, staff_id, reservation_id, "update-schedule-consultation-info",
                         lambda k, sid: k.open(PATH_CONSULT_MEMO, {"scheduleId": sid, "consultationMemo": memo}),
                         "consultation_memo", memo, mirror=False)

    # ------------------------------------------------------------------ 0.4.0 접수 목록(§6.11)
    async def board(self) -> dict[str, Any]:
        now = self.clock.now()
        day = now.astimezone(KST).date()
        await self.resv.ensure_day(day)  # 직원 board 와 같은 10초 날짜 캐시 · 실패 = 낡은 사본 + lastError
        with self.repo.tx() as tx:
            resvs = tx.reservations(day.isoformat())
            customers = tx.customers_in(sorted({r.customer_id for r in resvs if r.customer_id}))  # 그날 줄의 고객만
            staff_by_kos = {x.kos_id: x for x in tx.staff()}
            events: dict[int, list[dict]] = {}  # 판정에 쓰는 두 type · 그날 예약 id 로 거른 쿼리(코드 검수 r1 W5)
            for e in tx.events_for_reservations(("reception", "consultation_add"), [r.id for r in resvs]):
                events.setdefault(e["payload"].get("reservationId"), []).append(e)
            ok_at, error = tx.sync_state(f"resv:{day.isoformat()}")
        if self.resv.runtime is None:
            error = error or NO_KOS
        lines = []
        for r in resvs:
            main, sub = state_of(r.status, r.flow_step)
            start = parse(r.resources[0]["startAt"]) if r.resources else None
            lines.append((start, r, main, sub))
        lines.sort(key=lambda x: (x[0] is None, x[0] or now, x[1].id))  # 첫 묶음 시작 → id
        targets = [(r.kos_id, r.flow_step, main) for _, r, main, _ in lines if is_after(main)]
        deferred = await self._history(targets, now) if self.resv.runtime is not None else set()
        with self.repo.tx() as tx:
            waits = tx.consult_waits([k for k, _, _ in targets])
        partial = any(not (w := waits.get(k) or {}).get("first_at") and (w.get("last_failed") or k in deferred)
                      for k, _, _ in targets)
        rows = []
        for start, r, main, sub in lines:
            cust = customers.get(r.customer_id) if r.customer_id else None
            after = is_after(main)
            first = (waits.get(r.kos_id) or {}).get("first_at") if after else None
            rows.append({
                "reservationId": r.id, "start": iso(start),
                "end": iso(max(parse(x["endAt"]) for x in r.resources)) if r.resources else None,
                "state": {"main": main, "sub": sub},
                "customer": {"customerId": cust.id if cust else None, "name": cust.name if cust else "",
                             "phoneticName": cust.phonetic_name if cust else None,
                             "gender": cust.gender if cust else None,
                             "nationality": cust.nationality if cust else None, "isNew": bool(cust and cust.is_new)},
                "receptionAt": iso(r.reception_at), "counselor": self._staff(r.counselor, staff_by_kos),
                "roomTitle": r.room_title or None,
                "consultation": consultation_passed(after, r.flow_step, events.get(r.id, [])),
                "firstConsultationWaitingAt": iso(parse(first)) if first else None})
        return {"date": day.isoformat(), "now": iso(now), "sync": {"lastOkAt": iso(ok_at), "lastError": error},
                "partialErrors": ["consultationHistory"] if partial else [], "reservations": rows}

    def _reserve_history(self, targets: list[tuple[str, str | None, str]], now: datetime) -> tuple[list, set[str]]:
        """시도 예약 — 고르기 + 적기를 `BEGIN IMMEDIATE` 한 트랜잭션으로(안에 await 없음 · KOS 호출 전 커밋).

        사건(§6.11 4): ⓐ 처음 봄 · ⓑ 대기를 새로 봄 · ⓒ 귀가 뒤 1번 · ⓓ 실패 재시도(5분 뒤 · ≤ 3). 「못 찾음」만으로는 안 부른다.
        → (부를 일정 [kos_id], 사건은 있었는데 상한으로 못 부른 일정 {kos_id}).
        """
        with self.repo.immediate() as tx:
            rows = tx.consult_waits([k for k, _, _ in targets])
            picks = []
            for idx, (kid, flow, main) in enumerate(targets):
                row = rows.get(kid)
                if row is not None and row["first_at"]:
                    continue  # 굳은 행 — 다시 부르지 않는다
                checked = None
                if row is None:
                    rank = 0
                else:
                    if flow != CONSULT_WAITING and row["wait_called"]:
                        tx.put_consult_wait(kid, {"wait_called": 0})  # 대기 아닌 단계를 봄 — 다음 대기는 새 사건
                        row["wait_called"] = 0
                    if not row["last_failed"] and flow == CONSULT_WAITING and not row["wait_called"]:
                        rank = 1
                    elif main == "home" and not row["final_tried"]:
                        rank = 2
                    elif row["last_failed"] and row["retries"] < RETRY_MAX \
                            and now - (parse(row["checked_at"]) or now) >= RETRY_AFTER:
                        rank, checked = 3, parse(row["checked_at"])
                    else:
                        continue
                picks.append((rank, checked or now, idx, kid, flow, main, row))
            picks.sort(key=lambda x: (x[0], x[1], x[2]))  # ⓐ → ⓑ → ⓒ → ⓓ(오래된 시도 먼저) → 줄 차례
            chosen, rest = picks[:HISTORY_CAP], picks[HISTORY_CAP:]
            for rank, _, _, kid, flow, main, row in chosen:
                f: dict[str, Any] = {"checked_at": to_db(now), "last_failed": 1}  # 결과 전 = 1
                if rank == 0:
                    f["wait_called"] = int(flow == CONSULT_WAITING)  # 처음 봄이 대기면 ⓑ 몫을 겸함
                    f["final_tried"] = int(main == "home")  # 처음 봄이 귀가면 ⓒ 몫을 겸함(코드 검수 r1 W1 · Q1)
                elif rank == 1:
                    f["wait_called"] = 1
                elif rank == 2:
                    f["final_tried"] = 1
                else:
                    f["retries"] = row["retries"] + 1
                tx.put_consult_wait(kid, f)
        return [x[3] for x in chosen], {x[3] for x in rest}

    async def _history(self, targets: list[tuple[str, str | None, str]], now: datetime) -> set[str]:
        chosen, deferred = self._reserve_history(targets, now)
        if not chosen:
            return deferred
        got = await asyncio.gather(*(self._first_wait(k) for k in chosen), return_exceptions=True)
        with self.repo.tx() as tx:  # 결과 적기 — 또 다른 짧은 트랜잭션
            for kid, res in zip(chosen, got, strict=True):
                if isinstance(res, BaseException):
                    log.warning("KOS 일정 이력 조회 실패: %s", kos_errors.describe(res))  # last_failed = 1 그대로
                elif res is None:
                    tx.put_consult_wait(kid, {"last_failed": 0})  # 못 찾음 — 굳히지 않는다
                else:
                    tx.put_consult_wait(kid, {"first_at": to_db(res), "source": "kos_event_log", "last_failed": 0})
        return deferred

    async def _first_wait(self, kos_id: str) -> datetime | None:
        """이력에서 처음 상담 대기 시각 — 끝 조각 `FlowStepChanged` · `flowStep` 문자열 · 원소 시각 최솟값(D-42)."""
        resp = await self.resv.client().internal(PATH_EVENT_LOGS, {"scheduleId": kos_id})
        data = resp.get("data")
        if not isinstance(data, list):
            raise _Shape("data")
        found = []
        for e in data:
            if not isinstance(e, dict):
                raise _Shape("item")
            et = e.get("eventType")
            if not isinstance(et, str) or et.rsplit(".", 1)[-1] != FLOW_STEP_CHANGED:
                continue
            try:
                p = json.loads(e.get("payload") or "")
            except (TypeError, ValueError):
                raise _Shape("payload") from None
            if not isinstance(p, dict):
                raise _Shape("payload")
            if p.get("flowStep") == CONSULT_WAITING:
                at = parse(e.get("raisedDateTimeUtc")) if isinstance(e.get("raisedDateTimeUtc"), str) else None
                if at is None:
                    raise _Shape("time")
                found.append(at)
        return min(found) if found else None

    # ------------------------------------------------------------------ 0.4.0 병원 정보(§6.16) · 직원 목록(§6.17)
    @staticmethod
    def _text(v: Any) -> str | None:
        """빈 문자열 → null(DEC-012 D-26). 문자열이 아니면 모양 오류."""
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            raise _Shape("text")
        return v

    @staticmethod
    def _day_off(x: Any) -> dict[str, str]:
        """KOS `{id, startDateTime, endDateTime}` → `{startDate, endDate}` KST 날짜(끝은 배타 → 직전 시각의 날짜 · D-43)."""
        if not isinstance(x, dict):
            raise _Shape("day_off")
        a = parse(x.get("startDateTime")) if isinstance(x.get("startDateTime"), str) else None
        b = parse(x.get("endDateTime")) if isinstance(x.get("endDateTime"), str) else None
        if a is None or b is None:
            raise _Shape("day_off")
        last = max(a, b - timedelta(microseconds=1))
        return {"startDate": a.astimezone(KST).date().isoformat(), "endDate": last.astimezone(KST).date().isoformat()}

    async def clinic(self) -> dict[str, Any]:
        if self.resv.runtime is None:
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        client = self.resv.client()
        today = self.clock.now().astimezone(KST).date()
        start, end = day_range(today)[0], day_range(today + timedelta(days=DAYS_OFF_AHEAD))[1]
        got = await asyncio.gather(client.internal(PATH_HOSPITAL, {}), client.internal(PATH_OP_TIME, {}),
                                   client.internal(PATH_DAYS_OFF, {"startDateTime": kos_utc(start),
                                                                   "endDateTime": kos_utc(end)}),
                                   return_exceptions=True)
        try:
            for g in got:
                if isinstance(g, BaseException):
                    raise g
            hosp, table, off = (g.get("data") for g in got)  # type: ignore[union-attr]
            if not isinstance(hosp, dict) or not isinstance(table, dict) or not isinstance(off, list):
                raise _Shape("data")
            addr = hosp.get("addressContract")
            if addr is not None and not isinstance(addr, dict):
                raise _Shape("address")
            parts = {"address": self._text((addr or {}).get("address")),
                     "detailed": self._text((addr or {}).get("detailedAddress")),
                     "zipCode": self._text((addr or {}).get("zipCode"))}
            return {"clinicId": CLINIC_ID, "name": self._text(hosp.get("hospitalName")),
                    "phone": self._text(hosp.get("hospitalPhoneNumber")),
                    "address": parts if any(parts.values()) else None,
                    "operatingHours": timetable_of({"operationTimetable": table}),
                    "daysOff": [self._day_off(x) for x in off]}
        except Exception as e:  # 하나라도 실패 = 502(부분 응답 없음 · D-28)
            log.warning("KOS 병원 정보 조회 실패: %s", kos_errors.describe(e))
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE) from None

    async def staff(self, clinic_id: int) -> dict[str, Any]:
        if clinic_id != CLINIC_ID:
            raise NotFound(CLINIC_NOT_FOUND, "clinic_not_found")
        if self.resv.runtime is None:
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE)
        client = self.resv.client()
        try:
            data = (await client.internal(PATH_ACCOUNTS_INTERNAL, {})).get("data")
            if not isinstance(data, list) or not all(isinstance(x, dict) and x.get("id") for x in data):
                raise _Shape("data")
        except Exception as e:
            log.warning("KOS 직원 목록 조회 실패: %s", kos_errors.describe(e))
            raise BadGateway("kos_unavailable", kos_errors.UNAVAILABLE) from None
        skip = {client.system_kos_id(), *self.s.exclude_account_ids} - {None}
        with self.repo.tx() as tx:
            copy = {x.kos_id: x for x in tx.staff()}
        out = []
        for a in data:
            kid = str(a["id"])
            if kid in skip:
                continue
            st = copy.get(kid)
            out.append({"staffId": st.id if st else None, "name": str(a.get("name") or ""),
                        "roleName": a.get("roleName") or None, "roleTags": list(st.role_tags) if st else [],
                        "active": bool(a.get("activate")), "email": a.get("email") or None,
                        "realName": a.get("realName") or None, "kosAccountId": kid})
        return {"clinicId": clinic_id, "staff": out}
