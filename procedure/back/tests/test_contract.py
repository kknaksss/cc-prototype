"""WP1 — 계약 고정: 스냅샷 · 조작 스키마 · 오류 형식 · 로그인 · /stream 첫 프레임."""

import asyncio
import json

from app.schemas.actions import CreateCallRequest
from app.schemas.board import BoardEvent, BoardSnapshot
from app.service.stream import StreamHub
from tests.conftest import ADMIN


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True, "kos": {"open": False, "internal": False}}


def test_login_and_me(client, auth):
    r = client.get("/api/auth/me", headers=auth)
    assert r.status_code == 200 and r.json() == {"id": ADMIN["id"], "role": "admin", "name": "관리자", "staffId": None}
    # 틀린 비밀번호 · 없는 아이디 = 같은 401 · 같은 문구
    for body in ({"id": ADMIN["id"], "password": "wrong"}, {"id": "nobody", "password": "x"}):
        bad = client.post("/api/auth/login", json=body)
        assert bad.status_code == 401 and bad.json()["error"] == {"code": "invalid_credentials",
                                                                 "message": "아이디 또는 비밀번호가 맞지 않아요"}
    assert client.post("/api/auth/login", json={"id": ADMIN["id"]}).status_code == 400  # 비밀번호 필수
    assert client.get("/api/auth/accounts").status_code == 404  # 공개 계정 목록 없음
    long_pw = client.post("/api/auth/login", json={"id": ADMIN["id"], "password": "x" * 100})  # bcrypt 72바이트 넘음
    assert long_pw.status_code == 401


def test_login_lockout(client):
    auth = client.app.state.container.auth
    now = [1000.0]
    auth.now_mono = lambda: now[0]
    for _ in range(5):
        assert client.post("/api/auth/login", json={"id": ADMIN["id"], "password": "wrong"}).status_code == 401
    r = client.post("/api/auth/login", json=ADMIN)  # 맞는 비밀번호여도 잠금 중이면 429
    assert (r.status_code, r.json()["error"]["code"]) == (429, "too_many_attempts")
    assert client.post("/api/auth/login", json={"id": "other", "password": "x"}).status_code == 401  # 다른 아이디는 따로
    now[0] += 61  # 1분 뒤 풀림
    assert client.post("/api/auth/login", json=ADMIN).status_code == 200
    for _ in range(4):  # 성공하면 실패 수가 지워진다
        client.post("/api/auth/login", json={"id": ADMIN["id"], "password": "wrong"})
    assert client.post("/api/auth/login", json=ADMIN).status_code == 200


def test_board_requires_login(client):
    r = client.get("/api/board")
    assert r.status_code == 401 and r.json() == {"error": {"code": "unauthorized", "message": "로그인이 필요해요"}}
    assert client.get("/api/board", headers={"Authorization": "Bearer nope.sig"}).status_code == 401


def test_board_snapshot_shape(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import make_settings

    with TestClient(create_app(make_settings(tmp_path, proc_fake_board=True))) as client:
        tok = client.post("/api/auth/login", json=ADMIN).json()["token"]
        body = client.get("/api/board", headers={"Authorization": f"Bearer {tok}"}).json()
    BoardSnapshot.model_validate(body)
    assert len(body["cards"]) == 5
    assert set(body) == {"now", "sync", "doctors", "counts", "limits", "cards", "calls", "recentAccepts"}
    card = body["cards"][0]
    assert set(card) >= {"visitId", "room", "inAt", "homeAt", "customer", "state", "paymentRequired", "orderMemo",
                         "anesthesia", "procedures", "canCall", "canHome", "need", "kos"}
    assert body["now"].endswith("+09:00")


def test_stream_requires_token(client):
    r = client.get("/api/board/stream")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_stream_first_frame_and_publish(client):
    hub: StreamHub = client.app.state.container.hub

    async def run():
        gen = hub.frames(ping_sec=0.05)
        first = await gen.__anext__()
        assert first.startswith("retry: 3000\nevent: board\nid: ")
        data = json.loads(first.split("data: ", 1)[1])
        BoardEvent.model_validate(data)
        assert await gen.__anext__() == ": ping\n\n"
        v = hub.publish()
        nxt = await gen.__anext__()
        assert f"id: {v}\n" in nxt and json.loads(nxt.split("data: ", 1)[1])["version"] == v
        await gen.aclose()
        assert hub.connections == 0

    asyncio.run(run())


def test_call_request_schema():
    assert CreateCallRequest.model_validate({"procedureIds": [1], "target": {"kind": "one", "doctorId": 3}}).target.kind == "one"


def test_invalid_request_format(client, auth):
    r = client.post("/api/auth/login", json={"password": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
