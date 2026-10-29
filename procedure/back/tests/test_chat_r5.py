"""WORK-011 WP-BE5 — 직원 채팅 r5: 들어온 뒤 대화만(D9-69) · 초대 문구 · 그룹 만들기 줄(D9-68) · 모아보기 #20(D9-67)
(SPEC-007 0.5.0 §4.6 V1 ~ V12 · §13.1 r5 줄 · 코디 처분 r5 FAIL-1 · W-1).

경계(from_message_id) 거름은 읽기 길마다 실 router(TestClient · async def)로 부르고 받는 쪽(응답 · 가짜 APNs · 허브 연결 큐)에서
단언한다 — 서비스를 직접 불러 대신하지 않는다. 사진 · 동영상 바이트는 모양만 맞춘 가짜(고객 것 아님).
"""

import logging
import sqlite3

from app.repository.db import Database
from app.repository.repo import Repository
from tests import test_chat_push as cp
from tests import test_chat_r3 as r3
from tests.helpers import T0
from tests.test_push import tok

env = cp.env
settle, listen, chat_frames, upload = cp.settle, cp.listen, cp.chat_frames, cp.upload
code, up_video, patch = r3.code, r3.up_video, r3.patch


def photo(chat, login, room) -> dict:
    pid = upload(chat, login, room).json()["photoId"]
    r = chat.send(login, room, None, photoId=pid)
    assert r.status_code == 200, r.json()
    return r.json()


def video(chat, login, room) -> dict:
    vid = up_video(chat, login, room).json()["videoId"]
    r = chat.send(login, room, None, videoId=vid)
    assert r.status_code == 200, r.json()
    return r.json()


def invite(chat, login, room, logins):
    return chat.client.post(f"/api/chat/rooms/{room}/members", json={"accountIds": [chat.id(x) for x in logins]},
                            headers=chat.h(login))


def att(chat, login, room, **q):
    return chat.client.get(f"/api/chat/rooms/{room}/attachments", params=q, headers=chat.h(login))


def ids(r) -> list[int]:
    assert r.status_code == 200, r.json()
    return [m["id"] for m in r.json()["items"]]


def get(chat, login, path, **headers):
    return chat.client.get(path, headers={**chat.h(login), **headers})


def fwd(chat, login, mid, room, cid):
    return chat.client.post(f"/api/chat/messages/{mid}/forward", json={"targets": [{"roomId": room, "clientId": cid}]},
                            headers=chat.h(login))


def members(chat) -> list[dict]:
    with chat.c.repo.tx() as tx:
        return [dict(r) for r in tx.con.execute("SELECT * FROM chat_member")]


