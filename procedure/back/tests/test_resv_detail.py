"""WORK-007 WP-BE2 — 예약 상세 · 등록 칸 · 고객 검색 · 신분 확인 · 문진 이력.

SPEC-005 §5.7 · §5.8 · §5.11 ~ §5.14 · §7.3 · §7.4.
"""

from datetime import datetime

import pytest

from app.domain.errors import BadGateway, BadRequest, Conflict, NotFound
from app.domain.reservation_rules import identity_fields
from tests.fake_kos import ZONE, ZONE2, kst, rtask, visitor
from tests.resv_env import DESK, load, make_env, rid_of, run

ROOM1 = {"id": "room-1", "zoneId": ZONE, "title": "A-룸1", "order": 1}
ROOM2 = {"id": "room-2", "zoneId": ZONE, "title": "A-룸2", "order": 2}


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


def detail(c, fake, kos_id, **kw):
    if not fake._resv_sch(kos_id):
        fake.add_resv(kos_id, **kw)
    load(c)
    return run(c.resv.detail(rid_of(c, kos_id)))


# ------------------------------------------------------------------ §5.12 ① 신분 칸
def test_identity_fields_rules():
    full = visitor("v")
    assert identity_fields(full)[0] == "foreign" and identity_fields(full)[2] is True
    assert identity_fields({**full, "passportSurname": "  "})[2] is False
    given_only = {k: v for k, v in full.items() if k != "passportSurname"} | {"passportGivenNames": "HANAKO"}
    assert identity_fields(given_only)[2] is True  # 영문명 하나 이상
    no_nat = {k: v for k, v in full.items() if k != "nationality"}
    assert identity_fields(no_nat)[0] == "foreign"  # 국적 빈 값 = 외국인
    kr = visitor("k", nationality="KR")
    kind, fields, ok = identity_fields(kr)
    assert kind == "domestic" and [f["key"] for f in fields] == ["dateOfBirth", "registrationNumber"] and not ok
    assert identity_fields({**kr, "registrationNumber": "000000-0000000"})[2] is True
    kind, fields, ok = identity_fields({**full, "passportNumber": None})
    assert [f["key"] for f in fields if not f["filled"]] == ["passportNumber"] and not ok
    assert identity_fields(None) == ("foreign", [], False)


def test_detail_new_reception_identity_not_required(env):
    """10-27 — [접수 완료]는 신분 칸과 상관없이 켜짐(U2 뒤집음) · 신분 칸은 표시만."""
    c, fake, _ = env
    fake.visitors["vis-1"].pop("passportNumber")
    d = detail(c, fake, "s1")
    assert d.receiveMode == "new" and d.customer.identity.complete is False and d.can.receive is True
    assert [f.key for f in d.customer.identity.fields if not f.filled] == ["passportNumber"]
    assert d.customer.personal.passportNumber is None and d.customer.personalError is None
    assert d.can.editRoute is True and not hasattr(d.reservation, "consultationRequired")  # 초진 · 재진 모두 · KOS 체크 안 읽음
    assert [r.title for r in d.rooms] == ["A-룸1", "A-룸2", "A-룸3"] and not d.roomLocked


def test_detail_noshow_receivable_and_canceled_not(env):
    c, fake, _ = env
    d = detail(c, fake, "s1", status="NO_SHOW")
    assert (d.state.main, d.receiveMode, d.can.receive, d.can.cancel) == ("noshow", "new", True, False)
    assert d.can.editRoute is True and d.can.editMemo is True  # 추가 지시 1 W4 — 부도도 진행 경로 · 메모
    d = detail(c, fake, "s2", vid="vis-1", status="CANCELED")
    assert (d.receiveMode, d.can.receive, d.can.editMemo, d.can.editRoute, d.rooms) == (None, False, False, False, [])


