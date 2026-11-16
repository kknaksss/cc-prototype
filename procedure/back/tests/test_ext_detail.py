"""SPEC-008 0.4.0 §6.12 `GET /api/ext/reservations/{reservationId}` — T53(상세 몫) · T59 ~ T61. 값은 지어낸 것."""

import pytest

from tests.ext_env import H_CHARTY, H_LINKY, ext_calls, make_ext_env, run
from tests.fake_kos import kst, resv, rtask

TOKEN_CALLS = {"exchange-token", "sign-in", "get-user-account"}
DETAIL_KEYS = {"reservationId", "day", "start", "end", "state", "customer", "reservation", "health", "previousVisits",
               "partialErrors"}
CUSTOMER_KEYS = {"customerId", "name", "phoneticName", "gender", "nationality", "isNew", "chartNumber", "age", "language",
                 "funnel"}
RESV_KEYS = {"memo", "desiredDischargeAt", "funnel", "counselor", "orderMemo", "consultationMemo", "requestedDoctor",
             "requestedProcedures"}


@pytest.fixture
def env(tmp_path):
    return make_ext_env(tmp_path, menu=False)


def kos(fake, since=0) -> list[str]:
    return [p.rsplit("/", 1)[-1] for p, _ in fake.calls[since:] if p.rsplit("/", 1)[-1] not in TOKEN_CALLS]


def seed(c, fake, sid="s1", **kw):
    """오늘 예약 하나를 사본에 넣는다(날짜 조회 1번) → ccc id."""
    x = fake._resv_sch(sid) or fake.add_resv(sid, **kw)
    c.kos.resv.invalidate("2026-10-21")
    run(c.resv.board("2026-10-21"))
    with c.repo.tx() as tx:
        return tx.reservation_id_of(sid), x


def url(rid):
    return f"/api/ext/reservations/{rid}"


def views(c):
    with c.repo.tx() as tx:
        return tx.events("ext_view")


def rich(c, fake):
    """희망 시술 · 희망 의사 · 메모 · 이전 방문(상담자 · 의사) 모두 있는 예약."""
    fake.accounts.append({"id": "cs-1", "name": "<상담사>", "roleTags": ["COUNSELOR"], "activate": True})
    run(c.kos.master_once(force=True))
    rid, x = seed(c, fake, counselor={"id": "cs-1", "name": "<상담사>"})
    x["orderMemo"] = "<오더>"
    x["consultation"] = {"consultationMemo": "", "counselor": {"id": "cs-1", "name": "<상담사>"}}
    x["reservation"]["doctor"] = {"id": "doc-a", "name": "가 원장"}
    x["reservation"]["requestedProcedures"] = [
        {"type": "OPTION", "optionConfiguration": {"optionId": "opt-1", "optionTitle": "<옵션>", "productTitle": "<상품>",
                                                   "price": {"value": 1, "currency": "KRW"}}},
        {"type": "TICKET", "ticketConfiguration": {"ticketId": "tk-1", "ticketTitle": "<시술권>"}}]
    old = resv("old-1", start=kst(10).replace(month=9), status="COMPLETED", flow="COMPLETED", memo="<지난 예약 메모>",
               tasks=[{**rtask(1, title="<시술>"), "doctors": [{"id": "doc-a", "name": "가 원장"}]}])
    old["consultation"] = {"consultationMemo": "<지난 상담 메모>", "counselor": {"id": "x-9", "name": "<다른 사람>"}}
    old["consultations"] = [{"counselors": [{"id": "cs-1", "name": "<상담사>"}, {"id": "x-2", "name": "<둘>"}],
                             "content": {"text": "<상담 원문>"}},
                            {"counselors": [{"id": "cs-1", "name": "<상담사>"}]}]
    only_one = resv("old-2", start=kst(10).replace(month=8), status="NO_SHOW")
    only_one["consultation"] = {"counselor": {"id": "x-9", "name": "<다른 사람>"}}
    none = resv("old-3", start=kst(10).replace(month=7), status="CANCELED")
    same_day = resv("same", start=kst(15), status="RESERVED")
    fake.history = [old, only_one, none, same_day]
    fake.visitors["vis-1"]["visitorFunnel"] = {"funnelId": "fn-1", "funnelDetail": "<유입 상세>"}
    return rid


