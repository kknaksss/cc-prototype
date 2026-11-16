"""SPEC-008 0.4.0 §4.3 · §4.4 · §6.4 · §6.10 lookup 고침 — T48 ~ T52 · T69(lookup) · T71(헤더를 읽지 않는 기존 경로).

이름 · 이메일 · id 는 지어낸 값.
"""

import logging

import pytest

from tests.ext_env import H_CHARTY, H_LINKY, ext_calls, make_ext_env
from tests.fake_kos import kst, visitor

URL = "/api/ext/customers/lookup"
NAME, EMAIL = "가나다", "a@example.com"
TOKEN_CALLS = {"exchange-token", "sign-in", "get-user-account"}
BAD_STAFF = ("x" * 65, "직원1".encode(), "a@b", "a:b", "a b")  # 한글 = UTF-8 바이트(httpx str 헤더는 ASCII 만)


@pytest.fixture
def env(tmp_path):
    c, fake, cl = make_ext_env(tmp_path, menu=False)
    fake.visitors["v-1"] = visitor("v-1", name=NAME, email=EMAIL, isNew=True,
                                   lastVisitedDateTimeUtc="2026-10-20T15:10:00.000Z")
    fake.visitors_page = {"count": 1, "data": [fake.visitors["v-1"]]}
    return c, fake, cl


def kos(fake, since=0) -> list[str]:
    return [p.rsplit("/", 1)[-1] for p, _ in fake.calls[since:] if p.rsplit("/", 1)[-1] not in TOKEN_CALLS]


def paths(fake, since=0) -> list[str]:
    return [p for p, _ in fake.calls[since:]]


def by_name(cl, headers=H_LINKY, **kw):
    return cl.post(URL, json={"name": NAME, "email": EMAIL}, headers={**headers, **kw})


def cid_of(cl) -> int:
    return by_name(cl).json()["customer"]["customerId"]


def views(c):
    with c.repo.tx() as tx:
        return tx.events("ext_view")


def tk(status, at="2026-10-01T03:00:00Z"):
    return {"id": f"t-{status}", "status": status, "price": {"value": 1, "currency": "KRW"}, "createdDateTimeUtc": at}


def bundle(oid, statuses):
    return {"title": oid, "optionConfiguration": {"optionId": oid, "optionTitle": oid, "productTitle": ""},
            "price": {"value": 10000.0, "currency": "KRW"}, "purchaseId": "p", "purchaseItemId": "pi", "visitorId": "v-1",
            "translsMap": {}, "ticketSets": [{"title": "s", "ticketGroupId": "g", "tickets": [tk(s) for s in statuses]}]}


def card(**kw):
    m = lambda v: {"value": v, "currency": "KRW"}  # noqa: E731
    c = {"id": "card-kos-id", "title": "<카드>", "ownerId": "owner-kos-id", "description": "설명-비공개",
         "remainingBalance": {"balance": m(7000), "total": m(10000)},
         "remainingPoint": {"balance": m(300), "total": m(500)},
         "expirationDateTimeUtc": "2027-01-31T15:00Z", "createdDateTimeUtc": "2026-09-30T15:30:00.000Z",
         "translsMap": {}, "updatedDateTimeUtc": "2026-10-01T00:00:00.000Z"}
    c.update(kw)
    return c


# ------------------------------------------------------------------ T48 customerId 갈래
def test_t48_customer_id_branch(env):
    c, fake, cl = env
    named = by_name(cl).json()
    cid = named["customer"]["customerId"]
    fake.visitors["v-1"]["name"] = "<바뀐 이름>"
    n = len(fake.calls)
    r = cl.post(URL, json={"customerId": cid}, headers=H_LINKY)
    assert r.status_code == 200
    assert kos(fake, n).count("get-visitor") == 1 and "get-visitors" not in kos(fake, n)
    assert set(r.json()["customer"]) == set(named["customer"])
    assert r.json()["customer"]["name"] == "<바뀐 이름>" and r.json()["customer"]["customerId"] == cid
    with c.repo.tx() as tx:
        assert tx.customer(cid).name == "<바뀐 이름>"  # 사본 덮어씀

    fake.visitors_page = {"count": 0, "data": []}
    not_found = by_name(cl)
    n = len(fake.calls)
    r = cl.post(URL, json={"customerId": 9999}, headers=H_LINKY)
    assert (r.status_code, r.content) == (404, not_found.content) and kos(fake, n) == []

    fake.resv_fail["get-visitor"] = (404, {"className": "com.x.NotFoundException"})  # KOS HTTP 404(W2 · Q2)
    r = cl.post(URL, json={"customerId": cid}, headers=H_LINKY)
    assert (r.status_code, r.content) == (404, not_found.content)
    del fake.resv_fail["get-visitor"]
    del fake.visitors["v-1"]  # KOS 400 + errorProperties{id, NotFound}(K1 모양)
    r = cl.post(URL, json={"customerId": cid}, headers=H_LINKY)
    assert (r.status_code, r.content) == (404, not_found.content)