def test_detail_resume_with_and_without_room(env):
    c, fake, _ = env
    fake.visitors["vis-1"].pop("passportNumber")  # 신분 칸 빔 — 이어 하기는 안 본다
    d = detail(c, fake, "s1", flow="RECEPTION", status="IN_PROGRESS")
    assert (d.receiveMode, d.can.receive, d.roomLocked) == ("resume", True, False)
    assert not any(r.selected for r in d.rooms)
    fake._resv_sch("s1")["tasks"] = [rtask(1, "ETCETERA", "READY", room=ROOM2, title="방 배정")]
    load(c)
    d = run(c.resv.detail(d.reservationId))
    assert d.roomLocked and [r.title for r in d.rooms if r.selected] == ["A-룸2"]
    assert not any(r.busy for r in d.rooms if r.selected)


def test_detail_after_end_step_no_receive(env):
    c, fake, _ = env
    d = detail(c, fake, "s1", flow="CONSULTATION_WAITING", status="IN_PROGRESS")
    assert d.receiveMode is None and not d.can.receive and d.can.callCounselor and d.rooms == []


def test_visitor_read_failure(env):
    c, fake, _ = env
    fake.resv_fail = {"get-visitor": (500, {"className": "Boom"})}
    d = detail(c, fake, "s1")
    assert d.customer.personal is None and d.customer.personalError == "HTTP 500 Boom"
    assert d.customer.identity.fields == [] and d.can.receive is True and d.health.state in ("none", "ok")
    d = detail(c, fake, "s2", flow="RECEPTION", status="IN_PROGRESS")
    assert d.can.receive  # 이어 하기는 신분 칸을 안 본다


# ------------------------------------------------------------------ §5.7 방 · §5.8 상담사
def test_rooms_busy_by_zone_and_today_refresh(env):
    c, fake, _ = env
    fake.add_resv("busy1", "vis-2", flow="PROCEDURE", status="IN_PROGRESS", tasks=[rtask(1, room=ROOM1, status="READY")])
    fake.add_resv("home1", "vis-3", flow="PROCEDURE_DONE", status="IN_PROGRESS", tasks=[rtask(1, room=ROOM2, status="READY")])
    fake.add_resv("canc", "vis-4", flow="PROCEDURE", status="IN_PROGRESS",
                  tasks=[rtask(1, "ETCETERA", "CANCELED", room=ROOM2, title="방 배정")])
    fake.add_resv("other", "vis-5", grp="grp-3", zone=ZONE2, flow="PROCEDURE", status="IN_PROGRESS",
                  tasks=[rtask(1, room={"id": "room-b1", "zoneId": ZONE2, "title": "B-룸1", "order": 1}, status="READY")])
    fake.add_resv("tomorrow", start=kst(11).replace(day=22))
    load(c, "2026-10-22")  # 다른 날짜를 보다가
    n = fake.paths().count("get-schedules-for-reservation")
    d = run(c.resv.detail(rid_of(c, "tomorrow")))
    assert fake.paths().count("get-schedules-for-reservation") >= n + 1  # 오늘 사본 먼저 갱신(W7)
    busy = {r.title: r.busy for r in d.rooms}
    assert busy == {"A-룸1": True, "A-룸2": False, "A-룸3": False}  # 귀가 대기 · 취소 작업 방은 안 침 · 다른 구역 안 셈
    d5 = detail(c, fake, "z2", vid="vis-6", grp="grp-3", zone=ZONE2)
    assert [(r.title, r.busy) for r in d5.rooms] == [("B-룸1", True)] and d5.zoneTitle == "미사용"


