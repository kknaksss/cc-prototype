"""WORK-011 WP-BE1 — 직원 채팅 표 · 방 · 메시지 API(SPEC-007 §2 ~ §6 · §13.1 BE1 줄). 실 router(TestClient)로 부른다."""

import logging
import re
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.chat_env import NOPW, OFF, Chat, seed_people
from tests.conftest import make_settings
from tests.helpers import T0

MS_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$")
MS_KST = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+09:00$")


@pytest.fixture
def chat(tmp_path):
    s = make_settings(tmp_path, proc_photo_dir=str(tmp_path / "photos"))
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        c.clock.set(T0)
        yield Chat(client, c, seed_people(c))


def code(r) -> str:
    return r.json()["error"]["code"]


# ------------------------------------------------------------------ 상대 목록
def test_chat_people(chat):
    r = chat.client.get("/api/chat/people", headers=chat.h("c-amy"))
    assert r.status_code == 200
    items = r.json()["items"]
    names = [x["name"] for x in items]
    assert "가람" not in names  # 나 빠짐
    assert OFF[2] not in names and NOPW[2] not in names  # 비활성 · 비밀번호 없음 빠짐
    assert names == sorted(names) and {"나래", "다솜", "라온", "마루", "바다"} <= set(names)  # 가나다 순
    assert all(set(x) == {"id", "name", "role"} for x in items)
    assert chat.client.get("/api/chat/people").status_code == 401
    assert code(chat.client.get("/api/chat/people", headers={"Authorization": "Bearer x.y"})) == "unauthorized"


# ------------------------------------------------------------------ 권한
def test_chat_permission(chat):
    room = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    mid = chat.send("c-amy", room).json()["id"]
    outsider = "c-dan"
    h = chat.h(outsider)
    calls = [chat.msgs(outsider, room), chat.send(outsider, room), chat.read(outsider, room, mid),
             chat.client.post(f"/api/chat/rooms/{room}/members", json={"accountIds": [chat.id("c-eve")]}, headers=h),
             chat.client.post(f"/api/chat/rooms/{room}/leave", headers=h),
             chat.client.post(f"/api/chat/rooms/{room}/hide", headers=h),
             chat.client.put(f"/api/chat/rooms/{room}/mute", json={"muted": True}, headers=h),
             chat.client.get("/api/chat/rooms/9999/messages", headers=h)]
    assert [(x.status_code, code(x)) for x in calls] == [(404, "chat_room_not_found")] * len(calls)
    assert chat.client.delete(f"/api/chat/messages/{mid}", headers=h).status_code == 404
    assert chat.room(outsider, room) is None
    # 나간 사람도 404
    assert chat.client.post(f"/api/chat/rooms/{room}/leave", headers=chat.h("c-cat")).status_code == 200
    assert chat.msgs("c-cat", room).status_code == 404 and chat.send("c-cat", room).status_code == 404
    # 다섯 역할 모두 ○ — 다섯 역할 그룹에서 각자 읽고 보냄
    five = chat.group("c-amy", ["c-ben", "c-cat", "c-dan", "c-eve"]).json()["id"]
    for login in ("c-amy", "c-ben", "c-cat", "c-dan", "c-eve"):
        assert chat.send(login, five).status_code == 200 and chat.msgs(login, five).status_code == 200


# ------------------------------------------------------------------ 1:1 재사용
def test_chat_direct_reuse(chat):
    a = chat.direct("c-amy", "c-ben")
    assert a.status_code == 200
    room = a.json()
    assert room["kind"] == "direct" and room["title"] is None and room["name"] == "나래" and room["memberCount"] == 2
    assert chat.direct("c-ben", "c-amy").json()["id"] == room["id"]  # 어느 쪽이 열어도
    assert chat.direct("c-amy", "c-ben").json()["id"] == room["id"]  # 두 번 = 방 1
    with chat.c.repo.tx() as tx:
        n = tx.con.execute("SELECT COUNT(*) FROM chat_room WHERE kind = 'direct'").fetchone()[0]
    assert n == 1
    # 숨긴 뒤 다시 열면 보임
    assert chat.client.post(f"/api/chat/rooms/{room['id']}/hide", headers=chat.h("c-amy")).status_code == 200
    assert chat.room("c-amy", room["id"]) is None and chat.room("c-ben", room["id"]) is not None
    assert chat.direct("c-amy", "c-ben").json()["id"] == room["id"]
    assert chat.room("c-amy", room["id"]) is not None
    # 나 · 비활성 · 로그인 불가 · 없는 계정 = 400
    for target in (chat.id("c-amy"), chat.id(OFF[0]), chat.id(NOPW[0]), 9999):
        r = chat.client.post("/api/chat/rooms/direct", json={"accountId": target}, headers=chat.h("c-amy"))
        assert (r.status_code, code(r)) == (400, "chat_person_invalid")