@pytest.mark.parametrize("how", ["5xx", "shape", "400_other"])
def test_t48_get_visitor_failure_502(env, how):
    c, fake, cl = env
    cid = cid_of(cl)
    if how == "5xx":
        fake.fail_paths["get-visitor"] = 500
    elif how == "400_other":  # 코드 검수 r2 N3 — NotFound 가 아닌 400 은 404 가 아니라 502(T48 0.4.4)
        fake.resv_fail["get-visitor"] = (400, {"className": "x.InvalidRequestException"})
    else:
        fake.resv_fail["get-visitor"] = (200, {"data": ["x"]})  # data 가 객체 아님
    r = cl.post(URL, json={"customerId": cid}, headers=H_LINKY)
    assert (r.status_code, r.json()["error"]["code"]) == (502, "kos_unavailable")
    assert views(c) and len(views(c)) == 1  # 처음 이름 갈래 200 의 1줄뿐(502 는 0)


# ------------------------------------------------------------------ T49 요청 갈래 검사
@pytest.mark.parametrize("body,branch", [
    ({"customerId": 1, "name": NAME}, True), ({"customerId": 1, "name": NAME, "email": EMAIL}, True),
    ({"name": NAME}, True), ({"email": EMAIL}, True), ({}, True),
    ({"customerId": 0}, False), ({"customerId": -1}, False), ({"customerId": "1"}, False), ({"customerId": True}, False),
    ({"name": " ", "email": EMAIL}, False), ({"customerId": 1, "x": 1}, False),
])
def test_t49_branch_check(env, body, branch):
    c, fake, cl = env
    n = len(fake.calls)
    r = cl.post(URL, json=body, headers=H_LINKY)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    if branch:
        assert r.json()["error"]["message"].startswith("body: ")
    assert kos(fake, n) == []


def test_t49_old_shape_and_schema(env):
    c, fake, cl = env
    assert by_name(cl).status_code == 200
    r = cl.post(URL, json={"name": NAME, "email": EMAIL, "customerId": None}, headers=H_LINKY)  # 명시 null = 없음
    assert r.status_code == 200
    cid = r.json()["customer"]["customerId"]  # 코드 검수 r2 N3 — 명시 null 세 경우(T49 0.4.4)
    r = cl.post(URL, json={"customerId": cid, "name": None, "email": None}, headers=H_LINKY)
    assert r.status_code == 200 and r.json()["customer"]["customerId"] == cid
    r = cl.post(URL, json={"customerId": None}, headers=H_LINKY)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    assert r.json()["error"]["message"].startswith("body: ")
    schema = cl.get("/api/openapi.json").json()["components"]["schemas"]["ExtLookupRequest"]
    assert "name" not in schema.get("required", []) and "email" not in schema.get("required", [])
    assert set(schema["properties"]) == {"name", "email", "customerId"}


