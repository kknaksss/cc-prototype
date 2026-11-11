"""SPEC-008 §3.5 · §6.5 `POST /api/ext/reservations` — T17 ~ T22. 이름 · 이메일 · id 는 지어낸 값."""

import pytest

from tests.ext_env import H_CHARTY, H_LINKY, make_ext_env, run
from tests.fake_kos import SYSTEM, ZONE, kst, visitor

URL = "/api/ext/reservations"
START = "2026-10-21T15:00:00+09:00"
EMAIL = "a@example.com"


@pytest.fixture
def env(tmp_path):
    return make_ext_env(tmp_path, menu=False)


def post(cl, headers=H_LINKY, **kw):
    body = {"name": "고객", "email": EMAIL, "start": START}
    body.update(kw)
    return cl.post(URL, json=body, headers=headers)


def sent(fake, name):
    return [b for p, b in fake.calls if p.endswith("/" + name)]


def events(c, type_=None):
    with c.repo.tx() as tx:
        return tx.events(type_)


def found(fake, *vs):
    fake.visitors_page = {"count": len(vs), "data": list(vs)}


def code(r):
    return r.json()["error"]["code"]


# ------------------------------------------------------------------ T17 예약 1명 · 행위자
def test_t17_existing_customer_and_actor(env):
    c, fake, cl = env
    found(fake, {**visitor("vis-1", name="고객"), "email": EMAIL})
    r = post(cl, memo="메모 1")
    assert r.status_code == 200, r.text
    body = sent(fake, "reserve")[-1]
    o = body["occupiedResources"][0]
    assert body["visitorId"] == "vis-1" and body["zoneId"] == ZONE and body["reservationAssignee"]["id"] == SYSTEM
    assert o["reservationGroup"]["reservationGroupId"] == "grp-1" and body["reservationMemo"] == "메모 1"
    assert o["reservationTime"] == {"startDateTimeUtc": "2026-10-21T06:00:00.000Z", "endDateTimeUtc": "2026-10-21T06:30:00.000Z"}
    with c.repo.tx() as tx:
        cust = tx.con.execute("SELECT id FROM customer WHERE kos_id = 'vis-1'").fetchone()["id"]
        rid = tx.reservation_id_of("rsv-new-1")
    assert r.json() == {"reservationId": rid, "customerId": cust}
    ev = events(c, "resv_create")[-1]
    assert ev["actor"] == "ext:linky" and ev["payload"]["newCustomer"] is False
    assert sent(fake, "find-duplicated-visitor") == []
    # KOS 거절 — kos_rejected 줄 actor 도 ext:<연동처>
    fake.resv_fail["reserve"] = (400, {"className": "InvalidRequestException",
                                       "errorProperties": [{"key": "startDateTime", "reason": "NotAvailable"}]})
    r = post(cl, headers=H_CHARTY)
    assert (r.status_code, code(r)) == (409, "kos_rejected")
    assert events(c, "kos_rejected")[-1]["actor"] == "ext:charty"


# ------------------------------------------------------------------ T18 예약 0명 → 새 고객
def test_t18_new_customer(env):
    c, fake, cl = env
    found(fake)
    r = post(cl, name=" 새 고객 ", email=" New@Example.com ", memo="  ")
    assert r.status_code == 200, r.text
    assert sent(fake, "find-duplicated-visitor")[-1] == {"name": "새 고객", "email": "New@Example.com"}
    assert sent(fake, "create-visitor")[-1] == {"name": "새 고객", "email": "New@Example.com"}
    assert "reservationMemo" not in sent(fake, "reserve")[-1]  # 공백뿐인 메모는 보내지 않는다
    names = [p.rsplit("/", 1)[-1] for p, _ in fake.calls]
    assert names.index("find-duplicated-visitor") < names.index("create-visitor") < names.index("reserve")
    with c.repo.tx() as tx:
        new = tx.con.execute("SELECT id FROM customer WHERE kos_id = 'vis-new-1'").fetchone()["id"]
    assert r.json()["customerId"] == new
    assert events(c, "resv_create")[-1]["payload"]["newCustomer"] is True


