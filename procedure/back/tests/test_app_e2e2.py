"""앱 실기기 E2E batch 2 — #1 옛 기기 행(installId 없음) 가리기 · 띄우기 = SSE + 푸시 둘 다."""

import asyncio
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.api.board import stream
from app.main import create_app
from app.push.apns import ApnsClient
from app.service.push import PushService
from tests.conftest import PW, make_settings
from tests.helpers import T0, seed_staff, seed_visit
from tests.test_push import FakeApns, tok

IDS = {"admin": "admin1", "coordinator": "coord1"}


@pytest.fixture
def env(tmp_path):
    key = tmp_path / "AuthKey_TEST.p8"
    key.write_bytes(ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    s = make_settings(tmp_path, ccc_admin_id=IDS["admin"], ccc_coord_id=IDS["coordinator"], apns_key_path=str(key),
                      apns_key_id="KEYID00001", apns_team_id="TEAMID0001", apns_bundle_id="com.example.procedure",
                      apns_env="sandbox")
    apns = FakeApns()
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        c.clock.set(T0)
        c.push = PushService(c.repo, s, client=ApnsClient(s, transport=httpx.MockTransport(apns.handle)), clock=c.clock,
                             notifications=c.notifications)
        login = {k: client.post("/api/auth/login", json={"id": v, "password": PW[k]}).json() for k, v in IDS.items()}
        auth = {k: {"Authorization": f"Bearer {v['token']}"} for k, v in login.items()}
        with c.repo.tx() as tx:
            acc = {a.login_id: a for a in tx.accounts()}
            rid = tx.upsert("reservation", "sch-1", {"day": "2026-10-21"})
        yield client, c, apns, auth, acc, rid, {k: v["token"] for k, v in login.items()}


def reg(client, auth, token, **kw):
    r = client.post("/api/devices", json={"token": token, **kw}, headers=auth)
    assert r.status_code == 200, r.json()
    return r.json()["deviceId"]


def targets(client, auth):
    return [x["deviceId"] for x in client.get("/api/devices/targets", headers=auth).json()]


# ------------------------------------------------------------------ #1 옛 기기 행
def test_legacy_rows_hidden_once_account_has_install_row(env):
    """운영 행 8 · 9 꼴 — 같은 폰 옛 행 둘(installId 없음) · 새 빌드가 지금 토큰으로 등록하면
    그 행에 installId 를 붙이고 나머지 옛 행은 가림."""
    client, c, apns, auth, acc, rid, _ = env
    a = auth["coordinator"]
    row8 = reg(client, a, tok("old-sandbox"), kind="phone")
    row9 = reg(client, a, tok("prod"), kind="phone")
    assert sorted(targets(client, a)) == sorted([row8, row9])  # 지금 화면(아이폰 2대)
    same = reg(client, a, tok("prod"), kind="phone", installId="IFV-1")  # 같은 토큰 + installId = 그 행에 붙임
    assert same == row9
    with c.repo.tx() as tx:
        rows = {d.id: d for d in tx.devices()}
    assert len(rows) == 2 and rows[row9].install_id == "IFV-1" and rows[row8].install_id is None  # 새 행 0 · 지우지 않음
    assert targets(client, a) == [row9]


def test_legacy_rows_other_kind_and_other_account_kept(env):
    client, c, apns, auth, acc, rid, _ = env
    a = auth["coordinator"]
    pad_legacy = reg(client, a, tok("pad-old"), kind="tablet")  # 다른 kind 옛 행 = 그대로
    blank_legacy = reg(client, a, tok("blank-old"))  # kind 없는 옛 행 = 어느 kind 든 가림
    phone = reg(client, a, tok("phone"), kind="phone", installId="IFV-1")
    got = targets(client, a)
    assert phone in got and pad_legacy in got and blank_legacy not in got
    with c.repo.tx() as tx:  # 다른 코디 계정의 옛 행은 그 계정 기준(설치 행 없음 = 그대로)
        other = tx.put_account("coord2", T0, role="coordinator", name="코디 2", staff_id=None, active=True, card=False)
        legacy_other = tx.put_device(other, tok("c2-old"), T0, kind="phone")
    assert legacy_other in targets(client, a)


def test_legacy_rows_excluded_from_push(env):
    """가려진 옛 행엔 원장 호출 푸시도 안 간다."""
    client, c, apns, auth, acc, rid, _ = env
    seed_staff(c.repo)
    adm = auth["admin"]
    reg(client, adm, tok("adm-old"), kind="phone")
    reg(client, adm, tok("adm-new"), kind="phone", installId="IFV-9")
    v = seed_visit(c.repo, 1, procs=1)
    call = c.actions.create_call("setup", v["visit"], v["procs"], "all", None)
    asyncio.run(c.push.notify(call, "setup"))
    assert apns.tokens() == [tok("adm-new")]


# ------------------------------------------------------------------ 띄우기 = SSE + 푸시
def test_display_sse_and_push_both(env):
    client, c, apns, auth, acc, rid, tokens = env
    phone = reg(client, auth["coordinator"], tok("phone"), kind="phone", installId="IFV-1")
    scheduled = []
    c.display.push = scheduled.append

    async def go():
        resp = await stream(c, tokens["coordinator"], phone)
        it = resp.body_iterator
        await it.__anext__()
        q = c.display.create(acc[IDS["admin"]], rid, "scan", phone)
        frame = await asyncio.wait_for(it.__anext__(), 1)
        assert json.loads(frame.split("data: ", 1)[1])["requestId"] == q["id"]
        assert c.display.reach(q["id"], phone, "scan", rid) == "sse+push"
        await it.aclose()
        return q

    q = asyncio.run(go())
    assert scheduled == [q["id"], q["id"]]  # 만들기 1 + 위 reach 1 — SSE 가 열려 있어도 푸시
    assert c.display.reach(q["id"], phone, "scan", rid) == "push"  # 스트림 닫힘 = 푸시만
    assert asyncio.run(c.push.notify_display(q["id"]))["sent"] == 1 and apns.tokens() == [tok("phone")]


def test_display_api_sse_and_push_log(env):
    """API 만들기(그 기기 스트림 열림 · 이벤트 루프) → push_log display 1행(SSE 와 함께)."""
    import time

    client, c, apns, auth, acc, rid, tokens = env
    phone = reg(client, auth["coordinator"], tok("phone"), kind="phone", installId="IFV-1")
    c.hub.online = lambda device_id: True  # 열린 스트림 흉내(연결은 위 시험이 본다)
    c.display.online = c.hub.online
    r = client.post("/api/display-requests", json={"reservationId": rid, "kind": "questionnaire", "deviceId": phone},
                    headers=auth["admin"])
    assert r.status_code == 200
    deadline, rows = time.time() + 3, []
    while time.time() < deadline and not rows:
        with c.repo.tx() as tx:
            rows = tx.push_logs()
        time.sleep(0.02)
    assert [(x["kind"], x["device_id"], x["status"]) for x in rows] == [("display", phone, "sent")]
