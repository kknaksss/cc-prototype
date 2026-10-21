"""SPEC-004 WP11 — 원장 호출 푸시(§5-1 · §8.1 푸시 ① ~ ⑥). 가짜 APNs(요청을 적고 응답 코드를 고른다) · 키는 시험이 만든 것."""

import asyncio
import json
import logging
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.main import create_app
from app.push.apns import ApnsClient
from app.service.push import PushService
from tests.conftest import make_settings
from tests.helpers import T0, seed_staff, seed_visit

IDS = {"admin": "admin1", "doctor": "doctor1", "nurse": "nurse1"}


def tok(name: str) -> str:
    """가짜 기기 토큰(16진 64자)."""
    return (name.encode().hex() * 64)[:64]


class FakeApns:
    def __init__(self):
        self.requests: list[dict] = []
        self.status: dict[str, int] = {}  # 토큰 → 돌려줄 상태(기본 200)
        self.reason: dict[str, str] = {}  # 토큰 → 돌려줄 reason(기본 = 상태별)

    def handle(self, req: httpx.Request) -> httpx.Response:
        token = req.url.path.rsplit("/", 1)[-1]
        self.requests.append({"host": req.url.host, "token": token, "headers": dict(req.headers),
                              "payload": json.loads(req.content)})
        code = self.status.get(token, 200)
        reasons = {410: "Unregistered", 400: "BadDeviceToken", 500: "InternalServerError", 429: "TooManyRequests"}
        reason = self.reason.get(token) or reasons.get(code)
        return httpx.Response(code, json={"reason": reason} if code != 200 else None,
                              headers={"apns-id": f"00000000-0000-0000-0000-{len(self.requests):012d}"})

    def tokens(self) -> list[str]:
        return [r["token"] for r in self.requests]


@pytest.fixture
def key(tmp_path):
    pk = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "AuthKey_TEST.p8"
    path.write_bytes(pk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    return path, pk.public_key()


@pytest.fixture
def env(tmp_path, key):
    s = make_settings(tmp_path, ccc_admin_id=IDS["admin"], ccc_doctor_id=IDS["doctor"], ccc_doctor_kos_account_id="doc-a",
                      ccc_nurse_id=IDS["nurse"], ccc_nurse_name="간호 A", apns_key_path=str(key[0]), apns_key_id="KEYID00001",
                      apns_team_id="TEAMID0001", apns_bundle_id="com.example.procedure", apns_env="sandbox")
    fake = FakeApns()
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        c.clock.set(T0)
        staff = seed_staff(c.repo)
        c.accounts.sync()
        c.push = PushService(c.repo, s, client=ApnsClient(s, transport=httpx.MockTransport(fake.handle)))
        c.actions.on_call = c.push.schedule
        with c.repo.tx() as tx:  # 계정마다 기기 1대
            acc = {a.login_id: a for a in tx.accounts()}
            for login in acc:
                tx.put_device(acc[login].id, tok(login), T0)
        yield client, c, staff, fake, acc


def notify(c, call_id, actor):
    return asyncio.run(c.push.notify(call_id, actor))


def new_call(c, n, kind="all", target=None, procs=1, actor="setup"):
    v = seed_visit(c.repo, n, procs=procs)
    return c.actions.create_call(actor, v["visit"], v["procs"], kind, target), v


# ------------------------------------------------------------------ ① 받는 사람
def test_recipients(env):
    client, c, staff, fake, acc = env
    admin, nurse, doc_a = tok(IDS["admin"]), tok(IDS["nurse"]), tok(IDS["doctor"])
    doc_b, doc_c = tok(f"doctor-{staff['B']}"), tok(f"doctor-{staff['C']}")

    call, _ = new_call(c, 1)  # 전체 호출(간호사가 누름) = 관리자 + 의사 전원 · 간호사 0
    notify(c, call, IDS["nurse"])
    assert sorted(fake.tokens()) == sorted([admin, doc_a, doc_b, doc_c]) and nurse not in fake.tokens()

    fake.requests.clear()  # 지정 호출(관리자가 누름) = 그 원장 + 관리자(자기가 누른 것도)
    call, _ = new_call(c, 2, "one", staff["B"])
    notify(c, call, IDS["admin"])
    assert sorted(fake.tokens()) == sorted([admin, doc_b])

    fake.requests.clear()  # 의사가 누른 전체 호출 = 그 의사 자신 제외
    call, _ = new_call(c, 3)
    notify(c, call, IDS["doctor"])
    assert sorted(fake.tokens()) == sorted([admin, doc_b, doc_c])

    fake.requests.clear()  # 비활성 의사 제외
    with c.repo.tx() as tx:
        tx.update_account(acc[f"doctor-{staff['C']}"].id, T0, active=False)
    call, _ = new_call(c, 4)
    notify(c, call, IDS["nurse"])
    assert doc_c not in fake.tokens() and len(fake.tokens()) == 3

    fake.requests.clear()  # [다른 원장에게](새 전체 호출)도 발송
    one, _ = new_call(c, 5, "one", staff["B"])
    new = c.actions.reassign_all(IDS["nurse"], one)
    notify(c, new, IDS["nurse"])
    assert sorted(fake.tokens()) == sorted([admin, doc_a, doc_b])


def test_api_call_schedules_push_after_commit(env):
    """조작 API 응답 뒤 비동기로 발송 — 지정 호출 + [다른 원장에게](새 전체 호출) 둘 다."""
    client, c, staff, fake, acc = env
    v = seed_visit(c.repo, 1, procs=2)
    auth = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'id': IDS['nurse']}).json()['token']}"}
    body = {"procedureIds": v["procs"][:1], "target": {"kind": "one", "doctorId": staff["A"]}}
    one = client.post(f"/api/visits/{v['visit']}/calls", json=body, headers=auth).json()["callId"]
    new = client.post(f"/api/calls/{one}/reassign-all", headers=auth).json()["callId"]
    deadline = time.time() + 3
    while len(fake.requests) < 6 and time.time() < deadline:  # 지정(관리자 + A) 2 + 전체(관리자 + A · B · C) 4
        time.sleep(0.02)
    assert len(fake.requests) == 6
    assert sorted(r["payload"]["callId"] for r in fake.requests) == [one] * 2 + [new] * 4


