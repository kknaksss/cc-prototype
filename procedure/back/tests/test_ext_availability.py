"""SPEC-008 0.3.0 §6.6 `GET /api/ext/availability` — T32 ~ T37 · T42 · T43(가능 시간대 몫). id · 이름은 지어낸 값."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.clock import KST
from tests.ext_env import H_LINKY, ext_calls, make_ext_env, run
from tests.fake_kos import ZONE, ZONE2, group, visitor

URL = "/api/ext/availability"
TODAY, TOMORROW = "2026-10-21", "2026-10-22"  # 시험 시계 = 2026-10-21(수) KST 11:00
SUNDAY = "2026-10-25"
EMAIL = "a@example.com"
TOKEN_CALLS = {"exchange-token", "sign-in"}


def make(tmp_path, interval=30, caps=None, **kw):
    """기본 그룹 grp-1 = 간격 30 · 10:00 ~ 20:00 · 쉬는 시간 13:00 ~ 14:00 · 켜진 구역 둘(정원 3 · 3)."""
    c, fake, cl = make_ext_env(tmp_path, menu=False, startup=False, **kw)
    fake.groups[0] = group("grp-1", "일본", 1, interval, caps or {ZONE: 3, ZONE2: 3}, brk=True)
    run(c.kos.startup())
    return c, fake, cl


@pytest.fixture
def env(tmp_path):
    return make(tmp_path)


def get(cl, day=TOMORROW, headers=H_LINKY, **params):
    return cl.get(URL, params={"date": day, **params}, headers=headers)


def at(day: str, hhmm: str) -> str:
    return f"{day}T{hhmm}:00+09:00"


def starts(r) -> list[str]:
    return [s["start"][11:16] for s in r.json()["slots"]]


def seats(r) -> dict[str, int]:
    return {s["start"][11:16]: s["remainingSeats"] for s in r.json()["slots"]}


def kos_calls(fake, since=0) -> list[str]:
    return [p.rsplit("/", 1)[-1] for p, _ in fake.calls[since:] if p.rsplit("/", 1)[-1] not in TOKEN_CALLS]


def code(r):
    return r.json()["error"]["code"]


def set_now(c, day: str, hhmm: str) -> None:
    c.clock.set(datetime.fromisoformat(at(day, hhmm)).astimezone(UTC))


def copy_rows(c, day: str) -> list[tuple]:
    from app.domain.reservation_rules import day_range

    d0, d1 = day_range(datetime.fromisoformat(day).date())
    with c.repo.tx() as tx:
        return sorted((s.group_kos_id, s.zone_kos_id, s.start_at.astimezone(KST).strftime("%H:%M"), s.capacity,
                       s.reservation_count) for s in tx.slots(d0, d1))


# ------------------------------------------------------------------ T32 후보 시각 · 남은 자리
def test_t32_candidates_and_seats(env):
    c, fake, cl = env
    fake.slot_patch = {("grp-1", ZONE, "10:00"): {"capacity": 3, "reservationCount": 1},
                       ("grp-1", ZONE2, "10:00"): {"capacity": 3, "reservationCount": 3},  # 참 → A 몫만
                       ("grp-1", ZONE2, "10:30"): None,  # B 행 없음 → A 몫만
                       ("grp-1", ZONE, "11:00"): None, ("grp-1", ZONE2, "11:00"): None,  # 둘 다 행 없음 → 시각 없음
                       ("grp-1", ZONE, "11:30"): {"capacity": None}, ("grp-1", ZONE2, "11:30"): None,  # null · 없음 → 없음
                       ("grp-1", ZONE, "12:00"): {"capacity": 2, "reservationCount": 2},
                       ("grp-1", ZONE2, "12:00"): {"capacity": 3, "reservationCount": 4}}  # 둘 다 참 → 없음
    r = get(cl)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"date", "intervalMinutes", "slots"} and body["date"] == TOMORROW and body["intervalMinutes"] == 30
    assert all(set(s) == {"start", "remainingSeats"} for s in body["slots"])
    want = ["10:00", "10:30", "12:30", *[f"{h:02d}:{m:02d}" for h in range(14, 20) for m in (0, 30)]]
    assert starts(r) == want  # 13:00 · 13:30(쉬는 시간) · 20:00(구간 끝) 없음
    assert body["slots"][0]["start"] == at(TOMORROW, "10:00")
    got = seats(r)
    assert got["10:00"] == 2 and got["10:30"] == 3 and got["12:30"] == 6 and got["19:30"] == 6
    assert get(cl, SUNDAY).json() == {"date": SUNDAY, "intervalMinutes": 30, "slots": []}  # 휴무 요일


def test_t32_interval_15(tmp_path):
    c, fake, cl = make(tmp_path, interval=15)
    r = get(cl)
    assert r.json()["intervalMinutes"] == 15
    assert starts(r)[:3] == ["10:00", "10:15", "10:30"] and starts(r)[-1] == "19:45" and "12:45" in starts(r)
    assert "13:00" not in starts(r) and "13:45" not in starts(r) and "14:00" in starts(r)


# ------------------------------------------------------------------ T33 오늘 지난 시각
def test_t33_today_past_times(env):
    c, fake, cl = env
    set_now(c, TODAY, "14:10")
    assert starts(get(cl, TODAY))[0] == "14:30"
    set_now(c, TODAY, "14:30")
    assert starts(get(cl, TODAY))[0] == "15:00"
    set_now(c, TODAY, "11:00")
    assert starts(get(cl, TODAY))[0] == "11:30"


# ------------------------------------------------------------------ T34 날짜 검사
@pytest.mark.parametrize("day", ["2026-1-5", "20261105", "2026-10-20", "2027-01-20", "", "2026-W43-4", "2026-02-30"])
def test_t34_bad_date(env, day):
    c, fake, cl = env
    n = len(fake.calls)
    r = get(cl, day)
    assert (r.status_code, code(r)) == (400, "invalid_request") and r.json()["error"]["message"].startswith("date: ")
    assert kos_calls(fake, n) == []


def test_t34_missing_date_and_range_edges(env):
    c, fake, cl = env
    n = len(fake.calls)
    r = cl.get(URL, headers=H_LINKY)
    assert (r.status_code, code(r)) == (400, "invalid_request") and r.json()["error"]["message"].startswith("query.date:")
    assert kos_calls(fake, n) == []
    assert get(cl, TODAY).status_code == 200
    assert get(cl, "2027-01-19").status_code == 200  # 오늘 + 90일
    assert get(cl, "2027-01-20").status_code == 400  # 오늘 + 91일


# ------------------------------------------------------------------ T35 설정
@pytest.mark.parametrize("case", ["empty", "absent", "no_zone"])
def test_t35_not_configured(tmp_path, case):
    c, fake, cl = make(tmp_path, kos_ext_reservation_group_id="" if case == "empty" else "grp-1")
    with c.repo.tx() as tx:
        if case == "absent":
            tx.con.execute("UPDATE reservation_group SET present = 0 WHERE kos_id = 'grp-1'")
        if case == "no_zone":
            tx.con.execute("UPDATE reservation_group SET capacities = '[]' WHERE kos_id = 'grp-1'")
    n = len(fake.calls)
    r = get(cl)
    assert (r.status_code, code(r)) == (503, "ext_not_configured")
    assert kos_calls(fake, n) == []


# ------------------------------------------------------------------ T36 슬롯 새로 읽기
def test_t36_refresh_one_call_replaces_copy(env):
    c, fake, cl = env
    n = len(fake.calls)
    fake.slot_patch = {("grp-1", ZONE, "15:00"): {"capacity": 3, "reservationCount": 2}}
    r = get(cl)
    assert r.status_code == 200 and seats(r)["15:00"] == 4
    assert kos_calls(fake, n) == ["get-reservation-slots-by-groups"]  # 하루 예약 · 공지 · 금액 0번
    body = fake.calls[-1][1]
    assert sorted(body["reservationGroupIds"]) == ["grp-1", "grp-2", "grp-3"]
    assert body["startDateTimeUtc"] == "2026-10-21T15:00:00.000Z" and body["endDateTimeUtc"] == "2026-10-22T15:00:00.000Z"
    rows = copy_rows(c, TOMORROW)
    assert ("grp-1", ZONE, "15:00", 3, 2) in rows and ("grp-1", ZONE2, "15:00", 3, 0) in rows
    assert {g for g, *_ in rows} == {"grp-1", "grp-2", "grp-3"}
    before = rows
    for fail in ("5xx", "shape", "no_kos"):
        fake.slot_patch = {("grp-1", ZONE, "15:00"): {"capacity": 3, "reservationCount": 0}}
        if fail == "5xx":
            fake.fail_paths["get-reservation-slots-by-groups"] = 503
        elif fail == "shape":
            fake.fail_paths.clear()
            fake.slots_page = {"data": {"x": 1}}
        else:
            kos, c.kos = c.kos, None
        r = get(cl)
        assert (r.status_code, code(r)) == (502, "kos_unavailable"), fail
        assert copy_rows(c, TOMORROW) == before, fail  # 사본 그대로
    c.kos = kos


# ------------------------------------------------------------------ T37 예약과 같은 규칙
def found(fake):
    fake.visitors_page = {"count": 1, "data": [{**visitor("vis-1", name="고객"), "email": EMAIL}]}


def reserve(cl, start):
    return cl.post("/api/ext/reservations", json={"name": "고객", "email": EMAIL, "start": start}, headers=H_LINKY)


def test_t37_stale_full_copy_then_listed_then_reserved(env):
    c, fake, cl = env
    found(fake)
    full = {"capacity": 3, "reservationCount": 3}
    fake.slot_patch = {("grp-1", ZONE, "15:00"): full, ("grp-1", ZONE2, "15:00"): full}
    run(c.resv.board(TOMORROW))  # 직원 판이 읽어 둔 사본 — 15:00 「참」
    assert reserve(cl, at(TOMORROW, "15:00")).json()["error"]["code"] == "slot_full"
    fake.slot_patch = {("grp-1", ZONE, "15:00"): {"capacity": 3, "reservationCount": 2}}  # KOS 에서 자리 남
    r = get(cl)
    assert seats(r)["15:00"] == 4
    r = reserve(cl, at(TOMORROW, "15:00"))  # 곧바로 — 같은 사본을 본다
    assert r.status_code == 200, r.text


def test_t37_every_listed_time_reserves_and_unlisted_full_409(tmp_path):
    c, fake, cl = make(tmp_path, caps={ZONE: 1, ZONE2: 1})
    found(fake)
    full = {"capacity": 1, "reservationCount": 1}
    fake.slot_patch = {("grp-1", ZONE, "16:00"): full, ("grp-1", ZONE2, "16:00"): full,  # 둘 다 참
                       ("grp-1", ZONE, "17:00"): full, ("grp-1", ZONE2, "17:00"): None}  # A 참 · B 행 없음 → 목록에 없음
    r = get(cl)
    listed = [s["start"] for s in r.json()["slots"]]
    assert at(TOMORROW, "16:00") not in listed and at(TOMORROW, "17:00") not in listed and len(listed) == 16
    outs = [reserve(cl, s) for s in listed]
    assert [x.status_code for x in outs] == [200] * len(listed)
    assert all(x.json().get("error", {}).get("code") != "slot_full" for x in outs)
    r = reserve(cl, at(TOMORROW, "16:00"))  # 목록에 없는(모든 구역 참) 시각
    assert (r.status_code, code(r)) == (409, "slot_full")


# ------------------------------------------------------------------ T42 · T43 가능 시간대 몫
def test_t42_name_query_ignored_and_endpoint(env):
    c, fake, cl = env
    r = get(cl, name="<이름>", email=EMAIL)
    assert r.status_code == 200
    last = ext_calls(c)[-1]
    assert last["endpoint"] == "GET /api/ext/availability" and EMAIL not in repr(ext_calls(c))


def test_t43_availability_cost(env):
    c, fake, cl = env
    n = len(fake.calls)
    get(cl)
    get(cl, (datetime(2026, 10, 21) + timedelta(days=5)).date().isoformat())
    assert kos_calls(fake, n) == ["get-reservation-slots-by-groups"] * 2


# ------------------------------------------------------------------ 고침 1 W6 — 오류 갈래 경로마다 1줄
def test_w6_availability_no_runtime_502_zero_calls(env):
    c, fake, cl = env
    n = len(fake.calls)
    c.kos = None
    r = get(cl)
    assert (r.status_code, code(r)) == (502, "kos_unavailable") and kos_calls(fake, n) == []


@pytest.mark.parametrize("status", [400, 401, 500])
def test_w6_availability_kos_4xx_401_502(env, status):
    c, fake, cl = env
    fake.fail_paths["get-reservation-slots-by-groups"] = status
    r = get(cl)
    assert (r.status_code, code(r)) == (502, "kos_unavailable")


def test_w6_availability_post_405(env):
    c, fake, cl = env
    r = cl.post(URL, params={"date": TOMORROW}, headers=H_LINKY)
    assert (r.status_code, code(r)) == (405, "http_error") and r.headers["cache-control"] == "no-store"
