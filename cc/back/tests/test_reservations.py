"""SPEC-002 §3 — 예약관리 데모 API: 전이 · 409 · 400 · reset · version/SSE."""

import inspect

import pytest

from app.service import reservation_service as RS
from tests.helpers import ok
from tests.test_kos_comments import MARK

BASE = 1_791_943_320_000  # 2026-10-14 11:02 KST


@pytest.fixture
def api(client, container):
    t = {"now": BASE}

    def clock():
        t["now"] += 60_000
        return t["now"]

    container.reservations.clock = clock
    return client


def rows(client):
    return ok(client.get("/api/reservations"))["rows"]


def row(client, rid):
    return next(r for r in rows(client) if r["id"] == rid)


def req(client):
    return ok(client.post("/api/reservations/demo/request"))


def modify(client):
    return ok(client.post("/api/reservations/demo/modify"))


def register(client, rid):
    return client.post(f"/api/reservations/{rid}/register")


def change(client, rid, reason="10:00 은 원장 상담이 마감됐어요. 같은 날 14:00 이후로 가능해요."):
    return client.post(f"/api/reservations/{rid}/change-request", json={"reason": reason})


def conflict(r):
    assert r.status_code == 409, r.json()
    assert set(r.json()["error"]) == {"code", "message"}
    return r.json()["error"]["code"]


def test_empty(api):
    body = ok(api.get("/api/reservations"))
    assert body["rows"] == []
    assert body["counts"] == {"needCheck": 0, "changeRequested": 0, "confirmed": 0, "total": 0}
    assert isinstance(body["version"], int)


def test_request_register_confirmed(api):
    v0 = ok(api.get("/api/reservations"))["version"]
    assert req(api) == {"version": v0 + 1}
    r = rows(api)[0]
    assert r["kind"] == "request" and r["status"] == "requested" and r["groupId"] == r["id"]
    assert r["customer"]["name"] == "[TW] LIN YA CHEN" and r["customer"]["chart"] == "No.9041"
    assert (r["date"], r["time"], r["proc"], r["lang"]) == ("2026-10-16", "14:00", "울쎄라피 프라임 300shot", "중국어")
    assert r["snapshot"] is None and r["registeredAt"] is None and r["before"] is None
    assert ok(api.get("/api/reservations"))["counts"]["needCheck"] == 1

    assert ok(register(api, r["id"])) == {"version": v0 + 2}
    r = row(api, r["id"])
    assert r["status"] == "confirmed" and r["registeredAt"]
    snap = r["snapshot"]
    assert snap["kind"] == "register" and snap["visitType"] == "신규 환자" and snap["lastVisit"] == "없음"
    assert (snap["time"], snap["endTime"], snap["floor"]) == ("14:00", "14:30", "3층")
    assert snap["memo"] == "26.10.14/링키 본사/울쎄라피 프라임 300shot/중국어 통역 필요"
    assert ok(api.get("/api/reservations"))["counts"] == {"needCheck": 0, "changeRequested": 0, "confirmed": 1, "total": 1}
    assert conflict(register(api, r["id"])) == "invalid_status"
    assert conflict(change(api, r["id"])) == "invalid_status"


def test_change_request_then_modify_supersedes(api):
    req(api)
    a = rows(api)[0]["id"]
    ok(register(api, a))
    req(api)
    b = rows(api)[0]
    assert b["customer"]["name"] == "[JP] TANAKA YUKI" and b["time"] == "10:00"
    ok(change(api, b["id"], "  사유 \n"))
    b = row(api, b["id"])
    assert b["status"] == "change_requested" and b["changeReason"] == "사유" and b["changeAt"]
    assert conflict(register(api, b["id"])) == "invalid_status"

    modify(api)  # 변경 요청 걸린 묶음(B)이 확정 묶음(A)보다 먼저
    m = rows(api)[1]
    assert m["groupId"] == b["id"] and m["kind"] == "modify" and m["modifyReason"] == "change_request"
    assert (m["status"], m["time"], m["before"], m["date"]) == ("modify_requested", "14:30", {"time": "10:00"}, b["date"])
    # 묶음 단위 · 최신 묶음이 위 · 묶음 안은 오래된 줄이 위
    assert [(r["groupId"], r["id"]) for r in rows(api)] == [(b["id"], b["id"]), (b["id"], m["id"]), (a, a)]
    assert ok(api.get("/api/reservations"))["counts"] == {"needCheck": 1, "changeRequested": 1, "confirmed": 1, "total": 2}

    ok(register(api, m["id"]))
    b, m = row(api, b["id"]), row(api, m["id"])
    assert b["status"] == "superseded" and b["snapshot"] is None and b["changeReason"] == "사유"
    assert m["status"] == "modified" and m["snapshot"]["kind"] == "modify"
    assert m["snapshot"]["memo"].endswith("\n*예약 시간 변경 10:00 → 14:30")
    assert m["snapshot"]["lastVisit"] == "2026.08.21" and m["snapshot"]["visitType"] == "재내원"
    assert row(api, a)["status"] == "confirmed"  # 다른 묶음은 그대로