# ------------------------------------------------------------------ T50 내부 시술권 · inUseCount
def test_t50_internal_tickets(env):
    c, fake, cl = env
    fake.bundles["v-1"] = {"data": [bundle("o-avail", ["AVAILABLE", "IN_USE", "USED"]), bundle("o-inuse", ["IN_USE", "USED"]),
                                    bundle("o-dead", ["USED", "CANCELED"]), bundle("o-cancel", ["CANCELED"])]}
    n = len(fake.calls)
    r = by_name(cl)
    assert r.status_code == 200
    t = [p for p in paths(fake, n) if p.endswith("/get-ticket-bundles")]
    assert t == ["/tenants/tenant-x/ticket/v1/queries/get-ticket-bundles"]  # 내부만 · 공개 0
    body = [b for p, b in fake.calls[n:] if p.endswith("/get-ticket-bundles")][0]
    assert body == {"visitorId": "v-1", "sort": {"by": "ticket.createdDateTimeUtc", "order": 2}}
    tickets = r.json()["tickets"]
    assert [x["optionId"] for x in tickets] == ["o-avail", "o-inuse"]  # 다 쓴 · 다 취소된 묶음 빠짐
    assert [(x["remainingCount"], x["inUseCount"], x["totalCount"]) for x in tickets] == [(1, 1, 3), (0, 1, 2)]
    assert set(tickets[0]) == {"optionId", "optionTitle", "remainingCount", "inUseCount", "totalCount", "purchasedDate",
                               "bundlePrice"}
    assert "expir" not in r.text.lower().replace("expiresat", "")


# ------------------------------------------------------------------ T51 선불카드
def test_t51_prepaid_cards(env):
    c, fake, cl = env
    fake.prepaid["v-1"] = {"data": [card(), card(title="<카드2>", remainingPoint=None, expirationDateTimeUtc=None)]}
    n = len(fake.calls)
    r = by_name(cl)
    assert r.status_code == 200
    body = [b for p, b in fake.calls[n:] if p.endswith("/get-prepaid-card-summaries")]
    assert body == [{"visitorId": "v-1", "available": True}]
    assert [p for p, _ in fake.calls[n:] if p.endswith("/get-prepaid-card-summaries")][0].startswith(
        "/purchase/open/")  # 공개
    cards = r.json()["prepaidCards"]
    assert cards[0] == {"title": "<카드>", "issuedDate": "2026-10-01", "expiresAt": "2027-02-01T00:00:00+09:00",
                        "balance": {"remaining": {"value": 7000, "currency": "KRW"},
                                    "total": {"value": 10000, "currency": "KRW"}},
                        "point": {"remaining": {"value": 300, "currency": "KRW"}, "total": {"value": 500, "currency": "KRW"}}}
    assert cards[1]["point"] == {"remaining": None, "total": None} and cards[1]["expiresAt"] is None
    for leak in ("card-kos-id", "owner-kos-id", "설명-비공개"):
        assert leak not in r.text
    assert r.json()["partialErrors"] == []
    for empty in ({}, {"data": []}):
        fake.prepaid["v-1"] = empty
        assert (by_name(cl).json()["prepaidCards"], by_name(cl).json()["partialErrors"]) == ([], [])


@pytest.mark.parametrize("how", ["5xx", "not_list", "bad_item", "bad_money"])
def test_t51_prepaid_failure_is_200_null(env, how):
    c, fake, cl = env
    fake.bundles["v-1"] = {"data": [bundle("o-avail", ["AVAILABLE"])]}
    if how == "5xx":
        fake.fail_paths["get-prepaid-card-summaries"] = 503
    else:
        fake.prepaid["v-1"] = {"not_list": {"data": {"x": 1}}, "bad_item": {"data": ["x"]},
                               "bad_money": {"data": [card(remainingBalance={"balance": {"value": "1"}})]}}[how]
    before = len(views(c))
    r = by_name(cl)
    assert r.status_code == 200
    assert r.json()["prepaidCards"] is None and r.json()["partialErrors"] == ["prepaidCards"]
    assert r.json()["customer"]["name"] == NAME and len(r.json()["tickets"]) == 1
    assert len(views(c)) == before + 1


def test_t51_tickets_failure_still_502_and_gathered(env):
    c, fake, cl = env
    fake.fail_paths["get-ticket-bundles"] = 500
    n = len(fake.calls)
    r = by_name(cl)
    assert (r.status_code, r.json()["error"]["code"]) == (502, "kos_unavailable")
    assert "get-prepaid-card-summaries" in kos(fake, n)  # 동시에 불렀다(시술권 실패여도 선불카드 호출이 나감)