# ------------------------------------------------------------------ ② 내용 · 헤더
def test_content_and_headers(env, key):
    client, c, staff, fake, acc = env
    call, v = new_call(c, 1, procs=2)
    notify(c, call, IDS["nurse"])
    req = fake.requests[0]
    assert req["host"] == "api.sandbox.push.apple.com"
    alert = {"title": "원장 호출", "body": "A-룸1 · 시술 2건 · 전체 호출"}
    by_token = {r["token"]: r["payload"] for r in fake.requests}
    # 관리자 = category 없음(앱에서 원장 고름) · 의사 = category CALL(알림 · 워치에서 바로 수락)
    assert by_token[tok(IDS["admin"])] == {"aps": {"alert": alert, "sound": "default"}, "visitId": v["visit"], "callId": call}
    assert by_token[tok(IDS["doctor"])] == {"aps": {"alert": alert, "sound": "default", "category": "CALL"},
                                            "visitId": v["visit"], "callId": call}
    assert all(p["aps"].get("category") == "CALL" for t, p in by_token.items() if t != tok(IDS["admin"]))
    text = json.dumps(req["payload"], ensure_ascii=False)
    assert "고객1" not in text and "시술1" not in text and "KR" not in text  # 고객 이름 · 시술 이름 · 국적 없음
    h = req["headers"]
    assert (h["apns-topic"], h["apns-push-type"], h["apns-priority"], h["apns-expiration"]) == (
        "com.example.procedure", "alert", "10", "0")
    token = h["authorization"].removeprefix("bearer ")
    assert jwt.get_unverified_header(token) == {"alg": "ES256", "kid": "KEYID00001", "typ": "JWT"}
    assert jwt.decode(token, key[1], algorithms=["ES256"])["iss"] == "TEAMID0001"
    fake.requests.clear()
    one, _ = new_call(c, 2, "one", staff["A"], procs=1)
    notify(c, one, IDS["nurse"])
    assert fake.requests[0]["payload"]["aps"]["alert"]["body"] == "A-룸2 · 시술 1건 · 지정 호출"
    cats = {r["token"]: r["payload"]["aps"].get("category") for r in fake.requests}
    assert cats == {tok(IDS["admin"]): None, tok(IDS["doctor"]): "CALL"}  # 지정 = 그 원장만 CALL
    assert len({r["headers"]["authorization"] for r in fake.requests}) == 1  # JWT 재사용(40분)


# ------------------------------------------------------------------ ③ 실패 처리
def test_failures(env):
    client, c, staff, fake, acc = env
    gone, err, bad, busy = (tok(IDS["doctor"]), tok(f"doctor-{staff['B']}"), tok(f"doctor-{staff['C']}"),
                            tok(IDS["admin"]))
    fake.status = {gone: 410, err: 500, bad: 400, busy: 429}
    call, _ = new_call(c, 1)
    out = notify(c, call, IDS["nurse"])
    n = {t: fake.tokens().count(t) for t in (gone, err, bad, busy)}
    assert n == {gone: 1, err: 2, bad: 1, busy: 2}  # 5xx · 429 = 1회 재시도 뒤 멈춤 · 410 · 400 = 재시도 없음
    assert out == {"sent": 0, "failed": 4, "removed": 2}
    with c.repo.tx() as tx:
        left = set(tx.device_tokens([a.id for a in tx.accounts()]))
    assert gone not in left and bad not in left and err in left  # 410 · 400 BadDeviceToken 삭제 · 5xx 는 남김