# ------------------------------------------------------------------ 그룹
def test_chat_group(chat):
    r = chat.group("c-amy", ["c-ben", "c-cat"])
    assert r.status_code == 200
    g = r.json()
    assert g["kind"] == "group" and g["title"] is None and g["name"] == "나래, 다솜" and g["memberCount"] == 3
    assert [m["name"] for m in g["members"]] == ["가람", "나래", "다솜"] and g["members"][0]["me"]
    assert chat.room("c-cat", g["id"])["name"] == "가람, 나래"  # 보는 사람 기준 나열
    assert chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"] != g["id"]  # 같은 사람들 두 번 = 방 2
    assert chat.group("c-amy", ["c-ben", "c-cat"], title="   ").json()["title"] is None  # 빈 제목 = null
    assert chat.group("c-amy", ["c-ben", "c-cat"], title="가" * 40).json()["name"] == "가" * 40
    r = chat.group("c-amy", ["c-ben", "c-cat"], title="가" * 41)
    assert (r.status_code, code(r)) == (400, "invalid_request")
    assert code(chat.group("c-amy", ["c-ben"])) == "chat_group_size"  # 1명
    with chat.c.repo.tx() as tx:  # 20명(다른 사람) = 400
        for i in range(20):
            aid = tx.put_account(f"c-x{i:02d}", T0, role="nurse", name=f"자{i:02d}", staff_id=None, active=True, card=False)
            tx.update_account(aid, T0, password_hash="test-only")
        many = [a.id for a in tx.accounts() if a.login_id.startswith("c-x")]
    r = chat.client.post("/api/chat/rooms", json={"accountIds": many}, headers=chat.h("c-amy"))
    assert (r.status_code, code(r)) == (400, "chat_group_size")
    assert chat.client.post("/api/chat/rooms", json={"accountIds": many[:19]}, headers=chat.h("c-amy")).status_code == 200
    # 나 · 중복 · 비활성 = chat_person_invalid
    for ids in ([chat.id("c-amy"), chat.id("c-ben")], [chat.id("c-ben")] * 2, [chat.id("c-ben"), chat.id(OFF[0])]):
        assert code(chat.client.post("/api/chat/rooms", json={"accountIds": ids}, headers=chat.h("c-amy"))) == \
            "chat_person_invalid"
    # 1:1 에 추가 · 나가기 = 400 · 그룹 숨기기 = 400
    d = chat.direct("c-amy", "c-ben").json()["id"]
    r = chat.client.post(f"/api/chat/rooms/{d}/members", json={"accountIds": [chat.id("c-cat")]}, headers=chat.h("c-amy"))
    assert (r.status_code, code(r)) == (400, "chat_group_only")
    assert code(chat.client.post(f"/api/chat/rooms/{d}/leave", headers=chat.h("c-amy"))) == "chat_group_only"
    assert code(chat.client.post(f"/api/chat/rooms/{g['id']}/hide", headers=chat.h("c-amy"))) == "chat_direct_only"