# ------------------------------------------------------------------ 경계 — 처음 초대
def test_chat_boundary_invite(env, caplog):
    """§13.1 「들어온 뒤 대화만 — 경계」 — V1 · V2 · V3 · V4 · V5 · V6 · V7 를 HTTP 로."""
    chat, _, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    old_text = chat.send("c-amy", g, "옛 글").json()
    old_photo = photo(chat, "c-amy", g)
    old_video = video(chat, "c-ben", g)
    kept_photo = photo(chat, "c-ben", g)
    chat.tick()
    since = chat.msgs("c-amy", g).json()["items"][-1]["updatedAt"]
    assert invite(chat, "c-amy", g, ["c-dan"]).status_code == 200
    a_all = ids(chat.msgs("c-amy", g))
    # V1 — 처음 = 초대 줄부터만 · before 로 더 읽어도 그 전 없음 · hasMore false
    r = chat.msgs("c-dan", g)
    assert [m["text"] for m in r.json()["items"]] == ["가람님이 라온님을 초대했습니다"] and r.json()["hasMore"] is False
    line = r.json()["items"][0]["id"]
    r = chat.msgs("c-dan", g, before=line)
    assert r.json() == {"items": [], "hasMore": False}
    r = chat.msgs("c-dan", g, limit=1)
    assert ids(r) == [line] and r.json()["hasMore"] is False  # 경계에 닿음
    # V2 — since: 옛 메시지를 A 가 고침 · 지움(updated_at 올라감) → 라온에게 안 나옴 · A 에게는 나옴
    chat.tick()
    assert patch(chat, "c-amy", old_text["id"], {"text": "옛 글 고침"}).status_code == 200
    assert chat.client.delete(f"/api/chat/messages/{old_photo['id']}", headers=chat.h("c-amy")).status_code == 200
    assert ids(chat.msgs("c-dan", g, since=since)) == [line]
    assert {old_text["id"], old_photo["id"]} <= set(ids(chat.msgs("c-amy", g, since=since)))
    # V3 · V4 — 미리보기 = 초대 줄 · 안 읽음 0 → 새 글 = 1
    room = chat.room("c-dan", g)
    assert room["lastMessage"]["id"] == line and room["unread"] == 0 and chat.rooms("c-dan")["unreadRooms"] == 0
    chat.tick()
    new_photo = photo(chat, "c-amy", g)
    assert chat.room("c-dan", g)["unread"] == 1 and chat.rooms("c-dan")["unreadRooms"] == 1
    # V5 — 옛 사진 · 동영상 · 썸네일 404(Range 포함) · 새 사진 열림 · A 는 그대로
    vid, kept = old_video["video"]["id"], kept_photo["photo"]["id"]
    for path, headers, missing in ((f"/api/chat/videos/{vid}", {}, "chat_video_not_found"),
                                   (f"/api/chat/videos/{vid}", {"Range": "bytes=0-9"}, "chat_video_not_found"),
                                   (f"/api/chat/videos/{vid}/thumbnail", {}, "chat_video_not_found"),
                                   (f"/api/chat/photos/{kept}", {}, "chat_photo_not_found")):
        r = get(chat, "c-dan", path, **headers)
        assert (r.status_code, code(r)) == (404, missing), path
    assert get(chat, "c-dan", f"/api/chat/photos/{new_photo['photo']['id']}").status_code == 200
    assert get(chat, "c-amy", f"/api/chat/videos/{vid}", Range="bytes=0-9").status_code == 206
    assert get(chat, "c-amy", f"/api/chat/videos/{vid}/thumbnail").status_code == 200
    assert get(chat, "c-amy", f"/api/chat/photos/{kept}").status_code == 200
    # V6 — 옛 메시지 id 로 전달 = 404 chat_message_not_found · 새 것은 됨
    d = chat.direct("c-dan", "c-eve").json()["id"]
    for mid in (old_text["id"], old_video["id"], kept_photo["id"]):
        r = fwd(chat, "c-dan", mid, d, f"fwd-old-{mid:04d}")
        assert (r.status_code, code(r)) == (404, "chat_message_not_found")
    assert fwd(chat, "c-dan", new_photo["id"], d, "fwd-new-0001").json()["results"][0]["ok"] is True
    # V7 — 모아보기 = 새 첨부만 · A = 전부(지운 사진 빼고)
    assert ids(att(chat, "c-dan", g)) == [new_photo["id"]]
    assert ids(att(chat, "c-amy", g)) == [new_photo["id"], kept_photo["id"], old_video["id"]]
    # A(처음 멤버)는 전부 그대로
    assert ids(chat.msgs("c-amy", g))[: len(a_all)] == a_all
    assert "옛 글" not in caplog.text and "가람" not in caplog.text