# ------------------------------------------------------------------ ④ APNS_* 비면 발송 0 · 조작 성공
def test_disabled_without_apns_env(tmp_path, caplog):
    s = make_settings(tmp_path, ccc_admin_id=IDS["admin"])
    with caplog.at_level(logging.INFO), TestClient(create_app(s)) as client:
        c = client.app.state.container
        assert c.push.enabled is False and c.push.client is None
        seed_staff(c.repo)
        v = seed_visit(c.repo, 1, procs=1)
        login = client.post("/api/auth/login", json={"id": IDS["admin"]}).json()["token"]
        r = client.post(f"/api/visits/{v['visit']}/calls", json={"procedureIds": v["procs"], "target": {"kind": "all"}},
                        headers={"Authorization": f"Bearer {login}"})
        assert r.status_code == 200
        assert asyncio.run(c.push.notify(r.json()["callId"], IDS["admin"])) == {"sent": 0, "failed": 0, "removed": 0}
        with c.repo.tx() as tx:
            assert tx.push_logs() == []  # 등록된 기기가 없으면 내역도 없음
            tx.put_device(tx.account(IDS["admin"]).id, tok("admin-ipad"), T0)
        r = client.post(f"/api/visits/{v['visit']}/calls", json={"procedureIds": v["procs"], "target": {"kind": "all"}},
                        headers={"Authorization": f"Bearer {login}"})
        assert r.status_code == 200  # 대기 시술 재호출(새 유효 호출)
        with c.repo.tx() as tx:
            rows = tx.push_logs()
        assert [(x["call_id"], x["role"], x["status"], x["attempts"], x["apns_status"]) for x in rows] == [
            (r.json()["callId"], "admin", "skipped_no_key", 0, None)]  # 키 없음 = 받는 기기마다 skipped 로 쌓기만

    assert "APNS_* 가 비어" in caplog.text and "건너뜀" in caplog.text


# ------------------------------------------------------------------ ⑤ 기기 등록 · 삭제
def test_devices_api(env):
    client, c, staff, fake, acc = env

    def auth(role):
        return {"Authorization": f"Bearer {client.post('/api/auth/login', json={'id': IDS[role]}).json()['token']}"}

    t = tok("shared-ipad")
    assert client.post("/api/devices", json={"token": t}, headers=auth("admin")).json() == {"ok": True}
    assert client.post("/api/devices", json={"token": t.upper()}, headers=auth("doctor")).json() == {"ok": True}
    with c.repo.tx() as tx:  # 한 기기 = 마지막 로그인 계정
        assert t in tx.device_tokens([acc[IDS["doctor"]].id]) and t not in tx.device_tokens([acc[IDS["admin"]].id])
    assert client.delete(f"/api/devices/{t}", headers=auth("nurse")).json() == {"ok": True}  # 남의 토큰
    with c.repo.tx() as tx:
        assert t in tx.device_tokens([acc[IDS["doctor"]].id])  # 안 지워짐
    assert client.delete(f"/api/devices/{t}", headers=auth("doctor")).json() == {"ok": True}
    with c.repo.tx() as tx:
        assert t not in tx.device_tokens([acc[IDS["doctor"]].id])
    assert client.delete("/api/devices/" + tok("none"), headers=auth("doctor")).json() == {"ok": True}  # 없는 것
    r = client.post("/api/devices", json={"token": "not-hex"}, headers=auth("doctor"))
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert client.post("/api/devices", json={"token": t}).status_code == 401


# ------------------------------------------------------------------ ⑥ 로그에 토큰 전체 · JWT · 키 0
def test_logs_have_no_secrets(env, key, caplog):
    client, c, staff, fake, acc = env
    fake.status = {tok(IDS["admin"]): 410, tok(IDS["doctor"]): 400}
    with caplog.at_level(logging.DEBUG):
        call, _ = new_call(c, 1)
        notify(c, call, IDS["nurse"])
    jwt_value = fake.requests[0]["headers"]["authorization"].removeprefix("bearer ")
    text = caplog.text
    assert "…" + tok(IDS["admin"])[-6:] in text  # 끝 6자리만
    for t in (tok(IDS["admin"]), tok(IDS["doctor"])):
        assert t not in text
    assert jwt_value not in text and "TEAMID0001" not in text and "PRIVATE KEY" not in text
    assert key[0].read_text() not in text


