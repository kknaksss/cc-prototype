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
from typing import Any

from app.config import Settings
from app.domain.clock import KST, Clock, iso, parse
from app.domain.errors import BadGateway, Conflict, NotFound, ServiceUnavailable
from app.kos.reservation_sync import upsert_customer
from app.repository.repo import Repository
from app.schemas.reservations import CreateReservationRequest, ExistingCustomerRef, NewCustomer, NewCustomerRef
from app.service import kos_errors
from app.service.questionnaire import WINDOW_SEC, RateLimiter
from app.service.reservations import PATH_VISITORS, ReservationService, ResvContext

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

    # ------------------------------------------------------------------ 예약(§6.5)
    async def reserve(self, client: str, name: str, email: str, start: str, memo: str | None) -> dict[str, int]:
        gid = self.s.kos_ext_reservation_group_id.strip()
        with self.repo.tx() as tx:
            ctx = ResvContext(tx)
            g = ctx.group_by_kos.get(gid) if gid else None
            enabled = ctx.enabled_zones(g) if g is not None else []
        if g is None or not enabled:  # 사본 기준 · KOS 부르기 전(D-33 · 코디 Q3)
            raise ServiceUnavailable("ext_not_configured", "외부 예약 설정이 비어 있어요")
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
