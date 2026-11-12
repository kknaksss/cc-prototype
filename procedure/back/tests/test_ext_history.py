"""SPEC-008 0.3.0 §6.7 · §6.8 과거 시술 · 예약 내역 — T38 ~ T43(+ 고침 1 W1 · W2 · W6). 이름 · 이메일 · id 는 지어낸 값."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.ext_env import H_LINKY, make_ext_env, run
from tests.fake_kos import DAY, kst, resv, rtask, visitor

VISITS, RESV = "/api/ext/customers/visits", "/api/ext/customers/reservations"
LOOKUP = "/api/ext/customers/lookup"
EMAIL = "a@example.com"
TOKEN_CALLS = {"exchange-token", "sign-in"}


@pytest.fixture
def env(tmp_path):
    c, fake, cl = make_ext_env(tmp_path, menu=False)
    found(fake)
    return c, fake, cl


def found(fake, *vids):
    vs = [{**visitor(v, name="고객"), "email": EMAIL} for v in (vids or ("vis-1",))]
    fake.visitors_page = {"count": len(vs), "data": vs}


def post(cl, url, name="고객", email=EMAIL, **extra):
    return cl.post(url, json={"name": name, "email": email, **extra}, headers=H_LINKY)


def code(r):
    return r.json()["error"]["code"]


def kos_calls(fake, since=0) -> list[str]:
    return [p.rsplit("/", 1)[-1] for p, _ in fake.calls[since:] if p.rsplit("/", 1)[-1] not in TOKEN_CALLS]


def hist(fake, sid, start, *, status="RESERVED", flow="RESERVED", tasks=None, **kw):
    x = resv(sid, "vis-1", start=start, status=status, flow=flow, tasks=tasks or [], **kw)
    fake.history.append(x)
    return x


def rows(c) -> tuple[int, int]:
    with c.repo.tx() as tx:
        return (tx.con.execute("SELECT COUNT(*) FROM customer").fetchone()[0],
                tx.con.execute("SELECT COUNT(*) FROM reservation").fetchone()[0])


def set_now(c, at: datetime) -> None:
    c.clock.set(at.astimezone(UTC))


# ------------------------------------------------------------------ T38 과거 시술
def test_t38_visits(env):
    c, fake, cl = env
    results = ["COMPLETED", "NO_SHOW", "CANCELED", "RESERVED", None]
    for i in range(1, 54):  # 지난 53(하루씩 앞)
        x = hist(fake, f"p-{i}", kst(10, day=DAY - timedelta(days=i)), status=results[i % 5] or "RESERVED",
                 tasks=[rtask(1, title=f"시술{i}"), rtask(2, "ETCETERA", title="방 배정"),
                        rtask(3, "ETCETERA", title="시트팩")])
        if results[i % 5] is None:
            del x["reservation"]["status"]
    hist(fake, "f-1", kst(15))  # 오늘 15:00 — 지금(11:00) 뒤
    hist(fake, "f-2", kst(10, day=DAY + timedelta(days=3)))
    nostart = hist(fake, "n-1", kst(10, day=DAY - timedelta(days=60)))
    nostart["occupiedResources"] = []
    nostart["reservation"]["startDateTime"] = None
    r = post(cl, VISITS)
    assert r.status_code == 200, r.text
    vs = r.json()["visits"]
    assert len(vs) == 50 and set(r.json()) == {"visits"}
    assert all(set(v) == {"date", "start", "result", "procedures"} for v in vs)
    assert vs[0]["start"] == "2026-10-20T10:00:00+09:00" and vs[0]["date"] == "2026-10-20"
    assert [v["start"] for v in vs] == sorted((v["start"] for v in vs), reverse=True)
    assert vs[-1]["date"] == (DAY - timedelta(days=50)).date().isoformat()
    want = {1: "noshow", 2: "canceled", 3: "other", 4: "other", 5: "completed"}
    assert [v["result"] for v in vs[:5]] == [want[i] for i in range(1, 6)]
    assert vs[0]["procedures"] == ["시술1", "시트팩"]  # 「방 배정」 ETCETERA 뺌 · 다른 ETCETERA 남음
    for leak in ("reservationMemo", "consultationMemo", "doctors", "resultRaw", "zoneTitle", "groupTitle",
                 "예약 메모", "가 원장"):
        assert leak not in r.text
    fake.history = [x for x in fake.history if x["id"].startswith("f-")]
    assert post(cl, VISITS).json() == {"visits": []}


# ------------------------------------------------------------------ T39 고객 갈래 · 실패
def test_t39_customer_branches_same_404_and_no_schedule_read(env):
    c, fake, cl = env
    before = rows(c)
    cases = [({"count": 0, "data": []}, "고객", EMAIL),
             ({"count": 1, "data": [{**visitor("vis-1", name="다른"), "email": EMAIL}]}, "고객", EMAIL),
             ({"count": 1, "data": [{**visitor("vis-1", name="고객"), "email": EMAIL}]}, "고객", "b@example.com"),
             ({"count": 1001, "data": [{**visitor("vis-1", name="고객"), "email": EMAIL}]}, "고객", EMAIL)]
    outs = set()
    for page, name, email in cases:
        fake.visitors_page = page
        for url in (LOOKUP, VISITS, RESV):
            n = len(fake.calls)
            r = post(cl, url, name, email)
            outs.add((r.status_code, r.content))
            assert "get-schedules-by-visitor" not in kos_calls(fake, n)
    assert len(outs) == 1 and outs.pop()[0] == 404
    found(fake, "vis-1", "vis-2")
    for url in (VISITS, RESV):
        n = len(fake.calls)
        r = post(cl, url)
        assert r.status_code == 409
        assert r.json() == {"error": {"code": "customer_ambiguous", "message": "고객을 특정할 수 없어요"}}
        assert kos_calls(fake, n) == ["get-visitors"]
    found(fake)
    for bad in ((503, {}), (200, {"data": {"x": 1}}), (200, {"data": None})):
        fake.resv_fail["get-schedules-by-visitor"] = bad
        for url in (VISITS, RESV):
            r = post(cl, url)
            assert (r.status_code, code(r)) == (502, "kos_unavailable"), (bad, url)
    assert rows(c) == before  # 고객 · 예약 사본에 쓰지 않음


def test_w1_empty_object_is_empty_list(env):
    """고침 1 W1 — 일정 응답 `{}`(data 키 없음) · `data: []` = 일정 없음 → 200 빈 목록."""
    c, fake, cl = env
    for resp in ({}, {"data": []}):
        fake.resv_fail["get-schedules-by-visitor"] = (200, resp)
        assert post(cl, VISITS).json() == {"visits": []}
        assert post(cl, RESV).json() == {"reservations": []}


def test_w6_name_search_failure_502_no_schedule_read(env):
    c, fake, cl = env
    fake.fail_paths["get-visitors"] = 503
    for url in (VISITS, RESV):
        n = len(fake.calls)
        r = post(cl, url)
        assert (r.status_code, code(r)) == (502, "kos_unavailable")
        assert "get-schedules-by-visitor" not in kos_calls(fake, n)


def test_w6_no_runtime_502(env):
    c, fake, cl = env
    c.kos = None
    for url in (VISITS, RESV):
        assert code(post(cl, url)) == "kos_unavailable"


def test_w6_wrong_method_405(env):
    c, fake, cl = env
    for url in (VISITS, RESV):
        r = cl.get(url, headers=H_LINKY)
        assert (r.status_code, code(r)) == (405, "http_error")


# ------------------------------------------------------------------ T40 예약 내역
def test_t40_reservations(env):
    c, fake, cl = env
    in_copy = fake.add_resv("today-1", "vis-1", start=kst(16), flow="RECEPTION")  # 오늘 일정 — 하루 조회로 사본에 들어감
    run(c.resv.board("2026-10-21"))
    with c.repo.tx() as tx:
        copy_id = tx.reservation_id_of("today-1")
    assert copy_id is not None
    hist(fake, "past-1", kst(10, day=DAY - timedelta(days=1)))  # 어제 — 빠짐
    hist(fake, "h-home", kst(10, day=DAY + timedelta(days=2)), flow="PROCEDURE_DONE")
    hist(fake, "h-cancel", kst(9, day=DAY + timedelta(days=1)), status="CANCELED", flow="RECEPTION")
    hist(fake, "h-noshow", kst(10, day=DAY + timedelta(days=1)), status="NO_SHOW")
    odd = hist(fake, "h-odd", kst(11, day=DAY + timedelta(days=1)), flow="SOMETHING_NEW")
    odd["occupiedResources"] = []  # 묶음 없음 → end null · 시작 = reservation.startDateTime
    before = rows(c)
    r = post(cl, RESV)
    assert r.status_code == 200, r.text
    out = r.json()["reservations"]
    assert set(r.json()) == {"reservations"}
    assert all(set(x) == {"reservationId", "date", "start", "end", "state"} for x in out)
    assert [(x["start"], x["state"], x["reservationId"]) for x in out] == [
        ("2026-10-21T16:00:00+09:00", "reception", copy_id),
        ("2026-10-22T09:00:00+09:00", "canceled", None),
        ("2026-10-22T10:00:00+09:00", "noshow", None),
        ("2026-10-22T11:00:00+09:00", "reserved", None),
        ("2026-10-23T10:00:00+09:00", "home", None)]
    assert out[0]["end"] == "2026-10-21T16:30:00+09:00" and out[0]["date"] == "2026-10-21"
    assert out[3]["end"] is None
    assert rows(c) == before  # 사본 행 늘지 않음
    for leak in ("예약 메모", "가 원장", "시스템", "grp-1", "today-1"):
        assert leak not in r.text
    assert in_copy["id"] == "today-1"
    fake.resv, fake.history = [], [x for x in fake.history if x["id"] == "past-1"]
    assert post(cl, RESV).json() == {"reservations": []}  # 지난 일정만


def test_t40_external_reservation_shows_its_id(env):
    c, fake, cl = env
    made = cl.post("/api/ext/reservations", json={"name": "고객", "email": EMAIL, "start": "2026-10-22T15:00:00+09:00"},
                   headers=H_LINKY)
    assert made.status_code == 200, made.text
    out = post(cl, RESV).json()["reservations"]
    assert [(x["reservationId"], x["start"]) for x in out] == [(made.json()["reservationId"], "2026-10-22T15:00:00+09:00")]


def test_w2_deleted_schedules_dropped_from_both(env):
    """고침 1 W2(코디 결정) — `deleted: true` 일정은 과거 시술 · 예약 내역 둘 다에서 뺀다."""
    c, fake, cl = env
    hist(fake, "gone-past", kst(10, day=DAY - timedelta(days=1)))["deleted"] = True
    hist(fake, "gone-next", kst(10, day=DAY + timedelta(days=1)))["deleted"] = True
    hist(fake, "live-past", kst(10, day=DAY - timedelta(days=2)))
    hist(fake, "live-next", kst(10, day=DAY + timedelta(days=2)))
    assert [v["date"] for v in post(cl, VISITS).json()["visits"]] == ["2026-10-19"]
    assert [x["date"] for x in post(cl, RESV).json()["reservations"]] == ["2026-10-23"]


# ------------------------------------------------------------------ T41 오늘 겹침
def test_t41_today_overlap(env):
    c, fake, cl = env
    hist(fake, "t-9", kst(9), status="COMPLETED", flow="COMPLETED")
    set_now(c, kst(12))
    assert [v["start"] for v in post(cl, VISITS).json()["visits"]] == ["2026-10-21T09:00:00+09:00"]
    assert [x["start"] for x in post(cl, RESV).json()["reservations"]] == ["2026-10-21T09:00:00+09:00"]


# ------------------------------------------------------------------ T42 요청 칸
@pytest.mark.parametrize("url", [VISITS, RESV])
def test_t42_request_fields(env, url):
    c, fake, cl = env
    n = len(fake.calls)
    for body in ({"name": "고객", "email": EMAIL, "x": 1}, {"name": "  ", "email": EMAIL}, {"name": "고객", "email": ""},
                 {"name": "고객"}):
        r = cl.post(url, json=body, headers=H_LINKY)
        assert (r.status_code, code(r)) == (400, "invalid_request"), body
    assert kos_calls(fake, n) == []


# ------------------------------------------------------------------ T43 KOS 비용
def test_t43_cost(env):
    c, fake, cl = env
    for url in (VISITS, RESV):
        n = len(fake.calls)
        assert post(cl, url).status_code == 200
        assert kos_calls(fake, n) == ["get-visitors", "get-schedules-by-visitor"]
        fake.visitors_page = {"count": 0, "data": []}
        n = len(fake.calls)
        assert post(cl, url).status_code == 404 and kos_calls(fake, n) == ["get-visitors"]
        found(fake, "vis-1", "vis-2")
        n = len(fake.calls)
        assert post(cl, url).status_code == 409 and kos_calls(fake, n) == ["get-visitors"]
        found(fake)


# ------------------------------------------------------------------ 고침 2 N1 — 일정 원소 모양 오류 = 502(원문 0)
@pytest.mark.parametrize("broken", ["reservation_str", "time_str", "title_num"])
def test_n1_broken_schedule_item_502(env, broken):
    c, fake, cl = env
    x = hist(fake, "bad-1", kst(10, day=DAY - timedelta(days=1)), tasks=[rtask(1, title="시술1")])
    y = hist(fake, "bad-2", kst(10, day=DAY + timedelta(days=1)))
    for sch in (x, y):
        if broken == "reservation_str":
            sch["occupiedResources"] = []
            sch["reservation"] = "RAW-RESV-TEXT"
        elif broken == "time_str":
            sch["occupiedResources"][0]["reservationTime"] = "RAW-TIME-TEXT"
    if broken == "title_num":
        x["tasks"][0]["title"] = 98765
    urls = (VISITS,) if broken == "title_num" else (VISITS, RESV)  # 작업 이름은 과거 시술에만 나간다
    for url in urls:
        r = post(cl, url)
        assert (r.status_code, code(r)) == (502, "kos_unavailable"), (broken, url)
        assert "RAW-" not in r.text and "98765" not in r.text


# ------------------------------------------------------------------ 고침 2 N2 — 경계 시각 · 일정 읽기 4xx · 401
def test_n2_start_equals_now_is_not_past(env):
    c, fake, cl = env
    hist(fake, "at-now", kst(13))
    set_now(c, kst(13))  # 시계 = 일정 시작 정각
    assert post(cl, VISITS).json() == {"visits": []}  # 「지금보다 앞」 아님
    assert [x["start"] for x in post(cl, RESV).json()["reservations"]] == ["2026-10-21T13:00:00+09:00"]


def test_n2_today_midnight_in_reservations(env):
    c, fake, cl = env
    hist(fake, "midnight", kst(0))  # 오늘 00:00 KST 정각
    hist(fake, "yesterday-late", kst(0) - timedelta(minutes=30))  # 어제 23:30 — 빠짐
    assert [x["start"] for x in post(cl, RESV).json()["reservations"]] == ["2026-10-21T00:00:00+09:00"]


@pytest.mark.parametrize("status", [400, 401, 404])
def test_n2_schedule_read_4xx_401_502(env, status):
    c, fake, cl = env
    fake.fail_paths["get-schedules-by-visitor"] = status
    for url in (VISITS, RESV):
        assert (post(cl, url).status_code, code(post(cl, url))) == (502, "kos_unavailable"), (status, url)