# ------------------------------------------------------------------ push_log(쌓기만) · 수락 출처
def test_push_log_rows(env):
    client, c, staff, fake, acc = env
    call, v = new_call(c, 1)
    notify(c, call, IDS["nurse"])  # 받는 사람 = 관리자 + 의사 3
    with c.repo.tx() as tx:
        rows = tx.push_logs()
    assert len(rows) == 4 and {x["status"] for x in rows} == {"sent"}
    by_role = sorted((x["role"], x["category"]) for x in rows)
    assert by_role == [("admin", None), ("doctor", "CALL"), ("doctor", "CALL"), ("doctor", "CALL")]
    one = rows[0]
    assert one["call_id"] == call and one["visit_id"] == v["visit"] and one["attempts"] == 1 and one["apns_status"] == 200
    assert one["apns_id"].startswith("00000000-") and one["sent_at"] and one["created_at"]
    assert all(len(x["token_tail"]) == 6 for x in rows) and all(x["device_id"] for x in rows)
    full = {tok(login) for login in acc}
    assert not any(t in json.dumps(rows) for t in full)  # 전체 토큰은 없음

    fake.status = {tok(IDS["doctor"]): 410, tok(f"doctor-{staff['B']}"): 500}
    call2, _ = new_call(c, 2)
    notify(c, call2, IDS["nurse"])
    with c.repo.tx() as tx:
        rows2 = {x["account_id"]: x for x in tx.push_logs() if x["call_id"] == call2}
        assert len(tx.push_logs()) == 8  # 앞 4행은 그대로(쌓기만)
    gone, err = rows2[acc[IDS["doctor"]].id], rows2[acc[f"doctor-{staff['B']}"].id]
    assert (gone["status"], gone["apns_status"], gone["apns_reason"], gone["attempts"]) == (
        "token_removed", 410, "Unregistered", 1)
    assert (err["status"], err["apns_status"], err["attempts"], err["sent_at"]) == ("failed", 500, 2, None)


@pytest.mark.parametrize("headers,want", [
    ({"X-Accept-Source": "push"}, "push"),  # 알림 액션(앱이 넣음)
    ({"origin": "http://localhost:3700"}, "web"),  # 브라우저
    ({}, "app"),
])
def test_accept_source_recorded(env, headers, want):
    client, c, staff, fake, acc = env
    call, _ = new_call(c, 1)
    token = client.post("/api/auth/login", json={"id": IDS["doctor"]}).json()["token"]
    r = client.post(f"/api/calls/{call}/accept", json={}, headers={"Authorization": f"Bearer {token}", **headers})
    assert r.status_code == 200
    with c.repo.tx() as tx:
        ev = tx.events("call_accept")[-1]
    assert ev["payload"]["source"] == want and ev["payload"]["byRole"] == "doctor"


def test_startup_key_check(tmp_path, key, caplog):
    base = dict(apns_key_id="KEYID00001", apns_team_id="TEAMID0001", apns_bundle_id="com.example.procedure",
                apns_env="sandbox")
    with caplog.at_level(logging.INFO):
        ok = PushService(None, make_settings(tmp_path, apns_key_path=str(key[0]), **base))  # type: ignore[arg-type]
        bad = PushService(None, make_settings(tmp_path, apns_key_path=str(tmp_path / "none.p8"), **base))  # type: ignore[arg-type]
    assert ok.check_key() is True and bad.check_key() is False
    assert "APNs JWT 서명 OK(env=sandbox)" in caplog.text and "APNs JWT 서명 실패(FileNotFoundError)" in caplog.text
    assert "TEAMID0001" not in caplog.text and str(tmp_path) not in caplog.text


@pytest.mark.parametrize("reason,removed", [
    ("BadDeviceToken", True), ("DeviceTokenNotForTopic", True), ("Unregistered", True),  # 죽은 토큰 → 삭제
    ("BadTopic", False), ("PayloadTooLarge", False),  # 그 밖 400 → failed · 남김
])
def test_dead_token_400_removed(env, reason, removed):
    client, c, staff, fake, acc = env
    t = tok(IDS["doctor"])
    fake.status, fake.reason = {t: 400}, {t: reason}
    call, _ = new_call(c, 1)
    notify(c, call, IDS["nurse"])
    with c.repo.tx() as tx:
        left = set(tx.device_tokens([a.id for a in tx.accounts()]))
        row = next(x for x in tx.push_logs() if x["account_id"] == acc[IDS["doctor"]].id)
    assert (t not in left) is removed and fake.tokens().count(t) == 1  # 재시도 없음
    assert (row["status"], row["apns_status"], row["apns_reason"]) == ("token_removed" if removed else "failed", 400, reason)
