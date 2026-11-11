"""SPEC-008 §4.2 · §4.3 · §5 · §6.4 `POST /api/ext/customers/lookup` — T9 ~ T16(+ 보정 1 N2). 이름 · 이메일은 지어낸 값."""

import pytest

from tests.ext_env import H_LINKY, make_ext_env
from tests.fake_kos import visitor

URL = "/api/ext/customers/lookup"
NAME, EMAIL = "가나다", "a@example.com"


@pytest.fixture
def env(tmp_path):
    return make_ext_env(tmp_path, menu=False)


def v(vid, name=NAME, email=EMAIL, **kw):
    out = {"id": vid, "name": name, "phoneticName": kw.pop("phonetic", None), "isNew": False, "nationality": "JP",
           "chartNumber": f"C-{vid}", "gender": "FEMALE", "dateOfBirth": "1990-01-02 00:00:00.000Z",
           "phoneNumber": {"countryCode": "82", "phoneNumber": "1000000000"}, "passportNumber": "X0000000"}
    if email is not None:
        out["email"] = email
    out.update(kw)
    return {k: x for k, x in out.items() if x is not None}


def page(*items, count=None):
    return {"count": len(items) if count is None else count, "data": list(items)}


def post(cl, name=NAME, email=EMAIL):
    return cl.post(URL, json={"name": name, "email": email}, headers=H_LINKY)


def calls(fake, name):
    return [b for p, b in fake.calls if p.endswith("/" + name)]


def bundle(oid, title, sets, value, currency="KRW"):
    return {"title": title, "purchaseId": "pur-1", "purchaseItemId": "pi-1", "visitorId": "v-1",
            "optionConfiguration": {"optionId": oid, "optionTitle": title, "productTitle": ""},
            "price": {"value": value, "currency": currency},
            "ticketSets": [{"title": f"세트{i}", "ticketGroupId": f"tg-{i}", "procedure": {"id": "proc-1", "name": "시술"},
                            "tickets": [{"id": f"t-{i}-{j}", "status": st, "price": {"value": 1, "currency": "KRW"},
                                         "createdDateTimeUtc": at} for j, (st, at) in enumerate(ts)]}
                           for i, ts in enumerate(sets)]}


# ------------------------------------------------------------------ T9 한 페이지 · 상한 · 중복 제거
def test_t9_one_page_dedupe_and_cap(env):
    c, fake, cl = env
    fake.visitors_page = page(v("v-1"), v("v-1"))
    r = post(cl)
    assert r.status_code == 200 and r.json()["customer"]["name"] == NAME
    body = calls(fake, "get-visitors")[-1]
    assert body == {"indexOfPage": 0, "countInPage": 1000, "visitorName": NAME, "phoneNumber": "", "chartNumber": "",
                    "sort": {"by": "lastVisitedDateTimeUtc", "order": "DESC"}}
    assert len(calls(fake, "get-visitors")) == 1
    fake.visitors_page = page(v("v-1"), count=1001)
    n_v, n_t = len(calls(fake, "get-visitors")), len(calls(fake, "get-ticket-bundles"))
    r = post(cl)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "customer_not_found")
    assert len(calls(fake, "get-visitors")) == n_v + 1 and len(calls(fake, "get-ticket-bundles")) == n_t


# ------------------------------------------------------------------ T10 이름 다듬기
def test_t10_name_strip_only(env):
    c, fake, cl = env
    post(cl, name="  가 나다  ")
    assert [b["visitorName"] for b in calls(fake, "get-visitors")] == ["가 나다"]  # 가운데 공백 그대로 · 검색 1번


# ------------------------------------------------------------------ T11 이메일 비교
def test_t11_email_rules(env):
    c, fake, cl = env
    fake.visitors_page = page(v("v-1", email="  A@Example.COM "))
    assert post(cl, email=" a@EXAMPLE.com").status_code == 200
    for kos_email in (None, "", "   "):
        fake.visitors_page = page(v("v-2", email=kos_email))
        assert post(cl).status_code == 404
    fake.visitors_page = page(v("v-3", email="no-at-sign"))
    assert post(cl, email="No-At-Sign").status_code == 200


# ------------------------------------------------------------------ T12 이름 정확 일치 · 갈래
def test_t12_exact_name_and_branches(env):
    c, fake, cl = env
    fake.visitors_page = page(v("v-1", name="가나다라"))  # KOS 는 부분 일치로 돌려줌
    assert post(cl).status_code == 404
    fake.visitors_page = page(v("v-1", name="다른이름", phonetic="가나다"))
    assert post(cl).status_code == 200
    fake.visitors_page = page(v("v-1", name="Kim  Ga Na"))  # KOS 가 돌려준 고객이면 공백 · 대소문자 차이는 무시
    assert post(cl, name="kim gana").status_code == 200
    fake.visitors_page = page()
    r = post(cl)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "customer_not_found")
    fake.visitors_page = page(v("v-1"), v("v-2"))
    r = post(cl)
    assert r.status_code == 409 and r.json() == {"error": {"code": "customer_ambiguous", "message": "고객을 특정할 수 없어요"}}


def test_t12_kos_search_keeps_middle_space(env):
    """보정 1 N2 — 가운데 공백이 KOS 등록과 다른 입력은 KOS 검색이 0건 → 404(가짜 KOS 검색 = 공백 그대로 · 부분 일치)."""
    c, fake, cl = env
    fake.visitors["v-9"] = visitor("v-9", name="가나 다", email=EMAIL)
    assert post(cl, name="가나 다").status_code == 200
    r = post(cl, name="가 나다")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "customer_not_found")