# ------------------------------------------------------------------ T19 2명 · 중복 검사 걸림
def test_t19_ambiguous_and_duplicated(env):
    c, fake, cl = env
    found(fake, {**visitor("vis-1", name="고객"), "email": EMAIL}, {**visitor("vis-2", name="고객"), "email": EMAIL})
    r = post(cl)
    assert r.status_code == 409 and r.json() == {"error": {"code": "customer_ambiguous", "message": "고객을 특정할 수 없어요"}}
    found(fake)  # 0명 — 그런데 KOS 중복 검사에 걸림(같은 이메일 고객)
    fake.visitors["vis-1"]["email"] = EMAIL
    r = post(cl)
    assert r.status_code == 409 and r.json() == {"error": {"code": "customer_ambiguous", "message": "고객을 특정할 수 없어요"}}
    assert sent(fake, "reserve") == [] and sent(fake, "create-visitor") == []
    assert "duplicated_visitor" not in r.text and "candidate" not in r.text


# ------------------------------------------------------------------ T20 예약 그룹 설정
@pytest.mark.parametrize("case", ["empty", "absent", "no_zone", "unknown"])
def test_t20_not_configured(tmp_path, case):
    gid = {"empty": "", "unknown": "grp-x"}.get(case, "grp-1")
    c, fake, cl = make_ext_env(tmp_path, menu=False, kos_ext_reservation_group_id=gid)
    with c.repo.tx() as tx:
        if case == "absent":
            tx.con.execute("UPDATE reservation_group SET present = 0 WHERE kos_id = 'grp-1'")
        if case == "no_zone":
            tx.con.execute("UPDATE reservation_group SET capacities = '[]' WHERE kos_id = 'grp-1'")
    n = len(fake.calls)
    r = post(cl)
    assert (r.status_code, code(r)) == (503, "ext_not_configured")
    assert len(fake.calls) == n  # KOS 호출 0번


# ------------------------------------------------------------------ T21 정원 · KOS 실패
def test_t21_slot_full_and_kos_failure(env):
    c, fake, cl = env
    found(fake, {**visitor("vis-1", name="고객"), "email": EMAIL})
    for i in range(3):
        fake.add_resv(f"full-{i}", f"vis-f{i}", start=kst(15))
    c.kos.resv.invalidate("2026-10-21")
    run(c.resv.board("2026-10-21"))
    r = post(cl)
    assert (r.status_code, code(r)) == (409, "slot_full")
    assert sent(fake, "reserve") == []
    r = post(cl, start="2026-10-21T16:00:00+09:00")
    assert r.status_code == 200
    fake.fail_paths["reserve"] = 503
    r = post(cl, start="2026-10-21T16:30:00+09:00")
    assert (r.status_code, code(r)) == (502, "kos_unavailable") and "step" not in r.json()["error"]
    del fake.fail_paths["reserve"]
    fake.fail_paths["get-visitors"] = 503
    assert code(post(cl)) == "kos_unavailable"


# ------------------------------------------------------------------ T22 요청 칸
def test_t22_request_fields(env):
    c, fake, cl = env
    n = len(fake.calls)
    for extra in ({"groupId": 1}, {"zoneId": 1}, {"assigneeStaffId": 1}, {"counselorStaffId": 1}, {"funnelId": 1}):
        r = post(cl, **extra)
        assert (r.status_code, code(r)) == (400, "invalid_request"), extra
    for kw in ({"start": "내일 3시"}, {"start": ""}, {"name": "  "}, {"email": ""}, {"start": None}):
        r = post(cl, **kw)
        assert (r.status_code, code(r)) == (400, "invalid_request"), kw
    r = cl.post(URL, json={"name": "고객", "email": EMAIL}, headers=H_LINKY)
    assert code(r) == "invalid_request"
    assert len(fake.calls) == n


@pytest.mark.parametrize("resp", [{"count": 0}, {"data": None}, {"data": {"x": 1}}, {}])
def test_reserve_search_bad_shape_502_no_create(env, resp):
    """수정 1 W1 — 이름 검색 모양 오류면 「새 고객」 갈래로 가지 않는다(create-visitor · reserve 0번)."""
    c, fake, cl = env
    fake.visitors_page = resp
    r = post(cl)
    assert (r.status_code, code(r)) == (502, "kos_unavailable")
    assert sent(fake, "find-duplicated-visitor") == [] and sent(fake, "create-visitor") == [] and sent(fake, "reserve") == []