def test_counselor_status_two_zones(env):
    c, fake, _ = env
    with c.repo.tx() as tx:
        tx.upsert("staff", "cs-1", {"name": "상담사 1", "role_tags": ["COUNSELOR"], "active": True})
        tx.upsert("staff", "cs-2", {"name": "상담사 2", "role_tags": ["COUNSELOR"], "active": True})
        tx.upsert("staff", "cs-off", {"name": "쉬는 상담사", "role_tags": ["COUNSELOR"], "active": False})
    fake.add_resv("talk", "vis-2", grp="grp-3", zone=ZONE2, flow="CONSULTATION", status="IN_PROGRESS",
                  counselor={"id": "cs-1", "name": "상담사 1"},
                  tasks=[rtask(1, "ETCETERA", "READY", room={"id": "room-b1", "zoneId": ZONE2, "title": "B-룸1", "order": 1},
                               title="방 배정")])
    d = detail(c, fake, "s1", flow="CONSULTATION_WAITING", status="IN_PROGRESS")
    assert {x.name: x.busyRoom for x in d.counselors} == {"상담사 1": "B-룸1", "상담사 2": None}
    assert d.flow.consultation.state == "waiting" and d.flow.consultation.counselor is None
    talk = run(c.resv.detail(rid_of(c, "talk")))
    assert talk.flow.consultation.state == "doing" and talk.flow.consultation.counselor.name == "상담사 1"
    assert talk.flow.consultation.since == "2026-10-21T11:00:00+09:00"


def test_flow_stages_and_settlement(env, tmp_path):
    c, fake, _ = env
    fake.purchases["p1"] = {"id": "p1", "items": [{"priceV2": {"amount": {"value": 3000, "currency": "KRW"}}}],
                            "transactions": [{"status": "APPROVED", "price": {"value": 1000, "currency": "KRW"}}]}
    d = detail(c, fake, "s1", flow="PROCEDURE_DONE", status="IN_PROGRESS", consult=False, purchases=["p1"],
               tasks=[rtask(1, paid=True)])
    assert d.flow.stages.procedure == "done" and d.flow.stages.home == "waiting" and d.flow.consultation is None
    s = d.settlement
    assert (s.paymentRequiredCount, s.amount.total, s.amount.paid, s.prescriptionCount, s.links) == (1, 3000, 1000, 0, None)
    assert d.can.discharge is False
    c2, fake2, _ = make_env(tmp_path / "w", kos_web_base="https://kos-web.test/")
    d2 = detail(c2, fake2, "s1", flow="COMPLETED", status="COMPLETED")
    assert d2.settlement.links.purchase == ("https://kos-web.test/tenant-x/reservation/schedule/?visitorId=vis-1&scheduleId=s1"
                                            "&tab=purchase")
    assert d2.settlement.links.prescription.endswith("&tab=etceteraWork") and d2.flow.stages.home == "done"
    assert d2.can.editMemo is False  # 귀가 완료 = 메모 닫힘(§5.14 · r1 W1)


# ------------------------------------------------------------------ §5.11 건강 · 문진 이력
def test_health_none_ok_error_and_history(env):
    c, fake, _ = env
    d = detail(c, fake, "s1")
    assert d.health.state == "none" and [i.empty for i in d.health.items] == [True, True, True]
    fake.submits["vis-1"] = {"id": "sub-1", "visitorId": "vis-1", "createdDateTimeUtc": "2026-10-20T01:00:00.000Z", "answers": [
        {"seq": 1, "questionId": "q1", "questionTitle": "질문1", "answerId": "a", "answerTitle": "없음", "memo": ""},
        {"seq": 2, "questionId": "q2", "questionTitle": "질문2", "answerId": "b", "answerTitle": "꽃가루", "memo": "봄"},
        {"seq": 3, "questionId": "q2", "questionTitle": "질문2", "answerId": "c", "answerTitle": "약", "memo": None}]}
    d = run(c.resv.detail(d.reservationId))
    items = {i.title: i for i in d.health.items}
    assert d.health.state == "ok" and d.health.needCount == 1 and d.health.submittedAt == "2026-10-20T10:00:00+09:00"
    assert (items["질문1"].needsCheck, items["질문2"].answer, items["질문2"].memo, items["질문2"].needsCheck) == (
        False, "꽃가루 · 약", "봄", True)
    assert items["질문3"].empty and not items["질문3"].needsCheck
    run(c.resv.detail(d.reservationId))
    with c.repo.tx() as tx:
        hist = tx.questionnaire_history(d.customer.customerId)
    assert len(hist) == 1 and hist[0]["reservation_id"] == d.reservationId  # 같은 제출본은 한 번
    fake.submits["vis-1"]["createdDateTimeUtc"] = "2026-10-21T01:00:00.000Z"
    run(c.resv.detail(d.reservationId))
    with c.repo.tx() as tx:
        assert len(tx.questionnaire_history(d.customer.customerId)) == 2
    fake.resv_fail = {"get-questionnaire-submit": (500, {})}
    assert run(c.resv.detail(d.reservationId)).health.state == "error"