# ------------------------------------------------------------------ T13 「없음」 하나
def test_t13_not_found_bytes_identical(env):
    c, fake, cl = env
    cases = [(page(v("v-1", name="다른")), NAME, EMAIL), (page(v("v-1", name="가나다라")), NAME, EMAIL),
             (page(v("v-1")), NAME, "b@example.com"), (page(v("v-1", email="")), NAME, EMAIL),
             (page(), NAME, EMAIL), (page(v("v-1"), count=1001), NAME, EMAIL)]
    outs = set()
    for pg, name, email in cases:
        fake.visitors_page = pg
        r = post(cl, name, email)
        outs.add((r.status_code, r.content))
    assert len(outs) == 1 and outs.pop()[0] == 404


# ------------------------------------------------------------------ T14 시술권 · 「없음」 구분
def test_t14_no_tickets_vs_no_customer_vs_failure(env):
    c, fake, cl = env
    fake.visitors_page = page(v("v-1"))
    r = post(cl)
    assert r.status_code == 200 and r.json()["tickets"] == []  # 묶음 {}
    assert calls(fake, "get-ticket-bundles")[-1] == {"visitorId": "v-1"}
    fake.bundles["v-1"] = {"data": []}
    assert post(cl).json()["tickets"] == []
    fake.fail_paths["get-ticket-bundles"] = 500
    r = post(cl)
    assert (r.status_code, r.json()["error"]["code"]) == (502, "kos_unavailable")
    del fake.fail_paths["get-ticket-bundles"]
    fake.bundles["v-1"] = {"data": {"x": 1}}
    assert post(cl).status_code == 502
    fake.visitors_page = page()
    assert post(cl).status_code == 404


# ------------------------------------------------------------------ T15 시술권 한 줄
def test_t15_ticket_line(env):
    c, fake, cl = env
    fake.visitors_page = page(v("v-1"))
    fake.bundles["v-1"] = {"data": [
        bundle("opt-s1", "산 이름", [[("AVAILABLE", "2026-10-01T16:00:00Z"), ("USED", "2026-10-01T14:00:00Z"),
                                    ("IN_USE", "2026-10-01T15:00:00Z")]], 33000.0),
        bundle("opt-gone", "옛 묶음", [[("AVAILABLE", "2026-09-30T15:30:00Z")], [("AVAILABLE", None), ("CANCELED", None)]],
               50000),
    ]}
    r = post(cl)
    assert r.status_code == 200
    assert r.json()["tickets"] == [
        {"optionId": "opt-s1", "optionTitle": "산 이름", "remainingCount": 1, "totalCount": 3,
         "purchasedDate": "2026-10-01", "bundlePrice": {"value": 33000, "currency": "KRW"}},  # 14:00Z = KST 23:00
        {"optionId": "opt-gone", "optionTitle": "옛 묶음", "remainingCount": 2, "totalCount": 3,
         "purchasedDate": "2026-10-01", "bundlePrice": {"value": 50000, "currency": "KRW"}}]  # 15:30Z = KST 다음날
    text = r.text
    assert "purchasePrice" not in text and "VatIncluded" not in text


# ------------------------------------------------------------------ T16 고객 응답 칸
def test_t16_customer_fields(env):
    c, fake, cl = env
    fake.visitors_page = page(v("v-1", isNew=True, lastVisitedDateTimeUtc="2026-10-20T15:10:00.000Z"))
    r = post(cl)
    cust = r.json()["customer"]
    assert set(r.json()) == {"customer", "tickets"} and set(cust) == {"customerId", "name", "isNew", "lastVisitDate"}
    assert cust["isNew"] is True and cust["lastVisitDate"] == "2026-10-21"
    for leak in ("v-1", "C-v-1", "1990-01-02", "1000000000", "X0000000", EMAIL, "JP", "FEMALE"):
        assert leak not in r.text
    with c.repo.tx() as tx:  # 사본 덮어쓰기(이메일은 저장 안 함)
        row = tx.con.execute("SELECT * FROM customer WHERE id = ?", (cust["customerId"],)).fetchone()
    assert row["kos_id"] == "v-1" and row["chart_number"] == "C-v-1" and EMAIL not in repr(dict(row))
    fake.visitors_page = page(v("v-1"))
    assert post(cl).json()["customer"]["lastVisitDate"] is None
    assert post(cl).json()["customer"]["customerId"] == cust["customerId"]


def test_lookup_search_failure_502(env):
    c, fake, cl = env
    fake.fail_paths["get-visitors"] = 503
    r = post(cl)
    assert (r.status_code, r.json()["error"]["code"]) == (502, "kos_unavailable")


@pytest.mark.parametrize("resp", [{"count": 0}, {"data": None}, {"data": {"x": 1}}, {"items": []}, {}])
def test_lookup_search_bad_shape_502(env, resp):
    """수정 1 W1 — 이름 검색 2xx 인데 data 가 없거나 배열 아님 = 502(「없음」 404 와 섞지 않는다)."""
    c, fake, cl = env
    fake.visitors_page = resp
    r = post(cl)
    assert (r.status_code, r.json()["error"]["code"]) == (502, "kos_unavailable")
    assert calls(fake, "get-ticket-bundles") == []