# ------------------------------------------------------------------ T52 비용 · 열람 기록
def test_t52_cost_and_view(env):
    c, fake, cl = env
    n = len(fake.calls)
    r = by_name(cl, headers=H_CHARTY, **{"X-Ext-Staff-Id": "  staff.01_a-b  "})
    assert r.status_code == 200 and len(kos(fake, n)) == 3
    cid = r.json()["customer"]["customerId"]
    v = views(c)[-1]
    assert v["actor"] == "ext:charty:staff.01_a-b" and v["visit_id"] is None
    assert v["payload"] == {"client": "charty", "staffId": "staff.01_a-b", "path": "POST /api/ext/customers/lookup",
                            "customerId": cid, "reservationId": None}
    n = len(fake.calls)
    assert cl.post(URL, json={"customerId": cid}, headers=H_LINKY).status_code == 200 and len(kos(fake, n)) == 3
    v = views(c)[-1]
    assert v["actor"] == "ext:linky" and v["payload"]["staffId"] is None
    fake.visitors_page = {"count": 0, "data": []}
    n, before = len(fake.calls), len(views(c))
    assert by_name(cl).status_code == 404 and len(kos(fake, n)) == 1
    assert cl.post(URL, json={"customerId": 9999}, headers=H_LINKY).status_code == 404 and len(kos(fake, n)) == 1
    fake.visitors_page = {"count": 2, "data": [fake.visitors["v-1"], {**fake.visitors["v-1"], "id": "v-2"}]}
    assert by_name(cl).status_code == 409
    fake.visitors_page = {"count": 1, "data": [fake.visitors["v-1"]]}
    fake.fail_paths["get-ticket-bundles"] = 500
    assert by_name(cl).status_code == 502
    assert len(views(c)) == before  # 404 · 409 · 502 → ext_view 0


@pytest.mark.parametrize("bad", BAD_STAFF)
def test_t52_bad_header_is_absent_on_lookup(env, bad):
    c, fake, cl = env
    r = by_name(cl, **{"X-Ext-Staff-Id": bad})
    assert r.status_code == 200
    v = views(c)[-1]
    assert v["actor"] == "ext:linky" and v["payload"]["staffId"] is None


# ------------------------------------------------------------------ T69 ext_call 원칙(lookup)
def test_t69_ext_call_and_logs_clean(env, caplog):
    c, fake, cl = env
    caplog.set_level(logging.DEBUG)
    staff = "staff-zz-77"
    cid = by_name(cl, **{"X-Ext-Staff-Id": staff}).json()["customer"]["customerId"]
    cl.post(URL, json={"customerId": cid}, headers={**H_LINKY, "X-Ext-Staff-Id": staff})
    rows = repr(ext_calls(c))
    for leak in (staff, NAME, EMAIL, "v-1"):
        assert leak not in rows and leak not in caplog.text
    assert f"'customerId': {cid}" not in rows and all(r["endpoint"] == "POST /api/ext/customers/lookup"
                                                       for r in ext_calls(c))


# ------------------------------------------------------------------ T71 헤더를 읽지 않는 다섯 기존 경로
def test_t71_old_five_ignore_staff_header(env):
    c, fake, cl = env
    fake.add_resv("sch-h", "v-1", start=kst(9), status="COMPLETED", flow="COMPLETED")
    reqs = [("get", "/api/ext/menu", None), ("get", "/api/ext/availability?date=2026-10-22", None),
            ("post", "/api/ext/customers/visits", {"name": NAME, "email": EMAIL}),
            ("post", "/api/ext/customers/reservations", {"name": NAME, "email": EMAIL})]
    for method, url, body in reqs:
        base = getattr(cl, method)(url, headers=H_LINKY, **({"json": body} if body else {}))
        for bad in BAD_STAFF:
            r = getattr(cl, method)(url, headers={**H_LINKY, "X-Ext-Staff-Id": bad}, **({"json": body} if body else {}))
            assert (r.status_code, r.content) == (base.status_code, base.content), (url, bad)
    for bad in BAD_STAFF:  # 예약 — 상태 같음 · 행위자 ext:<연동처> 그대로
        r = cl.post("/api/ext/reservations", json={"name": NAME, "email": EMAIL, "start": "2026-10-22T14:00:00+09:00"},
                    headers={**H_LINKY, "X-Ext-Staff-Id": bad})
        assert r.status_code == 200, r.text
    with c.repo.tx() as tx:
        assert {e["actor"] for e in tx.events("resv_create")} == {"ext:linky"}
