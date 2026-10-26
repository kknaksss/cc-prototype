"""WORK-007 WP-BE3 — 등록 · 이동 · 취소 · 메모 · 진행 경로 · 고객 정보 · 특이사항(SPEC-005 §4.4 · §5.4 · §5.5 · §5.13 · §8).

KOS 본문 = WP-KOS K2 ~ K7 판정 모양(가짜 KOS 가 받은 본문을 본다).
"""

import uuid

import pytest

from app.domain.errors import BadGateway, BadRequest, Conflict, NotFound
from app.schemas.reservations import CreateReservationRequest, MoveRequest, PersonalIn
from tests.fake_kos import SYSTEM, ZONE, ZONE2, kst, visitor
from tests.resv_env import DAY, DESK, load, make_env, rid_of, run


@pytest.fixture
def env(tmp_path):
    c, fake, mono = make_env(tmp_path)
    with c.repo.tx() as tx:
        tx.upsert("staff", "cs-1", {"name": "상담사 1", "role_tags": ["COUNSELOR"], "active": True})
    load(c)
    return c, fake, mono


def ids(c):
    with c.repo.tx() as tx:
        return ({g.kos_id: g.id for g in tx.resv_groups()}, {z.kos_id: z.id for z in tx.zones()},
                {s.kos_id: s.id for s in tx.staff()}, {f.kos_id: f.id for f in tx.funnel_codes()})


def sent(fake, name):
    return [b for p, b in fake.calls if p.endswith("/" + name)]


def events(c, type_=None):
    with c.repo.tx() as tx:
        return tx.events(type_)


def existing_customer(c, fake, vid="vis-1"):
    fake.add_resv("seed", vid, start=kst(18))
    load(c)
    with c.repo.tx() as tx:
        return tx.reservation(rid_of(c, "seed")).customer_id


def req(c, **kw):
    g, z, s, f = ids(c)
    body = {"groupId": g["grp-1"], "start": "2026-10-21T15:00:00+09:00", "customer": {"customerId": 1},
            "consultationRequired": True, "sedationRequired": True, "doctorStaffIds": []}
    body.update(kw)
    return CreateReservationRequest.model_validate(body)


# ------------------------------------------------------------------ 등록 — 기존 고객(K2-3)
def test_create_existing_full_body(env):
    c, fake, mono = env
    cid = existing_customer(c, fake)
    g, z, s, f = ids(c)
    n = fake.paths().count("get-schedules-for-reservation")
    out = run(c.resv.create(DESK, req(c, customer={"customerId": cid}, doctorStaffIds=[s["doc-a"]], counselorStaffId=s["cs-1"],
                                      funnelId=f["fn-1"], memo="메모", desiredDischargeTime="17:30")))
    body = sent(fake, "reserve")[-1]
    o = body["occupiedResources"][0]
    assert uuid.UUID(o.pop("id")).version == 4
    assert o == {"type": "RESERVATION_GROUP",
                 "reservationTime": {"startDateTimeUtc": "2026-10-21T06:00:00.000Z",
                                     "endDateTimeUtc": "2026-10-21T06:30:00.000Z"},
                 "reservationGroup": {"reservationGroupId": "grp-1", "zoneId": ZONE,
                                      "doctors": [{"id": "doc-a", "name": "가 원장"}]}}
    assert {k: v for k, v in body.items() if k != "occupiedResources"} == {
        "visitorId": "vis-1", "zoneId": ZONE, "reservationAssignee": {"id": SYSTEM, "name": "시스템"},
        "consultationRequired": True, "sedationRequired": True, "counselor": {"id": "cs-1", "name": "상담사 1"},
        "reservationMemo": "메모", "desiredDischargeDateTimeUtc": "2026-10-21T08:30:00.000Z",
        "funnel": {"funnel": {"id": "fn-1", "category": "FUNNEL", "name": "인스타그램", "order": 1, "closed": False,
                              "default": False}, "funnelDetail": ""}}
    assert out.customerId == cid and out.reservationId == rid_of(c, "rsv-new-1")
    ev = events(c, "resv_create")[-1]
    assert ev["actor"] == "desk1" and ev["visit_id"] is None and ev["payload"] == {
        "reservationId": out.reservationId, "customerId": cid, "newCustomer": False, "groupId": g["grp-1"],
        "start": "2026-10-21T15:00:00+09:00", "end": "2026-10-21T15:30:00+09:00"}
    run(c.resv.board(DAY))  # 캐시 비움 → 다시 읽음
    assert fake.paths().count("get-schedules-for-reservation") == n + 1
    assert "create-visitor" not in fake.paths() and "find-duplicated-visitor" not in fake.paths()


