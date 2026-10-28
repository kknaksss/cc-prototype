"""앱 실기기 E2E batch 1 — #1 installId(기기 행 하나) · #3 SSE display 가 그 기기 스트림으로."""

import asyncio
import json
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.board import stream
from app.main import create_app
from app.repository.db import Database
from tests.conftest import PW, make_settings
from tests.helpers import T0
from tests.test_push import tok

IDS = {"admin": "admin1", "coordinator": "coord1"}


@pytest.fixture
def env(tmp_path):
    s = make_settings(tmp_path, ccc_admin_id=IDS["admin"], ccc_coord_id=IDS["coordinator"])
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        c.clock.set(T0)
        login = {k: client.post("/api/auth/login", json={"id": v, "password": PW[k]}).json() for k, v in IDS.items()}
        auth = {k: {"Authorization": f"Bearer {v['token']}"} for k, v in login.items()}
        with c.repo.tx() as tx:
            acc = {a.login_id: a for a in tx.accounts()}
            rid = tx.upsert("reservation", "sch-1", {"day": "2026-10-21"})
        yield client, c, auth, acc, rid, {k: v["token"] for k, v in login.items()}


def reg(client, auth, token, **kw):
    r = client.post("/api/devices", json={"token": token, **kw}, headers=auth)
    assert r.status_code == 200, r.json()
    return r.json()["deviceId"]


# ------------------------------------------------------------------ #1 installId
def test_install_id_keeps_one_row_per_install(env):
    client, c, auth, acc, rid, _ = env
    a = auth["coordinator"]
    first = reg(client, a, tok("sandbox"), installId="IFV-1", kind="phone", name="코디 폰")
    second = reg(client, a, tok("production"), installId="IFV-1")  # 토큰 바뀜(sandbox ↔ production · 재설치)
    assert first == second
    with c.repo.tx() as tx:
        rows = tx.devices()
    assert [(d.id, d.token, d.install_id, d.name, d.kind) for d in rows] == [
        (first, tok("production"), "IFV-1", "코디 폰", "phone")]  # 행 하나 · 이름 그대로
    other = reg(client, a, tok("pad"), installId="IFV-2", kind="tablet")
    assert other != first and len(client.get("/api/devices/targets", headers=a).json()) == 2


def test_install_id_absorbs_token_row_and_moves_account(env):
    client, c, auth, acc, rid, _ = env
    old = reg(client, auth["coordinator"], tok("old"))  # 옛 빌드(installId 없음)
    keep = reg(client, auth["coordinator"], tok("new"), installId="IFV-1")
    assert keep != old
    same = reg(client, auth["coordinator"], tok("old"), installId="IFV-1")  # 옛 토큰이 그 설치로 다시 오면
    assert same == keep
    with c.repo.tx() as tx:
        rows = tx.devices()
    assert [(d.id, d.token) for d in rows] == [(keep, tok("old"))]  # 토큰 행은 지우고 설치 행에 끼움
    moved = reg(client, auth["admin"], tok("x"), installId="IFV-1")  # 같은 기기에 다른 계정 로그인 = 마지막 계정
    with c.repo.tx() as tx:
        d = tx.device(moved)
    assert moved == keep and d.account_id == acc[IDS["admin"]].id


def test_install_id_absent_works_as_before(env):
    client, c, auth, acc, rid, _ = env
    a = reg(client, auth["coordinator"], tok("a"))
    assert reg(client, auth["coordinator"], tok("a")) == a
    assert reg(client, auth["coordinator"], tok("b")) != a
    r = client.post("/api/devices", json={"token": tok("c"), "installId": ""}, headers=auth["coordinator"])
    assert r.status_code == 400  # 빈 값 = 400(없으면 키를 빼고 보낸다)