# ------------------------------------------------------------------ 추가 · 나가기
def test_chat_members_add_leave(chat):
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    chat.send("c-amy", g, "첫 메시지")
    chat.tick()
    r = chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": [chat.id("c-dan"), chat.id("c-eve")]},
                         headers=chat.h("c-ben"))
    assert r.status_code == 200 and r.json()["memberCount"] == 5
    items = chat.msgs("c-dan", g).json()["items"]
    assert items[-1]["kind"] == "system" and items[-1]["text"] == "나래 님이 라온 님, 마루 님을 초대했어요"
    assert [m["text"] for m in items] == ["첫 메시지", "나래 님이 라온 님, 마루 님을 초대했어요"]  # 옛 메시지 보임
    assert chat.room("c-dan", g)["unread"] == 0  # D-45 — 처음 들어온 그룹의 옛 메시지 안 셈
    # 나가기 = 시스템 줄 · 내 목록에서 빠짐
    chat.tick()
    assert chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-cat")).json() == {"ok": True}
    assert chat.room("c-cat", g) is None
    assert chat.msgs("c-amy", g).json()["items"][-1]["text"] == "다솜 님이 나갔어요"
    # 빠진 동안 메시지 → 다시 초대 = 같은 행 · 옛 메시지 보임 · 빠진 동안 메시지 안 읽음 0
    chat.tick()
    chat.send("c-amy", g, "빠진 동안")
    chat.tick()
    assert chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": [chat.id("c-cat")]},
                            headers=chat.h("c-amy")).status_code == 200
    with chat.c.repo.tx() as tx:
        rows = tx.con.execute("SELECT COUNT(*) FROM chat_member WHERE room_id = ? AND account_id = ?",
                              (g, chat.id("c-cat"))).fetchone()[0]
    assert rows == 1
    assert chat.room("c-cat", g)["unread"] == 0
    assert "빠진 동안" in [m["text"] for m in chat.msgs("c-cat", g).json()["items"]]
    # 지금 멤버 20 넘음 = 409
    with chat.c.repo.tx() as tx:
        for i in range(16):
            aid = tx.put_account(f"c-y{i:02d}", T0, role="nurse", name=f"차{i:02d}", staff_id=None, active=True, card=False)
            tx.update_account(aid, T0, password_hash="test-only")
        extra = [a.id for a in tx.accounts() if a.login_id.startswith("c-y")]
    r = chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": extra}, headers=chat.h("c-amy"))
    assert (r.status_code, code(r)) == (409, "chat_room_full")  # 5 + 16 = 21
    assert chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": extra[:15]},
                            headers=chat.h("c-amy")).json()["memberCount"] == 20
    # 이미 멤버 = chat_person_invalid
    r = chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": [chat.id("c-ben")]}, headers=chat.h("c-amy"))
    assert code(r) == "chat_person_invalid"
    # 마지막 사람까지 나가도 방 행 남음
    small = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    for login in ("c-amy", "c-ben", "c-cat"):
        assert chat.client.post(f"/api/chat/rooms/{small}/leave", headers=chat.h(login)).status_code == 200
    with chat.c.repo.tx() as tx:
        assert tx.chat_room(small) is not None


def test_chat_new_member_unread_zero(chat):
    """코디 처분 W2-1(D-45) — 메시지 3개 있는 그룹에 새로 추가된 사람의 unread = 0."""
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    for t in ("하나", "둘", "셋"):
        chat.send("c-ben", g, t)
    assert chat.room("c-amy", g)["unread"] == 3
    chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": [chat.id("c-fay")]}, headers=chat.h("c-amy"))
    assert chat.room("c-fay", g)["unread"] == 0
    assert chat.rooms("c-fay")["unreadRooms"] == 0
    chat.send("c-ben", g, "넷")
    assert chat.room("c-fay", g)["unread"] == 1


# ------------------------------------------------------------------ 중복 방지
def test_chat_client_id_dedupe(chat):
    room = chat.direct("c-amy", "c-ben").json()["id"]
    a = chat.send("c-amy", room, "한 번만", client_id="dup-00000001")
    b = chat.send("c-amy", room, "한 번만", client_id="dup-00000001")
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert len(chat.msgs("c-amy", room).json()["items"]) == 1
    c = chat.send("c-ben", room, "다른 계정", client_id="dup-00000001")  # 다른 계정 같은 clientId = 각각 1
    assert c.status_code == 200 and c.json()["id"] != a.json()["id"]
    assert len(chat.msgs("c-amy", room).json()["items"]) == 2
    for cid in ("x" * 7, "x" * 65):
        r = chat.send("c-amy", room, "길이", client_id=cid)
        assert (r.status_code, code(r)) == (400, "invalid_request")
    r = chat.client.post(f"/api/chat/rooms/{room}/messages", json={"text": "없음"}, headers=chat.h("c-amy"))
    assert code(r) == "invalid_request"