# ------------------------------------------------------------------ 경계 — 다시 초대
def test_chat_boundary_reinvite(env):
    """§13.1 「들어온 뒤 대화만 — 다시 초대」 + V8(내 옛 메시지 고치기 · 지우기 404 · OQ-969)."""
    chat, _, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    mine = chat.send("c-cat", g, "다솜 옛 글").json()
    mine_photo = photo(chat, "c-cat", g)
    m1 = chat.send("c-amy", g, "m1").json()
    assert chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-cat")).status_code == 200
    m2 = chat.send("c-amy", g, "m2").json()
    chat.tick()
    assert invite(chat, "c-ben", g, ["c-cat"]).status_code == 200
    m3 = chat.send("c-amy", g, "m3").json()
    assert [m["text"] for m in chat.msgs("c-cat", g).json()["items"]] == ["나래님이 다솜님을 초대했습니다", "m3"]
    seen = set(ids(chat.msgs("c-cat", g)))
    assert not {mine["id"], mine_photo["id"], m1["id"], m2["id"]} & seen and m3["id"] in seen
    # 내 옛 메시지 — 고치기 · 지우기 · 전달 = 404(403 · 400 보다 먼저) · 그 사진 열기 404
    for r in (patch(chat, "c-cat", mine["id"], {"text": "고침"}),
              patch(chat, "c-cat", mine_photo["id"], {"text": "고침"}),  # 사진(원래 400) · 경계 안 = 404
              patch(chat, "c-cat", m1["id"], {"text": "고침"}),  # 남의 것(원래 403) · 경계 안 = 404
              chat.client.delete(f"/api/chat/messages/{mine['id']}", headers=chat.h("c-cat")),
              chat.client.delete(f"/api/chat/messages/{m1['id']}", headers=chat.h("c-cat")),
              fwd(chat, "c-cat", mine["id"], g, "fwd-mine-0001")):
        assert (r.status_code, code(r)) == (404, "chat_message_not_found")
    r = get(chat, "c-cat", f"/api/chat/photos/{mine_photo['photo']['id']}")
    assert (r.status_code, code(r)) == (404, "chat_photo_not_found")
    assert ids(att(chat, "c-cat", g)) == []
    # 남은 멤버에게는 다솜의 옛 메시지 그대로
    texts = [m["text"] for m in chat.msgs("c-ben", g).json()["items"]]
    assert "다솜 옛 글" in texts and "m1" in texts and "m2" in texts
    assert get(chat, "c-ben", f"/api/chat/photos/{mine_photo['photo']['id']}").status_code == 200
    # 경계 밖 내 새 글은 고칠 수 있다
    new = chat.send("c-cat", g, "새 글").json()
    assert patch(chat, "c-cat", new["id"], {"text": "새 글 고침"}).status_code == 200


# ------------------------------------------------------------------ 경계 — 같은 밀리초
def test_chat_boundary_same_ms(env):
    """시계를 한 밀리초에 고정 — 시각이 같아도 id 로 가른다(OQ-962)."""
    chat, _, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    chat.tick()
    x = chat.send("c-amy", g, "x").json()
    assert invite(chat, "c-amy", g, ["c-dan"]).status_code == 200  # 같은 밀리초(tick 없음)
    items = chat.msgs("c-dan", g).json()["items"]
    assert [m["text"] for m in items] == ["가람님이 라온님을 초대했습니다"]
    assert items[0]["createdAt"] == x["createdAt"]
    with chat.c.repo.tx() as tx:
        me = tx.chat_member(g, chat.id("c-dan"))
    assert me["from_message_id"] == x["id"] and me["joined_at"] == tx_created(chat, x["id"])


def tx_created(chat, mid) -> str:
    with chat.c.repo.tx() as tx:
        return tx.chat_message(mid)["created_at"]


