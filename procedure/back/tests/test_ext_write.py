"""SPEC-008 0.4.0 §6.13 ~ §6.15 쓰기 셋 — T53(쓰기 몫) · T62 ~ T65. 값은 지어낸 것."""

from datetime import date

import pytest

from tests.ext_env import H_CHARTY, H_LINKY, make_ext_env, run
from tests.fake_kos import kst
from tests.test_ext_detail import seed

TOKEN_CALLS = {"exchange-token", "sign-in", "get-user-account"}
LOOKUP = "/api/ext/customers/lookup"


@pytest.fixture
def env(tmp_path):
    return make_ext_env(tmp_path, menu=False)


def kos(fake, since=0) -> list[str]:
    return [p.rsplit("/", 1)[-1] for p, _ in fake.calls[since:] if p.rsplit("/", 1)[-1] not in TOKEN_CALLS]


def bodies(fake, name, since=0):
    return [b for p, b in fake.calls[since:] if p.endswith("/" + name)]


def events(c, type_=None):
    with c.repo.tx() as tx:
        return tx.events(type_)


def cust_id(c, kos_id="vis-1") -> int:
    with c.repo.tx() as tx:
        return tx.con.execute("SELECT id FROM customer WHERE kos_id = ?", (kos_id,)).fetchone()["id"]


def lang(cl, cid, value, headers=H_CHARTY, **kw):
    return cl.put(f"/api/ext/customers/{cid}/language", json={"language": value}, headers={**headers, **kw})


def order(cl, rid, memo, headers=H_CHARTY, **kw):
    return cl.put(f"/api/ext/reservations/{rid}/order-memo", json={"orderMemo": memo}, headers={**headers, **kw})


def consult(cl, rid, memo, headers=H_CHARTY, **kw):
    return cl.put(f"/api/ext/reservations/{rid}/consultation-memo", json={"consultationMemo": memo},
                  headers={**headers, **kw})


# ------------------------------------------------------------------ T62 고객 언어
def test_t62_language(env):
    c, fake, cl = env
    seed(c, fake)
    cid = cust_id(c)
    n = len(fake.calls)
    r = lang(cl, cid, "  en  ", **{"X-Ext-Staff-Id": "st-1"})
    assert (r.status_code, r.json()) == (200, {"ok": True})
    assert kos(fake, n) == ["get-visitor", "update-visitor-personal-information"]
    body = bodies(fake, "update-visitor-personal-information", n)[0]
    v0 = {k: x for k, x in fake.visitors["vis-1"].items()}
    assert body["language"] == "en" and body["id"] == "vis-1"
    assert body["name"] == v0["name"] and body["passportNumber"] == v0["passportNumber"]  # 다시 읽은 묶음 전체
    assert "memo" not in body  # 개인 정보 17키 밖은 보내지 않는다
    ev = events(c, "visitor_personal")[-1]
    assert ev["actor"] == "ext:charty:st-1" and ev["payload"] == {"customerId": cid, "fields": ["language"]}
    n = len(fake.calls)
    assert lang(cl, cid, "en").status_code == 200 and kos(fake, n) == ["get-visitor"]  # 같은 값 → 쓰기 0
    assert len(events(c, "visitor_personal")) == 1
    assert lang(cl, cid, "").status_code == 200 and fake.visitors["vis-1"]["language"] == ""  # 비움
    assert events(c, "visitor_personal")[-1]["actor"] == "ext:charty"
    r = cl.put(f"/api/ext/customers/{cid}/language", json={"language": None}, headers=H_CHARTY)
    assert r.status_code == 400


def test_t62_language_404_and_reject(env):
    c, fake, cl = env
    fake.visitors_page = {"count": 0, "data": []}
    lookup_404 = cl.post(LOOKUP, json={"name": "<이름>", "email": "a@example.com"}, headers=H_LINKY)
    n = len(fake.calls)
    r = lang(cl, 9999, "en")
    assert (r.status_code, r.content) == (404, lookup_404.content) and kos(fake, n) == []
    seed(c, fake)
    cid = cust_id(c)
    fake.resv_fail["update-visitor-personal-information"] = (400, {"className": "x.InvalidRequestException"})
    r = lang(cl, cid, "en", **{"X-Ext-Staff-Id": "st-2"})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "kos_rejected")
    rej = events(c, "kos_rejected")[-1]
    assert rej["actor"] == "ext:charty:st-2" and rej["payload"]["op"] == "update-visitor-personal-information"
    assert events(c, "visitor_personal") == []