# ------------------------------------------------------------------ 메시지
def test_chat_message_rules(chat):
    room = chat.direct("c-amy", "c-ben").json()["id"]
    ok = chat.send("c-amy", room, "😀" * 2000)  # 2000 코드 포인트(이모지)
    assert ok.status_code == 200 and ok.json()["text"] == "😀" * 2000
    assert chat.send("c-amy", room, "가" * 2000).status_code == 200
    r = chat.send("c-amy", room, "가" * 2001)
    assert (r.status_code, code(r)) == (400, "chat_message_too_long")
    r = chat.send("c-amy", room, "😀" * 2001)
    assert code(r) == "chat_message_too_long"
    assert code(chat.send("c-amy", room, None)) == "chat_message_empty"
    assert code(chat.send("c-amy", room, "  \n ")) == "chat_message_empty"
    # 텍스트 + 사진 = invalid_request
    assert code(chat.send("c-amy", room, "글", photoId=1)) == "invalid_request"
    # 남이 올린 · 다른 방 · 이미 붙은 사진 = chat_photo_invalid (사진 행은 픽스처로)
    other = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    with chat.c.repo.tx() as tx:
        def photo(owner, rid, msg=None):
            return tx.add_chat_photo(room_id=rid, account_id=chat.id(owner), message_id=msg, file_name="x.jpg", bytes=3,
                                     sha256="0", width=10, height=10, created_at="2026-10-21T02:00:00.000+00:00")
        theirs, elsewhere, attached, mine = photo("c-ben", room), photo("c-amy", other), photo("c-amy", room, 1), \
            photo("c-amy", room)
    for pid in (theirs, elsewhere, attached, 9999):
        r = chat.send("c-amy", room, None, photoId=pid)
        assert (r.status_code, code(r)) == (400, "chat_photo_invalid"), pid
    m = chat.send("c-amy", room, None, photoId=mine).json()
    assert m["kind"] == "photo" and m["text"] is None and m["photo"] == {"id": mine, "width": 10, "height": 10}
    # 비활성 상대 1:1 = 409 chat_peer_inactive
    d = chat.direct("c-amy", "c-fay").json()["id"]
    with chat.c.repo.tx() as tx:
        tx.update_account(chat.id("c-fay"), T0, active=False)
    r = chat.send("c-amy", d, "받을 사람 없음")
    assert (r.status_code, code(r)) == (409, "chat_peer_inactive")
    assert chat.room("c-amy", d)["name"] == "바다 (비활성)"
    # 혼자 남은 그룹 = 됨
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    for login in ("c-ben", "c-cat"):
        chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h(login))
    assert chat.send("c-amy", g, "혼자").status_code == 200


# ------------------------------------------------------------------ 삭제
def test_chat_delete(chat):
    room = chat.direct("c-amy", "c-ben").json()["id"]
    mine = chat.send("c-amy", room, "지울 것").json()
    theirs = chat.send("c-ben", room, "남의 것").json()
    since = mine["updatedAt"]
    chat.tick(5)
    r = chat.client.delete(f"/api/chat/messages/{mine['id']}", headers=chat.h("c-amy"))
    assert r.json() == {"ok": True}
    got = {m["id"]: m for m in chat.msgs("c-ben", room).json()["items"]}[mine["id"]]
    assert got["deletedAt"] and got["text"] is None and got["updatedAt"] > since
    assert chat.client.delete(f"/api/chat/messages/{mine['id']}", headers=chat.h("c-amy")).status_code == 200  # 두 번
    r = chat.client.delete(f"/api/chat/messages/{theirs['id']}", headers=chat.h("c-amy"))
    assert (r.status_code, code(r)) == (403, "chat_not_yours")
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-cat"))
    system = chat.msgs("c-amy", g).json()["items"][-1]
    with chat.c.repo.tx() as tx:  # 시스템 줄의 account_id = 그 일을 한 계정(나간 다솜) — 다솜은 이제 멤버 아님
        assert tx.chat_message(system["id"])["account_id"] == chat.id("c-cat")
    chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": [chat.id("c-dan")]}, headers=chat.h("c-amy"))
    add = chat.msgs("c-amy", g).json()["items"][-1]
    assert code(chat.client.delete(f"/api/chat/messages/{add['id']}", headers=chat.h("c-amy"))) == "chat_not_yours"
    assert code(chat.client.delete("/api/chat/messages/9999", headers=chat.h("c-amy"))) == "chat_message_not_found"
    # since 로 지운 것이 나옴
    items = chat.msgs("c-ben", room, since=since).json()["items"]
    assert [m["id"] for m in items if m["deletedAt"]] == [mine["id"]]