# ------------------------------------------------------------------ §5.13 이전 방문
def test_previous_visits_skip_same_day(env):
    from tests.fake_kos import resv

    c, fake, _ = env
    old = resv("old", status="COMPLETED", flow="COMPLETED", start=kst(14).replace(day=1),
               tasks=[rtask(1, status="DONE", title="토닝"), rtask(2, "ETCETERA", title="방 배정")])
    old["consultation"] = {"consultationMemo": "상담 메모"}
    fake.history = [old, resv("ns", status="NO_SHOW", start=kst(10).replace(month=9)),
                    resv("odd", status="IN_PROGRESS", flow="PROCEDURE", start=kst(10).replace(month=8))]
    fake.add_resv("same", start=kst(16))  # 오늘 다른 예약 — 뺀다
    d = detail(c, fake, "s1")
    assert [(p.result, p.resultRaw) for p in d.previousVisits] == [
        ("completed", "COMPLETED"), ("noshow", "NO_SHOW"), ("other", "IN_PROGRESS")]
    p = d.previousVisits[0]
    got = (p.date, p.groupTitle, p.consultationMemo, [x.title for x in p.procedures])
    assert got == ("2026-10-01", "일본", "상담 메모", ["토닝"])


# ------------------------------------------------------------------ 상세 머리 · 예약 칸
def test_detail_head_and_reservation_fields(env):
    c, fake, _ = env
    x = fake.add_resv("s1", resources=[("grp-1", kst(11), 30), ("grp-2", kst(12), 60)],
                      counselor={"id": "cs-9", "name": "상담 9"})
    x["reservation"]["funnel"] = {"funnel": {"id": "fn-1", "category": "FUNNEL", "name": "인스타그램"}, "funnelDetail": "광고"}
    x["reservation"]["desiredDischargeDateTimeUtc"] = "2026-10-21T08:00:00.000Z"
    d = detail(c, fake, "s1")
    assert (d.start, d.end) == ("2026-10-21T11:00:00+09:00", "2026-10-21T13:00:00+09:00")
    assert (d.groupTitle, d.zoneTitle) == ("일본", "4층")
    assert d.reservation.funnel.model_dump() == {"name": "인스타그램", "detail": "광고"}
    assert d.reservation.doctors[0].name == "가 원장" and len(d.reservation.doctors) == 1
    assert d.reservation.counselor.name == "상담 9" and d.reservation.counselor.staffId is None
    assert d.reservation.assignee.name == "시스템" and d.reservation.desiredDischargeAt == "2026-10-21T17:00:00+09:00"
    assert d.customer.age == 36 and d.customer.remark == "특이 메모" and d.customer.personal.dateOfBirth == "1990-01-02"
    assert d.flow is None and d.settlement is None


def test_detail_404(env):
    c, _, _ = env
    with pytest.raises(NotFound):
        run(c.resv.detail(999))


