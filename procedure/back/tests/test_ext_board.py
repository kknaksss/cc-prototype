"""SPEC-008 0.4.0 · 0.4.3 §3.6 · §6.11 `GET /api/ext/reservations/board` — T54 ~ T58. 값은 지어낸 것."""

import asyncio
import json
from datetime import timedelta

import pytest

from tests.ext_env import H_LINKY, T0, make_ext_env, run
from tests.fake_kos import kst, rtask, z

URL = "/api/ext/reservations/board"
DAY = "2026-10-21"
FSC = "protos.schedule.event.FlowStepChanged"
ROW_KEYS = {"reservationId", "start", "end", "state", "customer", "receptionAt", "counselor", "roomTitle", "consultation",
            "firstConsultationWaitingAt"}


@pytest.fixture
def env(tmp_path):
    return make_ext_env(tmp_path, menu=False)


def ev(sid, step, at, version=1, etype=FSC):
    return {"scheduleId": sid, "version": version, "eventType": etype,
            "payload": json.dumps({"flowStep": step, "raisedDateTimeUtc": at.replace("Z", "123456Z")}),
            "raisedDateTimeUtc": at, "initiator": {"type": "ACCOUNT", "id": "acc-1"}}


def other(sid, version=9):
    return {"scheduleId": sid, "version": version, "eventType": "protos.schedule.consultation.events.ConsultationPlanned",
            "payload": json.dumps({"consultationId": "c-1"}), "raisedDateTimeUtc": "2026-10-21T01:00:00.000Z",
            "initiator": {"type": "INTERNAL_SYSTEM"}}


def hist_calls(fake, sid=None, since=0):
    return [b["scheduleId"] for p, b in fake.calls[since:] if p.endswith("/get-schedule-event-logs")
            and (sid is None or b["scheduleId"] == sid)]


def board(c, cl):
    c.kos.resv.invalidate(DAY)  # 사본을 가짜 KOS 지금 값으로(시험마다 단계를 바꾸므로)
    r = cl.get(URL, headers=H_LINKY)
    assert r.status_code == 200, r.text
    return r.json()


def row(b, rid):
    return next(x for x in b["reservations"] if x["reservationId"] == rid)


def rid_of(c, sid):
    with c.repo.tx() as tx:
        return tx.reservation_id_of(sid)


def wait_row(c, sid):
    with c.repo.tx() as tx:
        return tx.consult_waits([sid]).get(sid)


def later(c, minutes):
    c.clock.set(c.clock.now() + timedelta(minutes=minutes))


def add(fake, sid, flow="RECEPTION", status="IN_PROGRESS", hh=11, **kw):
    return fake.add_resv(sid, start=kst(hh), flow=flow, status=status, **kw)