def test_create_minimal_body_and_assignee(env):
    c, fake, _ = env
    cid = existing_customer(c, fake)
    g, z, s, f = ids(c)
    run(c.resv.create(DESK, req(c, customer={"customerId": cid}, assigneeStaffId=s["nurse-0"], consultationRequired=False,
                                sedationRequired=False)))
    body = sent(fake, "reserve")[-1]
    assert set(body) == {"visitorId", "zoneId", "occupiedResources", "reservationAssignee", "consultationRequired",
                         "sedationRequired"}  # 값 없는 칸은 넣지 않는다
    assert body["reservationAssignee"] == {"id": "nurse-0", "name": "간호"}


def test_create_zone_rules(env):
    c, fake, _ = env
    cid = existing_customer(c, fake)
    g, z, s, f = ids(c)
    with pytest.raises(BadRequest):  # 그 그룹에서 꺼진 구역
        run(c.resv.create(DESK, req(c, customer={"customerId": cid}, zoneId=z[ZONE2])))
    for i in range(3):
        fake.add_resv(f"full{i}", f"v{i}", grp="grp-3", start=kst(15), minutes=15)
    load(c)
    run(c.resv.create(DESK, req(c, groupId=g["grp-3"], customer={"customerId": cid})))
    assert sent(fake, "reserve")[-1]["zoneId"] == ZONE2  # 기본 구역이 꽉 참 → 자리 있는 구역
    n = len(sent(fake, "reserve"))
    with pytest.raises(Conflict) as e:
        run(c.resv.create(DESK, req(c, groupId=g["grp-3"], zoneId=z[ZONE], customer={"customerId": cid})))
    assert e.value.code == "slot_full" and len(sent(fake, "reserve")) == n  # KOS 를 부르지 않는다


@pytest.mark.parametrize("bad", [{"groupId": 999}, {"funnelId": 999}, {"doctorStaffIds": [-1]}, {"start": "15:00"},
                                 {"desiredDischargeTime": "5시"}, {"counselorStaffId": -1}])
def test_create_400(env, bad):
    c, fake, _ = env
    cid = existing_customer(c, fake)
    with pytest.raises(BadRequest):
        run(c.resv.create(DESK, req(c, customer={"customerId": cid}, **bad)))
    assert not sent(fake, "reserve")


def test_create_unknown_customer_404(env):
    c, _, _ = env
    with pytest.raises(NotFound):
        run(c.resv.create(DESK, req(c, customer={"customerId": 999})))


def test_create_check_order_400_404_409(env):
    """검사 순서 = 400 → 404 → 409(정원은 KOS 쓰기 직전 · r1 W3)."""
    c, fake, _ = env
    for i in range(3):
        fake.add_resv(f"full{i}", f"v{i}", start=kst(15))  # 일본 15:00 4층 꽉 참
    load(c)
    with pytest.raises(BadRequest):  # 없는 고객 + 꽉 찬 줄 + 틀린 유입 → 400
        run(c.resv.create(DESK, req(c, customer={"customerId": 999}, funnelId=999)))
    with pytest.raises(NotFound):  # 없는 고객 + 꽉 찬 줄 → 404
        run(c.resv.create(DESK, req(c, customer={"customerId": 999})))
    with pytest.raises(BadRequest):  # 구분 안 됨 + 생년월일 꼴 틀림 → 400
        run(c.resv.create(DESK, req(c, customer={"new": {"name": " ", "dateOfBirth": "1990/1/1"}})))
    with pytest.raises(Conflict) as e:
        run(c.resv.create(DESK, req(c, customer={"new": {"name": "새", "dateOfBirth": "1990-01-01"}})))
    assert e.value.code == "slot_full" and "find-duplicated-visitor" not in fake.paths()  # KOS 를 부르기 전