# ------------------------------------------------------------------ §5.12 ② 신분 확인 표시
def test_identity_mark(env):
    c, fake, _ = env
    d = detail(c, fake, "s1")
    cid = d.customer.customerId
    assert d.customer.identity.status == "unconfirmed" and d.can.confirmIdentity and not d.can.unconfirmIdentity
    c.resv.identity(DESK, cid, "confirmed")
    d = run(c.resv.detail(d.reservationId))
    ident = d.customer.identity
    assert (ident.status, ident.checkedBy, ident.method) == ("confirmed", "desk1", "web_manual")
    assert d.can.unconfirmIdentity and d.can.receive  # 표시만 — 접수 조건 아님
    c.resv.identity(DESK, cid, "unconfirmed")
    fake._resv_sch("s1").update(flowStep="RECEPTION")
    fake._resv_sch("s1")["reservation"]["status"] = "IN_PROGRESS"
    load(c)
    c.resv.identity(DESK, cid, "confirmed")
    with pytest.raises(Conflict) as e:
        c.resv.identity(DESK, cid, "unconfirmed")
    assert e.value.code == "identity_locked"
    other = detail(c, fake, "s2", start=kst(17))  # 같은 고객의 다른(접수 전) 예약도 끔 — 고객 단위(r1 W4)
    assert other.customer.identity.status == "confirmed" and other.can.unconfirmIdentity is False
    assert run(c.resv.detail(d.reservationId)).can.unconfirmIdentity is False
    with c.repo.tx() as tx:
        assert [x["payload"] for x in tx.events("identity")] == [{"customerId": cid, "status": s}
                                                                 for s in ("confirmed", "unconfirmed", "confirmed")]
    with pytest.raises(NotFound):
        c.resv.identity(DESK, 999, "confirmed")


# ------------------------------------------------------------------ §7.4 등록 칸 · 검색
def test_form_defaults(env):
    c, fake, _ = env
    with c.repo.tx() as tx:
        tx.upsert("staff", "cs-1", {"name": "상담사 1", "role_tags": ["COUNSELOR"], "active": True})
    for i in range(3):
        fake.add_resv(f"f{i}", f"v{i}", grp="grp-3", start=kst(10), minutes=15)
    load(c)
    with c.repo.tx() as tx:
        gid = {g.kos_id: g.id for g in tx.resv_groups()}
        zid = {z.kos_id: z.id for z in tx.zones()}
    f = run(c.resv.form("2026-10-21", gid["grp-3"], "2026-10-21T10:00:00+09:00"))
    names = [x.name for x in f.staff]
    assert "시스템" in names and "마취용" not in names  # 시스템 포함 · 제외 계정 뺌
    assert f.defaultAssigneeStaffId == next(x.staffId for x in f.staff if x.name == "시스템")
    assert [x.name for x in f.counselors] == ["상담사 1"] and not hasattr(f, "doctors")  # 당일 지정 의사 칸 없음(10-27)
    assert f.snsTypes == ["etc", "kakaotalk", "line", "instagram", "whatsapp", "wechat"]
    assert [x.name for x in f.funnels] == ["인스타그램"]  # 닫힌 코드 뺌
    assert {(x.zoneId, x.available) for x in f.zones} == {(zid[ZONE], False), (zid[ZONE2], True)}
    assert f.defaultZoneId == zid[ZONE2]  # 기본 구역이 꽉 차면 order 첫 자리 있는 구역
    f = run(c.resv.form(None, gid["grp-1"], "2026-10-21T10:00:00+09:00"))
    assert {(x.zoneId, x.available) for x in f.zones} == {(zid[ZONE], True), (zid[ZONE2], False)}
    assert f.defaultZoneId == zid[ZONE]
    assert all(z.available for z in run(c.resv.form(None, None, None)).zones)
    with pytest.raises(BadRequest):
        run(c.resv.form(None, 999, None))


def test_search(env):
    c, fake, _ = env
    fake.visitors.update({f"vs-{i}": visitor(f"vs-{i}", name=f"검색 고객 {i}") for i in range(25)})
    r = run(c.resv.search(" 검색 ", None, None, None, 1))
    assert (r.total, r.page, r.pageSize, len(r.items)) == (25, 1, 20, 20)
    body = [b for p, b in fake.calls if p.endswith("get-visitors")][-1]
    assert body["visitorName"] == "검색" and body["indexOfPage"] == 0 and body["countInPage"] == 20
    assert r.items[0].dateOfBirth == "1990-01-02" and r.items[0].customerId > 0
    assert len(run(c.resv.search("검색", None, None, None, 2)).items) == 5
    with c.repo.tx() as tx:
        assert tx.customer(r.items[0].customerId).name.startswith("검색 고객")
    run(c.resv.search(None, None, "1990-01-02", None, 1))
    assert [b for p, b in fake.calls if p.endswith("get-visitors")][-1]["dateOfBirth"] == "1990-01-02 00:00:00.000Z"
    every = run(c.resv.search(None, None, None, None, 1))  # 조건 없음 = 최근 방문 순 목록(10-27 #1)
    body = [b for p, b in fake.calls if p.endswith("get-visitors")][-1]
    assert (body["visitorName"], body["phoneNumber"], body["chartNumber"]) == ("", "", "") and "dateOfBirth" not in body
    assert every.total == len(fake.visitors) and len(every.items) == 20
    assert run(c.resv.search(" ", None, None, None, 1)).total == every.total
    bad = (("a", None, None, None, 0), (None, None, "1990/1/2", None, 1))
    for args in bad:
        with pytest.raises(BadRequest):
            run(c.resv.search(*args))
    fake.resv_fail = {"get-visitors": (500, {})}
    with pytest.raises(BadGateway):
        run(c.resv.search("a", None, None, None, 1))