# ------------------------------------------------------------------ T63 오더 메모
def test_t63_order_memo(env):
    c, fake, cl = env
    fake.add_resv("sch-1", start=kst(12))  # 시술 현황 사본 visit 에 같은 kos_id 행이 있는 예약
    run(c.kos.sync.sync_schedules())
    rid, _ = seed(c, fake, sid="sch-1")
    rid2, _ = seed(c, fake, sid="s-novisit", start=kst(13))
    with c.repo.tx() as tx:
        before = [dict(r) for r in tx.con.execute("SELECT * FROM visit ORDER BY id")]
        memo_before = tx.reservation(rid).memo
    assert len(before) == 1 and before[0]["kos_id"] == "sch-1"
    n = len(fake.calls)
    r = order(cl, rid, "<새 오더>", **{"X-Ext-Staff-Id": "st-1"})
    assert (r.status_code, r.json()) == (200, {"ok": True}) and kos(fake, n) == ["change-order-memo"]
    assert bodies(fake, "change-order-memo", n) == [{"scheduleId": "sch-1", "orderMemo": "<새 오더>"}]
    assert any(p.startswith("/tenants/") for p, _ in fake.calls[n:])  # 내부
    ev = events(c, "order_memo")[-1]
    assert ev["actor"] == "ext:charty:st-1" and ev["payload"] == {"reservationId": rid, "length": len("<새 오더>")}
    assert "<새 오더>" not in repr(events(c))
    with c.repo.tx() as tx:
        after = [dict(r) for r in tx.con.execute("SELECT * FROM visit ORDER BY id")]
        assert tx.reservation(rid).memo == memo_before  # 예약 메모 그대로
    assert after[0]["order_memo"] == "<새 오더>"
    assert {k: v for k, v in after[0].items() if k != "order_memo"} == {k: v for k, v in before[0].items() if k != "order_memo"}
    assert order(cl, rid2, "").status_code == 200  # visit 행 없는 예약 · 빈 글
    with c.repo.tx() as tx:
        assert tx.con.execute("SELECT COUNT(*) n FROM visit").fetchone()["n"] == 1  # 새 행 0
    n = len(fake.calls)
    order(cl, rid, "<새 오더>")
    order(cl, rid, "<새 오더>")
    assert kos(fake, n).count("change-order-memo") == 2  # 같은 글이어도 늘 KOS


def test_t63_invalidates_day_cache(env):
    c, fake, cl = env
    rid, _ = seed(c, fake)
    day = date(2026, 10, 21)
    assert c.kos.resv.fresh(day)
    order(cl, rid, "x")
    assert not c.kos.resv.fresh(day)  # after_write — 그 날짜 캐시 비움


# ------------------------------------------------------------------ T64 상담 메모
def test_t64_consultation_memo(env):
    c, fake, cl = env
    rid, x = seed(c, fake)
    n = len(fake.calls)
    r = consult(cl, rid, "<상담>")
    assert r.status_code == 200 and kos(fake, n) == ["update-schedule-consultation-info"]
    path, body = [(p, b) for p, b in fake.calls[n:] if p.endswith("/update-schedule-consultation-info")][0]
    assert path.startswith("/schedule/open/") and body == {"scheduleId": "s1", "consultationMemo": "<상담>"}  # 공개
    ev = events(c, "consultation_memo")[-1]
    assert ev["actor"] == "ext:charty" and ev["payload"] == {"reservationId": rid, "length": 4}


# ------------------------------------------------------------------ T63 · T64 404 · 409 · 502 / T65 KOS 먼저
@pytest.mark.parametrize("write,op", [(order, "change-order-memo"), (consult, "update-schedule-consultation-info")])
def test_t63_t64_errors(env, write, op):
    c, fake, cl = env
    n = len(fake.calls)
    r = write(cl, 9999, "x")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "reservation_not_found") and kos(fake, n) == []
    rid, _ = seed(c, fake)
    for status, code in ((400, "kos_rejected"), (500, "kos_unavailable"), (401, "kos_unavailable")):
        fake.resv_fail[op] = (status, {"className": "x.Err"})
        r = write(cl, rid, "x")
        assert (r.status_code, r.json()["error"]["code"]) == ({"kos_rejected": 409}.get(code, 502), code)
    c.kos = None
    assert write(cl, rid, "x").status_code == 502


@pytest.mark.parametrize("which", ["language", "order", "consult"])
def test_t65_kos_first(env, which):
    c, fake, cl = env
    fake.add_resv("sch-1", start=kst(12))
    run(c.kos.sync.sync_schedules())
    rid, _ = seed(c, fake, sid="sch-1")
    cid = cust_id(c)
    with c.repo.tx() as tx:
        visit0 = [dict(r) for r in tx.con.execute("SELECT * FROM visit")]
        cust0 = dict(tx.con.execute("SELECT * FROM customer WHERE id = ?", (cid,)).fetchone())
    op = {"language": "update-visitor-personal-information", "order": "change-order-memo",
          "consult": "update-schedule-consultation-info"}[which]
    fake.resv_fail[op] = (400, {"className": "x.InvalidRequestException"})
    n_ev = len(events(c))
    r = {"language": lambda: lang(cl, cid, "en"), "order": lambda: order(cl, rid, "<글>"),
         "consult": lambda: consult(cl, rid, "<글>")}[which]()
    assert (r.status_code, r.json()["error"]["code"]) == (409, "kos_rejected")
    new = events(c)[n_ev:]
    assert [e["type"] for e in new] == ["kos_rejected"] and new[0]["actor"] == "ext:charty"
    with c.repo.tx() as tx:
        assert [dict(r) for r in tx.con.execute("SELECT * FROM visit")] == visit0
        assert dict(tx.con.execute("SELECT * FROM customer WHERE id = ?", (cid,)).fetchone()) == cust0