def test_create_closed_funnel_and_non_doctor(env):
    c, fake, _ = env
    cid = existing_customer(c, fake)
    g, z, s, f = ids(c)
    for bad in ({"funnelId": f["fn-2"]}, {"doctorStaffIds": [s["nurse-0"]]}, {"counselorStaffId": s["doc-a"]}):
        with pytest.raises(BadRequest):
            run(c.resv.create(DESK, req(c, customer={"customerId": cid}, **bad)))


# ------------------------------------------------------------------ 등록 — 신규 고객(K2-1 · K2-2)
NEW = {"name": " 새 고객 ", "phoneticName": "シン", "gender": "MALE", "nationality": "US"}


@pytest.mark.parametrize("extra", [{"phone": {"countryCode": "+1", "number": "5550000"}},
                                   {"sns": {"type": "line", "accountId": "abc"}}, {"email": "a@example.com"},
                                   {"passportNumber": "P1"}, {"dateOfBirth": "1999-02-03"}])
def test_new_customer_identifiable(env, extra):
    c, fake, _ = env
    out = run(c.resv.create(DESK, req(c, customer={"new": {**NEW, **extra}})))
    assert fake.paths()[-4:-1] == ["find-duplicated-visitor", "create-visitor", "reserve"]
    create = sent(fake, "create-visitor")[-1]
    assert create["name"] == "새 고객" and not any(k.startswith(("aggrement", "agreement")) for k in create)
    dup = sent(fake, "find-duplicated-visitor")[-1]
    assert dup["name"] == "새 고객"
    if "dateOfBirth" in extra:
        assert create["dateOfBirth"] == "1999-02-03 00:00:00.000Z" and dup["birthDateUtc"] == "1999-02-02T15:00:00.000Z"
    if "phone" in extra:
        assert create["phoneNumber"] == dup["phone"] == {"countryCode": "+1", "phoneNumber": "5550000"}
    if "sns" in extra:
        assert create["snsInfo"] == {"snsType": "line", "accountId": "abc"}
    with c.repo.tx() as tx:
        cust = tx.customer(out.customerId)
    assert cust.is_new and cust.name == "새 고객" and sent(fake, "reserve")[-1]["visitorId"] == cust.kos_id
    assert events(c, "resv_create")[-1]["payload"]["newCustomer"] is True


@pytest.mark.parametrize("new", [{"name": "이름만"}, {"name": "  ", "dateOfBirth": "1990-01-01"},
                                 {"name": "a", "phone": {"countryCode": "", "number": "1"}},
                                 {"name": "a", "sns": {"type": "line", "accountId": " "}}])
def test_new_customer_not_identifiable(env, new):
    c, fake, _ = env
    with pytest.raises(Conflict) as e:
        run(c.resv.create(DESK, req(c, customer={"new": new})))
    assert e.value.code == "not_identifiable" and e.value.message == "고객을 구분할 수 있는 정보가 부족합니다"
    assert "find-duplicated-visitor" not in fake.paths()


def test_new_customer_duplicated(env):
    c, fake, _ = env
    fake.visitors["vis-1"]["name"] = "같은 이름"
    with pytest.raises(Conflict) as e:
        run(c.resv.create(DESK, req(c, customer={"new": {"name": "같은 이름", "dateOfBirth": "1990-01-02"}})))
    assert e.value.code == "duplicated_visitor"
    cand = e.value.extra["candidate"]
    with c.repo.tx() as tx:
        assert tx.customer(cand["customerId"]).kos_id == "vis-1"
    assert cand == {"customerId": cand["customerId"], "name": "같은 이름", "chartNumber": "C-vis-1", "dateOfBirth": "1990-01-02"}
    assert "create-visitor" not in fake.paths() and "reserve" not in fake.paths()


