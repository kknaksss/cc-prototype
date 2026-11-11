"""KOS 시술 · 상품 메뉴 → 메뉴 표 9(SPEC-008 §3 · §4.1) — 공개 API 만 · 마스터 루프(1시간 · 서버 시작 1회).

- 작업 ① ~ ⑧ 은 서로 독립이다. 단 ③ `getProductOptions` 는 ② `getProducts` 가 성공했을 때만 부른다
- 실패한 작업은 그 표를 건드리지 않는다(이전 값 · present 그대로). 성공한 작업만 「이번 결과에 없는 행 = present 0」
- `raw` = KOS 가 준 객체를 고치지 않고 `json.dumps`(상품은 `options` · 옵션은 `compositions` 만 뺀다)
- 실패는 `sync_state("menu").last_error` 에 `"<작업>: <오류>"` · 로그는 예외 종류 · HTTP 상태만(본문 · 키 없음)
- 경로 = KOS `openapi.yaml` 1.0.1 operationId 의 경로(SPEC-008 §4.1 「스펙의 경로가 맞다」)
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from app.domain.clock import Clock
from app.kos.client import KosClient
from app.kos.reservation_sync import _data_list, _err
from app.repository.repo import Repository, Tx

log = logging.getLogger("procedure.kos")

PATH_CATEGORIES = "procedure-menu/open/categories/queries/get-categories"
PATH_PRODUCTS = "procedure-menu/open/products/queries/get-products"
PATH_PRODUCT_OPTIONS = "procedure-menu/open/v1/product-options/queries/get-product-options"
PATH_PROCEDURES = "procedure-menu/open/v1/procedures/queries/get-procedures"
PATH_MEDICAL_SERVICES = "procedure-menu/open/v1/medical-services/queries/get-medical-services"
PATH_MACHINES = "procedure-menu/open/v1/machines/queries/get-machines"
PATH_MEDICINES = "procedure-menu/open/v1/medicines/queries/get-medicines"
PATH_TARGET_COUNTRIES = "procedure-menu/open/target-countries/queries/get-target-countries"

# ③ 한 번에 넣는 옵션 수 — KOS 스펙에는 하한(minItems 1)만 있고 상한이 없다. 데모 실측(SINGLE 307개)은 WORK-012 BE1 리포트
OPTION_BATCH = 100


def _raw(obj: dict[str, Any], drop: str | None = None) -> str:
    return json.dumps({k: v for k, v in obj.items() if k != drop}, ensure_ascii=False)


def _id(obj: Any) -> str | None:
    v = obj.get("id") if isinstance(obj, dict) else None
    return str(v) if v not in (None, "") else None


def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _amount(obj: dict[str, Any]) -> tuple[int | None, str | None]:
    """`price.amount{value, currency}` → (정수 원, 통화). 없으면 (None, None)."""
    price = obj.get("price") if isinstance(obj.get("price"), dict) else {}
    amount = price.get("amount") if isinstance(price.get("amount"), dict) else {}
    cur = amount.get("currency")
    return _int(amount.get("value")), cur if isinstance(cur, str) and cur else None


def _unit(obj: Any) -> tuple[str | None, float | None]:
    if not isinstance(obj, dict):
        return None, None
    t = obj.get("type")
    return (t if isinstance(t, str) and t else None), _num(obj.get("value"))


class MenuSync:
    def __init__(self, repo: Repository, client: KosClient, clock: Clock):
        self.repo = repo
        self.client = client
        self.clock = clock
        self._lock = asyncio.Lock()

    async def run(self) -> bool:
        """한 바퀴(① ~ ⑧). 다 성공하면 True · last_ok_at."""
        async with self._lock:
            now = self.clock.now()
            errors: list[str] = []

            async def step(name: str, fn: Callable[[datetime], Awaitable[Any]]) -> Any:
                try:
                    return await fn(now)
                except Exception as e:  # 하나가 실패해도 나머지 작업은 한다
                    errors.append(f"{name}: {_err(e)}")
                    log.warning("KOS 메뉴(%s) 조회 실패: %s", name, _err(e))
                    return None

            await step("getCategories", self._categories)
            singles = await step("getProducts", self._products)
            if singles is not None:  # ③ 은 ② 가 성공했을 때만
                await step("getProductOptions", lambda _: self._product_options(singles))
            await step("getProcedures", lambda at: self._named("menu_procedure", PATH_PROCEDURES, "시술", at))
            await step("getMedicalServices", self._medical_services)
            await step("getMachines", lambda at: self._named("menu_machine", PATH_MACHINES, "기기", at))
            await step("getMedicines", lambda at: self._named("menu_medicine", PATH_MEDICINES, "약물", at))
            await step("getTargetCountries", self._target_countries)
            with self.repo.tx() as tx:
                tx.set_sync("menu", None if errors else now, "; ".join(errors) or None)
            return not errors

    # ------------------------------------------------------------------ 작업
    async def _categories(self, now: datetime) -> None:
        rows = _data_list(await self.client.open(PATH_CATEGORIES, {}), "카테고리")
        with self.repo.tx() as tx:
            keep = set()
            for c in rows:
                kid = _id(c)
                if kid is None:
                    continue
                keep.add(kid)
                tx.upsert("menu_category", kid, {
                    "name": c.get("name") or "", "order": _int(c.get("order")) or 0, "opened": c.get("opened") is not False,
                    "deleted": bool(c.get("deleted")), "raw": _raw(c), "present": True, "synced_at": now})
            tx.mark_absent_kos("menu_category", keep)

    async def _products(self, now: datetime) -> list[str]:
        """상품 · 옵션 · 구성 한 트랜잭션 → 이번 결과의 SINGLE 옵션 kos_id(③ 용)."""
        rows = _data_list(await self.client.open(PATH_PRODUCTS, {}), "상품")
        singles: list[str] = []
        with self.repo.tx() as tx:
            keep_p, keep_o, keep_c = set(), set(), set()
            for seq, p in enumerate(rows):
                pid = _id(p)
                if pid is None:
                    continue
                keep_p.add(pid)
                cats = [cid for cid in (_id(c) for c in p.get("categories") or []) if cid]
                tx.upsert("menu_product", pid, {
                    "title": p.get("title") or "", "is_event": bool(p.get("isEvent")), "closed": bool(p.get("closed")),
                    "deleted": bool(p.get("deleted")), "seq": seq, "category_kos_ids": cats, "raw": _raw(p, "options"),
                    "present": True, "synced_at": now})
                options = [o for o in p.get("options") or [] if isinstance(o, dict)]
                for oseq, o in enumerate(options):
                    oid = _id(o)
                    if oid is None:
                        continue
                    keep_o.add(oid)
                    self._option(tx, pid, oseq, o, now)
                    if o.get("type") == "SINGLE":
                        singles.append(oid)
                    if o.get("type") != "GROUP":
                        continue
                    comps = [c for c in o.get("compositions") or [] if isinstance(c, dict)]
                    for cseq, c in enumerate(comps):
                        keep_c.add((oid, cseq))
                        self._composition(tx, oid, cseq, c, now)
            tx.mark_absent_kos("menu_product", keep_p)
            tx.mark_absent_kos("menu_option", keep_o)
            tx.mark_absent_compositions(keep_c)
        return singles

    @staticmethod
    def _option(tx: Tx, product_kos_id: str, seq: int, o: dict[str, Any], now: datetime) -> None:
        single = o.get("type") == "SINGLE"
        price, cur = _amount(o)
        fields: dict[str, Any] = {
            "product_kos_id": product_kos_id, "seq": seq, "type": o.get("type"), "title": o.get("title") or "",
            "deleted": bool(o.get("deleted")), "list_price": price, "currency": cur,
            "count": _int(o.get("count")) if single else None,
            "procedure_kos_id": _id(o.get("procedure")) if single else None,
            "raw": _raw(o, "compositions"), "present": True, "synced_at": now}
        if not single:  # SINGLE 의 진료항목은 ③ 이 채운다(③ 에서 빠지면 이전 값) — 그 밖 type 은 null
            fields["medical_service_kos_id"] = None
        tx.upsert("menu_option", str(o["id"]), fields)

    @staticmethod
    def _composition(tx: Tx, option_kos_id: str, seq: int, c: dict[str, Any], now: datetime) -> None:
        price, cur = _amount(c)
        unit_type, unit_value = _unit(c.get("unit"))
        tx.upsert_composition(option_kos_id, seq, {
            "title": c.get("title") or "", "count": _int(c.get("count")), "unit_type": unit_type, "unit_value": unit_value,
            "list_price": price, "currency": cur, "procedure_kos_id": _id(c.get("procedure")),
            "medical_service_kos_id": _id(c.get("medicalService")), "raw": _raw(c), "present": True, "synced_at": now})

    async def _product_options(self, singles: list[str]) -> None:
        """SINGLE 옵션 → 진료항목 id. N 개씩 나눠 다 받은 뒤 한 번에 반영 — 하나라도 실패하면 바꾸지 않는다."""
        found: dict[str, str] = {}
        for i in range(0, len(singles), OPTION_BATCH):
            body = {"optionIds": singles[i:i + OPTION_BATCH], "includePromotions": False}
            for o in _data_list(await self.client.open(PATH_PRODUCT_OPTIONS, body), "상품 옵션"):
                oid, ms = _id(o), _id(o.get("medicalService"))
                if oid and ms:
                    found[oid] = ms
        with self.repo.tx() as tx:
            for oid, ms in found.items():  # 응답에서 빠진 옵션은 이전 값 그대로
                tx.set_option_medical_service(oid, ms)

    async def _named(self, table: str, path: str, what: str, now: datetime) -> None:
        """시술 · 기기 · 약물 — `{id, name}` 평평한 목록."""
        rows = _data_list(await self.client.open(path, {}), what)
        with self.repo.tx() as tx:
            keep = set()
            for x in rows:
                kid = _id(x)
                if kid is None:
                    continue
                keep.add(kid)
                tx.upsert(table, kid, {"name": x.get("name") or "", "raw": _raw(x), "present": True, "synced_at": now})
            tx.mark_absent_kos(table, keep)

    async def _medical_services(self, now: datetime) -> None:
        rows = _data_list(await self.client.open(PATH_MEDICAL_SERVICES, {}), "진료항목")
        with self.repo.tx() as tx:
            keep = set()
            for m in rows:
                kid = _id(m)
                if kid is None:
                    continue
                keep.add(kid)
                conf = m.get("configuration") if isinstance(m.get("configuration"), dict) else {}
                unit_type, unit_value = _unit(conf.get("unit"))
                tx.upsert("menu_medical_service", kid, {
                    "title": m.get("title") or "", "status": m.get("status"), "code": conf.get("code"),
                    "procedure_kos_id": _id(conf.get("procedure")), "unit_type": unit_type, "unit_value": unit_value,
                    "raw": _raw(m), "present": True, "synced_at": now})
            tx.mark_absent_kos("menu_medical_service", keep)

    async def _target_countries(self, now: datetime) -> None:
        rows = _data_list(await self.client.open(PATH_TARGET_COUNTRIES, {}), "타겟 국가")
        with self.repo.tx() as tx:
            keep = set()
            for t in rows:
                raw = _raw(t)
                keep.add(raw)
                tx.upsert_target_country(raw, {"code": t.get("code"), "order": _int(t.get("order")), "present": True,
                                               "synced_at": now})
            tx.mark_absent_target_countries(keep)