# ------------------------------------------------------------------ T54 줄
def test_t54_rows(env):
    c, fake, cl = env
    fake.accounts.append({"id": "cs-1", "name": "<상담사>", "roleTags": ["COUNSELOR"], "activate": True})
    run(c.kos.master_once(force=True))
    two = add(fake, "s-two", hh=12, resources=[("grp-1", kst(12), 30), ("grp-2", kst(13), 60)],
              counselor={"id": "cs-1", "name": "<상담사>"},
              tasks=[rtask(1, "ETCETERA", room={"id": "room-1", "zoneId": "zone-4", "title": "A-룸1", "order": 1},
                           assigned="2026-10-21T03:00:00Z", title="방 배정"),
                     rtask(2, room={"id": "room-2", "zoneId": "zone-4", "title": "A-룸2", "order": 2},
                           assigned="2026-10-21T03:30:00Z")])
    two["receptionDateTimeUtc"] = "2026-10-21T02:50:00Z"
    add(fake, "s-cancel", flow="RESERVED", status="CANCELED", hh=10)
    add(fake, "s-noshow", flow="RESERVED", status="NO_SHOW", hh=10)
    home = add(fake, "s-home", flow="COMPLETED", status="COMPLETED", hh=9)
    home["receptionDateTimeUtc"] = "2026-10-21T00:05:00Z"
    add(fake, "s-before", flow="RESERVED", status="RESERVED", hh=12)
    b = board(c, cl)
    assert set(b) == {"date", "now", "sync", "partialErrors", "reservations"} and b["date"] == DAY
    rows = b["reservations"]
    assert len(rows) == 5 and all(set(x) == ROW_KEYS for x in rows)
    assert [x["reservationId"] for x in rows] == [rid_of(c, s) for s in ("s-home", "s-cancel", "s-noshow", "s-two",
                                                                          "s-before")]  # 시작 → id
    t = row(b, rid_of(c, "s-two"))
    assert t["start"] == "2026-10-21T12:00:00+09:00" and t["end"] == "2026-10-21T14:00:00+09:00"
    assert t["counselor"]["name"] == "<상담사>" and isinstance(t["counselor"]["staffId"], int)
    assert t["roomTitle"] == "A-룸2" and t["receptionAt"] == "2026-10-21T11:50:00+09:00"
    assert row(b, rid_of(c, "s-home"))["receptionAt"] == "2026-10-21T09:05:00+09:00"
    assert row(b, rid_of(c, "s-before"))["receptionAt"] is None
    assert row(b, rid_of(c, "s-cancel"))["state"]["main"] == "canceled"
    assert set(t["customer"]) == {"customerId", "name", "phoneticName", "gender", "nationality", "isNew"}
    with c.repo.tx() as tx:  # 코드 검수 r2 N2 — 고객 칸 값 = 사본(키 집합만이 아님)
        for sid in ("s-two", "s-home", "s-cancel"):
            r0 = tx.reservation(rid_of(c, sid))
            cu = tx.customer(r0.customer_id)
            got = row(b, r0.id)["customer"]
            assert isinstance(got["customerId"], int) and got["customerId"] == cu.id and got["name"] == cu.name != ""
            assert (got["phoneticName"], got["gender"], got["nationality"], got["isNew"]) == (
                cu.phonetic_name, cu.gender, cu.nationality, cu.is_new)


# ------------------------------------------------------------------ T55 상담 판정
def test_t55_consultation_same_as_staff(env):
    c, fake, cl = env
    add(fake, "s-wait", flow="CONSULTATION_WAITING")
    add(fake, "s-recv", flow="PROCEDURE_WAITING")
    add(fake, "s-add", flow="PROCEDURE")
    add(fake, "s-flag", flow="PROCEDURE_WAITING", consult=True)  # KOS consultationRequired 만
    add(fake, "s-cxl", flow="RESERVED", status="CANCELED")
    add(fake, "s-ns", flow="RESERVED", status="NO_SHOW")
    add(fake, "s-rsv", flow="RESERVED", status="RESERVED")
    board(c, cl)
    with c.repo.tx() as tx:
        tx.add_event(T0, "desk", "reception", None, {"reservationId": rid_of(c, "s-recv"), "endStep": "CONSULTATION_WAITING"})
        for s in ("s-add", "s-cxl", "s-ns", "s-rsv"):
            tx.add_event(T0, "desk", "consultation_add", None, {"reservationId": rid_of(c, s)})
    b = board(c, cl)
    want = {"s-wait": True, "s-recv": True, "s-add": True, "s-flag": False, "s-cxl": False, "s-ns": False, "s-rsv": False}
    for sid, v in want.items():
        rid = rid_of(c, sid)
        assert row(b, rid)["consultation"] is v, sid
        d = run(c.resv.detail(rid))
        assert (d.flow is not None and d.flow.consultation is not None) is v, sid  # 직원 상세와 같은 판정