def test_detail_reads_schedule_fresh_every_time(env):
    """10-27 #17 — 상세는 열 때마다 그 일정을 KOS 에서 바로 읽는다(날짜 캐시 10초와 상관없이) → 모달 폴링이 수납을 곧바로 본다."""
    c, fake, _ = env
    d = detail(c, fake, "s1", flow="PROCEDURE_DONE", status="IN_PROGRESS", tasks=[rtask(1, status="DONE", paid=True)])
    assert d.settlement.paymentRequiredCount == 1 and not d.can.discharge
    fake._resv_sch("s1")["tasks"][0]["paymentRequired"] = False  # KOS 에서 수납 — 캐시는 아직 신선
    assert c.kos.resv.fresh(datetime.fromisoformat("2026-10-21").date())
    n = fake.paths().count("get-schedule-detail")
    d = run(c.resv.detail(d.reservationId))
    assert fake.paths().count("get-schedule-detail") == n + 1
    assert d.settlement.paymentRequiredCount == 0 and d.can.discharge


def test_detail_kos_gone_404_logged_once(env, caplog):
    """E2E b2 #2 — 상세가 다시 읽은 일정이 KOS 에 없으면(404) 404 reservation_gone · 로그는 일정마다 한 번 · WARNING 없음."""
    c, fake, _ = env
    d = detail(c, fake, "s1")
    fake.resv.remove(fake._resv_sch("s1"))
    caplog.set_level("INFO", logger="procedure.resv")
    for _ in range(3):  # 모달 폴링
        with pytest.raises(NotFound) as e:
            run(c.resv.detail(d.reservationId))
        assert (e.value.code, e.value.message) == ("reservation_gone", "KOS 에서 사라진 예약이에요")
    mine = [r for r in caplog.records if r.name == "procedure.resv"]
    assert len(mine) == 1 and mine[0].levelname == "INFO"


def test_counselors_exclude_system_and_excluded_accounts(env):
    """E2E b2 #5 — 상담사 목록에서 시스템 계정 · 제외 목록(마취용 등) 뺌 · 그 밖 COUNSELOR 태그는 그대로."""
    c, fake, _ = env
    with c.repo.tx() as tx:
        for kos in ("cs-1", "anes-0", "cs-2"):
            tx.upsert("staff", kos, {"name": kos, "role_tags": ["COUNSELOR"], "active": True})
        sys_id = tx.token("internal")[2]
        tx.upsert("staff", sys_id, {"role_tags": ["DOCTOR", "ADMIN", "COUNSELOR"]})
    f = run(c.resv.form(None, None, None))
    assert [x.name for x in f.counselors] == ["cs-1", "cs-2"]
    d = detail(c, fake, "s1", flow="CONSULTATION_WAITING", status="IN_PROGRESS")
    assert [x.name for x in d.counselors] == ["cs-1", "cs-2"]
    with c.repo.tx() as tx:
        sid = {s.kos_id: s.id for s in tx.staff()}
    with pytest.raises(Conflict) as e:
        run(c.reception.counselor_call(DESK, d.reservationId, sid["anes-0"]))
    assert e.value.code == "not_counselor"