# ------------------------------------------------------------------ 경계 — SSE · 푸시(V9 · V10 · FAIL-1)
def test_chat_boundary_sse(env):
    """경계 안 메시지를 고침 · 지움 → 라온 연결에 edited · deleted 0 · 새 메시지는 받음 · chat_room lastMessage null."""
    chat, apns, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    old = chat.send("c-amy", g, "옛 글").json()
    old2 = chat.send("c-amy", g, "옛 글 2").json()
    assert invite(chat, "c-amy", g, ["c-dan"]).status_code == 200
    settle(chat.c)
    a, b, dan = listen(chat.c, chat.id("c-amy")), listen(chat.c, chat.id("c-ben")), listen(chat.c, chat.id("c-dan"))
    assert patch(chat, "c-amy", old["id"], {"text": "고침"}).status_code == 200
    assert chat.client.delete(f"/api/chat/messages/{old2['id']}", headers=chat.h("c-amy")).status_code == 200
    assert [f[0] for f in chat_frames(dan)] == []
    for conn in (a, b):
        assert [f[0] for f in chat_frames(conn)] == ["chat_message_edited", "chat_message_deleted"]
    new = chat.send("c-ben", g, "새 글").json()
    assert [f[1]["message"]["id"] for f in chat_frames(dan) if f[0] == "chat_message"] == [new["id"]]
    settle(chat.c)
    assert tok("c-dan") in apns.tokens()
    # chat_room(라온 기준) — 마지막 메시지가 라온 경계 안이면 lastMessage null · lastMessageAt 그대로
    with chat.c.repo.tx() as tx:
        tx.update_chat_member(g, chat.id("c-dan"), from_message_id=new["id"], last_read_message_id=new["id"])
    chat_frames(a)
    assert chat.client.put(f"/api/chat/rooms/{g}/mute", json={"muted": True}, headers=chat.h("c-dan")).status_code == 200
    room = [f[1]["room"] for f in chat_frames(dan) if f[0] == "chat_room"][0]
    assert room["lastMessage"] is None and room["lastMessageAt"] == new["createdAt"]
    assert chat.room("c-dan", g)["lastMessage"] is None
    assert chat.room("c-amy", g)["lastMessage"]["id"] == new["id"]
    chat.c.hub._conns.clear()


def test_chat_boundary_push_race(env):
    """처분 FAIL-1 — 글 커밋 뒤 푸시 태스크가 받는 사람을 다시 읽기 전에 초대 → 새 멤버 가짜 APNs 요청 0 · SSE 0."""
    chat, apns, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    settle(chat.c)
    dan = listen(chat.c, chat.id("c-dan"))
    held: list[int] = []
    real = chat.c.chat.push
    chat.c.chat.push = held.append  # 태스크를 띄우지 않고 잡아 둔다(초대 뒤에 같은 길로 보낸다)
    try:
        mid = chat.send("c-amy", g, "글").json()["id"]
        assert invite(chat, "c-ben", g, ["c-dan"]).status_code == 200
    finally:
        chat.c.chat.push = real
    assert held == [mid]
    apns.requests.clear()
    chat.client.portal.call(chat.c.push.notify_chat, mid)
    assert sorted(apns.tokens()) == sorted([tok("c-ben"), tok("c-cat")])  # 라온 0
    assert [f for f in chat_frames(dan) if f[0] == "chat_message" and f[1]["message"]["id"] == mid] == []
    chat.c.hub._conns.clear()


# ------------------------------------------------------------------ 안 읽음 불변식 · 옛 DB
def test_chat_unread_invariant(env):
    """모든 길(만들기 · 추가 · 다시 초대 · 1:1 만들기 · 읽음 · 보내기 · 전달) 뒤 last_read ≥ from."""
    chat, _, _ = env

    def check():
        rows = members(chat)
        assert rows and all(r["last_read_message_id"] >= r["from_message_id"] for r in rows), rows

    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    check()
    for _ in range(3):
        chat.send("c-ben", g, "글")
    assert invite(chat, "c-amy", g, ["c-dan"]).status_code == 200
    check()
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-dan"))
    chat.send("c-ben", g, "빠진 동안")
    assert invite(chat, "c-amy", g, ["c-dan"]).status_code == 200
    check()
    d = chat.direct("c-dan", "c-eve").json()["id"]
    check()
    first = ids(chat.msgs("c-dan", g))[0]
    assert chat.read("c-dan", g, 1).status_code == 200 and chat.read("c-dan", g, first).status_code == 200
    check()
    m = chat.send("c-dan", g, "보냄").json()
    check()
    r = chat.client.post(f"/api/chat/messages/{m['id']}/forward",
                         json={"targets": [{"roomId": d, "clientId": "inv-fwd-0001"},
                                           {"accountId": chat.id("c-fay"), "clientId": "inv-fwd-0002"}]},
                         headers=chat.h("c-dan"))
    assert all(x["ok"] for x in r.json()["results"])
    check()