# ------------------------------------------------------------------ T56 신선도 · 실패
def test_t56_freshness_and_failures(env):
    c, fake, cl = env
    add(fake, "s1", flow="RESERVED", status="RESERVED")
    c.kos.resv.invalidate(DAY)
    n = len(fake.calls)
    cl.get(URL, headers=H_LINKY)
    cl.get(URL, headers=H_LINKY)
    day_calls = [p for p, _ in fake.calls[n:] if p.endswith("/get-schedules-for-reservation")]
    assert len(day_calls) == 1  # 10초 캐시
    fake.resv_fail["get-schedules-for-reservation"] = (500, {})
    b = board(c, cl)
    assert b["sync"]["lastError"] and len(b["reservations"]) == 1  # 낡은 사본 그대로 · 200
    c.kos = None
    r = cl.get(URL, headers=H_LINKY)
    assert r.status_code == 200 and r.json()["sync"]["lastError"]


# ------------------------------------------------------------------ T57 처음 상담 대기 시각
def test_t57_found_earliest_and_frozen(env):
    c, fake, cl = env
    add(fake, "s1", flow="PROCEDURE_WAITING")
    fake.event_logs["s1"] = {"data": [
        ev("s1", "PROCEDURE_WAITING", "2026-10-21T02:40:00.5Z", 3),
        ev("s1", "CONSULTATION_WAITING", "2026-10-21T02:30:00.12Z", 4),  # 두 번째 대기(차례 섞임 · 소수 2자리)
        other("s1"), ev("s1", "RECEPTION", "2026-10-21T02:00:00.000Z", 1),
        ev("s1", "CONSULTATION_WAITING", "2026-10-21T02:10:00.123Z", 2)]}
    b = board(c, cl)
    rid = rid_of(c, "s1")
    assert row(b, rid)["firstConsultationWaitingAt"] == "2026-10-21T11:10:00+09:00"
    assert row(b, rid)["consultation"] is False  # 두 칸은 따로(KOS 웹에서만 지나간 대기)
    w = wait_row(c, "s1")
    assert w["source"] == "kos_event_log" and w["last_failed"] == 0 and w["first_at"]
    n = len(fake.calls)
    fake._resv_sch("s1")["flowStep"] = "COMPLETED"
    fake._resv_sch("s1")["reservation"]["status"] = "COMPLETED"
    for _ in range(3):
        later(c, 10)
        board(c, cl)
    assert hist_calls(fake, since=n) == []  # 굳음 — 귀가해도 0번


def test_t57_short_event_type_also_matches(env):
    c, fake, cl = env
    add(fake, "s1", flow="PROCEDURE")
    fake.event_logs["s1"] = {"data": [ev("s1", "CONSULTATION_WAITING", "2026-10-21T02:10:00Z", etype="FlowStepChanged")]}
    assert row(board(c, cl), rid_of(c, "s1"))["firstConsultationWaitingAt"] == "2026-10-21T11:10:00+09:00"


def test_t57_targets_are_after_rows(env):
    c, fake, cl = env
    add(fake, "s-rsv", flow="RESERVED", status="RESERVED")
    add(fake, "s-cxl", flow="RECEPTION", status="CANCELED")
    add(fake, "s-ns", flow="RESERVED", status="NO_SHOW")
    add(fake, "s-in", flow="RECEPTION")
    fake.event_logs = {s: {"data": [ev(s, "CONSULTATION_WAITING", "2026-10-21T02:10:00Z")]}
                       for s in ("s-rsv", "s-cxl", "s-ns", "s-in")}
    b = board(c, cl)
    assert hist_calls(fake) == ["s-in"]
    assert row(b, rid_of(c, "s-cxl"))["firstConsultationWaitingAt"] is None