# ------------------------------------------------------------------ 안 읽음
def test_chat_unread(chat):
    room = chat.direct("c-amy", "c-ben").json()["id"]
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    chat.send("c-amy", room, "내 것")
    chat.tick()
    a = chat.send("c-ben", room, "남의 것 1").json()
    chat.tick()
    b = chat.send("c-ben", room, "남의 것 2").json()
    chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": [chat.id("c-dan")]}, headers=chat.h("c-ben"))
    assert chat.room("c-amy", room)["unread"] == 2  # 남이 보낸 것만
    assert chat.room("c-amy", g)["unread"] == 0  # 시스템 줄 안 셈
    chat.client.delete(f"/api/chat/messages/{b['id']}", headers=chat.h("c-ben"))
    assert chat.room("c-amy", room)["unread"] == 1  # 지운 것 안 셈
    # 읽음 뒤 0 · 방 마지막 id 보다 큰 messageId = 마지막 id 로 · 더 작은 값으로 다시 와도 줄지 않음
    r = chat.read("c-amy", room, 99999)
    assert r.status_code == 200 and r.json()["lastReadMessageId"] == b["id"]
    assert MS_KST.match(r.json()["lastViewedAt"])
    assert chat.room("c-amy", room)["unread"] == 0
    assert chat.read("c-amy", room, a["id"]).json()["lastReadMessageId"] == b["id"]
    # unreadRooms — 알림 끈 방도 셈
    chat.send("c-ben", g, "그룹 새 글")
    chat.client.put(f"/api/chat/rooms/{g}/mute", json={"muted": True}, headers=chat.h("c-amy"))
    listing = chat.rooms("c-amy")
    assert {x["id"]: x["muted"] for x in listing["items"]}[g] is True and listing["unreadRooms"] == 1
    assert chat.read("c-amy", g, 0).json()["unreadRooms"] == 1  # messageId 0 = 안 바뀜
    # unreadRooms = items 방만 — 숨긴 1:1 안 셈 → 새 메시지로 다시 보이면 셈(숨기기 전 안 읽음 + 새 것)
    chat.tick()
    chat.send("c-ben", room, "숨기기 전")
    chat.tick()
    chat.client.post(f"/api/chat/rooms/{room}/hide", headers=chat.h("c-amy"))
    listing = chat.rooms("c-amy")
    assert room not in [x["id"] for x in listing["items"]] and listing["unreadRooms"] == 1
    chat.tick()
    chat.send("c-ben", room, "다시 보임")
    listing = chat.rooms("c-amy")
    assert {x["id"]: x["unread"] for x in listing["items"]}[room] == 2 and listing["unreadRooms"] == 2


