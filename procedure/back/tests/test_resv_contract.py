"""WORK-007 WP-BE0 — 예약 현황 계약 뼈대(SPEC-005 §7): 가짜 응답 모양 · 조작 403 fake_board · 401 · 오류 본문."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.reservations import CustomerSearch, ReservationBoard, ReservationDetail, ReservationForm
from tests.conftest import ADMIN, make_settings

OPS = [
    ("post", "/api/reservations", {"groupId": 1, "start": "2026-10-26T10:00:00+09:00", "customer": {"customerId": 1},
                                   "consultationRequired": True, "sedationRequired": False, "doctorStaffIds": []}),
    ("post", "/api/reservations/1/move", {"resourceIndex": 0, "groupId": 1, "start": "2026-10-26T10:00:00+09:00"}),
    ("post", "/api/reservations/1/cancel", {"reason": "CANCELED"}),
    ("put", "/api/reservations/1/memo", {"memo": ""}),
    ("put", "/api/reservations/1/route", {"consultationRequired": False}),
    ("post", "/api/reservations/1/reception", {"roomId": 1}),
    ("post", "/api/reservations/1/counselor-call", {"staffId": 1}),
    ("post", "/api/reservations/1/discharge", None),
    ("put", "/api/customers/1/personal", {"personal": {"passportNumber": "X1"}}),
    ("put", "/api/customers/1/remark", {"memo": "m"}),
    ("put", "/api/customers/1/identity", {"status": "confirmed"}),
]


@pytest.fixture
def fake(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, proc_fake_board=True))) as c:
        tok = c.post("/api/auth/login", json=ADMIN).json()["token"]
        c.headers.update({"Authorization": f"Bearer {tok}"})
        yield c


def test_board_shape(fake):
    body = fake.get("/api/reservations/board").json()
    ReservationBoard.model_validate(body)
    assert set(body) == {"date", "isToday", "now", "sync", "axis", "zones", "columns", "cards", "slots", "rows", "counts",
                         "notices", "requests", "clinic"}
    assert body["isToday"] and body["now"].endswith("+09:00") and body["requests"] == []
    cols = body["columns"]
    assert len(cols) == 14 and cols[-1]["groupId"] is None and cols[-1]["title"] == "그룹 없음"
    assert sum(1 for c in cols if len(c["capacities"]) == 2) == 1 and len(body["zones"]) == 2
    mains = {c["state"]["main"] for c in body["cards"]}
    assert mains == {"reserved", "reception", "consultation", "procedure", "home", "canceled", "noshow"}
    assert any(c["paymentRequiredCount"] >= 1 for c in body["cards"])
    assert any(not r["plusAllowed"] for r in body["rows"]) and any(s["full"] for s in body["slots"])
    assert len({i["zoneId"] for i in body["clinic"]["items"]}) == 2
    assert body["counts"]["total"] == sum(v for k, v in body["counts"].items() if k not in ("total", "canceled", "noshow"))
    assert len(body["notices"]) == 1


def test_board_other_day_has_no_clinic(fake):
    body = fake.get("/api/reservations/board?date=2030-01-01").json()
    assert body["date"] == "2030-01-01" and body["isToday"] is False and body["clinic"] is None


@pytest.mark.parametrize("bad", ["2026-1-1", "x", "2026-13-01"])
def test_board_bad_date_400(fake, bad):
    r = fake.get(f"/api/reservations/board?date={bad}")
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")


def test_detail_every_reservation(fake):
    ids = {c["reservationId"] for c in fake.get("/api/reservations/board").json()["cards"]}
    seen = set()
    for rid in ids:
        body = fake.get(f"/api/reservations/{rid}").json()
        d = ReservationDetail.model_validate(body)
        seen.add((d.state.main, d.receiveMode, d.roomLocked, d.customer.identity.complete))
    assert ("noshow", "new", False, True) in seen  # 부도 — 접수 가능
    assert ("reception", "resume", True, True) in seen  # 이어 하기 · 방 고정
    assert any(m == "reserved" and not complete for m, _, _, complete in seen)  # 신분 칸 빔
    assert fake.get("/api/reservations/999").json()["error"]["code"] == "not_found"


def test_detail_settlement_and_locked_room(fake):
    home = ReservationDetail.model_validate(fake.get("/api/reservations/8").json())
    assert home.settlement and home.settlement.paymentRequiredCount == 1 and not home.can.discharge
    resume = ReservationDetail.model_validate(fake.get("/api/reservations/3").json())
    assert [r.roomId for r in resume.rooms if r.selected] and resume.can.receive


def test_form_and_search(fake):
    form = ReservationForm.model_validate(fake.get("/api/reservations/form").json())
    assert form.defaultZoneId is not None and form.defaultAssigneeStaffId is not None
    s = CustomerSearch.model_validate(fake.get("/api/customers/search?name=고객 A").json())
    assert s.pageSize == 20 and s.total > 20 and len(s.items) == 20
    assert len(fake.get("/api/customers/search?name=고객 A&page=2").json()["items"]) == s.total - 20
    assert fake.get("/api/customers/search").json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(("method", "path", "body"), OPS)
def test_ops_fake_board_403(fake, method, path, body):
    r = getattr(fake, method)(path, json=body) if body is not None else getattr(fake, method)(path)
    assert (r.status_code, r.json()["error"]["code"]) == (403, "fake_board")


@pytest.mark.parametrize(("method", "path", "body"), OPS)
def test_ops_require_login(tmp_path, method, path, body):
    with TestClient(create_app(make_settings(tmp_path, proc_fake_board=True))) as c:
        r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
        assert (r.status_code, r.json()["error"]["code"]) == (401, "unauthorized")


def test_gets_require_login(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, proc_fake_board=True))) as c:
        for path in ("/api/reservations/board", "/api/reservations/1", "/api/reservations/form", "/api/customers/search?name=a"):
            assert c.get(path).status_code == 401


def test_error_body_carries_extra(client):
    """오류 본문 `{error:{code, message, step?, candidate?, fields?}}`(§7.1) — None 은 싣지 않는다."""
    from app.domain.errors import Conflict

    app = client.app

    @app.get("/__boom")
    def boom():
        raise Conflict("kos_rejected", "거절", step="recept", candidate=None)

    assert client.get("/__boom").json() == {"error": {"code": "kos_rejected", "message": "거절", "step": "recept"}}


def test_real_mode_without_kos(client, auth):
    """실제 경로(가짜 아님 · KOS env 없음) — 조회는 사본 + lastError · 조작은 404 → 502 · 신분 표시는 ccc 만."""
    b = client.get("/api/reservations/board?date=2026-10-21", headers=auth)
    assert b.status_code == 200 and b.json()["sync"]["lastError"] == "KOS 설정이 비어 있어요" and b.json()["cards"] == []
    assert client.get("/api/reservations/1", headers=auth).json()["error"]["code"] == "not_found"
    assert client.post("/api/reservations/1/cancel", json={"reason": "CANCELED"}, headers=auth).status_code == 404
    assert client.post("/api/reservations/1/cancel", json={"reason": "X"}, headers=auth).status_code == 400
    c = client.app.state.container
    with c.repo.tx() as tx:
        cid = tx.upsert("customer", "cust-x", {"name": "고객 X"})
        tx.upsert("reservation", "sch-x", {"customer_id": cid, "status": "RESERVED", "flow_step": "RESERVED",
                                           "day": "2026-10-21"})
    r = client.post("/api/reservations/1/cancel", json={"reason": "CANCELED"}, headers=auth)
    assert (r.status_code, r.json()["error"]["code"]) == (502, "kos_unavailable")
    assert client.put(f"/api/customers/{cid}/identity", json={"status": "confirmed"}, headers=auth).json() == {"ok": True}
    form = client.get("/api/reservations/form", headers=auth)
    assert form.status_code == 200 and form.json()["zones"] == []
    assert client.get("/api/customers/search?name=a", headers=auth).json()["error"]["code"] == "kos_unavailable"