def test_t57_events_a_b_c(env):
    c, fake, cl = env
    x = add(fake, "s1", flow="RECEPTION")
    b = board(c, cl)  # ⓐ 처음 봄 → 못 찾음
    assert hist_calls(fake, "s1") == ["s1"] and b["partialErrors"] == []
    w = wait_row(c, "s1")
    assert w["first_at"] is None and w["last_failed"] == 0 and w["wait_called"] == 0
    for _ in range(3):  # 사건 없이 · 시계를 30분 넘겨도
        later(c, 11)
        assert board(c, cl)["partialErrors"] == []
    assert len(hist_calls(fake, "s1")) == 1
    x["flowStep"] = "CONSULTATION_WAITING"  # ⓑ 대기를 새로 봄
    board(c, cl)
    board(c, cl)
    assert len(hist_calls(fake, "s1")) == 2 and wait_row(c, "s1")["wait_called"] == 1
    x["flowStep"] = "PROCEDURE_WAITING"
    board(c, cl)
    assert wait_row(c, "s1")["wait_called"] == 0 and len(hist_calls(fake, "s1")) == 2
    x["flowStep"] = "CONSULTATION_WAITING"  # 재진입 → 1번 더
    board(c, cl)
    board(c, cl)
    assert len(hist_calls(fake, "s1")) == 3
    x["flowStep"], x["reservation"]["status"] = "COMPLETED", "COMPLETED"  # ⓒ 귀가 → 1번
    fake.event_logs["s1"] = {"data": [ev("s1", "CONSULTATION_WAITING", "2026-10-21T02:20:00Z")]}
    b = board(c, cl)
    assert len(hist_calls(fake, "s1")) == 4 and wait_row(c, "s1")["final_tried"] == 1
    assert row(b, rid_of(c, "s1"))["firstConsultationWaitingAt"] == "2026-10-21T11:20:00+09:00"
    later(c, 30)
    board(c, cl)
    assert len(hist_calls(fake, "s1")) == 4


def test_t57_first_seen_in_waiting_covers_b(env):
    c, fake, cl = env
    add(fake, "s1", flow="CONSULTATION_WAITING")
    board(c, cl)
    board(c, cl)
    assert len(hist_calls(fake, "s1")) == 1 and wait_row(c, "s1")["wait_called"] == 1


def test_t57_home_not_found_then_frozen(env):
    c, fake, cl = env
    x = add(fake, "s1", flow="PROCEDURE")
    board(c, cl)
    x["flowStep"], x["reservation"]["status"] = "COMPLETED", "COMPLETED"
    board(c, cl)
    for _ in range(3):
        later(c, 10)
        board(c, cl)
    assert len(hist_calls(fake, "s1")) == 2  # ⓐ + ⓒ · 그 뒤 0


@pytest.mark.parametrize("how", ["5xx", "403", "not_list", "bad_payload"])
def test_t57_failure_retry_cap(env, how):
    c, fake, cl = env
    add(fake, "s1", flow="PROCEDURE")
    if how in ("5xx", "403"):
        fake.fail_paths["get-schedule-event-logs"] = 500 if how == "5xx" else 403
    else:
        bad = {"data": {"x": 1}} if how == "not_list" else {"data": [{**ev("s1", "CONSULTATION_WAITING", "2026-10-21T02:10:00Z"),
                                                                       "payload": "{깨짐"}]}
        fake.event_logs["s1"] = bad
    b = board(c, cl)
    assert row(b, rid_of(c, "s1"))["firstConsultationWaitingAt"] is None
    assert b["partialErrors"] == ["consultationHistory"] and wait_row(c, "s1")["last_failed"] == 1
    later(c, 4)
    board(c, cl)
    assert len(hist_calls(fake, "s1")) == 1  # 5분 안
    for i in range(1, 4):
        later(c, 5)
        board(c, cl)
        assert len(hist_calls(fake, "s1")) == 1 + i and wait_row(c, "s1")["retries"] == i
    for _ in range(5):
        later(c, 10)
        b = board(c, cl)
    assert len(hist_calls(fake, "s1")) == 4 and b["partialErrors"] == ["consultationHistory"]  # 1 + 3 에서 멈춤


