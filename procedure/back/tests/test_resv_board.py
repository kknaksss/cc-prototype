"""WORK-007 WP-BE1 — 예약 사본 · 스케줄 표(SPEC-005 §3 · §4.2 · §5.1 ~ §5.4 · §5.9 · §7.2). KOS = 가짜(WP-KOS K1 모양)."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.container import build_container
from app.domain.clock import Clock
from app.domain.reservation_rules import axis, capacity_label, lines, payment_required_count, purchase_amount, state_of
from app.kos.client import KosClient, KosError, _error_of
from app.kos.runtime import KosRuntime
from app.repository.db import RESV_SCHEMA, SCHEMA, Database
from tests.fake_kos import ZONE, ZONE2, FakeKos, kos_settings, kst, rtask

T0 = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)  # KST 수요일 11:00
DAY = "2026-10-21"


@pytest.fixture
def env(tmp_path):
    fake = FakeKos()
    clock = Clock()
    clock.set(T0)
    s = kos_settings(tmp_path)
    c = build_container(s, clock)
    c.kos = KosRuntime(s, c.repo, clock, c.hub.publish, client=KosClient(s, c.repo, clock, transport=fake.transport()))
    mono = [1000.0]
    c.kos.resv.mono = lambda: mono[0]
    asyncio.run(c.kos.startup())
    return c, fake, mono


def run(coro):
    return asyncio.run(coro)


def board(c, day=DAY):
    return run(c.resv.board(day)).model_dump()


def count(fake, name):
    return fake.paths().count(name)


# ------------------------------------------------------------------ 1시간 목록
def test_master_lists(env):
    c, fake, _ = env
    with c.repo.tx() as tx:
        zones = tx.zones()
        groups = {g.kos_id: g for g in tx.resv_groups()}
        rooms = {r.kos_id: r.zone_kos_id for r in tx.rooms()}
        funnels = tx.funnel_codes()
        etc = tx.etc_task_defs()
    assert [(z.kos_id, z.is_default) for z in zones] == [(ZONE, True), (ZONE2, False)]
    assert groups["grp-1"].capacities == [{"zoneKosId": ZONE, "capacity": 3}]  # 꺼진 구역은 뺀다
    assert groups["grp-3"].capacities == [{"zoneKosId": ZONE, "capacity": 3}, {"zoneKosId": ZONE2, "capacity": 3}]
    wed = groups["grp-1"].timetable["wednesday"]
    got = (wed["enabled"], wed["start"], wed["end"], wed["breakStart"], wed["breakEnd"])
    assert got == (True, "10:00", "20:00", "13:00", "14:00")
    assert groups["grp-1"].timetable["sunday"]["enabled"] is False
    assert rooms["room-b1"] == ZONE2 and rooms["room-1"] == ZONE  # 다른 구역 방 = 같은 room 사본
    body = next(b for p, b in fake.calls if p.endswith("get-reservation-groups"))
    assert body == {"deleted": False, "zoneIds": [ZONE, ZONE2]}
    rooms_bodies = [b for p, b in fake.calls if p.endswith("get-rooms")]
    assert rooms_bodies == [{"zoneId": ZONE}, {"zoneId": ZONE2}]  # 4층(시술 현황) + 다른 구역 1번
    assert [f.kos_id for f in funnels] == ["fn-1", "fn-2"] and ("etc-room", "방 배정", False) in etc


def test_master_failure_recorded_and_others_kept(env):
    c, fake, _ = env
    fake.resv_fail = {"get-codes": (503, {})}
    run(c.kos.master_once())
    with c.repo.tx() as tx:
        ok, err = tx.sync_state("resv_master")
        assert err and "funnels" in err and len(tx.resv_groups()) == 3


# ------------------------------------------------------------------ 하루 조회 · 카드 · 칸
def test_day_query_body_and_cards(env):
    c, fake, _ = env
    fake.add_resv("s1", start=kst(10))
    fake.add_resv("s2", "vis-2", resources=[("grp-1", kst(11), 30), ("grp-2", kst(12), 60)], name="둘 묶음")
    fake.add_resv("s3", "vis-3", grp="grp-x", start=kst(15))  # 사본에 없는 그룹
    b = board(c)
    body = next(x for p, x in fake.calls if p.endswith("get-schedules-for-reservation"))
    assert body == {"baseDateUtc": "2026-10-20T15:00:00.000Z", "reservationGroupIds": ["grp-1", "grp-2", "grp-3"],
                    "zoneIds": [ZONE, ZONE2]}
    by = {(x["customer"]["name"], x["resourceIndex"]): x for x in b["cards"]}
    assert len(b["cards"]) == 4  # 묶음당 한 장
    two = by[("둘 묶음", 1)]
    assert two["start"] == "2026-10-21T12:00:00+09:00" and two["end"] == "2026-10-21T13:00:00+09:00"
    lost = [x for x in b["cards"] if x["groupId"] is None]
    assert len(lost) == 1 and b["columns"][-1] == {"groupId": None, "title": "그룹 없음", "order": 4, "intervalMinutes": 30,
                                                   "count": 1, "capacities": [], "open": []}
    cols = {x["title"]: x for x in b["columns"]}
    assert cols["일본"]["count"] == 2 and cols["리프팅"]["count"] == 1  # 예약 수(묶음 수 아님)
    assert cols["일본"]["open"] == [{"start": "10:00", "end": "13:00"}, {"start": "14:00", "end": "20:00"}]
    assert [len(x["capacities"]) for x in b["columns"][:3]] == [1, 1, 2]
    assert b["axis"] == {"start": "10:00", "end": "20:00"} and b["isToday"] and b["clinic"] is not None
    assert b["notices"][0]["content"] == "공지 예시" and b["requests"] == []
    assert b["zones"][0]["isDefault"] and b["sync"]["lastError"] is None and b["sync"]["lastOkAt"]


def test_customer_copy_has_gender_and_present_flag(env):
    c, fake, mono = env
    fake.add_resv("s1", gender="MALE")
    board(c)
    with c.repo.tx() as tx:
        r = tx.reservations(DAY)[0]
        assert tx.customer(r.customer_id).gender == "MALE"
        assert r.resources[0]["startAt"] == "2026-10-21T02:00:00+00:00"  # 밀리초 없는 KOS 시각도 파싱해 저장
    fake.resv.clear()
    mono[0] += 11
    board(c)
    with c.repo.tx() as tx:
        assert tx.reservations(DAY) == [] and len(tx.reservations(DAY, present_only=False)) == 1


def test_moved_to_other_day(env):
    c, fake, mono = env
    x = fake.add_resv("s1")
    board(c)
    x["occupiedResources"][0]["reservationTime"] = {"startDateTimeUtc": "2026-10-22T02:00:00Z",
                                                    "endDateTimeUtc": "2026-10-22T02:30:00Z"}
    run(c.resv.board("2026-10-22"))
    with c.repo.tx() as tx:
        assert tx.reservations("2026-10-22")[0].kos_id == "s1" and tx.reservations(DAY) == []


def test_state_table():
    assert state_of("CANCELED", "PROCEDURE") == ("canceled", None)
    assert state_of("NO_SHOW", "RESERVED") == ("noshow", None)
    table = {"RESERVED": ("reserved", None), "RECEPTION": ("reception", None),
             "CONSULTATION_WAITING": ("consultation", "waiting"), "CONSULTATION": ("consultation", "doing"),
             "PROCEDURE_WAITING": ("procedure", "waiting"), "PROCEDURE": ("procedure", "doing"),
             "PROCEDURE_DONE": ("home", "waiting"), "COMPLETED": ("home", "done"),
             "FLOW_STATUS_UNSPECIFIED": ("reserved", None), None: ("reserved", None)}
    for flow, want in table.items():
        assert state_of("IN_PROGRESS", flow) == want


def test_counts_exclude_canceled_noshow(env):
    c, fake, _ = env
    fake.add_resv("s1", start=kst(10))
    fake.add_resv("s2", "vis-2", start=kst(10), status="CANCELED")
    fake.add_resv("s3", "vis-3", start=kst(10), status="NO_SHOW")
    fake.add_resv("s4", "vis-4", start=kst(10, 30), flow="CONSULTATION", status="IN_PROGRESS")
    b = board(c)
    assert b["counts"] == {"total": 2, "reserved": 1, "reception": 0, "consultation": 1, "procedure": 0, "home": 0,
                           "canceled": 1, "noshow": 1}
    assert b["columns"][0]["count"] == 2
    assert {x["state"]["main"]: x["draggable"] for x in b["cards"]} == {
        "reserved": True, "canceled": False, "noshow": False, "consultation": False}


def test_axis_rules():
    tt = {"wednesday": {"enabled": True, "start": "10:00", "end": "20:00"}}
    off = {"wednesday": {"enabled": False}}
    d = datetime(2026, 10, 21).date()
    assert axis([tt, off], d, []) == ("10:00", "20:00")
    assert axis([off], d, []) is None  # 모든 그룹이 쉬는 요일
    assert axis([tt], d, [(9 * 60 + 15, 9 * 60 + 45), (20 * 60, 20 * 60 + 40)]) == ("09:00", "21:00")  # 축 밖 예약 → 늘림
    assert lines(("09:30", "12:00"), 60) == [540, 600, 660]  # 축 시작을 간격으로 내림(r1 W2) — 09:00 · 10:00 · 11:00
    assert lines(("09:30", "11:00"), 30) == [570, 600, 630] and lines(("09:45", "10:30"), 15)[0] == 585
    assert capacity_label([]) == "- 명" and capacity_label([("4층", 3)]) == "3명"
    assert capacity_label([("4층", 3), ("미사용", 3)]) == "4층 3 · 미사용 3명"


def test_sunday_no_axis(env):
    c, _, _ = env
    b = board(c, "2026-10-25")  # 일요일 — 데모 그룹 모두 꺼짐
    assert b["axis"] is None and b["rows"] == [] and b["slots"] == []


# ------------------------------------------------------------------ 정원(§5.4)
def test_slots_full_per_zone_and_plus(env):
    c, fake, _ = env
    for i in range(3):
        fake.add_resv(f"a{i}", f"v{i}", start=kst(10))  # 일본 10:00 4층 3/3
    fake.add_resv("b1", "vb", grp="grp-3", start=kst(10), minutes=15)
    for i in range(3):
        fake.add_resv(f"c{i}", f"vc{i}", grp="grp-3", start=kst(10, 15), minutes=15)  # 제모 10:15 4층 꽉 · 미사용 자리
    b = board(c)
    zid = {z["title"]: z["zoneId"] for z in b["zones"]}
    gid = {x["title"]: x["groupId"] for x in b["columns"]}
    slot = {(s["groupId"], s["zoneId"], s["start"][11:16]): s for s in b["slots"]}
    row = {(r["groupId"], r["start"][11:16]): r["plusAllowed"] for r in b["rows"]}
    assert slot[(gid["일본"], zid["4층"], "10:00")]["full"] and slot[(gid["일본"], zid["4층"], "10:00")]["count"] == 3
    assert row[(gid["일본"], "10:00")] is False and row[(gid["일본"], "10:30")] is True  # 켜진 구역 하나 — 꽉 참 = [+] 없음
    assert slot[(gid["제모"], zid["4층"], "10:15")]["full"] and not slot[(gid["제모"], zid["미사용"], "10:15")]["full"]
    assert row[(gid["제모"], "10:15")] is True  # 하나라도 자리 있으면 [+]
    assert (gid["일본"], zid["미사용"], "10:00") not in slot  # 꺼진 구역 슬롯 없음
    assert all(r["groupId"] is not None for r in b["rows"])  # 「그룹 없음」 줄 없음
    assert len([r for r in b["rows"] if r["groupId"] == gid["제모"]]) == 40  # 15분 × 10시간


def test_slot_missing_is_null_not_full(env):
    c, fake, _ = env
    fake.resv_fail = {"get-reservation-slots-by-groups": (500, {})}
    fake.add_resv("s1")
    b = board(c)
    assert b["cards"] and all(s["capacity"] is None and s["full"] is False for s in b["slots"])
    assert all(r["plusAllowed"] for r in b["rows"])
    assert "정원" in b["sync"]["lastError"]  # 슬롯 실패해도 예약은 보인다


# ------------------------------------------------------------------ 캐시 · 실패(§4.2)
def test_cache_10s_and_lock(env):
    c, fake, mono = env
    board(c)
    board(c)
    assert count(fake, "get-schedules-for-reservation") == 1
    mono[0] += 9.9
    board(c)
    assert count(fake, "get-schedules-for-reservation") == 1
    mono[0] += 0.2
    board(c)
    assert count(fake, "get-schedules-for-reservation") == 2

    async def two():
        mono[0] += 20
        await asyncio.gather(c.resv.board(DAY), c.resv.board(DAY))

    run(two())
    assert count(fake, "get-schedules-for-reservation") == 3  # 같은 날짜 동시 = 한 번
    c.kos.resv.invalidate(DAY)
    board(c)
    assert count(fake, "get-schedules-for-reservation") == 4


def test_day_failure_keeps_copy(env):
    c, fake, mono = env
    fake.add_resv("s1")
    ok = board(c)
    fake.resv_fail = {"get-schedules-for-reservation": (503, {"className": "Boom"})}
    mono[0] += 11
    b = board(c)
    assert b["sync"]["lastError"] == "HTTP 503 Boom" and b["sync"]["lastOkAt"] == ok["sync"]["lastOkAt"]
    assert len(b["cards"]) == 1  # 마지막 사본 그대로
    fake.resv_fail = {"get-schedules-for-reservation": (200, {"data": {"x": 1}})}  # 2xx 인데 배열 아님 = 실패
    mono[0] += 11
    assert board(c)["sync"]["lastError"] == "예약 응답 형식" and len(board(c)["cards"]) == 1


def test_bad_date_400(env):
    from app.domain.errors import BadRequest

    c, _, _ = env
    with pytest.raises(BadRequest):
        run(c.resv.board("2026/10/21"))


def test_no_kos_board_from_copy(tmp_path):
    from app.container import build_container

    c = build_container(kos_settings(tmp_path, kos_zone_id=""))
    assert c.kos is None
    b = run(c.resv.board(None))
    assert b.cards == [] and b.sync.lastError == "KOS 설정이 비어 있어요"


# ------------------------------------------------------------------ 수납 필요 · 금액(§5.9)
def test_payment_required_room_task_link(env):
    c, fake, _ = env
    room = {"id": "room-1", "zoneId": ZONE, "title": "A-룸1", "order": 1}
    tasks = [rtask(1, paid=True), rtask(2, "PROCEDURE", "CANCELED", paid=True),
             rtask(3, "ETCETERA", "READY", room=room, paid=True, title="방 배정"),
             rtask(4, "ETCETERA", "NOT_STARTED", paid=True, title="시트팩")]
    fake.add_resv("s1", flow="PROCEDURE_DONE", status="IN_PROGRESS", tasks=tasks, purchases=["pur-1"])
    fake.purchases["pur-1"] = {"id": "pur-1", "items": [{"priceV2": {"amount": {"value": 10000, "currency": "KRW"}}},
                                                       {"priceV2": {"amount": {"value": 5000, "currency": "KRW"}}}],
                               "transactions": [{"status": "APPROVED", "price": {"value": 7000, "currency": "KRW"}},
                                                {"status": "APPROVED", "price": {"value": 1000}, "canceledRefId": "t0"},
                                                {"status": "PENDING", "price": {"value": 99}}]}
    b = board(c)
    # 1(시술) + 4(방 없는 ETCETERA) = 2 · 취소 · 「방 배정」 뺌 — visit 사본 없음 = 호출 0
    assert b["cards"][0]["paymentRequiredCount"] == 2
    item = b["clinic"]["items"][0]
    assert item["paymentRequiredCount"] == 2 and item["amount"] == {"total": 15000, "paid": 7000, "currency": "KRW"}
    called = [{"type": "ETCETERA", "sequence": 3, "roomKosId": "room-1", "paymentRequired": True, "status": "READY"}]
    assert payment_required_count(called, {3}) == 1 and payment_required_count(called, set()) == 0  # 호출됨 = 「방 배정」 아님


def test_payment_called_room_task_via_visit(env):
    """잇는 키 — visit.kos_id = reservation.kos_id · procedure.kos_sequence = task.sequence 가 ccc 호출에 있으면 수납 셈."""
    c, fake, _ = env
    from tests.helpers import seed_staff

    room = {"id": "room-1", "zoneId": ZONE, "title": "A-룸1", "order": 1}
    fake.add_resv("sch-x", flow="PROCEDURE_WAITING", status="IN_PROGRESS",
                  tasks=[rtask(1, "ETCETERA", "READY", room=room, paid=True, title="시트팩", assigned="2026-10-21T02:00:00Z")])
    assert board(c)["cards"][0]["paymentRequiredCount"] == 0
    staff = seed_staff(c.repo)
    with c.repo.tx() as tx:
        vid = tx.upsert("visit", "sch-x", {"flow_step": "PROCEDURE_WAITING", "present": True})
        pid = tx.upsert_procedure(vid, 1, {"title": "시트팩", "kind": "etc", "room_kos_id": "room-1"})
        tx.add_call(vid, "all", None, T0, 0, [pid])
    assert staff and run(c.resv.board(DAY)).cards[0].paymentRequiredCount == 1


def test_purchase_amount_none():
    assert purchase_amount([]) is None


def test_clinic_only_today_two_zones(env):
    c, fake, _ = env
    fake.add_resv("s1", start=kst(10), flow="RECEPTION", status="IN_PROGRESS")
    fake.add_resv("s2", "vis-2", grp="grp-3", start=kst(10), zone=ZONE2, flow="CONSULTATION", status="IN_PROGRESS")
    fake.add_resv("s3", "vis-3", start=kst(10), flow="COMPLETED", status="COMPLETED")
    fake.add_resv("s4", "vis-4", start=kst(10), flow="PROCEDURE", status="CANCELED")
    b = board(c)
    assert b["clinic"]["counts"] == {"all": 2, "reception": 1, "consultation": 1, "procedure": 0, "home": 0}
    zones = [i["zoneId"] for i in b["clinic"]["items"]]
    assert zones == sorted(zones) and len(set(zones)) == 2  # 구역 order 순
    assert board(c, "2026-10-22")["clinic"] is None


# ------------------------------------------------------------------ KosError.errorProperties(§4.4)
def test_error_properties_parsed():
    import httpx

    e = _error_of(httpx.Response(400, json={"className": "com.x.InvalidRequestException", "message": "secret-body",
                                            "errorProperties": [{"key": "visitorId", "reason": "NotFound", "value": "v-123"}]}))
    assert isinstance(e, KosError) and str(e) == "HTTP 400 InvalidRequestException" and e.name == "InvalidRequestException"
    assert e.error_properties == [{"key": "visitorId", "reason": "NotFound"}] and e.has("visitorId", "NotFound")
    assert "v-123" not in repr(e.error_properties)  # 값은 싣지 않는다


def test_rejected_messages():
    from app.service.kos_errors import rejected_message, to_domain

    def err(props=(), name="InvalidRequestException", status=400):
        return KosError(f"HTTP {status} {name}", status, name, list(props))

    assert rejected_message(err([{"key": "startDateTime", "reason": "NotAvailable"}])) == "같은 고객의 예약이 그 시간에 있어요"
    batch = [{"key": "occupiedResources[0].startDateTimeUtc", "reason": "NotAvailable"}]
    assert rejected_message(err(batch)) == "묶음 날짜가 서로 달라요"
    assert rejected_message(err(name="ReservationCapacityExceeded")) == "그 시간은 정원이 찼어요"
    assert rejected_message(err([{"key": "status", "reason": "NotAvailable"}])) == "지금 상태에서는 취소할 수 없어요"
    assert rejected_message(err([{"key": "x", "reason": "ReservationNotAllowedByPolicy"}])) == "예약 정책상 바꿀 수 없어요"
    assert rejected_message(err()) == "KOS 가 거절했어요 (InvalidRequestException)"
    assert (to_domain(err()).status, to_domain(err()).code) == (409, "kos_rejected")
    for e in (err(status=500), err(status=401), KosError("network ConnectError")):
        assert (to_domain(e).status, to_domain(e).code) == (502, "kos_unavailable")


# ------------------------------------------------------------------ 옛 DB 파일(§3.2 끝)
def test_old_db_gets_new_tables_and_column(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)  # 시술 현황 SCHEMA 만(예약 표 · customer.gender 없음)
    con.execute("INSERT INTO customer (kos_id, name) VALUES ('c-old', '옛 고객')")
    con.commit()
    assert "gender" not in {r[1] for r in con.execute("PRAGMA table_info(customer)")}
    con.close()
    Database(path)
    with sqlite3.connect(path) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        cols = {r[1] for r in con.execute("PRAGMA table_info(customer)")}
        rows = con.execute("SELECT kos_id, name, gender FROM customer").fetchall()
    for t in ("zone", "reservation_group", "reservation", "reservation_slot", "notice", "funnel_code", "etc_task_def",
              "identity_check", "questionnaire_history"):
        assert t in tables and f"CREATE TABLE IF NOT EXISTS {t} " in RESV_SCHEMA
    assert "gender" in cols and rows == [("c-old", "옛 고객", None)]


def test_procedure_board_unchanged_with_other_zone_rooms(env):
    """다른 구역 방 행이 늘어도 시술 현황 카드는 그대로(SPEC-005 §4.2)."""
    c, fake, _ = env
    run(c.kos.tick())
    snap = c.board.snapshot()
    assert [x.room.title for x in snap.cards] == ["A-룸1"]
    with c.repo.tx() as tx:
        assert any(r.zone_kos_id == ZONE2 for r in tx.rooms())


def test_today_refresh_helper(env):
    c, fake, mono = env
    run(c.resv.board("2026-10-22"))
    n = count(fake, "get-schedules-for-reservation")
    run(c.resv.ensure_today())
    assert count(fake, "get-schedules-for-reservation") == n + 1
    run(c.resv.ensure_today())
    assert count(fake, "get-schedules-for-reservation") == n + 1  # 10초 안 = 다시 안 부름
    mono[0] += timedelta(seconds=11).total_seconds()
    run(c.resv.ensure_today())
    assert count(fake, "get-schedules-for-reservation") == n + 2


def test_rows_align_to_interval_when_axis_extended(env):
    """축이 09:30 으로 늘어나도 60분 칸 줄은 09:00 · 10:00 …(자정 기준 경계 = move 의 간격 경계와 같다 · r1 W2)."""
    c, fake, _ = env
    fake.add_resv("early", start=kst(9, 30))  # 축 밖 → 09:30 까지 늘림
    b = board(c)
    assert b["axis"]["start"] == "09:30"
    gid = {x["title"]: x["groupId"] for x in b["columns"]}
    starts = [r["start"][11:16] for r in b["rows"] if r["groupId"] == gid["리프팅"]]
    assert starts[:2] == ["09:00", "10:00"]
    assert [r["start"][11:16] for r in b["rows"] if r["groupId"] == gid["일본"]][:2] == ["09:30", "10:00"]