OLD_MEMBER = """
CREATE TABLE chat_member (room_id INTEGER NOT NULL, account_id INTEGER NOT NULL, joined_at TEXT NOT NULL, left_at TEXT,
    hidden_at TEXT, last_viewed_at TEXT, last_read_message_id INTEGER NOT NULL DEFAULT 0,
    muted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (room_id, account_id));
"""


def test_chat_from_backfill_migration(tmp_path):
    """옛 DB(경계 열 없음) 부팅 → 열 생김 · joined_at 보다 먼저 만든 마지막 id(없으면 0 · 같은 밀리초 = 보임) · 나간 행도 ·
    두 번째 부팅은 채우지 않음 · 채우기 전 · 뒤 안 읽음 같음(처분 W-1)."""
    path = tmp_path / "old.db"
    Database(path)  # 새 모양으로 만든 뒤 chat_member 만 옛 모양(경계 열 없음)으로 되돌린다
    con = sqlite3.connect(path)
    con.executescript("DROP TABLE chat_member;" + OLD_MEMBER)
    t = "2026-10-29T01:00:00.{:03d}+00:00".format
    # 방 1: 메시지 1(t1) · 2(t3) · 3(t5) · 4(t5) · 5(t7)
    for mid, ms in ((1, 1), (2, 3), (3, 5), (4, 5), (5, 7)):
        con.execute("INSERT INTO chat_message (id, room_id, account_id, kind, body, created_at, updated_at) "
                    "VALUES (?, 1, 1, 'text', 'x', ?, ?)", (mid, t(ms), t(ms)))
    con.execute("INSERT INTO chat_message (id, room_id, account_id, kind, body, created_at, updated_at) "
                "VALUES (6, 2, 1, 'text', 'x', ?, ?)", (t(9), t(9)))
    rows = [  # (room, account, joined_at, left_at, last_read) — 들어올 때 last_read = 그 순간 마지막 id(D9-45)
        (1, 1, t(0), None, 5),  # 처음부터 → 0
        (1, 2, t(4), None, 2),  # t4 전 = 1 · 2 → 2
        (1, 3, t(5), None, 4),  # 같은 밀리초 t5 = 보임 → 2
        (1, 4, t(6), t(8), 4),  # 나간 행 → 4
        (2, 1, t(0), None, 0),  # 메시지보다 먼저 → 0
        (2, 2, t(10), None, 6),  # → 6
    ]
    con.executemany("INSERT INTO chat_member (room_id, account_id, joined_at, left_at, last_read_message_id) "
                    "VALUES (?, ?, ?, ?, ?)", rows)
    con.commit()

    def unread():
        return {(r[0], r[1]): con.execute("SELECT COUNT(*) FROM chat_message WHERE room_id = ? AND id > ? AND account_id != ? "
                                          "AND kind != 'system' AND deleted_at IS NULL", (r[0], r[4], r[1])).fetchone()[0]
                for r in rows}

    before = unread()
    con.close()
    Database(path)
    con = sqlite3.connect(path)
    got = dict(((r, a), f) for r, a, f in con.execute("SELECT room_id, account_id, from_message_id FROM chat_member"))
    assert got == {(1, 1): 0, (1, 2): 2, (1, 3): 2, (1, 4): 4, (2, 1): 0, (2, 2): 6}
    assert all(lr >= f for lr, f in con.execute("SELECT last_read_message_id, from_message_id FROM chat_member"))
    assert unread() == before
    con.execute("UPDATE chat_member SET from_message_id = 99 WHERE room_id = 1 AND account_id = 1")  # 두 번째 부팅은 손대지 않음
    con.commit()
    con.close()
    Database(path)
    with Repository(Database(path)).tx() as tx:
        assert tx.chat_member(1, 1)["from_message_id"] == 99 and tx.chat_member(1, 2)["from_message_id"] == 2