def test_create_kos_rejected_and_unavailable(env):
    c, fake, _ = env
    cid = existing_customer(c, fake)
    fake.resv_fail = {"reserve": (400, {"className": "InvalidRequestException",
                                        "errorProperties": [{"key": "startDateTime", "reason": "NotAvailable"}]})}
    with pytest.raises(Conflict) as e:
        run(c.resv.create(DESK, req(c, customer={"customerId": cid})))
    assert (e.value.code, e.value.message) == ("kos_rejected", "같은 고객의 예약이 그 시간에 있어요")
    ev = events(c, "kos_rejected")[-1]["payload"]
    assert ev == {"customerId": cid, "op": "reserve", "httpStatus": 400, "kosError": "HTTP 400 InvalidRequestException"}
    fake.resv_fail = {"reserve": (503, {})}
    with pytest.raises(BadGateway) as e:
        run(c.resv.create(DESK, req(c, customer={"customerId": cid})))
    assert e.value.code == "kos_unavailable" and not events(c, "resv_create")


def test_writes_without_kos_502(tmp_path):
    from app.container import build_container
    from tests.fake_kos import kos_settings

    c = build_container(kos_settings(tmp_path, kos_zone_id=""))
    with c.repo.tx() as tx:
        rid = tx.upsert("reservation", "x", {"status": "RESERVED", "flow_step": "RESERVED", "day": DAY})
    with pytest.raises(BadGateway):
        run(c.resv.cancel(DESK, rid, "CANCELED"))


# ------------------------------------------------------------------ 이동(K3)
def move(c, kos_id, group, start, index=0):
    g, *_ = ids(c)
    return run(c.resv.move(DESK, rid_of(c, kos_id), MoveRequest(resourceIndex=index, groupId=g[group], start=start)))


def test_move_body_keeps_everything(env):
    c, fake, _ = env
    fake.add_resv("m1", resources=[("grp-1", kst(11), 30), ("grp-2", kst(12), 60)])
    load(c)
    move(c, "m1", "grp-2", "2026-10-21T16:00:00+09:00", index=1)
    body = sent(fake, "update-reservation")[-1]
    items = body["occupiedResources"]["items"]
    assert body["scheduleId"] == "m1" and set(body) == {"scheduleId", "occupiedResources"}
    assert items[0] == {"id": "m1-r0", "type": "RESERVATION_GROUP",
                        "reservationTime": {"startDateTimeUtc": "2026-10-21T02:00:00.000Z",
                                            "endDateTimeUtc": "2026-10-21T02:30:00.000Z"},
                        "reservationGroup": {"reservationGroupId": "grp-1", "zoneId": ZONE,
                                             "doctors": [{"id": "doc-a", "name": "가 원장"}]}}
    assert items[1]["id"] == "m1-r1" and items[1]["reservationTime"] == {
        "startDateTimeUtc": "2026-10-21T07:00:00.000Z", "endDateTimeUtc": "2026-10-21T08:00:00.000Z"}  # 길이 60분 그대로
    assert items[1]["reservationGroup"]["doctors"] == [{"id": "doc-a", "name": "가 원장"}]
    ev = events(c, "resv_move")[-1]["payload"]
    assert ev["resourceIndex"] == 1 and ev["from"]["start"] == "2026-10-21T12:00:00+09:00"
    assert ev["to"]["end"] == "2026-10-21T17:00:00+09:00"
    b = load(c)
    assert [x.start for x in b.cards if x.reservationId == rid_of(c, "m1")] == [
        "2026-10-21T11:00:00+09:00", "2026-10-21T16:00:00+09:00"]


@pytest.mark.parametrize("start", ["2026-10-21T16:10:00+09:00", "2026-10-22T16:00:00+09:00", "16:00"])
def test_move_400(env, start):
    c, fake, _ = env
    fake.add_resv("m1")
    load(c)
    with pytest.raises(BadRequest):
        move(c, "m1", "grp-1", start)
    assert not sent(fake, "update-reservation")


def test_move_zone_not_enabled_400(env):
    """추가 지시 1 W2 — 끄는 카드의 구역이 그 칸에서 꺼져 있으면 400."""
    c, fake, _ = env
    fake.add_resv("m2", grp="grp-3", zone=ZONE2, minutes=15)
    load(c)
    with pytest.raises(BadRequest):
        move(c, "m2", "grp-1", "2026-10-21T16:00:00+09:00")
    move(c, "m2", "grp-3", "2026-10-21T16:15:00+09:00")
    assert sent(fake, "update-reservation")[-1]["occupiedResources"]["items"][0]["reservationGroup"]["zoneId"] == ZONE2


