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
    # 비밀번호는 보지 않는다(카드 로그인) · 목록에 없는 id 는 401
    assert client.post("/api/auth/login", json={"id": ADMIN["id"], "password": "아무거나"}).status_code == 200
    bad = client.post("/api/auth/login", json={"id": "nobody"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"


def test_accounts_list(client, tmp_path):
    assert client.get("/api/auth/accounts").json() == [
        {"id": ADMIN["id"], "name": "관리자", "label": "간호 스테이션 · 의국", "role": "admin"}]
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import make_settings

    with TestClient(create_app(make_settings(tmp_path, ccc_admin_id=""))) as c2:  # 관리자 id 가 없으면 아무도 못 들어온다
        assert c2.get("/api/auth/accounts").json() == []
        assert c2.post("/api/auth/login", json={"id": ""}).status_code == 401


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