# ------------------------------------------------------------------ T59 칸
def test_t59_fields(env):
    c, fake, cl = env
    rid = rich(c, fake)
    n = len(fake.calls)
    r = cl.get(url(rid), headers=H_LINKY)
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == DETAIL_KEYS and set(d["customer"]) == CUSTOMER_KEYS and set(d["reservation"]) == RESV_KEYS
    assert d["partialErrors"] == []
    cu, rv = d["customer"], d["reservation"]
    assert cu["language"] == "ja" and cu["age"] == 36 and cu["funnel"] == {"name": "인스타그램", "detail": "<유입 상세>"}
    assert rv["counselor"]["name"] == "<상담사>" and isinstance(rv["counselor"]["staffId"], int)
    assert rv["requestedDoctor"] == {"staffId": rv["requestedDoctor"]["staffId"], "name": "가 원장"}
    assert rv["orderMemo"] == "<오더>" and rv["consultationMemo"] == ""  # 빈 문자열 그대로
    assert rv["requestedProcedures"] == [
        {"type": "OPTION", "optionId": "opt-1", "optionTitle": "<옵션>", "productTitle": "<상품>", "ticketId": None,
         "ticketTitle": None},
        {"type": "TICKET", "optionId": None, "optionTitle": None, "productTitle": None, "ticketId": "tk-1",
         "ticketTitle": "<시술권>"}]
    pv = d["previousVisits"]
    assert [p["start"][:10] for p in pv] == ["2026-09-21", "2026-08-21", "2026-07-21"]  # 같은 날 뺌 · 최신 순
    assert pv[0]["reservationMemo"] == "<지난 예약 메모>" and pv[0]["consultationMemo"] == "<지난 상담 메모>"
    assert pv[0]["procedures"][0]["doctors"] == ["가 원장"]
    assert [x["name"] for x in pv[0]["counselors"]] == ["<상담사>", "<둘>"]  # 같은 KOS id 한 번
    assert pv[0]["counselors"][1]["staffId"] is None
    assert pv[1]["counselors"] == [{"staffId": None, "name": "<다른 사람>"}]  # consultations 없음 → consultation.counselor
    assert pv[2]["counselors"] == []
    for leak in ('"phone"', '"email"', '"passportNumber"', '"remark"', '"content"', '"settlement"', '"can"', "<상담 원문>",
                 '"vis-1"', '"personal"'):
        assert leak not in r.text
    assert len(kos(fake, n)) == 5  # 일정 상세 1 + 고객 1 + 문진 2 + 고객 일정 1


def test_t59_no_consultation_and_empty_requested(env):
    c, fake, cl = env
    rid, x = seed(c, fake)
    d = cl.get(url(rid), headers=H_LINKY).json()
    assert d["reservation"]["consultationMemo"] is None and d["reservation"]["requestedProcedures"] == []
    assert d["reservation"]["requestedDoctor"] is None


# ------------------------------------------------------------------ T60 부분 실패
def test_t60_schedule_failure(env):
    c, fake, cl = env
    rid = rich(c, fake)
    fake.resv_fail["get-schedule-detail"] = (500, {})
    d = cl.get(url(rid), headers=H_LINKY)
    assert d.status_code == 200
    rv = d.json()["reservation"]
    assert (rv["requestedProcedures"], rv["requestedDoctor"], rv["orderMemo"], rv["consultationMemo"]) == (None,) * 4
    assert d.json()["partialErrors"] == ["schedule"] and rv["memo"] == "예약 메모"  # 사본 값


@pytest.mark.parametrize("fail,part", [("get-visitor", "visitor"), ("get-visitor-questionnaire", "questionnaire"),
                                       ("get-schedules-by-visitor", "previousVisits")])
def test_t60_reads_failure(env, fail, part):
    c, fake, cl = env
    rid = rich(c, fake)
    fake.resv_fail[fail] = (500, {})
    d = cl.get(url(rid), headers=H_LINKY).json()
    assert d["partialErrors"] == [part]
    if part == "visitor":
        assert (d["customer"]["language"], d["customer"]["age"], d["customer"]["funnel"]) == (None, None, None)
    if part == "questionnaire":
        assert d["health"]["state"] == "error"
    if part == "previousVisits":
        assert d["previousVisits"] is None