def test_move_slot_full_and_same_spot(env):
    c, fake, _ = env
    for i in range(3):
        fake.add_resv(f"f{i}", f"v{i}", start=kst(16))
    fake.add_resv("m1", "vm", start=kst(17))
    load(c)
    with pytest.raises(Conflict) as e:
        move(c, "m1", "grp-1", "2026-10-21T16:00:00+09:00")
    assert e.value.code == "slot_full" and not sent(fake, "update-reservation")
    move(c, "f0", "grp-1", "2026-10-21T16:00:00+09:00")  # 제자리는 꽉 차도 된다
    assert len(sent(fake, "update-reservation")) == 1


def test_move_not_movable_and_reception_movable(env):
    c, fake, _ = env
    fake.add_resv("c1", flow="CONSULTATION_WAITING", status="IN_PROGRESS")
    fake.add_resv("r1", "v2", flow="RECEPTION", status="IN_PROGRESS")
    fake.add_resv("x1", "v3", status="CANCELED")
    load(c)
    for k in ("c1", "x1"):
        with pytest.raises(Conflict) as e:
            move(c, k, "grp-1", "2026-10-21T16:00:00+09:00")
        assert e.value.code == "not_movable"
    move(c, "r1", "grp-1", "2026-10-21T16:00:00+09:00")


def test_move_kos_rejected_message(env):
    c, fake, _ = env
    fake.add_resv("m1")
    load(c)
    fake.resv_fail = {"update-reservation": (400, {"className": "InvalidRequestException",
                                                   "errorProperties": [{"key": "startDateTime", "reason": "NotAvailable"}]})}
    with pytest.raises(Conflict) as e:
        move(c, "m1", "grp-1", "2026-10-21T16:00:00+09:00")
    assert e.value.message == "같은 고객의 예약이 그 시간에 있어요"
    assert events(c, "kos_rejected")[-1]["payload"]["reservationId"] == rid_of(c, "m1") and not events(c, "resv_move")


# ------------------------------------------------------------------ 취소 · 메모 · 진행 경로(K4 · K6)
def test_cancel(env):
    c, fake, _ = env
    fake.add_resv("a")
    fake.add_resv("b", "v2")
    fake.add_resv("ns", "v3", status="NO_SHOW")
    fake.add_resv("rc", "v4", flow="RECEPTION", status="IN_PROGRESS")
    load(c)
    run(c.resv.cancel(DESK, rid_of(c, "a"), "CANCELED"))
    run(c.resv.cancel(DESK, rid_of(c, "b"), "NO_SHOW"))
    assert sent(fake, "cancel-reservation") == [{"scheduleId": "a", "reason": "CANCELED"},
                                                {"scheduleId": "b", "reason": "NO_SHOW"}]
    assert [e["payload"] for e in events(c, "resv_cancel")] == [
        {"reservationId": rid_of(c, "a"), "reason": "CANCELED", "prevStatus": "RESERVED"},
        {"reservationId": rid_of(c, "b"), "reason": "NO_SHOW", "prevStatus": "RESERVED"}]
    b = load(c)
    assert b.counts.canceled == 1 and b.counts.noshow == 2
    for k in ("ns", "rc"):
        with pytest.raises(Conflict) as e:
            run(c.resv.cancel(DESK, rid_of(c, k), "CANCELED"))
        assert e.value.code == "not_cancelable"
    with pytest.raises(NotFound):
        run(c.resv.cancel(DESK, 999, "CANCELED"))


def test_memo_rules(env):
    c, fake, _ = env
    fake.add_resv("a", status="NO_SHOW")
    fake.add_resv("done", "v2", flow="COMPLETED", status="COMPLETED")
    fake.add_resv("x", "v3", status="CANCELED")
    load(c)
    run(c.resv.memo(DESK, rid_of(c, "a"), ""))  # 부도는 연다(추가 지시 1 W4)
    assert sent(fake, "change-reservation-memo") == [{"scheduleId": "a", "memo": ""}]
    for k in ("x", "done"):  # 취소 · 귀가 완료 = 막음(§5.14 · r1 W1)
        with pytest.raises(Conflict) as e:
            run(c.resv.memo(DESK, rid_of(c, k), "m"))
        assert e.value.code == "reservation_closed"
    assert len(events(c, "resv_memo")) == 1 and len(sent(fake, "change-reservation-memo")) == 1


