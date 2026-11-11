"""외부 연동 API 시험 환경(SPEC-008) — 가짜 KOS + 가짜 메뉴 · 키. id · 이름 · 키 · 이메일은 전부 지어낸 값."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.container import build_container
from app.domain.clock import Clock
from app.kos.client import KosClient
from app.kos.runtime import KosRuntime
from app.main import create_app
from tests.conftest import ADMIN
from tests.fake_kos import FakeKos, kos_settings

T0 = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)  # KST 수요일 11:00
LINKY = "test-linky-key-0000"  # 시험 전용 키(지어냄)
CHARTY = "test-charty-key-0000"
H_LINKY = {"X-Api-Key": LINKY}
H_CHARTY = {"X-Api-Key": CHARTY}


def run(coro):
    return asyncio.run(coro)


def money(v):
    return {"value": v, "currency": "KRW"}


def price(v):
    """getProducts 꼴 — 세부 금액은 UNKNOWN 이면 0 · 빈 통화(조사 1 §1.1)."""
    zero = {"value": 0, "currency": ""}
    return {"amount": money(v), "suppliedAmount": zero, "vatAmount": zero, "taxFreeAmount": zero,
            "taxation": "Taxation_UNKNOWN", "additional": []}


def proc(pid, name):
    return {"id": pid, "name": name, "createDate": "", "categoryIds": []}


def tr(**fields):
    return {k: {"translation": {"ko": v, "en": f"{v}-en"}} for k, v in fields.items()}


def single(oid, title, value, count=1, pid="proc-1", **kw):
    o = {"id": oid, "type": "SINGLE", "title": title, "description": f"{title} 설명", "deleted": False, "price": price(value),
         "count": count, "procedure": proc(pid, f"시술-{pid}"), "medicineAndMachines": [{"id": "mach-1", "name": "기기1"}],
         "compositions": [], "displayChannels": ["HOMEPAGE"], "badges": [], "frequentlyUsedOption": False,
         "promotionConfigurations": [], "translsMap": tr(title=title, description=f"{title} 설명")}
    o.update(kw)
    return o


def comp(title, value, count, unit, pid):
    return {"title": title, "count": count, "unit": unit, "price": price(value), "procedure": proc(pid, f"시술-{pid}"),
            "medicineAndMachines": [{"id": "med-1", "name": "약물1"}],
            "medicalService": {"id": "ms-2", "title": "진료2", "description": "", "caution": "", "deleted": False},
            "refSingleOptionId": ""}


def group_opt(oid, title, comps, **kw):
    o = {"id": oid, "type": "GROUP", "title": title, "description": f"{title} 설명", "deleted": False,
         "price": price(sum(c["price"]["amount"]["value"] for c in comps)), "medicineAndMachines": [], "compositions": comps,
         "displayChannels": ["HOMEPAGE"], "badges": [], "frequentlyUsedOption": False, "promotionConfigurations": [],
         "translsMap": tr(title=title)}
    o.update(kw)
    return o


def consult(oid, title):
    return {"id": oid, "type": "CONSULTATION", "title": title, "description": "", "deleted": False,
            "displayChannels": ["HOMEPAGE"], "badges": [], "translsMap": {}}


def product(pid, title, cats, options, **kw):
    p = {"id": pid, "title": title, "description": f"{title} 설명", "caution": "", "cautions": [],
         "categories": [{"id": c, "name": f"분류-{c}", "translsMap": {}} for c in cats], "options": options,
         "medicineAndMachines": [], "closed": False, "deleted": False, "isEvent": False, "order": 1, "badges": [],
         "translsMap": tr(title=title)}
    p.update(kw)
    return p


def cat(cid, name, order, **kw):
    c = {"id": cid, "name": name, "order": order, "opened": True, "deleted": False, "translsMap": tr(name=name)}
    c.update(kw)
    return c


def medical(mid, title, unit=None, pid="proc-1"):
    conf = {"code": f"00-X-{mid}", "procedure": {"id": pid, "name": f"시술-{pid}", "searchPhoneticName": "", "categoryIds": []},
            "machines": [], "medicines": [], "healthcareReimbursement": "NON_REIMBURSABLE", "taxation": "TAXABLE"}
    if unit:
        conf["unit"] = unit
    return {"id": mid, "title": title, "status": "PUBLISHED", "configuration": conf,
            "draftedDateTimeUtc": "2026-01-01T00:00:00.000Z", "updatedDateTimeUtc": "2026-01-01T00:00:00.000Z",
            "translsMap": tr(title=title)}


def sample_menu() -> dict:
    """카테고리 3(하나 숨김) · 상품 4(닫힘 · 숨긴 카테고리 하나씩) · SINGLE · GROUP · CONSULTATION · 지운 옵션."""
    g_comps = [comp("구성A", 40000, 1, {"type": "SHOT", "value": 100.0}, "proc-2"),
               comp("구성B", 20000, 5, {"type": "UnitType_UNKNOWN", "value": 0}, "proc-3")]
    return {
        "get-categories": [cat("cat-2", "두번째", 1), cat("cat-1", "첫째", 0), cat("cat-h", "숨김", 2, opened=False)],
        "get-products": [
            product("prod-1", "상품1", ["cat-1"], [
                single("opt-s1", "단일1", 10000, count=3), group_opt("opt-g1", "묶음1", g_comps), consult("opt-c1", "상담1"),
                single("opt-del", "지운 옵션", 5000, deleted=True)]),
            product("prod-2", "상품2", ["cat-2", "cat-1"], [single("opt-s2", "단일2", 30000, pid="proc-2")], isEvent=True),
            product("prod-x", "닫힌 상품", ["cat-1"], [single("opt-s3", "단일3", 1000)], closed=True),
            product("prod-h", "숨은 상품", ["cat-h"], [single("opt-s4", "단일4", 1000)]),
        ],
        "get-procedures": [proc("proc-1", "시술-proc-1"), proc("proc-2", "시술-proc-2"), proc("proc-3", "시술-proc-3")],
        "get-medical-services": [medical("ms-1", "진료1", {"type": "SHOT", "value": 300.0}), medical("ms-2", "진료2"),
                                 medical("ms-3", "진료3", pid="proc-2")],
        "get-machines": [{"id": "mach-1", "name": "기기1"}],
        "get-medicines": [{"id": "med-1", "name": "약물1"}],
        "get-target-countries": [{"code": "KR", "order": 0}, {"code": "KR", "order": 1}, {"code": "ETC", "order": 3}],
    }


SAMPLE_SERVICES = {"opt-s1": "ms-1", "opt-s2": "ms-3", "opt-s3": "ms-1", "opt-s4": "ms-1"}


def fill_menu(fake: FakeKos, menu: dict | None = None) -> None:
    fake.menu.update(deepcopy(menu or sample_menu()))
    services = {m["id"]: m for m in fake.menu["get-medical-services"]}
    fake.option_services = {oid: deepcopy(services[mid]) for oid, mid in SAMPLE_SERVICES.items()}


def make_ext_env(tmp_path, *, menu: bool = True, startup: bool = True, **kw):
    """컨테이너 + 가짜 KOS(+ 메뉴) + TestClient(lifespan 없음 — 조회 루프를 띄우지 않는다)."""
    fake = FakeKos()
    if menu:
        fill_menu(fake)
    kw.setdefault("proc_ext_key_linky", LINKY)
    kw.setdefault("proc_ext_key_charty", CHARTY)
    kw.setdefault("kos_ext_reservation_group_id", "grp-1")
    for k, v in (("ccc_admin_id", ADMIN["id"]), ("ccc_admin_password", ADMIN["password"]), ("proc_bcrypt_rounds", 4),
                 ("proc_session_secret", "test-secret")):
        kw.setdefault(k, v)
    clock = Clock()
    clock.set(T0)
    s = kos_settings(tmp_path, **kw)
    c = build_container(s, clock)
    c.kos = KosRuntime(s, c.repo, clock, c.hub.publish, client=KosClient(s, c.repo, clock, transport=fake.transport()))
    mono = [1000.0]
    c.kos.resv.mono = lambda: mono[0]
    if startup:
        run(c.kos.startup())
    client = TestClient(create_app(s, container=c))
    return c, fake, client


def ext_calls(c) -> list[dict]:
    with c.repo.tx() as tx:
        return tx.ext_calls()