# ------------------------------------------------------------------ 시각 경계(r2 · F-2)
def test_chat_time_boundary(chat):
    room = chat.direct("c-amy", "c-ben").json()["id"]
    same = T0 + timedelta(milliseconds=215)
    chat.c.clock.set(same)  # 같은 밀리초에 고정
    first = chat.send("c-ben", room, "첫째").json()
    assert chat.read("c-amy", room, first["id"]).status_code == 200  # 같은 밀리초에 읽음(messageId = 첫 것)
    second = chat.send("c-ben", room, "둘째").json()
    assert first["updatedAt"] == second["updatedAt"] == "2026-10-21T11:00:00.215+09:00"
    assert MS_KST.match(first["createdAt"])
    assert chat.room("c-amy", room)["unread"] == 1  # 시각이 같아도 잃지 않음
    # since = 첫 것의 updatedAt → 둘 다(>=) · KST(%2B 인코딩) · Z · 밀리초 없음 꼴도 같은 결과
    kst = first["updatedAt"]
    for since in (kst, "2026-10-21T02:00:00.215Z", "2026-10-21T02:00:00.215+00:00"):
        assert [m["id"] for m in chat.msgs("c-amy", room, since=since).json()["items"]] == [first["id"], second["id"]]
    raw = chat.client.get(f"/api/chat/rooms/{room}/messages?since=2026-10-21T11%3A00%3A00.215%2B09%3A00",
                          headers=chat.h("c-amy"))
    assert [m["id"] for m in raw.json()["items"]] == [first["id"], second["id"]]
    assert len(chat.msgs("c-amy", room, since="2026-10-21T11:00:00+09:00").json()["items"]) == 2  # 밀리초 없음
    assert chat.msgs("c-amy", room, since="2026-10-21T11:00:00.216+09:00").json()["items"] == []
    # 「+」 가 공백으로 읽힌 꼴 · 아무 글자 = 400
    for bad in ("2026-10-21T11:00:00.215 09:00", "어제"):
        r = chat.msgs("c-amy", room, since=bad)
        assert (r.status_code, code(r)) == (400, "invalid_request"), bad
    # 같은 초 · 다른 밀리초 = createdAt 다르고 차례 = id 차례
    chat.c.clock.set(same + timedelta(milliseconds=1))
    third = chat.send("c-amy", room, "셋째").json()
    assert third["createdAt"] != second["createdAt"] and third["id"] > second["id"]
    assert [m["id"] for m in chat.msgs("c-amy", room).json()["items"]] == [first["id"], second["id"], third["id"]]
    # 채팅 시각 열 = .mmm+00:00 · 기존 표 = 초 꼴 그대로(회귀)
    with chat.c.repo.tx() as tx:
        cols = []
        for table, names in (("chat_room", ("created_at", "last_message_at")),
                             ("chat_member", ("joined_at", "last_viewed_at")),
                             ("chat_message", ("created_at", "updated_at"))):
            for r in tx.con.execute(f"SELECT {', '.join(names)} FROM {table}"):
                cols += [x for x in r if x is not None]
        tx.add_notification(account_id=chat.id("c-amy"), kind="doctor_call", title="t", body="b", created_at=T0)
        note = tx.con.execute("SELECT created_at FROM notification").fetchone()[0]
    assert cols and all(MS_UTC.match(x) for x in cols), cols
    assert note == "2026-10-21T02:00:00+00:00"
    listing = chat.room("c-amy", room)
    assert MS_KST.match(listing["createdAt"]) and MS_KST.match(listing["lastMessageAt"])
    assert MS_KST.match(listing["lastMessage"]["createdAt"])


# ------------------------------------------------------------------ 페이지
def test_chat_paging(chat):
    room = chat.direct("c-amy", "c-ben").json()["id"]
    ids = []
    for i in range(120):
        chat.tick()
        ids.append(chat.send("c-amy" if i % 2 else "c-ben", room, f"글 {i}").json()["id"])
    first = chat.msgs("c-amy", room).json()
    assert [m["id"] for m in first["items"]] == ids[-50:] and first["hasMore"] is True
    older = chat.msgs("c-amy", room, before=ids[-50]).json()
    assert [m["id"] for m in older["items"]] == ids[20:70] and older["hasMore"] is True
    last = chat.msgs("c-amy", room, before=ids[20]).json()
    assert [m["id"] for m in last["items"]] == ids[:20] and last["hasMore"] is False
    # since = 새 것 + 지운 것
    mark = first["items"][-1]["updatedAt"]
    chat.tick()
    new = chat.send("c-ben", room, "새 것").json()
    chat.client.delete(f"/api/chat/messages/{ids[1]}", headers=chat.h("c-amy"))
    got = chat.msgs("c-amy", room, since=mark).json()
    assert [m["id"] for m in got["items"]] == [ids[1], ids[-1], new["id"]] and got["hasMore"] is False
    # 50 넘으면 최근 50 + hasMore
    big = chat.msgs("c-amy", room, since=chat.msgs("c-amy", room, before=ids[0] + 1).json()["items"][0]["updatedAt"])
    assert len(big.json()["items"]) == 50 and big.json()["hasMore"] is True
    r = chat.msgs("c-amy", room, before=ids[5], since=mark)
    assert (r.status_code, code(r)) == (400, "invalid_request")
    assert code(chat.msgs("c-amy", room, limit=51)) == "invalid_request"
    assert len(chat.msgs("c-amy", room, limit=3).json()["items"]) == 3