def test_install_id_targets_one_per_install(env):
    """targets = 계정 · installId 당 하나(가장 최근) · installId 없는 옛 행은 행마다."""
    client, c, auth, acc, rid, _ = env
    a = auth["coordinator"]
    keep = reg(client, a, tok("new"), installId="IFV-1", name="데스크 패드")
    legacy = reg(client, a, tok("legacy"))
    with c.repo.tx() as tx:  # 같은 설치 id 를 가진 옛 행이 남아 있던 DB(직접 넣음)
        tx.con.execute("INSERT INTO device (account_id, token, name, install_id, created_at, updated_at, last_seen_at) "
                       "VALUES (?, ?, 'iPhone', 'IFV-1', 'x', 'x', ?)",
                       (acc[IDS["coordinator"]].id, tok("dup"), (T0 - timedelta(hours=1)).isoformat()))
    got = client.get("/api/devices/targets", headers=a).json()
    assert sorted(x["deviceId"] for x in got) == sorted([keep, legacy])
    assert next(x for x in got if x["deviceId"] == keep)["name"] == "데스크 패드"


def test_install_id_migration_on_old_device_table(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE device (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, token TEXT NOT NULL UNIQUE, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    con.execute("INSERT INTO device VALUES (8, 1, 'abc', 'x', 'x')")
    con.commit()
    con.close()
    with Database(path).connect() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(device)")}
        row = dict(c.execute("SELECT * FROM device").fetchone())
    assert {"install_id", "name", "kind", "last_seen_at"} <= cols and row["id"] == 8 and row["install_id"] is None


# ------------------------------------------------------------------ #3 SSE display — 실제 stream 경로(deviceId 쿼리)
def test_sse_display_reaches_device_stream_via_route(env):
    client, c, auth, acc, rid, tokens = env
    pushed = []
    c.display.push = pushed.append
    phone = reg(client, auth["coordinator"], tok("phone"), installId="IFV-1")
    pad = reg(client, auth["coordinator"], tok("pad"), installId="IFV-2")

    async def go():
        resp = await stream(c, tokens["coordinator"], phone)  # 앱 = …/stream?token=…&deviceId=<자기>
        web = await stream(c, tokens["admin"], None)
        it, wit = resp.body_iterator, web.body_iterator
        assert (await it.__anext__()).startswith("retry:") and (await wit.__anext__()).startswith("retry:")
        assert c.hub.online(phone) and not c.hub.online(pad)
        targets = {x["deviceId"]: x["online"] for x in c.display.targets()}
        assert targets == {phone: True, pad: False}
        q = c.display.create(acc[IDS["admin"]], rid, "scan", phone)  # 웹 [스캔할 기기] → 폰
        frame = await asyncio.wait_for(it.__anext__(), 1)
        assert frame.startswith("event: display\ndata: ")
        assert json.loads(frame.split("data: ", 1)[1]) == {"requestId": q["id"], "deviceId": phone, "kind": "scan",
                                                           "reservationId": rid}
        assert pushed == []  # SSE 로 닿으면 푸시 없음(운영 #10 과 같은 길)
        c.display.create(acc[IDS["admin"]], rid, "questionnaire", pad)  # 연결 없는 기기 = 푸시
        assert len(pushed) == 1
        with pytest.raises(TimeoutError):  # 웹 연결엔 display 0(시간 초과가 생성기를 닫으므로 끝에)
            await asyncio.wait_for(wit.__anext__(), 0.1)
        await it.aclose()
        assert not c.hub.online(phone)

    asyncio.run(go())


def test_sse_foreign_device_id_ignored(env):
    client, c, auth, acc, rid, tokens = env
    theirs = reg(client, auth["admin"], tok("adm"), installId="IFV-9")

    async def go():
        resp = await stream(c, tokens["coordinator"], theirs)  # 남의 계정 기기 id = 무시(기기 없는 연결)
        it = resp.body_iterator
        await it.__anext__()
        assert not c.hub.online(theirs)
        await it.aclose()

    asyncio.run(go())
