"""WORK-009 WP-BE3 — 띄우기 요청(SPEC-004 §5-3 · §8.6 「띄우기」). 가짜 APNs · KOS 없음(예약 행은 시험이 넣는다)."""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.main import create_app
from app.push.apns import ApnsClient
from app.service.push import PushService
from tests.conftest import PW, make_settings
from tests.helpers import T0
from tests.test_push import FakeApns, tok

IDS = {"admin": "admin1", "coordinator": "coord1", "nurse": "nurse1"}


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "AuthKey_TEST.p8"
    path.write_bytes(ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    s = make_settings(tmp_path, ccc_admin_id=IDS["admin"], ccc_coord_id=IDS["coordinator"], ccc_nurse_id=IDS["nurse"],
                      apns_key_path=str(path), apns_key_id="KEYID00001", apns_team_id="TEAMID0001",
                      apns_bundle_id="com.example.procedure", apns_env="sandbox")
    apns = FakeApns()
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        c.clock.set(T0)
        c.push = PushService(c.repo, s, client=ApnsClient(s, transport=httpx.MockTransport(apns.handle)), clock=c.clock,
                             notifications=c.notifications)
        sent = []
        c.display.push = lambda rid: sent.append(rid)  # 발송은 시험이 notify_display 로
        with c.repo.tx() as tx:
            cust = tx.upsert("customer", "vis-1", {"name": "고객이름", "nationality": "JP"})
            rid = tx.upsert("reservation", "sch-1", {"customer_id": cust, "day": "2026-10-21"})
            rid2 = tx.upsert("reservation", "sch-2", {"customer_id": cust, "day": "2026-10-21"})
            acc = {a.login_id: a for a in tx.accounts()}
        login = {k: client.post("/api/auth/login", json={"id": v, "password": PW[k]}).json() for k, v in IDS.items()}
        auth = {k: {"Authorization": f"Bearer {v['token']}"} for k, v in login.items()}
        dev = {}  # 코디 계정 기기 둘(태블릿 · 폰) + 관리자 기기
        for name, role, kind in (("tab", "coordinator", "tablet"), ("phone", "coordinator", "phone"), ("adm", "admin", "phone")):
            r = client.post("/api/devices", json={"token": tok(name), "kind": kind, "name": name}, headers=auth[role])
            dev[name] = r.json()["deviceId"]
        yield client, c, apns, auth, dev, sent, (rid, rid2, cust), acc


def create(client, auth, rid, kind="questionnaire", device=None):
    body = {"reservationId": rid, "kind": kind, **({"deviceId": device} if device else {})}
    r = client.post("/api/display-requests", json=body, headers=auth)
    assert r.status_code == 200, r.json()
    return r.json()


def rows(c):
    with c.repo.db.connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM display_request ORDER BY id")]


def test_display_create_cancels_previous_and_hash_only(env):
    client, c, apns, auth, dev, sent, (rid, rid2, _), acc = env
    a = create(client, auth["coordinator"], rid, "scan")
    assert set(a) == {"id", "qrToken", "qrUrl", "expiresAt"} and len(a["qrToken"]) >= 40 and a["qrUrl"] is None
    assert a["expiresAt"] == "2026-10-21T11:10:00+09:00"
    b = create(client, auth["coordinator"], rid, "scan")
    s = create(client, auth["coordinator"], rid)  # 다른 종류(문진)는 그대로
    create(client, auth["coordinator"], rid2, "scan")  # 다른 예약도 그대로
    st = {r["id"]: r["status"] for r in rows(c)}
    assert st[a["id"]] == "canceled" and st[b["id"]] == "pending" and st[s["id"]] == "pending"
    dump = json.dumps(rows(c))
    assert a["qrToken"] not in dump and b["qrToken"] not in dump  # 해시만
    assert s["qrToken"] is None and s["qrUrl"].split("#", 1)[1] not in dump  # 문진 = 링크(원문 0)
    assert all(len(r["qr_token_hash"]) == 64 for r in rows(c))
    r = client.post("/api/display-requests", json={"reservationId": 999, "kind": "scan"}, headers=auth["admin"])
    assert r.status_code == 404
    r = client.post("/api/display-requests", json={"reservationId": rid, "kind": "x"}, headers=auth["admin"])
    assert r.status_code == 400


@pytest.mark.parametrize("role", ["admin", "coordinator", "nurse"])
def test_display_roles_open(env, role):
    client, c, apns, auth, dev, sent, (rid, *_), acc = env
    assert client.get("/api/devices/targets", headers=auth[role]).status_code == 200
    q = create(client, auth[role], rid)
    assert client.post(f"/api/display-requests/{q['id']}/close", json={"status": "canceled"},
                       headers=auth[role]).status_code == 200


def test_display_sse_to_that_device_only(env):
    """같은 코디 계정 태블릿 · 폰 — 태블릿으로 보낸 요청은 태블릿 스트림 · pending 에만(r2)."""
    client, c, apns, auth, dev, sent, (rid, *_), acc = env
    hub = c.hub
    coord = acc[IDS["coordinator"]].id

    async def go():
        tab = hub.frames(ping_sec=5, account_id=coord, device_id=dev["tab"])
        phone = hub.frames(ping_sec=5, account_id=coord, device_id=dev["phone"])
        await tab.__anext__(), await phone.__anext__()
        q = create(client, auth["admin"], rid, device=dev["tab"])
        frame = await asyncio.wait_for(tab.__anext__(), 1)
        assert frame == ("event: display\ndata: " + json.dumps(
            {"requestId": q["id"], "deviceId": dev["tab"], "kind": "questionnaire", "reservationId": rid,
             "qrUrl": q["qrUrl"]}) + "\n\n")  # 문진 = 고객 웹 링크(SPEC-006 §6.6)
        with pytest.raises(TimeoutError):  # 폰 0(시간 초과가 생성기를 닫으므로 끝에)
            await asyncio.wait_for(phone.__anext__(), 0.1)
        await tab.aclose()
        return q

    q = asyncio.run(go())
    assert sent == [q["id"]]  # SSE 로 보내도 푸시도 1(E2E batch 2 — 둘 다)
    got = client.get(f"/api/display-requests/pending?deviceId={dev['phone']}", headers=auth["coordinator"]).json()
    assert got == {"items": []}
    got = client.get(f"/api/display-requests/pending?deviceId={dev['tab']}", headers=auth["coordinator"]).json()
    assert got == {"items": [{"requestId": q["id"], "kind": "questionnaire", "reservationId": rid,
                              "customerId": rows(c)[0]["customer_id"], "deviceId": dev["tab"], "status": "pending",
                              "expiresAt": q["expiresAt"], "qrUrl": q["qrUrl"]}]}
    assert rows(c)[0]["status"] == "pending"  # 문진 = 돌려줘도 pending(opened = 고객이 엶 · SPEC-006 §6.6)
    again = client.get(f"/api/display-requests/pending?deviceId={dev['tab']}", headers=auth["coordinator"]).json()
    assert [x["requestId"] for x in again["items"]] == [q["id"]]  # 열린 것은 닫힐 때까지 다시 나온다


def test_display_push_when_offline(env):
    client, c, apns, auth, dev, sent, (rid, *_), acc = env
    q = create(client, auth["admin"], rid, "scan", device=dev["tab"])
    assert sent == [q["id"]]  # SSE 없음 → 띄우기 푸시
    assert asyncio.run(c.push.notify_display(q["id"]))["sent"] == 1
    assert apns.tokens() == [tok("tab")]
    p = apns.requests[0]["payload"]
    assert p == {"aps": {"alert": {"title": "여권 스캔 요청", "body": "데스크에서 보냈어요"}}, "kind": "display",
                 "requestId": q["id"]}
    assert "sound" not in p["aps"] and "content-available" not in p["aps"] and "고객이름" not in json.dumps(p)
    with c.repo.tx() as tx:
        logs = tx.push_logs()
    assert [(x["kind"], x["display_request_id"], x["notification_id"], x["status"]) for x in logs] == [
        ("display", q["id"], None, "sent")]
    assert client.get("/api/notifications", headers=auth["coordinator"]).json() == {"unread": 0, "items": []}  # 목록 0


def test_display_wired_push_without_key(tmp_path):
    """컨테이너 연결 — 키 없음이어도 그 기기 push_log display skipped_no_key 1행."""
    s = make_settings(tmp_path, ccc_coord_id=IDS["coordinator"])
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        with c.repo.tx() as tx:
            rid = tx.upsert("reservation", "sch-1", {"day": "2026-10-21"})
        a = {"Authorization": "Bearer " + client.post(
            "/api/auth/login", json={"id": IDS["coordinator"], "password": PW["coordinator"]}).json()["token"]}
        d = client.post("/api/devices", json={"token": tok("tab")}, headers=a).json()["deviceId"]
        create(client, a, rid, device=d)
        with c.repo.tx() as tx:
            assert [(x["kind"], x["status"], x["device_id"]) for x in tx.push_logs()] == [("display", "skipped_no_key", d)]


def test_display_pending_requires_own_device(env):
    client, c, apns, auth, dev, sent, (rid, *_), acc = env
    r = client.get("/api/display-requests/pending", headers=auth["coordinator"])
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    r = client.get(f"/api/display-requests/pending?deviceId={dev['adm']}", headers=auth["coordinator"])  # 남의 계정 기기
    assert (r.status_code, r.json()["error"]["code"]) == (404, "device_not_found")
    r = client.get("/api/display-requests/pending?deviceId=9999", headers=auth["coordinator"])
    assert (r.status_code, r.json()["error"]["code"]) == (404, "device_not_found")


def test_display_claim_once_expiry_and_device(env):
    client, c, apns, auth, dev, sent, (rid, rid2, cust), acc = env
    q = create(client, auth["admin"], rid, "scan", device=dev["tab"])  # 태블릿으로 보냈지만 폰이 QR 을 찍음
    r = client.post("/api/display-requests/claim", json={"qrToken": q["qrToken"], "deviceId": dev["adm"]},
                    headers=auth["coordinator"])
    assert (r.status_code, r.json()["error"]["code"]) == (404, "device_not_found")  # 남의 계정 기기
    r = client.post("/api/display-requests/claim", json={"qrToken": q["qrToken"], "deviceId": dev["phone"]},
                    headers=auth["coordinator"])
    assert r.status_code == 200 and (r.json()["deviceId"], r.json()["status"]) == (dev["phone"], "opened")
    r = client.post("/api/display-requests/claim", json={"qrToken": q["qrToken"]}, headers=auth["coordinator"])
    assert (r.status_code, r.json()["error"]["code"]) == (409, "display_closed")  # 1회
    r = client.post("/api/display-requests/claim", json={"qrToken": "nope"}, headers=auth["coordinator"])
    assert (r.status_code, r.json()["error"]["code"]) == (404, "display_not_found")
    qr = create(client, auth["admin"], rid2, "scan")  # QR 만 — deviceId 없이 claim = device_id 그대로(null)
    r = client.post("/api/display-requests/claim", json={"qrToken": qr["qrToken"]}, headers=auth["coordinator"])
    assert r.json()["deviceId"] is None and r.json()["status"] == "opened"
    late = create(client, auth["admin"], rid, "scan")
    c.clock.set(T0 + timedelta(minutes=10))  # 10분 뒤 expired
    r = client.post("/api/display-requests/claim", json={"qrToken": late["qrToken"]}, headers=auth["coordinator"])
    assert (r.status_code, r.json()["error"]["code"]) == (409, "display_expired")
    assert {x["id"]: x["status"] for x in rows(c)}[late["id"]] == "expired"


def test_display_expired_not_in_pending(env):
    client, c, apns, auth, dev, sent, (rid, *_), acc = env
    create(client, auth["admin"], rid, device=dev["tab"])
    c.clock.set(T0 + timedelta(minutes=11))
    got = client.get(f"/api/display-requests/pending?deviceId={dev['tab']}", headers=auth["coordinator"]).json()
    assert got == {"items": []}


def test_display_close_and_detail_displays(env):
    client, c, apns, auth, dev, sent, (rid, *_), acc = env
    q = create(client, auth["admin"], rid, device=dev["tab"])
    r = client.post(f"/api/display-requests/{q['id']}/close", json={"status": "done"}, headers=auth["coordinator"])
    assert r.json() == {"ok": True}
    r = client.post(f"/api/display-requests/{q['id']}/close", json={"status": "canceled"}, headers=auth["admin"])
    assert (r.status_code, r.json()["error"]["code"]) == (409, "display_closed")
    assert client.post("/api/display-requests/999/close", json={"status": "done"},
                       headers=auth["admin"]).status_code == 404
    assert client.post(f"/api/display-requests/{q['id']}/close", json={"status": "opened"},
                       headers=auth["admin"]).status_code == 400
    with c.repo.tx() as tx:
        items = c.display.of_reservation(tx, rid)
    assert items == [{"id": q["id"], "kind": "questionnaire", "status": "done", "deviceName": "tab",
                      "createdAt": "2026-10-21T11:00:00+09:00", "openedAt": None,
                      "closedAt": "2026-10-21T11:00:00+09:00", "qrUrl": None}]
    assert c.resv.displays_of == c.display.of_reservation  # 상세 응답에 붙는다


def test_display_targets_coordinator_24h(env):
    client, c, apns, auth, dev, sent, (rid, *_), acc = env
    with c.repo.tx() as tx:
        tx.touch_device(dev["phone"], T0 + timedelta(minutes=5))
        tx.touch_device(dev["tab"], T0 - timedelta(hours=25))  # 24시간 밖
    got = client.get("/api/devices/targets", headers=auth["admin"]).json()
    assert [x["deviceId"] for x in got] == [dev["phone"]]  # 관리자 기기 = 목록 밖
    assert got[0] == {"deviceId": dev["phone"], "name": "phone", "kind": "phone",
                      "lastSeenAt": "2026-10-21T11:05:00+09:00", "online": False}
    with c.repo.tx() as tx:
        tx.touch_device(dev["tab"], T0 + timedelta(minutes=9))

    async def go():
        g = c.hub.frames(ping_sec=5, account_id=acc[IDS["coordinator"]].id, device_id=dev["tab"])
        await g.__anext__()
        out = client.get("/api/devices/targets", headers=auth["admin"]).json()
        await g.aclose()
        return out

    got = asyncio.run(go())
    assert [(x["deviceId"], x["online"]) for x in got] == [(dev["tab"], True), (dev["phone"], False)]  # 최근 순


def test_display_api_create_push_log_row(env):
    """리뷰 r1 FAIL-1 — API 만들기(기기 SSE 없음) → 이벤트 루프에서 띄우기 푸시 → push_log display 1행."""
    import time

    client, c, apns, auth, dev, sent, (rid, *_), acc = env
    c.display.push = lambda request_id: c.push.schedule_display(request_id)  # 컨테이너 연결 그대로
    q = create(client, auth["admin"], rid, "scan", device=dev["tab"])
    deadline = time.time() + 3
    rows = []
    while time.time() < deadline:
        with c.repo.tx() as tx:
            rows = tx.push_logs()
        if rows:
            break
        time.sleep(0.02)
    assert [(x["kind"], x["display_request_id"], x["device_id"], x["status"]) for x in rows] == [
        ("display", q["id"], dev["tab"], "sent")]
    assert apns.tokens() == [tok("tab")]
