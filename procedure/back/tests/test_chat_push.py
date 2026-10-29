"""WORK-011 WP-BE2 — 직원 채팅 SSE · 푸시 · 사진(SPEC-007 §7 · §8 · §9 · §13.1 BE2 줄).

모두 실 router(TestClient · async def)로 부르고, 받는 쪽(가짜 APNs `httpx.MockTransport` · 허브 연결 큐)에서 단언한다.
서비스 함수를 직접 불러 대신하지 않는다 — 동기 핸들러면 푸시가 「이벤트 루프 없음」으로 0 이 되어 여기서 깨진다.
"""

import asyncio
import json
import logging
import re
import time

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.main import create_app
from app.push.apns import ApnsClient
from app.service.push import Delivery, PushService
from app.service.stream import _Conn
from tests.chat_env import PEOPLE, Chat, seed_people
from tests.conftest import make_settings
from tests.helpers import T0
from tests.test_push import FakeApns, tok

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 2000  # 모양만 JPEG(가짜 · 단색 · 고객 사진 아님)


@pytest.fixture
def env(tmp_path):
    key = tmp_path / "AuthKey_TEST.p8"
    key.write_bytes(ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    s = make_settings(tmp_path, proc_photo_dir=str(tmp_path / "photos"), apns_key_path=str(key), apns_key_id="KEYID00001",
                      apns_team_id="TEAMID0001", apns_bundle_id="com.example.procedure", apns_env="sandbox")
    apns = FakeApns()
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        c.clock.set(T0)
        c.push = PushService(c.repo, s, client=ApnsClient(s, transport=httpx.MockTransport(apns.handle)), clock=c.clock,
                             notifications=c.notifications)
        people = seed_people(c)
        with c.repo.tx() as tx:  # 계정마다 기기 1대(+ 가람은 두 대)
            for login, *_ in PEOPLE:
                tx.put_device(people[login][0].id, tok(login), T0, install_id=f"inst-{login}")
            tx.put_device(people["c-amy"][0].id, tok("c-amy-2"), T0, install_id="inst-c-amy-2")
        yield Chat(client, c, people), apns, tmp_path / "photos"


def settle(c, timeout: float = 3.0) -> None:
    """이벤트 루프에 띄운 푸시 태스크가 다 끝날 때까지(TestClient 의 루프는 다른 스레드에서 돈다)."""
    deadline = time.time() + timeout
    while c.push.tasks and time.time() < deadline:
        time.sleep(0.01)
    assert not c.push.tasks


def listen(c, account_id: int, device_id: int | None = None) -> _Conn:
    """허브에 연결 하나를 꽂는다(GET /api/board/stream 이 frames() 에서 하는 것과 같은 _Conn)."""
    conn = _Conn(account_id, device_id)
    c.hub._conns.add(conn)
    return conn


def frames(conn: _Conn) -> list[tuple[str, dict, str]]:
    """(이벤트, 데이터, 원문) — 큐를 비운다."""
    out = []
    while not conn.q.empty():
        raw = conn.q.get_nowait()
        event = raw.split("\n", 1)[0].removeprefix("event: ")
        out.append((event, json.loads(raw.split("data: ", 1)[1]), raw))
    return out


def chat_frames(conn: _Conn) -> list[tuple[str, dict, str]]:
    return [f for f in frames(conn) if f[0].startswith("chat_")]


# ------------------------------------------------------------------ 푸시 대상(HTTP 경로 → 가짜 APNs)
def test_chat_push_targets_http(env, caplog):
    chat, apns, _ = env
    with chat.c.repo.tx() as tx:
        unread_before = {a: tx.unread_count(chat.id(a), T0.replace(hour=0)) for a in ("c-ben", "c-cat")}
    g = chat.group("c-amy", ["c-ben", "c-cat", "c-dan", "c-eve"]).json()["id"]
    chat.client.put(f"/api/chat/rooms/{g}/mute", json={"muted": True}, headers=chat.h("c-cat"))  # 알림 끔
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-dan"))  # 나감
    with chat.c.repo.tx() as tx:
        tx.update_account(chat.id("c-eve"), T0, active=False)  # 비활성
    settle(chat.c)
    assert apns.requests == []  # 시스템 줄(나감) = 푸시 0
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        r = chat.send("c-amy", g, "그룹 글", client_id="push-0000001")
        settle(chat.c)
    assert r.status_code == 200
    assert apns.tokens() == [tok("c-ben")]  # 보낸 사람 · 알림 끈 사람 · 나간 사람 · 비활성 = 빠짐
    assert "이벤트 루프 없음" not in caplog.text
    # 같은 clientId 다시 = 0
    assert chat.send("c-amy", g, "그룹 글", client_id="push-0000001").status_code == 200
    settle(chat.c)
    assert len(apns.requests) == 1
    # 숨긴 1:1 = 받음
    d = chat.direct("c-amy", "c-fay").json()["id"]
    chat.client.post(f"/api/chat/rooms/{d}/hide", headers=chat.h("c-fay"))
    chat.tick()
    chat.send("c-amy", d, "숨긴 방에도")
    settle(chat.c)
    assert apns.tokens()[1:] == [tok("c-fay")]
    # 받는 사람이 보낸 글 = 보낸 사람 기기 둘 다(같은 계정 두 기기)
    chat.send("c-fay", d, "답장")
    settle(chat.c)
    assert sorted(apns.tokens()[2:]) == sorted([tok("c-amy"), tok("c-amy-2")])
    # notification 행 0 · 종 unread 그대로
    with chat.c.repo.tx() as tx:
        assert tx.con.execute("SELECT COUNT(*) FROM notification").fetchone()[0] == 0
        assert {a: tx.unread_count(chat.id(a), T0.replace(hour=0)) for a in ("c-ben", "c-cat")} == unread_before
        logs = tx.push_logs()
    assert {x["kind"] for x in logs} == {"chat"} and len(logs) == 4


# ------------------------------------------------------------------ 푸시 내용
def test_chat_push_content(env):
    chat, apns, _ = env
    d = chat.direct("c-amy", "c-ben").json()["id"]
    m = chat.send("c-amy", d, "첫 줄\n둘째 줄").json()
    settle(chat.c)
    req = apns.requests[0]
    assert req["payload"] == {"aps": {"alert": {"title": "가람", "body": "첫 줄 둘째 줄"}, "sound": "default",
                                      "thread-id": f"chat-{d}"}, "kind": "chat", "roomId": d, "messageId": m["id"]}
    assert "category" not in req["payload"]["aps"] and "badge" not in req["payload"]["aps"]
    apns.requests.clear()
    chat.send("c-amy", d, "가" * 150)
    settle(chat.c)
    assert apns.requests[0]["payload"]["aps"]["alert"]["body"] == "가" * 100 + "…"
    # 사진 = 「사진」
    apns.requests.clear()
    pid = chat.client.post("/api/chat/photos", data={"roomId": str(d), "width": "20", "height": "10"},
                           files={"photo": ("a.jpg", JPEG, "image/jpeg")}, headers=chat.h("c-amy")).json()["photoId"]
    chat.send("c-amy", d, None, photoId=pid)
    settle(chat.c)
    assert apns.requests[0]["payload"]["aps"]["alert"] == {"title": "가람", "body": "사진"}
    # 그룹 = 「보낸 사람 · 방 이름」 · 이름 없는 그룹 = 받는 사람 기준 나열
    apns.requests.clear()
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    chat.send("c-amy", g, "그룹")
    settle(chat.c)
    titles = {r["token"]: r["payload"]["aps"]["alert"]["title"] for r in apns.requests}
    assert titles == {tok("c-ben"): "가람 · 가람, 다솜", tok("c-cat"): "가람 · 가람, 나래"}
    apns.requests.clear()
    named = chat.group("c-amy", ["c-ben", "c-cat"], title="오후 회의").json()["id"]
    chat.send("c-amy", named, "이름 있는 그룹")
    settle(chat.c)
    assert {r["payload"]["aps"]["alert"]["title"] for r in apns.requests} == {"가람 · 오후 회의"}
    assert all(r["payload"]["aps"]["thread-id"] == f"chat-{named}" for r in apns.requests)
    with chat.c.repo.tx() as tx:
        logs = tx.push_logs()
    assert logs[0]["kind"] == "chat" and logs[0]["chat_message_id"] == m["id"]
    assert all(x["call_id"] is None and x["visit_id"] is None and x["notification_id"] is None and x["category"] is None
               for x in logs)


# ------------------------------------------------------------------ 만료
def test_chat_push_expiration(env):
    chat, apns, _ = env
    d = chat.direct("c-amy", "c-ben").json()["id"]
    chat.send("c-amy", d, "만료")
    settle(chat.c)
    assert apns.requests[0]["headers"]["apns-expiration"] == str(int(T0.timestamp()) + 86400)
    # 원장 호출 · 상담사 호출 · 띄우기 = 0 그대로(Delivery 기본값 · _send 까지 같은 길)
    apns.requests.clear()
    base = dict(call_id=None, visit_id=None, account_id=chat.id("c-ben"), role="doctor", device_id=1, token=tok("x"),
                category=None, payload={"aps": {"alert": {"title": "t", "body": "b"}}})
    msgs = [Delivery(**base, kind=k) for k in ("doctor_call", "counselor_call", "display")]
    asyncio.run(chat.c.push.deliver(msgs, "회귀"))
    assert [r["headers"]["apns-expiration"] for r in apns.requests] == ["0", "0", "0"]


# ------------------------------------------------------------------ SSE
def test_chat_sse(env):
    chat, apns, _ = env
    c = chat.c
    conns = {login: listen(c, chat.id(login)) for login in ("c-amy", "c-ben", "c-cat", "c-dan")}
    amy2 = listen(c, chat.id("c-amy"), device_id=99)  # 보낸 사람 다른 기기
    version = c.hub.version
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    created = {k: chat_frames(v) for k, v in conns.items()}
    # chat_room = 계정마다 다른 name · unread · me
    assert created["c-dan"] == []
    room_of = {k: v[0][1]["room"] for k, v in created.items() if v}
    assert room_of["c-amy"]["name"] == "나래, 다솜" and room_of["c-ben"]["name"] == "가람, 다솜"
    assert [m["me"] for m in room_of["c-ben"]["members"]] == [True, False, False]
    chat_frames(amy2)
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-cat"))
    left = chat_frames(conns["c-cat"])
    assert [e for e, *_ in left] == ["chat_room_removed"] and left[0][1] == {"roomId": g}
    assert {e for e, *_ in chat_frames(conns["c-amy"])} == {"chat_room", "chat_message"}
    chat_frames(conns["c-ben"])
    chat_frames(amy2)
    # chat_message = 지금 멤버 연결만(나간 사람 · 다른 계정 0) · 보낸 사람 다른 기기 받음
    m = chat.send("c-amy", g, "멤버만").json()
    got = {k: chat_frames(v) for k, v in conns.items()}
    assert [e for e, *_ in got["c-amy"]] == ["chat_message"] and got["c-amy"][0][1] == {"roomId": g, "message": m}
    assert [e for e, *_ in got["c-ben"]] == ["chat_message"]
    assert got["c-cat"] == [] and got["c-dan"] == []
    assert [e for e, *_ in chat_frames(amy2)] == ["chat_message"]
    # chat_read = 내 계정 연결만
    chat.read("c-ben", g, m["id"])
    assert [(e, d) for e, d, _ in chat_frames(conns["c-ben"])] == [
        ("chat_read", {"roomId": g, "lastViewedAt": "2026-10-21T11:00:00.000+09:00", "lastReadMessageId": m["id"],
                       "unreadRooms": 0})]
    assert chat_frames(conns["c-amy"]) == []
    # 알림 끄기 = 나만 chat_room(muted)
    chat.client.put(f"/api/chat/rooms/{g}/mute", json={"muted": True}, headers=chat.h("c-ben"))
    mine = chat_frames(conns["c-ben"])
    assert [e for e, *_ in mine] == ["chat_room"] and mine[0][1]["room"]["muted"] is True
    assert chat_frames(conns["c-amy"]) == []
    # 삭제 = chat_message_deleted
    chat.tick()
    chat.client.delete(f"/api/chat/messages/{m['id']}", headers=chat.h("c-amy"))
    dele = chat_frames(conns["c-ben"])
    assert [e for e, *_ in dele] == ["chat_message_deleted"]
    assert dele[0][1] == {"roomId": g, "messageId": m["id"], "updatedAt": "2026-10-21T11:00:00.001+09:00"}
    # 1:1 처음 만듦 = 두 사람 · 숨김 = chat_room_removed(내 계정) · 숨긴 1:1 이 새 메시지로 다시 보임 = 그 사람 chat_room
    d = chat.direct("c-amy", "c-dan").json()["id"]
    assert [e for e, *_ in chat_frames(conns["c-dan"])] == ["chat_room"]
    chat_frames(conns["c-amy"])
    chat.client.post(f"/api/chat/rooms/{d}/hide", headers=chat.h("c-dan"))
    assert [e for e, *_ in chat_frames(conns["c-dan"])] == ["chat_room_removed"]
    chat.tick()
    chat.send("c-amy", d, "다시 보여요")
    back = chat_frames(conns["c-dan"])
    assert [e for e, *_ in back] == ["chat_room", "chat_message"] and back[0][1]["room"]["unread"] == 1
    # 허브 version 그대로(id: 없음은 아래 시험)
    c.hub._conns.clear()
    assert c.hub.version == version
    settle(c)


def test_chat_sse_frames_have_no_id(env):
    """다섯 이벤트 이름 · `id:` 없음 — 원문 꼴."""
    chat, _, _ = env
    c = chat.c
    amy, ben = listen(c, chat.id("c-amy")), listen(c, chat.id("c-ben"))
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    m = chat.send("c-ben", g, "글").json()
    chat.read("c-amy", g, m["id"])
    chat.client.delete(f"/api/chat/messages/{m['id']}", headers=chat.h("c-ben"))
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-amy"))
    raws = [raw for conn in (amy, ben) for *_, raw in chat_frames(conn)]
    names = {r.split("\n", 1)[0] for r in raws}
    assert names == {f"event: {n}" for n in ("chat_room", "chat_message", "chat_message_deleted", "chat_read",
                                             "chat_room_removed")}
    assert all(r.split("\n")[1].startswith("data: ") and "\nid:" not in r for r in raws)
    c.hub._conns.clear()
    settle(c)


# ------------------------------------------------------------------ 중복 방지 — SSE · 푸시
def test_chat_dedupe_sse_push(env):
    chat, apns, _ = env
    d = chat.direct("c-amy", "c-ben").json()["id"]
    ben = listen(chat.c, chat.id("c-ben"))
    for _ in range(2):
        assert chat.send("c-amy", d, "한 번", client_id="same-00000001").status_code == 200
    settle(chat.c)
    assert [e for e, *_ in chat_frames(ben)] == ["chat_message"]
    assert apns.tokens() == [tok("c-ben")]
    chat.c.hub._conns.clear()


# ------------------------------------------------------------------ 사진
def upload(chat, login, room, data=JPEG, **headers):
    return chat.client.post("/api/chat/photos", data={"roomId": str(room), "width": "40", "height": "30"},
                            files={"photo": ("p.jpg", data, "image/jpeg")}, headers={**chat.h(login), **headers})


def test_chat_photo(env, caplog):
    chat, _, folder = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    big = b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024 - 3)  # 정확히 5MB
    r = upload(chat, "c-amy", g, big)
    assert r.status_code == 200
    r = upload(chat, "c-amy", g, big + b"\x00")
    assert (r.status_code, r.json()["error"]["code"]) == (413, "photo_too_large")
    r = upload(chat, "c-amy", g, b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "chat_photo_type")
    assert upload(chat, "c-dan", g).json()["error"]["code"] == "chat_room_not_found"  # 멤버 아님
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        pid = upload(chat, "c-amy", g).json()["photoId"]
        # 파일 = PROC_PHOTO_DIR/chat/ · 이름에 계정 값 없음
        with chat.c.repo.tx() as tx:
            row = tx.chat_photo(pid)
        assert row["width"] == 40 and row["height"] == 30 and row["message_id"] is None
        assert (folder / "chat" / row["file_name"]).read_bytes() == JPEG
        assert re.fullmatch(r"[0-9a-f]{32}\.jpg", row["file_name"])  # 무작위 이름만(계정 · 방 값 없음)
        assert not list(folder.glob("*.jpg"))  # 신분증 자리(바로 아래)와 섞지 않음
        # 붙기 전 = 올린 사람만(같은 방 다른 멤버 = 404)
        r = chat.client.get(f"/api/chat/photos/{pid}", headers=chat.h("c-amy"))
        assert r.status_code == 200 and r.content == JPEG
        assert r.headers["cache-control"] == "no-store" and r.headers["content-type"] == "image/jpeg"
        assert r.headers["content-disposition"] == "inline"
        assert chat.client.get(f"/api/chat/photos/{pid}", headers=chat.h("c-ben")).json()["error"]["code"] == \
            "chat_photo_not_found"
        # 붙인 뒤 = 방 멤버 열림 · 멤버 아님 · 나간 사람 = 404
        m = chat.send("c-amy", g, None, photoId=pid).json()
        assert m["photo"] == {"id": pid, "width": 40, "height": 30}
        assert chat.client.get(f"/api/chat/photos/{pid}", headers=chat.h("c-ben")).status_code == 200
        assert chat.client.get(f"/api/chat/photos/{pid}", headers=chat.h("c-dan")).status_code == 404
        chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-cat"))
        assert chat.client.get(f"/api/chat/photos/{pid}", headers=chat.h("c-cat")).status_code == 404
    text = "\n".join(x.getMessage() for x in caplog.records)
    assert row["file_name"] not in text and "가람" not in text
    # Bearer 헤더만 — 헤더 없음 · ?token= = 401
    assert chat.client.get(f"/api/chat/photos/{pid}").status_code == 401
    token = chat.h("c-amy")["Authorization"].removeprefix("Bearer ")
    assert chat.client.get(f"/api/chat/photos/{pid}?token={token}").status_code == 401
    # 열람 · 올리기 event_log 0
    with chat.c.repo.tx() as tx:
        assert tx.events() == []
    # 행 있고 파일 없음 = 404
    (folder / "chat" / row["file_name"]).unlink()
    assert chat.client.get(f"/api/chat/photos/{pid}", headers=chat.h("c-amy")).json()["error"]["code"] == \
        "chat_photo_not_found"
    assert chat.client.get("/api/chat/photos/9999", headers=chat.h("c-amy")).status_code == 404