# ------------------------------------------------------------------ 초대 문구 · 그룹 만들기 줄(D9-68)
def test_chat_invite_text_create_line(env):
    chat, apns, _ = env
    settle(chat.c)
    apns.requests.clear()
    conns = {x: listen(chat.c, chat.id(x)) for x in ("c-amy", "c-ben", "c-cat")}
    chat.tick(5)
    r = chat.group("c-amy", ["c-cat", "c-ben"])  # 요청 차례 = 다솜 · 나래
    g = r.json()
    assert r.status_code == 200 and g["lastMessageAt"] == g["createdAt"] and g["unread"] == 0
    assert g["lastMessage"]["kind"] == "system" and g["lastMessage"]["text"] == "가람님이 다솜님, 나래님을 초대했습니다"
    items = chat.msgs("c-ben", g["id"]).json()["items"]
    assert [(m["kind"], m["text"]) for m in items] == [("system", "가람님이 다솜님, 나래님을 초대했습니다")]
    for x, conn in conns.items():
        got = [f[1]["message"]["id"] for f in chat_frames(conn) if f[0] == "chat_message"]
        assert got == [items[0]["id"]], x
    assert chat.room("c-ben", g["id"])["unread"] == 0 and chat.rooms("c-ben")["unreadRooms"] == 0
    # #5 — 한 사람 · 여럿(고른 차례)
    assert invite(chat, "c-ben", g["id"], ["c-dan"]).status_code == 200
    assert invite(chat, "c-amy", g["id"], ["c-fay", "c-eve"]).status_code == 200
    texts = [m["text"] for m in chat.msgs("c-amy", g["id"]).json()["items"]]
    assert texts[-2:] == ["나래님이 라온님을 초대했습니다", "가람님이 바다님, 마루님을 초대했습니다"]
    settle(chat.c)
    assert apns.requests == []  # 시스템 줄 = 푸시 0
    # 옛 「…초대했어요」 행은 그대로
    with chat.c.repo.tx() as tx:
        old = tx.add_chat_message(room_id=g["id"], account_id=chat.id("c-amy"), kind="system",
                                  body="가람 님이 나래 님을 초대했어요", created_at="2026-10-28T00:00:00.000+00:00",
                                  updated_at="2026-10-28T00:00:00.000+00:00")
    assert invite(chat, "c-amy", g["id"], ["c-cat"]).status_code == 400  # 이미 멤버 — 아무것도 안 씀
    with chat.c.repo.tx() as tx:
        assert tx.chat_message(old)["body"] == "가람 님이 나래 님을 초대했어요"
    # 1:1 [초대] 꼴 — accountIds = [1:1 상대, C] → 새 그룹 · 1:1 그대로 · 두 번 = 방 2
    d = chat.direct("c-amy", "c-ben").json()["id"]
    chat.send("c-amy", d, "1:1 글")
    one = chat.group("c-amy", ["c-ben", "c-dan"]).json()
    two = chat.group("c-amy", ["c-ben", "c-dan"]).json()
    assert one["id"] != two["id"] != d and one["kind"] == "group" and one["title"] is None and one["name"] == "나래, 라온"
    assert [m["text"] for m in chat.msgs("c-ben", one["id"]).json()["items"]] == ["가람님이 나래님, 라온님을 초대했습니다"]
    assert chat.room("c-amy", d)["kind"] == "direct" and chat.room("c-amy", d)["memberCount"] == 2
    assert [m["text"] for m in chat.msgs("c-ben", d).json()["items"]] == ["1:1 글"]
    # 1:1 상대 비활성 = 400 chat_person_invalid
    with chat.c.repo.tx() as tx:
        tx.update_account(chat.id("c-ben"), T0, active=False)
    r = chat.group("c-amy", ["c-ben", "c-dan"])
    assert (r.status_code, code(r)) == (400, "chat_person_invalid")
    chat.c.hub._conns.clear()