def test_chat_empty_room(chat):
    """코디 처분 W2-2 — 메시지 0개 방: since 없이 = 빈 목록 · read {messageId: 0} = 200 · 아무것도 안 바꿈."""
    room = chat.direct("c-amy", "c-ben").json()["id"]
    assert chat.msgs("c-amy", room).json() == {"items": [], "hasMore": False}
    with chat.c.repo.tx() as tx:
        before = tx.chat_member(room, chat.id("c-amy"))
    r = chat.read("c-amy", room, 0)
    assert r.status_code == 200 and r.json()["lastReadMessageId"] == 0 and r.json()["unreadRooms"] == 0
    with chat.c.repo.tx() as tx:
        assert tx.chat_member(room, chat.id("c-amy")) == before
    assert code(chat.client.post(f"/api/chat/rooms/{room}/read", json={"messageId": -1}, headers=chat.h("c-amy"))) == \
        "invalid_request"


# ------------------------------------------------------------------ 방 목록 · 미리보기 · 알림 끄기
def test_chat_room_list(chat):
    d = chat.direct("c-amy", "c-ben").json()["id"]
    chat.tick()
    g = chat.group("c-amy", ["c-ben", "c-cat"], title="수요일 회의").json()["id"]
    assert [x["id"] for x in chat.rooms("c-amy")["items"]] == [g, d]  # 메시지 없으면 created_at
    chat.tick()
    chat.send("c-ben", d, "가" * 150)
    listing = chat.rooms("c-amy")["items"]
    assert [x["id"] for x in listing] == [d, g]
    p = listing[0]["lastMessage"]
    assert p["text"] == "가" * 100 and p["senderName"] == "나래" and not p["mine"] and not p["deleted"]
    assert listing[1]["name"] == "수요일 회의" and listing[1]["title"] == "수요일 회의"
    r = chat.client.put(f"/api/chat/rooms/{g}/mute", json={"muted": True}, headers=chat.h("c-amy"))
    assert r.json() == {"ok": True, "muted": True}
    assert chat.room("c-amy", g)["muted"] is True and chat.room("c-ben", g)["muted"] is False
    assert code(chat.client.put(f"/api/chat/rooms/{g}/mute", json={"muted": "yes"}, headers=chat.h("c-amy"))) == \
        "invalid_request"


# ------------------------------------------------------------------ 마이그레이션
def test_chat_migration(tmp_path):
    """옛 push_log(chat_message_id 없음) DB 에서 시작 → 열 생김 · 옛 행 그대로 · 두 번 열어도 그대로 · 채팅 표 4개."""
    from app.repository.db import Database

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE push_log (id INTEGER PRIMARY KEY, call_id INTEGER, visit_id INTEGER, account_id INTEGER, role TEXT,
            device_id INTEGER, token_tail TEXT, category TEXT, status TEXT NOT NULL, apns_status INTEGER, apns_reason TEXT,
            apns_id TEXT, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, sent_at TEXT,
            kind TEXT NOT NULL DEFAULT 'doctor_call', reservation_id INTEGER, display_request_id INTEGER,
            notification_id INTEGER);
        INSERT INTO push_log (call_id, status, created_at, kind) VALUES (7, 'sent', '2026-10-01T00:00:00+00:00', 'doctor_call');
    """)
    con.commit()
    con.close()
    for _ in range(2):
        Database(path)
    con = sqlite3.connect(path)
    cols = [r[1] for r in con.execute("PRAGMA table_info(push_log)")]
    rows = con.execute("SELECT call_id, status, kind, chat_message_id FROM push_log").fetchall()
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    con.close()
    assert cols.count("chat_message_id") == 1
    assert rows == [(7, "sent", "doctor_call", None)]
    assert {"chat_room", "chat_member", "chat_message", "chat_photo"} <= tables


# ------------------------------------------------------------------ 로그(보내기)
def test_chat_log_ids_only(chat, caplog):
    g = chat.group("c-amy", ["c-ben", "c-cat"], title="비밀 방 이름").json()["id"]
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        m = chat.send("c-amy", g, "로그에 남으면 안 되는 본문").json()
        chat.client.delete(f"/api/chat/messages/{m['id']}", headers=chat.h("c-amy"))
        chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-cat"))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert f"message={m['id']}" in text and f"room={g}" in text
    for secret in ("로그에 남으면 안 되는 본문", "비밀 방 이름", "가람", "나래", "다솜"):
        assert secret not in text