# ------------------------------------------------------------------ T53 열람 헤더 꼴(쓰기 셋)
@pytest.mark.parametrize("bad", ["x" * 65, "a b", "직원".encode(), "a:b", "a@b"])
def test_t53_write_header(env, bad):
    c, fake, cl = env
    rid, _ = seed(c, fake)
    cid = cust_id(c)
    for r in (lang(cl, cid, "en", **{"X-Ext-Staff-Id": bad}), order(cl, rid, "x", **{"X-Ext-Staff-Id": bad}),
              consult(cl, rid, "x", **{"X-Ext-Staff-Id": bad})):
        assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
        assert r.json()["error"]["message"].startswith("header.X-Ext-Staff-Id:")
    assert not [k for k in kos(fake) if k in ("change-order-memo", "update-schedule-consultation-info",
                                              "update-visitor-personal-information")]


def test_t53_write_header_ok(env):
    c, fake, cl = env
    rid, _ = seed(c, fake)
    for good, actor in (("  ", "ext:linky"), ("x" * 64, "ext:linky:" + "x" * 64), ("a.b_c-d", "ext:linky:a.b_c-d")):
        assert order(cl, rid, "x", headers=H_LINKY, **{"X-Ext-Staff-Id": good}).status_code == 200
        assert events(c, "order_memo")[-1]["actor"] == actor


def test_write_body_rules(env):
    c, fake, cl = env
    rid, _ = seed(c, fake)
    for body in ({}, {"orderMemo": None}, {"orderMemo": 1}, {"orderMemo": "x", "y": 1}):
        assert cl.put(f"/api/ext/reservations/{rid}/order-memo", json=body, headers=H_CHARTY).status_code == 400
    assert cl.put("/api/ext/reservations/abc/order-memo", json={"orderMemo": "x"}, headers=H_CHARTY).status_code == 400
    assert cl.put(f"/api/ext/reservations/{rid}/order-memo", json={"orderMemo": "x"}).status_code == 401


def test_w4_order_memo_logs_clean(env, caplog):
    """코드 검수 r1 W4 — 오더 메모 경로 로그(성공 · KOS 거절)에 헤더 직원 id · 예약 id · 고객 값 · 글 0."""
    import logging

    from tests.test_ext_detail import _leaks

    c, fake, cl = env
    rid, _ = seed(c, fake, name="<이름78>")
    caplog.set_level(logging.DEBUG)
    caplog.clear()
    assert order(cl, rid, "<글w4>", **{"X-Ext-Staff-Id": "staff-w4-y"}).status_code == 200
    fake.resv_fail["change-order-memo"] = (400, {"className": "x.InvalidRequestException"})
    assert order(cl, rid, "<글w4>", **{"X-Ext-Staff-Id": "staff-w4-y"}).status_code == 409
    assert caplog.records and _leaks(caplog, "staff-w4-y", rid, cust_id(c), "<이름78>", "vis-1", "s1", "<글w4>") == []


# ------------------------------------------------------------------ 로컬 e2e 2 — 상담 메모는 KOS 에서 비울 수 없다
@pytest.mark.parametrize("blank", ["", "  ", "\n\t "])
def test_e2e2_consultation_memo_blank_400(env, blank):
    c, fake, cl = env
    rid, _ = seed(c, fake)
    n, n_ev = len(fake.calls), len(events(c))
    r = consult(cl, rid, blank, **{"X-Ext-Staff-Id": "st-1"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    assert r.json()["error"]["message"] == "body.consultationMemo: KOS 는 상담 메모를 비울 수 없어요"
    assert kos(fake, n) == [] and len(events(c)) == n_ev  # KOS 호출 0 · event_log 0(kos_rejected 도 0)


def test_e2e2_order_memo_blank_still_clears(env):
    """오더 메모는 빈 값 = 비움 그대로(KOS 가 비운다)."""
    c, fake, cl = env
    rid, x = seed(c, fake)
    n = len(fake.calls)
    assert order(cl, rid, "").status_code == 200
    assert bodies(fake, "change-order-memo", n) == [{"scheduleId": "s1", "orderMemo": ""}] and x["orderMemo"] == ""
    assert consult(cl, rid, " <앞뒤 공백 글> ").status_code == 200  # 비지 않으면 글 그대로 보냄
    assert bodies(fake, "update-schedule-consultation-info", n) == [{"scheduleId": "s1", "consultationMemo": " <앞뒤 공백 글> "}]


def test_e2e2_swagger_lines(client):
    spec = client.get("/api/openapi.json").json()
    cm = spec["paths"]["/api/ext/reservations/{reservationId}/consultation-memo"]["put"]
    assert "비울 수 없다" in cm["description"] and "KOS 는 상담 메모를 비울 수 없어요" in cm["responses"]["400"]["description"]
    det = spec["paths"]["/api/ext/reservations/{reservationId}"]["get"]
    assert "예약을 만든 직후" in det["description"] and "다시 부르면 된다" in det["description"]