# ------------------------------------------------------------------ 모아보기 #20(D9-67)
def test_chat_attachments(env, caplog):
    chat, _, _ = env
    caplog.set_level(logging.INFO)
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    p1 = photo(chat, "c-amy", g)
    chat.send("c-ben", g, "글은 빠짐")
    v1 = video(chat, "c-ben", g)
    p2 = photo(chat, "c-cat", g)
    gone = photo(chat, "c-amy", g)
    assert chat.client.delete(f"/api/chat/messages/{gone['id']}", headers=chat.h("c-amy")).status_code == 200
    row_gone = photo(chat, "c-amy", g)
    with chat.c.repo.tx() as tx:  # 첨부 행만 지운 것(메시지는 그대로) — 빠짐
        tx.update_chat_photo(row_gone["photo"]["id"], deleted_at="2026-10-29T00:00:00.000+00:00")
    # 전달본 = 그 방 행으로
    other = chat.group("c-amy", ["c-dan", "c-eve"]).json()["id"]
    fw = chat.client.post(f"/api/chat/messages/{v1['id']}/forward", json={"targets": [{"roomId": other,
                                                                                         "clientId": "att-fwd-0001"}]},
                          headers=chat.h("c-amy")).json()["results"][0]["message"]
    r = att(chat, "c-ben", g)
    assert r.status_code == 200 and r.json()["hasMore"] is False
    assert ids(r) == [p2["id"], v1["id"], p1["id"]]  # 최근 것 위 · 텍스트 · 시스템 줄 · 지운 것 빠짐
    items = r.json()["items"]
    assert items[1] == v1 and items[0] == p2  # Message 모양 그대로
    fwd_items = att(chat, "c-dan", other).json()["items"]
    assert [m["id"] for m in fwd_items] == [fw["id"]] and fwd_items[0]["video"]["id"] != v1["video"]["id"]
    # before · limit · hasMore
    r = att(chat, "c-ben", g, limit=2)
    assert ids(r) == [p2["id"], v1["id"]] and r.json()["hasMore"] is True
    r = att(chat, "c-ben", g, limit=2, before=v1["id"])
    assert ids(r) == [p1["id"]] and r.json()["hasMore"] is False
    for q in ({"limit": 0}, {"limit": 61}, {"before": "x"}, {"limit": "a"}):
        r = att(chat, "c-ben", g, **q)
        assert (r.status_code, code(r)) == (400, "invalid_request"), q
    # 멤버 아님 · 나간 사람 · 없는 방 = 404 · 401
    for login, room in (("c-dan", g), ("c-ben", 9999)):
        r = att(chat, login, room)
        assert (r.status_code, code(r)) == (404, "chat_room_not_found")
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-cat"))
    assert code(att(chat, "c-cat", g)) == "chat_room_not_found"
    assert chat.client.get(f"/api/chat/rooms/{g}/attachments").status_code == 401
    # 로그에 이름 · 본문 없음 · event_log 0
    assert "글은 빠짐" not in caplog.text and "가람" not in caplog.text and "나래" not in caplog.text
    with chat.c.repo.tx() as tx:
        assert tx.events() == []


def test_chat_attachments_default_60(env):
    chat, _, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    made = [photo(chat, "c-amy", g)["id"] for _ in range(61)]
    r = att(chat, "c-ben", g)
    assert ids(r) == made[::-1][:60] and r.json()["hasMore"] is True
    r = att(chat, "c-ben", g, before=made[1])
    assert ids(r) == [made[0]] and r.json()["hasMore"] is False
    assert ids(att(chat, "c-ben", g, limit=60)) == made[::-1][:60]