def test_confirmed_then_customer_modify(api):
    req(api)
    a = rows(api)[0]
    ok(register(api, a["id"]))
    shot = row(api, a["id"])["snapshot"]
    modify(api)
    m = rows(api)[1]
    assert (m["modifyReason"], m["time"], m["before"]) == ("customer", "16:30", {"time": "14:00"})
    # 확인 중인 묶음에는 더 붙지 않는다
    assert conflict(api.post("/api/reservations/demo/modify")) == "no_modify_target"
    ok(register(api, m["id"]))
    a = row(api, a["id"])
    assert a["status"] == "superseded" and a["snapshot"] == shot  # 이전 스크린샷 보관
    assert row(api, m["id"])["status"] == "modified"
    # 수정 확정 묶음도 다시 수정 대상 — 같은 시간이면 +1시간
    modify(api)
    m2 = rows(api)[2]
    assert (m2["before"], m2["time"]) == ({"time": "16:30"}, "17:30")


def test_modify_request_can_be_change_requested(api):
    req(api)
    a = rows(api)[0]["id"]
    ok(register(api, a))
    modify(api)
    m = rows(api)[1]["id"]
    ok(change(api, m))
    assert row(api, m)["status"] == "change_requested"
    modify(api)  # 변경 요청 걸린 수정 줄 아래에 또
    m2 = rows(api)[2]
    assert m2["modifyReason"] == "change_request" and m2["before"] == {"time": "16:30"}
    ok(register(api, m2["id"]))
    assert [r["status"] for r in rows(api)] == ["superseded", "superseded", "modified"]


def test_pool_rotates():
    from app.service import resv_demo as D
    names = [D.sample(i, BASE)["customer"]["name"] for i in range(4)]
    assert names == ["[TW] LIN YA CHEN", "[JP] TANAKA YUKI", "[HK] CHAN MEI LING", "[TW] LIN YA CHEN"]


def test_errors(api):
    assert conflict(api.post("/api/reservations/demo/modify")) == "no_modify_target"
    req(api)  # requested 만 있으면 수정 대상 없음
    assert conflict(api.post("/api/reservations/demo/modify")) == "no_modify_target"
    rid = rows(api)[0]["id"]
    for reason in ("", "   "):
        r = change(api, rid, reason)
        assert r.status_code == 400 and r.json()["error"]["code"] == "empty_reason"
    r = api.post(f"/api/reservations/{rid}/change-request", json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert row(api, rid)["status"] == "requested"
    assert register(api, 999).status_code == 404
    assert register(api, 999).json()["error"]["code"] == "reservation_not_found"


def test_failed_op_keeps_version(api):
    v = ok(api.get("/api/reservations"))["version"]
    api.post("/api/reservations/demo/modify")
    change(api, 1, "")
    assert ok(api.get("/api/reservations"))["version"] == v


def test_version_shared_with_board_and_sse(api, container):
    seen = []
    container.bus.publish = seen.append
    v = api.get("/api/board").json()["version"]
    assert req(api) == {"version": v + 1}
    assert seen == [v + 1]
    assert api.get("/api/board").json()["version"] == v + 1


def test_reset_clears_reservations(api):
    req(api)
    ok(register(api, 1))
    req(api)
    v = ok(api.post("/api/admin/reset"))["version"]
    body = ok(api.get("/api/reservations"))
    assert body["rows"] == [] and body["counts"]["total"] == 0 and body["version"] == v
    req(api)  # 풀도 처음부터, id 도 1부터
    r = rows(api)[0]
    assert (r["id"], r["customer"]["name"]) == (1, "[TW] LIN YA CHEN")
    assert api.get("/api/board").status_code == 200  # 1차 시드도 그대로


def test_reset_without_seed_keeps_rows(api, container):
    req(api)
    container.settings.seed_path.unlink()
    assert api.post("/api/admin/reset").status_code == 404
    assert len(rows(api)) == 1


def test_register_has_kos_comment():
    src = inspect.getsource(RS.ReservationService.register)
    assert src.count(MARK) == 2
    assert "예약 생성" in src and "예약 변경" in src