def test_chat_photo_disabled(tmp_path):
    """PROC_PHOTO_DIR 빔 = 올리기 · 열기 둘 다 409 photo_disabled."""
    s = make_settings(tmp_path)
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        c.clock.set(T0)
        chat = Chat(client, c, seed_people(c))
        d = chat.direct("c-amy", "c-ben").json()["id"]
        r = upload(chat, "c-amy", d)
        assert (r.status_code, r.json()["error"]["code"]) == (409, "photo_disabled")
        with c.repo.tx() as tx:
            pid = tx.add_chat_photo(room_id=d, account_id=chat.id("c-amy"), file_name="x.jpg", bytes=3, sha256="0",
                                    width=1, height=1, created_at="2026-10-21T02:00:00.000+00:00")
        r = client.get(f"/api/chat/photos/{pid}", headers=chat.h("c-amy"))
        assert (r.status_code, r.json()["error"]["code"]) == (409, "photo_disabled")


# ------------------------------------------------------------------ 삭제 — 사진
def test_chat_photo_delete(env):
    chat, _, folder = env
    d = chat.direct("c-amy", "c-ben").json()["id"]
    pid = upload(chat, "c-amy", d).json()["photoId"]
    m = chat.send("c-amy", d, None, photoId=pid).json()
    with chat.c.repo.tx() as tx:
        name = tx.chat_photo(pid)["file_name"]
    assert (folder / "chat" / name).is_file()
    chat.tick()
    assert chat.client.delete(f"/api/chat/messages/{m['id']}", headers=chat.h("c-amy")).status_code == 200
    assert not (folder / "chat" / name).exists()
    with chat.c.repo.tx() as tx:
        assert tx.chat_photo(pid)["deleted_at"] == "2026-10-21T02:00:00.001+00:00"
    got = chat.msgs("c-ben", d).json()["items"][0]
    assert got["photo"] is None and got["deletedAt"]
    for login in ("c-amy", "c-ben"):
        assert chat.client.get(f"/api/chat/photos/{pid}", headers=chat.h(login)).status_code == 404
    # 지운 사진은 다시 붙일 수 없다
    assert chat.send("c-amy", d, None, photoId=pid).json()["error"]["code"] == "chat_photo_invalid"


# ------------------------------------------------------------------ 로그(푸시)
def test_chat_push_log_ids_only(env, caplog):
    chat, apns, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat"], title="비밀 방 이름").json()["id"]
    apns.status[tok("c-cat")] = 500  # 실패 로그도 본다
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        m = chat.send("c-amy", g, "푸시 본문은 로그 밖").json()
        settle(chat.c)
    text = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("procedure"))
    assert f"채팅 message={m['id']} 푸시 실패" in text and f"채팅 message={m['id']} 푸시 보냄 1" in text
    for secret in ("푸시 본문은 로그 밖", "비밀 방 이름", "가람", "나래", "다솜", "가람 · 비밀 방 이름"):
        assert secret not in text
    assert "이벤트 루프 없음" not in text