def test_route_rules(env):
    c, fake, _ = env
    fake.add_resv("re", status="NO_SHOW")  # 재진(isNew false) · 부도도 연다(W4)
    fake.add_resv("new", "v2", is_new=True)
    fake.add_resv("rc", "v3", flow="RECEPTION", status="IN_PROGRESS")
    load(c)
    run(c.resv.route(DESK, rid_of(c, "re"), False))
    assert sent(fake, "update-reservation") == [{"scheduleId": "re", "consultationRequired": False}]
    assert events(c, "resv_route")[-1]["payload"] == {"reservationId": rid_of(c, "re"), "consultationRequired": False}
    for k in ("new", "rc"):
        with pytest.raises(Conflict) as e:
            run(c.resv.route(DESK, rid_of(c, k), True))
        assert e.value.code == "route_locked"


# ------------------------------------------------------------------ 고객 정보 · 특이사항(K7 · MT§4)
def test_personal_reads_then_sends_bundle_plus_changes(env):
    c, fake, _ = env
    cid = existing_customer(c, fake)
    before = dict(fake.visitors["vis-1"])
    p = PersonalIn.model_validate({"passportSurname": "NEW", "passportNumber": "", "dateOfBirth": "1991-05-06",
                                   "passportExpiryDate": "2031-01-01", "nationality": "TW",
                                   "phone": {"countryCode": "+886", "number": "900"}})
    run(c.resv.personal(DESK, cid, p))
    assert fake.paths()[-2:] == ["get-visitor", "update-visitor-personal-information"]
    body = sent(fake, "update-visitor-personal-information")[-1]
    assert body["id"] == "vis-1" and body["name"] == before["name"] and body["language"] == "ja"
    assert body["address"] == before["address"]  # 고치지 않은 칸 그대로
    assert (body["passportSurname"], body["passportNumber"], body["dateOfBirth"], body["passportExpiryDate"]) == (
        "NEW", "", "1991-05-06 00:00:00.000Z", "2031-01-01")
    assert body["phoneNumber"] == {"countryCode": "+886", "phoneNumber": "900"}
    assert "additionalPhoneNumber" not in body and "email" not in body and "memo" not in body  # 없던 키 · 관리 칸 안 보냄
    with c.repo.tx() as tx:
        assert tx.customer(cid).nationality == "TW"
    assert events(c, "visitor_personal")[-1]["payload"] == {
        "customerId": cid, "fields": ["dateOfBirth", "nationality", "passportExpiryDate", "passportNumber", "passportSurname",
                                      "phone"]}


def test_personal_bad_date_400_before_kos(env):
    c, fake, _ = env
    cid = existing_customer(c, fake)
    n = len(fake.calls)
    with pytest.raises(BadRequest):
        run(c.resv.personal(DESK, cid, PersonalIn.model_validate({"dateOfBirth": "1991/5/6"})))
    assert len(fake.calls) == n
    with pytest.raises(NotFound):
        run(c.resv.personal(DESK, 999, PersonalIn()))


def test_remark_management_bundle(env):
    c, fake, _ = env
    cid = existing_customer(c, fake)
    fake.visitors["vis-1"]["customAttributes"] = [{"id": "ca", "value": "x"}]
    run(c.resv.remark(DESK, cid, "새 특이사항"))
    body = sent(fake, "update-visitor-management-information")[-1]
    v = visitor("vis-1")
    assert body == {"id": "vis-1", "memo": "새 특이사항", "visitorFunnel": v["visitorFunnel"], "visitorType": v["visitorType"],
                    "doctor": v["doctor"], "counselor": v["counselor"], "aggrementPersonalInformation": False,
                    "aggrementAdvertisements": False, "agreementInformationalNotification": True,
                    "customAttributes": [{"id": "ca", "value": "x"}]}  # 빈 배열(visitorCategories)은 뺀다 · 개인 칸 없음
    assert events(c, "visitor_remark")[-1]["payload"] == {"customerId": cid}
    fake.resv_fail = {"get-visitor": (500, {})}
    with pytest.raises(BadGateway):
        run(c.resv.remark(DESK, cid, "x"))
    assert events(c, "kos_rejected")[-1]["payload"]["op"] == "get-visitor"
