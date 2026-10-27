"""WORK-009 WP-BE1 — 역할 다섯 · 상담사 계정 · push_log 마이그레이션 · 원장 호출 회귀 · 알림 · SSE 허브(SPEC-004 §8.6)."""

import asyncio
import json
import re
import sqlite3
import typing
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.domain.models import MANAGER_ROLES, ROLES
from app.main import create_app
from app.push.apns import ApnsClient
from app.repository.db import Database
from app.schemas.actions import Role
from app.service.push import PushService
from app.service.stream import StreamHub
from tests.conftest import PW, make_settings
from tests.helpers import T0, seed_staff, seed_visit
from tests.test_push import FakeApns, tok

IDS = {"admin": "admin1", "doctor": "doctor1", "nurse": "nurse1", "coordinator": "coord1", "counselor": "counsel1"}
APNS = dict(apns_key_id="KEYID00001", apns_team_id="TEAMID0001", apns_bundle_id="com.example.procedure", apns_env="sandbox")


@pytest.fixture
def env(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    path = tmp_path / "AuthKey_TEST.p8"
    path.write_bytes(ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    s = make_settings(tmp_path, ccc_admin_id=IDS["admin"], ccc_doctor_id=IDS["doctor"], ccc_doctor_kos_account_id="doc-a",
                      ccc_nurse_id=IDS["nurse"], ccc_nurse_name="간호 A", ccc_coord_id=IDS["coordinator"],
                      ccc_counselor_id=IDS["counselor"], ccc_counselor_kos_account_id="cs-1", apns_key_path=str(path), **APNS)
    fake = FakeApns()
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        c.clock.set(T0)
        staff = seed_staff(c.repo)
        with c.repo.tx() as tx:
            staff["CS1"] = tx.upsert("staff", "cs-1", {"name": "상담 1", "role_tags": ["COUNSELOR"], "active": True})
            staff["CS2"] = tx.upsert("staff", "cs-2", {"name": "상담 2", "role_tags": ["COUNSELOR"], "active": True})
        c.accounts.sync()
        c.push = PushService(c.repo, s, client=ApnsClient(s, transport=httpx.MockTransport(fake.handle)),
                             clock=c.clock, notifications=c.notifications)
        c.actions.on_call = c.push.schedule
        with c.repo.tx() as tx:  # 계정마다 기기 1대
            acc = {a.login_id: a for a in tx.accounts()}
            for login in acc:
                tx.put_device(acc[login].id, tok(login), T0)
        yield client, c, staff, fake, acc


def login(client, role):
    r = client.post("/api/auth/login", json={"id": IDS[role], "password": PW[role]})
    assert r.status_code == 200, r.json()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def new_call(c, n, kind="all", target=None):
    v = seed_visit(c.repo, n, procs=1)
    return c.actions.create_call("setup", v["visit"], v["procs"], kind, target), v


# ------------------------------------------------------------------ 역할 다섯(§3.4 0.4.0)
def test_role_five_literal_and_grep():
    """Role 리터럴 = 다섯 · 수락 분기 = 관리자 묶음 상수 · back 에 역할 값 튜플이 하드코딩된 곳 0(grep)."""
    assert set(typing.get_args(Role)) == set(ROLES) and set(MANAGER_ROLES) == {"admin", "coordinator", "counselor"}
    app_dir = Path(__file__).resolve().parent.parent / "app"
    hits = []
    for f in app_dir.rglob("*.py"):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"role\s+in\s+\(", line) or re.search(r"role\s*==\s*\"(admin|coordinator)\"", line):
                hits.append(f"{f.name}:{i}")
    # 남는 것 = 원장 호출 받는 사람(관리자만 받음 — 코디 · 상담사는 안 받는 것이 계약 · §5-1.2)
    assert all(h.startswith("push.py") for h in hits), hits


def test_role_counselor_accept_needs_doctor_id(env):
    client, c, staff, fake, acc = env
    auth = login(client, "counselor")
    call, v = new_call(c, 1)
    r = client.post(f"/api/calls/{call}/accept", json={}, headers=auth)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    r = client.post(f"/api/calls/{call}/accept", json={"doctorId": staff["A"]}, headers=auth)
    assert r.status_code == 200
    with c.repo.tx() as tx:
        assert tx.events("call_accept")[-1]["payload"]["byRole"] == "counselor"


@pytest.mark.parametrize("role", ["admin", "doctor", "nurse", "coordinator", "counselor"])
def test_role_new_apis_open_to_five(env, role):
    client, c, staff, fake, acc = env
    auth = login(client, role)
    assert client.get("/api/notifications", headers=auth).status_code == 200
    assert client.post("/api/notifications/read", json={}, headers=auth).status_code == 200
    assert client.get("/api/me/notification-settings", headers=auth).status_code == 200
    r = client.post("/api/devices", json={"token": tok(f"x-{role}"), "name": "데스크 패드", "kind": "tablet"}, headers=auth)
    assert r.status_code == 200 and r.json()["deviceId"] > 0


# ------------------------------------------------------------------ 상담사 계정(§3.7)
def test_counselor_account_rows(tmp_path):
    s = make_settings(tmp_path, ccc_counselor_id=IDS["counselor"], ccc_counselor_kos_account_id="cs-1",
                      kos_exclude_account_ids="cs-ex")
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        with c.repo.tx() as tx:
            sid = {k: tx.upsert("staff", k, {"name": k, "role_tags": tags, "active": active}) for k, tags, active in (
                ("cs-1", ["COUNSELOR"], True), ("cs-2", ["COUNSELOR", "NURSE"], True), ("cs-off", ["COUNSELOR"], False),
                ("cs-ex", ["COUNSELOR"], True), ("sys-0", ["COUNSELOR", "ADMIN"], True), ("doc-z", ["DOCTOR"], True))}
            tx.save_token("internal", "t", None, "sys-0")  # 시스템 계정
        c.accounts.sync()
        with c.repo.tx() as tx:
            rows = {a.staff_id: a for a in tx.accounts() if a.role == "counselor"}
        assert set(rows) == {sid["cs-1"], sid["cs-2"]}  # 비활성 · 제외 · 시스템 · 원장 빠짐(상담사 목록 함수와 같음)
        assert (rows[sid["cs-1"]].login_id, rows[sid["cs-1"]].card) == (IDS["counselor"], True)
        assert rows[sid["cs-1"]].password_hash and rows[sid["cs-2"]].password_hash is None
        assert rows[sid["cs-2"]].login_id == f"counselor-{sid['cs-2']}" and not rows[sid["cs-2"]].card
        body = client.post("/api/auth/login", json={"id": IDS["counselor"], "password": PW["counselor"]}).json()
        assert (body["role"], body["staffId"], body["name"]) == ("counselor", sid["cs-1"], "cs-1")
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"}).json()
        assert me["role"] == "counselor" and me["staffId"] == sid["cs-1"]
        with c.repo.tx() as tx:  # 목록에서 빠짐 → active=false(행 남김)
            tx.upsert("staff", "cs-2", {"role_tags": ["NURSE"]})
        c.accounts.sync()
        with c.repo.tx() as tx:
            gone = next(a for a in tx.accounts() if a.staff_id == sid["cs-2"] and a.role == "counselor")
        assert gone.active is False


def test_counselor_account_card_absent_when_not_listed(tmp_path):
    s = make_settings(tmp_path, ccc_counselor_id=IDS["counselor"], ccc_counselor_kos_account_id="cs-off")
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        with c.repo.tx() as tx:
            tx.upsert("staff", "cs-off", {"name": "쉬는", "role_tags": ["COUNSELOR"], "active": False})
        c.accounts.sync()
        with c.repo.tx() as tx:
            assert tx.account(IDS["counselor"]) is None
        assert client.post("/api/auth/login", json={"id": IDS["counselor"], "password": PW["counselor"]}).status_code == 401


# ------------------------------------------------------------------ 마이그레이션(§7.4 r2 — 옛 모양 DB 파일에서 시작)
OLD_PUSH_LOG = """
CREATE TABLE push_log (
    id INTEGER PRIMARY KEY, call_id INTEGER NOT NULL, visit_id INTEGER, account_id INTEGER, role TEXT,
    device_id INTEGER, token_tail TEXT, category TEXT, status TEXT NOT NULL,
    apns_status INTEGER, apns_reason TEXT, apns_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, sent_at TEXT
);
CREATE TABLE device (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


def test_migration_push_log_rebuilt_from_old_db(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_PUSH_LOG)
    old = [(1, 7, 3, 1, "doctor", 2, "abcdef", "CALL", "sent", 200, None, "x-1", 1, "2026-10-20T01:00:00Z",
            "2026-10-20T01:00:01Z"),
           (2, 8, 4, 2, "admin", 3, "123456", None, "failed", 500, "Internal", None, 2, "2026-10-20T02:00:00Z", None)]
    con.executemany("INSERT INTO push_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", old)
    con.commit()
    con.close()
    for _ in range(2):  # 두 번 열어도 그대로(멱등)
        db = Database(path)
        with db.connect() as c:
            info = {r["name"]: r for r in c.execute("PRAGMA table_info(push_log)")}
            rows = [dict(r) for r in c.execute("SELECT * FROM push_log ORDER BY id")]
            dev = {r["name"] for r in c.execute("PRAGMA table_info(device)")}
        assert info["call_id"]["notnull"] == 0 and info["visit_id"]["notnull"] == 0
        assert {"kind", "reservation_id", "display_request_id", "notification_id"} <= set(info)
        assert {"name", "kind", "last_seen_at"} <= dev
        assert len(rows) == 2 and all(r["kind"] == "doctor_call" for r in rows)
        assert [tuple(r[k] for k in ("id", "call_id", "visit_id", "account_id", "role", "device_id", "token_tail", "category",
                                     "status", "apns_status", "apns_reason", "apns_id", "attempts", "created_at", "sent_at"))
                for r in rows] == old
    with db.connect() as c:  # call_id 없는 counselor_call · display 행
        c.execute("INSERT INTO push_log (status, created_at, kind, reservation_id) VALUES ('sent', 'x', 'counselor_call', 5)")
        c.execute("INSERT INTO push_log (status, created_at, kind, display_request_id) VALUES ('sent', 'x', 'display', 1)")
    with Database(path).connect() as c:
        assert c.execute("SELECT COUNT(*) FROM push_log").fetchone()[0] == 4


# ------------------------------------------------------------------ 원장 호출 회귀(§8.6)
def test_push_doctor_call_regression_notifications(env):
    client, c, staff, fake, acc = env
    call, v = new_call(c, 1)
    asyncio.run(c.push.notify(call, IDS["nurse"]))
    got = set(fake.tokens())
    assert tok(IDS["coordinator"]) not in got and tok(IDS["counselor"]) not in got and tok(IDS["nurse"]) not in got
    assert all(r["payload"]["kind"] == "doctor_call" for r in fake.requests)
    with c.repo.tx() as tx:
        notes = c.repo.db.connect
        logs = tx.push_logs()
    with notes() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM notification ORDER BY id")]
    to = {r["account_id"] for r in rows}
    want = {a.id for a in acc.values() if a.role in ("admin", "doctor") and a.active}
    assert to == want and len(rows) == len(want)  # 계정마다 1행
    assert all((r["kind"], r["call_id"], r["visit_id"], r["title"]) == ("doctor_call", call, v["visit"], "원장 호출")
               for r in rows)
    by_acc = {r["account_id"]: r["id"] for r in rows}
    assert all(x["kind"] == "doctor_call" and x["notification_id"] == by_acc[x["account_id"]] for x in logs)


def test_push_doctor_call_note_without_device_and_setting_off(env):
    """기기 없어도 알림 행 · 설정 끔 = 알림 행 · push_log 둘 다 0(D7-42 · D7-69)."""
    client, c, staff, fake, acc = env
    admin = acc[IDS["admin"]]
    with c.repo.tx() as tx:
        tx.delete_device(tok(IDS["admin"]))
    doc = login(client, "doctor")
    r = client.put("/api/me/notification-settings", json={"kind": "doctor_call", "enabled": False}, headers=doc)
    assert r.json() == {"items": [{"kind": "doctor_call", "enabled": False}]}
    call, _ = new_call(c, 1)
    asyncio.run(c.push.notify(call, IDS["nurse"]))
    with c.repo.db.connect() as con:
        to = [r["account_id"] for r in con.execute("SELECT account_id FROM notification")]
    with c.repo.tx() as tx:
        logged = {x["account_id"] for x in tx.push_logs()}
    assert admin.id in to and admin.id not in logged  # 기기 없음 = 행만
    assert acc[IDS["doctor"]].id not in to and acc[IDS["doctor"]].id not in logged
    assert tok(IDS["doctor"]) not in fake.tokens()


def test_push_skipped_without_key_still_writes_notifications(tmp_path):
    s = make_settings(tmp_path, ccc_admin_id=IDS["admin"])
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        seed_staff(c.repo)
        v = seed_visit(c.repo, 1, procs=1)
        c.actions.create_call("setup", v["visit"], v["procs"], "all", None)  # 키 없음 → skip 경로(동기)
        auth = login(client, "admin")
        body = client.get("/api/notifications", headers=auth).json()
    assert body["unread"] == 1 and body["items"][0]["kind"] == "doctor_call"


# ------------------------------------------------------------------ 알림(§5-4)
def test_notification_list_read_and_scope(env):
    client, c, staff, fake, acc = env
    admin, doc = login(client, "admin"), login(client, "doctor")
    calls = [new_call(c, n)[0] for n in range(1, 4)]
    for call in calls:
        asyncio.run(c.push.notify(call, IDS["nurse"]))
    with c.repo.tx() as tx:  # 어제 행(KST) · 다른 계정 — 목록 밖
        c.notifications.add(tx, acc[IDS["admin"]].id, "doctor_call", "원장 호출", "어제", call_id=99)
        tx.con.execute("UPDATE notification SET created_at = '2026-10-20T10:00:00Z' WHERE call_id = 99")
    body = client.get("/api/notifications", headers=admin).json()
    assert body["unread"] == 3 and [x["target"]["callId"] for x in body["items"]] == calls[::-1]  # 새것 위 · 오늘만
    first = body["items"][0]
    assert set(first) == {"id", "kind", "title", "body", "createdAt", "readAt", "target"} and first["readAt"] is None
    assert first["target"]["visitId"] and "고객" not in json.dumps(body, ensure_ascii=False)
    r = client.post("/api/notifications/read", json={"ids": [first["id"]]}, headers=admin)
    assert r.json() == {"ok": True, "read": 1}
    assert client.get("/api/notifications", headers=admin).json()["unread"] == 2
    r = client.post("/api/notifications/read", json={"callId": calls[0]}, headers=admin)  # 푸시 눌러 열기
    assert r.json()["read"] == 1
    doc_before = client.get("/api/notifications", headers=doc).json()["unread"]
    assert client.post("/api/notifications/read", json={}, headers=admin).json()["read"] == 2  # 전부(어제 행 포함)
    assert client.get("/api/notifications", headers=admin).json()["unread"] == 0
    assert client.get("/api/notifications", headers=doc).json()["unread"] == doc_before == 3  # 남의 것 안 바뀜
    other = client.get("/api/notifications", headers=doc).json()["items"][0]["id"]
    assert client.post("/api/notifications/read", json={"ids": [other]}, headers=admin).json()["read"] == 0


def test_notification_list_max_50(env):
    client, c, staff, fake, acc = env
    with c.repo.tx() as tx:
        for i in range(55):
            c.notifications.add(tx, acc[IDS["admin"]].id, "doctor_call", "원장 호출", f"{i}", call_id=i)
    body = client.get("/api/notifications", headers=login(client, "admin")).json()
    assert len(body["items"]) == 50 and body["unread"] == 55


@pytest.mark.parametrize("role,kinds", [("admin", ["doctor_call"]), ("doctor", ["doctor_call"]),
                                        ("counselor", ["counselor_call"]), ("coordinator", []), ("nurse", [])])
def test_notification_settings_by_role(env, role, kinds):
    client, c, staff, fake, acc = env
    auth = login(client, role)
    assert client.get("/api/me/notification-settings", headers=auth).json() == {
        "items": [{"kind": k, "enabled": True} for k in kinds]}
    for k in ("doctor_call", "counselor_call", "display"):
        r = client.put("/api/me/notification-settings", json={"kind": k, "enabled": False}, headers=auth)
        if k in kinds:
            assert r.status_code == 200 and r.json()["items"] == [{"kind": k, "enabled": False}]
        else:
            assert (r.status_code, r.json()["error"]["code"]) == (400, "setting_not_allowed")


def test_notification_sse_to_account_only(env):
    client, c, staff, fake, acc = env
    hub = c.hub

    async def go():
        admin = hub.frames(ping_sec=5, account_id=acc[IDS["admin"]].id)
        nurse = hub.frames(ping_sec=5, account_id=acc[IDS["nurse"]].id)
        await admin.__anext__(), await nurse.__anext__()
        call, _ = new_call(c, 1)  # 호출 = board 1개(모든 연결)
        for g in (admin, nurse):
            assert (await asyncio.wait_for(g.__anext__(), 1)).startswith("event: board\n")
        version = hub.version
        await c.push.notify(call, IDS["nurse"])
        frame = await asyncio.wait_for(admin.__anext__(), 1)
        assert frame == 'event: notification\ndata: {"unread": 1}\n\n' and "id:" not in frame
        assert hub.version == version
        # 시간 초과는 생성기를 닫으므로(연결 끝) 음성 확인은 맨 끝에
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(nurse.__anext__(), 0.2)
        await admin.aclose(), await nurse.aclose()

    asyncio.run(go())


# ------------------------------------------------------------------ SSE 허브(§7.1 r2)
def test_stream_hub_board_account_device(env):
    client, c, staff, fake, acc = env
    hub: StreamHub = c.hub

    async def nxt(g, t=0.2):
        return await asyncio.wait_for(g.__anext__(), t)

    async def go():
        tab = hub.frames(ping_sec=5, account_id=1, device_id=11)
        phone = hub.frames(ping_sec=5, account_id=1, device_id=12)
        web = hub.frames(ping_sec=5, account_id=1)
        other = hub.frames(ping_sec=5, account_id=2, device_id=21)
        gens = [tab, phone, web, other]
        for g in gens:
            assert (await nxt(g)).startswith("retry:")
        assert hub.online(11) and hub.online(12) and not hub.online(99)
        v = hub.publish()  # board = 모든 연결
        for g in gens:
            assert (await nxt(g)).startswith(f"event: board\nid: {v}\n")
        assert hub.send_to_device(11, "display", {"requestId": 1}) == 1  # 그 기기만
        assert (await nxt(tab)) == 'event: display\ndata: {"requestId": 1}\n\n'
        assert hub.send_to_account(1, "notification", {"unread": 2}) == 3  # 그 계정 셋(기기 둘 + 웹)
        for g in (tab, phone, web):
            assert (await nxt(g)).startswith("event: notification\n")
        assert hub.version == v
        await tab.aclose()
        assert not hub.online(11) and hub.online(12)
        # display 는 같은 계정 다른 기기 · 웹 · 다른 계정 0 — 시간 초과가 생성기를 닫으므로 맨 끝에
        for g in (phone, web, other):
            with pytest.raises(TimeoutError):
                await nxt(g, 0.05)
        assert hub.connections == 0

    asyncio.run(go())


def test_stream_device_id_own_only(env):
    """SSE deviceId — 그 계정 기기면 last_seen_at 갱신 · 남의 계정 · 없는 id 는 무시(404 아님)."""
    client, c, staff, fake, acc = env
    admin, nurse = acc[IDS["admin"]], acc[IDS["nurse"]]
    with c.repo.tx() as tx:
        mine = next(d for d in tx.devices() if d.account_id == admin.id)
        theirs = next(d for d in tx.devices() if d.account_id == nurse.id)
    c.clock.set(T0.replace(hour=5))
    assert c.devices.own(admin, mine.id).id == mine.id
    assert c.devices.own(admin, theirs.id) is None and c.devices.own(admin, 99999) is None
    with c.repo.tx() as tx:
        assert tx.device(mine.id).last_seen_at == T0.replace(hour=5)
        assert tx.device(theirs.id).last_seen_at == T0


def test_stream_requires_token_with_device(env):
    client, c, staff, fake, acc = env
    assert client.get("/api/board/stream?deviceId=1").status_code == 401


def test_push_device_register_name_kind(env):
    client, c, staff, fake, acc = env
    auth = login(client, "coordinator")
    t = tok("desk-pad")
    d1 = client.post("/api/devices", json={"token": t, "kind": "tablet"}, headers=auth).json()["deviceId"]
    d2 = client.post("/api/devices", json={"token": t, "name": "데스크 패드"}, headers=auth).json()["deviceId"]
    with c.repo.tx() as tx:
        d = tx.device(d1)
    assert d1 == d2 and (d.name, d.kind) == ("데스크 패드", "tablet")
    assert client.post("/api/devices", json={"token": tok("p"), "kind": "phone"}, headers=auth).status_code == 200
    with c.repo.tx() as tx:
        assert next(x for x in tx.devices() if x.token == tok("p")).name == "iPhone"  # 이름 없음 = 기본
    for bad in ({"token": t, "name": ""}, {"token": t, "name": "x" * 41}, {"token": t, "kind": "watch"}):
        assert client.post("/api/devices", json=bad, headers=auth).status_code == 400