def test_t57_home_failure_retried_by_d(env):
    """D-41 — 귀가 뒤 1번이 실패하면 실패 재시도가 받는다(귀가 사건으로는 다시 안 부름)."""
    c, fake, cl = env
    x = add(fake, "s1", flow="PROCEDURE")
    board(c, cl)  # ⓐ 못 찾음
    x["flowStep"], x["reservation"]["status"] = "COMPLETED", "COMPLETED"
    fake.fail_paths["get-schedule-event-logs"] = 500
    board(c, cl)  # ⓒ 실패
    board(c, cl)
    assert len(hist_calls(fake, "s1")) == 2
    del fake.fail_paths["get-schedule-event-logs"]
    later(c, 5)
    board(c, cl)
    assert len(hist_calls(fake, "s1")) == 3 and wait_row(c, "s1")["retries"] == 1


def test_t57_cap_ten_per_request(env):
    c, fake, cl = env
    sids = [f"s{i:02d}" for i in range(15)]
    for i, s in enumerate(sids):
        add(fake, s, flow="RECEPTION", hh=9 + i // 2)
    b = board(c, cl)
    assert len(hist_calls(fake)) == 10 and b["partialErrors"] == ["consultationHistory"]
    first = set(hist_calls(fake))
    n = len(fake.calls)
    b = board(c, cl)
    assert set(hist_calls(fake, since=n)) == set(sids) - first and b["partialErrors"] == []


def test_t57_cap_deferred_waiting_rows_reported(env):
    """D-39 넓힘 — 미뤄진 줄이 모두 「대기를 새로 봄」(행 있음 · 못 찾음)이어도 첫 응답에 consultationHistory."""
    c, fake, cl = env
    sids = [f"s{i:02d}" for i in range(15)]
    for i, s in enumerate(sids):
        add(fake, s, flow="RECEPTION", hh=9 + i // 2)
    board(c, cl)
    board(c, cl)  # 15줄 모두 행 있음 · 못 찾음
    for s in sids:
        fake._resv_sch(s)["flowStep"] = "CONSULTATION_WAITING"
    n = len(fake.calls)
    b = board(c, cl)
    assert len(hist_calls(fake, since=n)) == 10 and b["partialErrors"] == ["consultationHistory"]
    n = len(fake.calls)
    assert board(c, cl)["partialErrors"] == [] and len(hist_calls(fake, since=n)) == 5


def test_t57_overlapping_requests_call_once(env):
    c, fake, cl = env
    add(fake, "s1", flow="RECEPTION")
    board(c, cl)  # 사본만 채움(ⓐ 1번 · 못 찾음)
    fake._resv_sch("s1")["flowStep"] = "CONSULTATION_WAITING"
    c.kos.resv.invalidate(DAY)
    run(c.kos.resv.ensure(kst(0).date()))
    gate, seen, calls = asyncio.Event(), [], []
    real = c.ext._first_wait

    async def slow(kos_id):
        seen.append(wait_row(c, kos_id))  # 시도 예약 행이 KOS 호출보다 먼저 적혔나
        calls.append(kos_id)
        await gate.wait()
        return await real(kos_id)

    c.ext._first_wait = slow

    async def both():
        first = asyncio.create_task(c.ext.board())
        await asyncio.sleep(0)
        while not calls:
            await asyncio.sleep(0)
        second = await c.ext.board()  # 첫 요청이 부르는 중
        gate.set()
        return await first, second

    _, second = run(both())
    assert calls == ["s1"]  # 같은 일정 이력 1번
    assert seen[0]["last_failed"] == 1 and seen[0]["wait_called"] == 1
    r2 = next(x for x in second["reservations"] if x["reservationId"] == rid_of(c, "s1"))
    assert r2["firstConsultationWaitingAt"] is None and second["partialErrors"] == ["consultationHistory"]


def test_t57_yesterday_not_called_and_sum_bounded(env):
    c, fake, cl = env
    fake.add_resv("old", start=kst(11) - timedelta(days=1), flow="PROCEDURE", status="IN_PROGRESS")
    add(fake, "s1", flow="PROCEDURE")
    fake.fail_paths["get-schedule-event-logs"] = 500
    for _ in range(30):  # 30분 동안 1분에 2번(줄인 판 — 사건 규칙이라 호출은 board 수에 비례하지 않는다)
        later(c, 1)
        board(c, cl)
        board(c, cl)
    assert "old" not in hist_calls(fake) and len(hist_calls(fake, "s1")) <= 1 + 3


# ------------------------------------------------------------------ T58 비용 · 경로 차례
def test_t58_zero_kos_when_no_events(env):
    c, fake, cl = env
    add(fake, "s1", flow="PROCEDURE")
    fake.event_logs["s1"] = {"data": [ev("s1", "CONSULTATION_WAITING", "2026-10-21T02:10:00Z")]}
    add(fake, "s2", flow="PROCEDURE")  # 못 찾음 뒤 단계 그대로
    board(c, cl)
    n = len(fake.calls)
    r = cl.get(URL, headers=H_LINKY)  # 사본 신선 + 대상 줄 모두 굳음 또는 사건 없음
    assert r.status_code == 200 and [p for p, _ in fake.calls[n:]] == []


def test_t58_route_order(env):
    c, fake, cl = env
    r = cl.get(URL, headers=H_LINKY)
    assert r.status_code == 200 and "reservations" in r.json()
    assert cl.get(URL).status_code == 401
    assert z(T0)  # 시험 시계 그대로


# ------------------------------------------------------------------ 코드 검수 r1 W1 · W3
def test_w1_first_seen_home_covers_c(env):
    """W1(Q1) — 처음 봄이 이미 귀가면 ⓐ 1번이 ⓒ 몫을 겸한다(final_tried 1) → board 여러 번에도 이력 1번."""
    c, fake, cl = env
    add(fake, "s1", flow="COMPLETED", status="COMPLETED")
    for _ in range(4):
        later(c, 10)
        board(c, cl)
    assert len(hist_calls(fake, "s1")) == 1 and wait_row(c, "s1")["final_tried"] == 1


def test_w1_first_seen_home_overlapping_once(env):
    c, fake, cl = env
    add(fake, "s1", flow="COMPLETED", status="COMPLETED")
    c.kos.resv.invalidate(DAY)
    run(c.kos.resv.ensure(kst(0).date()))
    gate, calls = asyncio.Event(), []
    real = c.ext._first_wait

    async def slow(kos_id):
        calls.append(kos_id)
        await gate.wait()
        return await real(kos_id)

    c.ext._first_wait = slow

    async def both():
        first = asyncio.create_task(c.ext.board())
        while not calls:
            await asyncio.sleep(0)
        second = await c.ext.board()
        gate.set()
        await first
        return second

    run(both())
    c.ext._first_wait = real
    board(c, cl)
    assert calls == ["s1"] and hist_calls(fake, "s1") == ["s1"]


def test_w3_mixed_events_pick_order(env):
    """W3 — ⓐ · ⓑ · ⓒ · ⓓ 섞인 12줄 → 첫 board 10개의 집합 · 차례 · 남은 줄."""
    from app.domain.clock import to_db

    c, fake, cl = env
    plan = [("d1", "d", 5), ("d2", "d", 25), ("d3", "d", 15), ("d4", "d", 6),  # 줄 차례 = 앞(시작이 이른 줄)
            ("c1", "c", None), ("c2", "c", None), ("b1", "b", None), ("b2", "b", None),
            ("a1", "a", None), ("a2", "a", None), ("a3", "a", None), ("a4", "a", None)]
    flows = {"a": ("RECEPTION", "IN_PROGRESS"), "b": ("CONSULTATION_WAITING", "IN_PROGRESS"),
             "c": ("COMPLETED", "COMPLETED"), "d": ("PROCEDURE", "IN_PROGRESS")}
    now = c.clock.now()
    for i, (sid, kind, ago) in enumerate(plan):
        flow, status = flows[kind]
        fake.add_resv(sid, start=kst(9, i * 5), flow=flow, status=status)
        if kind != "a":
            with c.repo.tx() as tx:
                tx.put_consult_wait(sid, {"checked_at": to_db(now - timedelta(minutes=ago or 60)),
                                          "last_failed": int(kind == "d"), "retries": 0, "wait_called": 0,
                                          "final_tried": 0})
    b = board(c, cl)
    assert hist_calls(fake) == ["a1", "a2", "a3", "a4", "b1", "b2", "c1", "c2", "d2", "d3"]  # ⓐ→ⓑ→ⓒ→ⓓ(오래된 시도 먼저)
    assert b["partialErrors"] == ["consultationHistory"]
    rest = {"d1", "d4"}
    assert all(wait_row(c, s)["retries"] == 0 and wait_row(c, s)["last_failed"] == 1 for s in rest)
    n = len(fake.calls)
    board(c, cl)
    assert hist_calls(fake, since=n) == ["d4", "d1"]  # 남은 줄만 · 그다음 차례(d4 6분 > d1 5분)


def test_n1_board_reads_only_todays_events(env, monkeypatch):
    """코드 검수 r2 N1(T55 0.4.4) — 다른 날 예약의 reception · consultation_add 가 많아도 결과 같음 ·
    board 가 읽는 event_log = 그날 예약 id 조건 쿼리만(전체 읽기 `events()` 를 부르지 않음)."""
    from app.repository.repo import Tx

    c, fake, cl = env
    add(fake, "s-a", flow="PROCEDURE_WAITING")
    add(fake, "s-b", flow="PROCEDURE_WAITING", hh=12)
    fake.add_resv("s-old", start=kst(11) - timedelta(days=1), flow="PROCEDURE", status="IN_PROGRESS")
    run(c.resv.board("2026-10-20"))  # 어제 사본(다른 날 예약 id)
    base = board(c, cl)
    today = {rid_of(c, "s-a"), rid_of(c, "s-b")}
    old_rid = rid_of(c, "s-old")
    with c.repo.tx() as tx:
        tx.add_event(T0, "desk", "consultation_add", None, {"reservationId": rid_of(c, "s-a")})
        for rid in (old_rid, 9001, 9002, 9003):
            tx.add_event(T0, "desk", "reception", None, {"reservationId": rid, "endStep": "CONSULTATION_WAITING"})
            tx.add_event(T0, "desk", "consultation_add", None, {"reservationId": rid})
    asked = []
    real = Tx.events_for_reservations

    def spy(self, types, ids):
        asked.append((types, sorted(ids)))
        out = real(self, types, ids)
        assert {e["payload"]["reservationId"] for e in out} <= set(ids)  # 그날 예약 id 밖 줄 0
        return out

    def no_full_read(self, type_=None):
        raise AssertionError("board 가 event_log 전체를 읽음")

    monkeypatch.setattr(Tx, "events_for_reservations", spy)
    monkeypatch.setattr(Tx, "events", no_full_read)
    b = board(c, cl)
    monkeypatch.undo()
    assert asked == [(("reception", "consultation_add"), sorted(today))]
    with c.repo.tx() as tx:
        got = tx.events_for_reservations(("reception", "consultation_add"), sorted(today))
    assert {e["payload"]["reservationId"] for e in got} == {rid_of(c, "s-a")}  # 어제 · 없는 id 줄 0
    assert row(b, rid_of(c, "s-a"))["consultation"] is True and row(base, rid_of(c, "s-a"))["consultation"] is False
    assert row(b, rid_of(c, "s-b")) == row(base, rid_of(c, "s-b"))  # 다른 날 이벤트는 결과에 영향 0
    assert old_rid not in {x["reservationId"] for x in b["reservations"]}