# ------------------------------------------------------------------ T61 404 · 비용 · 열람 · T53(상세)
def test_t61_errors_and_cost(env):
    c, fake, cl = env
    n = len(fake.calls)
    r = cl.get(url(9999), headers=H_LINKY)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "reservation_not_found") and kos(fake, n) == []
    assert cl.get("/api/ext/reservations/abc", headers=H_LINKY).status_code == 400
    rid, _ = seed(c, fake)
    fake.resv.remove(fake._resv_sch("s1"))
    n = len(fake.calls)
    r = cl.get(url(rid), headers=H_LINKY)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "reservation_gone") and kos(fake, n) == ["get-schedule-detail"]
    assert views(c) == []
    c.kos = None
    r = cl.get(url(rid), headers=H_LINKY)
    assert (r.status_code, r.json()["error"]["code"]) == (502, "kos_unavailable")


def test_t61_no_amount_no_day_query_and_view(env):
    c, fake, cl = env
    fake.purchases["p1"] = {"id": "p1", "items": [{"priceV2": {"amount": {"value": 3000, "currency": "KRW"}}}]}
    rid, _ = seed(c, fake, flow="PROCEDURE_DONE", status="IN_PROGRESS", purchases=["p1"])
    n = len(fake.calls)
    r = cl.get(url(rid), headers={**H_CHARTY, "X-Ext-Staff-Id": "st-9"})
    assert r.status_code == 200 and len(kos(fake, n)) == 5
    assert "get-purchase-summaries" not in kos(fake, n) and "get-schedules-for-reservation" not in kos(fake, n)
    v = views(c)[-1]
    assert v["actor"] == "ext:charty:st-9"
    assert v["payload"] == {"client": "charty", "staffId": "st-9", "path": "GET /api/ext/reservations/{reservationId}",
                            "customerId": r.json()["customer"]["customerId"], "reservationId": rid}
    assert cl.get(url(rid), headers=H_LINKY).status_code == 200 and views(c)[-1]["actor"] == "ext:linky"
    n = len(fake.calls)
    run(c.resv.detail(rid))  # 직원 상세는 지금처럼 수납 금액을 부른다(amount 기본값)
    assert "get-purchase-summaries" in kos(fake, n)
    assert all(str(rid) not in r["endpoint"] and "st-9" not in repr(r) for r in ext_calls(c))


@pytest.mark.parametrize("bad", ["x" * 65, "a b", "직원".encode(), "a:b", "a@b"])
def test_t53_detail_header(env, bad):
    c, fake, cl = env
    rid, _ = seed(c, fake)
    n = len(fake.calls)
    r = cl.get(url(rid), headers={**H_LINKY, "X-Ext-Staff-Id": bad})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    assert r.json()["error"]["message"].startswith("header.X-Ext-Staff-Id:") and kos(fake, n) == []


def test_t53_detail_header_ok_values(env):
    c, fake, cl = env
    rid, _ = seed(c, fake)
    for good, actor in (("   ", "ext:linky"), ("x" * 64, "ext:linky:" + "x" * 64), ("a.b_c-d", "ext:linky:a.b_c-d")):
        assert cl.get(url(rid), headers={**H_LINKY, "X-Ext-Staff-Id": good}).status_code == 200
        assert views(c)[-1]["actor"] == actor


def test_t72_staff_detail_previous_failure_still_empty_list(env):
    """직원 상세 무변경 — 이전 방문 조회가 실패해도 지금처럼 `previousVisits = []`(외부만 null)."""
    c, fake, cl = env
    rid = rich(c, fake)
    fake.resv_fail["get-schedules-by-visitor"] = (500, {})
    assert run(c.resv.detail(rid)).previousVisits == []


def _leaks(caplog, *values):
    import re

    msgs = [r.getMessage() for r in caplog.records]
    return [v for v in values for m in msgs if re.search(rf"(?<![\w-]){re.escape(str(v))}(?![\w-])", m)]


def test_w4_detail_logs_clean(env, caplog):
    """코드 검수 r1 W4 — 상세 경로 로그에 헤더 직원 id · 예약 id · 고객 값 0(부분 실패 로그 포함)."""
    import logging

    c, fake, cl = env
    rid, _ = seed(c, fake, name="<이름77>")
    fake.resv_fail["get-visitor-questionnaire"] = (500, {})
    caplog.set_level(logging.DEBUG)
    caplog.clear()
    r = cl.get(url(rid), headers={**H_LINKY, "X-Ext-Staff-Id": "staff-w4-x"})
    assert r.status_code == 200 and r.json()["partialErrors"] == ["questionnaire"]
    cid = r.json()["customer"]["customerId"]
    assert caplog.records and _leaks(caplog, "staff-w4-x", rid, cid, "<이름77>", "vis-1", "s1") == []
