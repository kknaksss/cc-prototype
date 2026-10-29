"""WORK-011 WP-BE4 — 직원 채팅 r4: 앱 안 전달 API #19 · 파일 = 마지막 참조와 함께 지움(SPEC-007 0.4.0 §13.1 r4 줄 ·
DEC-009 D-62 ~ D-64 · D-66 · 코디 처분 r4 W-4).

모두 실 router(TestClient · async def)로 부르고 받는 쪽(가짜 APNs · 허브 연결 큐 · 디스크)에서 단언한다 — 리뷰 r4
「조용히 통과하는 자리」(#19 SSE · 푸시를 서비스 직접 부르기로 대신 · 썸네일만 남는 파일 셈)는 HTTP 경로 · 동영상 전달본으로 본다.
사진 · 동영상 바이트는 모양만 맞춘 가짜(고객 것 아님).
"""

import logging
import sqlite3
import threading

from fastapi.testclient import TestClient

from app.main import create_app
from app.repository.repo import Tx
from tests import test_chat_push as cp
from tests import test_chat_r3 as r3
from tests.chat_env import Chat, seed_people
from tests.conftest import make_settings
from tests.helpers import T0
from tests.test_push import tok

env = cp.env
settle, listen, chat_frames, upload, JPEG = cp.settle, cp.listen, cp.chat_frames, cp.upload, cp.JPEG
code, up_video, chat_files = r3.code, r3.up_video, r3.chat_files


def fwd(chat, login, mid, targets, headers=None):
    return chat.client.post(f"/api/chat/messages/{mid}/forward", json={"targets": targets},
                            headers=chat.h(login) if headers is None else headers)


def room_t(room: int, cid: str) -> dict:
    return {"roomId": room, "clientId": cid}


def person_t(chat, login: str, cid: str) -> dict:
    return {"accountId": chat.id(login), "clientId": cid}


def count_messages(chat) -> int:
    with chat.c.repo.tx() as tx:
        return tx.con.execute("SELECT COUNT(*) FROM chat_message").fetchone()[0]


def member(chat, room: int, login: str) -> dict:
    with chat.c.repo.tx() as tx:
        return tx.chat_member(room, chat.id(login))


# ------------------------------------------------------------------ 전달 — 권한 · 모양
def test_chat_forward_auth_shape(env):
    chat, _, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    d = chat.direct("c-amy", "c-dan").json()["id"]
    theirs = chat.send("c-ben", g, "나래 글").json()  # 남의 메시지도 된다
    r = fwd(chat, "c-amy", theirs["id"], [room_t(d, "fwd-ok-0001")])
    assert r.status_code == 200, r.json()
    res = r.json()["results"]
    assert len(res) == 1 and res[0]["ok"] is True and res[0]["roomId"] == d
    assert res[0]["message"]["sender"]["id"] == chat.id("c-amy") and res[0]["message"]["text"] == "나래 글"
    # 401 — 헤더 없음 · 모양이 틀려도 401 먼저(W-4)
    assert fwd(chat, "c-amy", theirs["id"], [room_t(d, "fwd-ok-0002")], headers={}).status_code == 401
    r = fwd(chat, "c-amy", theirs["id"], [], headers={})
    assert (r.status_code, code(r)) == (401, "unauthorized")
    # 400 invalid_request — 대상 0 · 11 · 같은 roomId · clientId · accountId 두 번 · 둘 다 · 둘 다 없음 · 모르는 키 · 길이
    bad = [[], [room_t(d, f"fwd-many-{i:03d}") for i in range(11)],
           [room_t(d, "fwd-dup-0001"), room_t(d, "fwd-dup-0002")],
           [room_t(d, "fwd-same-001"), room_t(g, "fwd-same-001")],
           [person_t(chat, "c-dan", "fwd-pdup-001"), person_t(chat, "c-dan", "fwd-pdup-002")],
           [{"roomId": d, "accountId": chat.id("c-dan"), "clientId": "fwd-both-001"}],
           [{"clientId": "fwd-none-001"}], [{**room_t(d, "fwd-key-0001"), "extra": 1}],
           [room_t(d, "short7c")], [room_t(d, "x" * 65)]]
    for targets in bad:
        r = fwd(chat, "c-amy", theirs["id"], targets)
        assert (r.status_code, code(r)) == (400, "invalid_request"), targets
    r = chat.client.post(f"/api/chat/messages/{theirs['id']}/forward", json={"targets": [room_t(d, "fwd-key-0002")],
                                                                              "more": 1}, headers=chat.h("c-amy"))
    assert (r.status_code, code(r)) == (400, "invalid_request")
    # 모양 400 이 404 보다 먼저(W-4)
    r = fwd(chat, "c-amy", 99999, [])
    assert (r.status_code, code(r)) == (400, "invalid_request")
    # 404 chat_message_not_found — 없는 id · 원본 방 멤버 아님 · 나간 사람
    for login, mid in (("c-amy", 99999), ("c-eve", theirs["id"])):
        r = fwd(chat, login, mid, [room_t(d, "fwd-404-0001")])
        assert (r.status_code, code(r)) == (404, "chat_message_not_found")
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-cat"))
    cat_d = chat.direct("c-cat", "c-dan").json()["id"]
    r = fwd(chat, "c-cat", theirs["id"], [room_t(cat_d, "fwd-404-0002")])
    assert (r.status_code, code(r)) == (404, "chat_message_not_found")
    # 400 chat_not_forwardable — 시스템 줄(다솜 나감) · 지운 메시지
    system = chat.msgs("c-amy", g).json()["items"][-1]
    assert system["kind"] == "system"
    mine = chat.send("c-amy", g, "지울 글").json()
    chat.client.delete(f"/api/chat/messages/{mine['id']}", headers=chat.h("c-amy"))
    for mid in (system["id"], mine["id"]):
        r = fwd(chat, "c-amy", mid, [room_t(d, "fwd-unfit-01")])
        assert (r.status_code, code(r)) == (400, "chat_not_forwardable")
        assert r.json()["error"]["message"] == "전달할 수 없는 메시지예요"
    assert count_messages(chat) == 5  # 만듦 줄(r5) · 나래 글 · 전달본 · 나감 줄 · 지운 글 — 실패들은 아무것도 만들지 않음


# ------------------------------------------------------------------ 전달 — 대상별
def test_chat_forward_targets(env):
    chat, _, _ = env
    src = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    orig = chat.send("c-amy", src, "처음 글").json()
    chat.tick()
    r3.patch(chat, "c-amy", orig["id"], {"text": "고친 글"})
    g2 = chat.group("c-amy", ["c-dan", "c-eve"]).json()["id"]
    not_mine = chat.direct("c-ben", "c-cat").json()["id"]
    with chat.c.repo.tx() as tx:  # 비활성 상대 1:1 — 활성일 때 만든 뒤 끔
        tx.update_account(chat.id("c-off"), T0, active=True)
    off_d = chat.direct("c-amy", "c-off").json()["id"]
    with chat.c.repo.tx() as tx:
        tx.update_account(chat.id("c-off"), T0, active=False)
    conns = {x: listen(chat.c, chat.id(x)) for x in ("c-amy", "c-fay", "c-ben")}
    before = count_messages(chat)
    chat.tick()
    targets = [room_t(g2, "fwd-t-00001"), person_t(chat, "c-fay", "fwd-t-00002"), room_t(not_mine, "fwd-t-00003"),
               room_t(off_d, "fwd-t-00004"), person_t(chat, "c-off", "fwd-t-00005"),
               person_t(chat, "c-amy", "fwd-t-00006"), person_t(chat, "c-nopw", "fwd-t-00007"),
               room_t(src, "fwd-t-00008")]
    r = fwd(chat, "c-amy", orig["id"], targets)
    assert r.status_code == 200, r.json()
    res = r.json()["results"]
    assert [x["ok"] for x in res] == [True, True, False, False, False, False, False, True]  # 요청 차례 그대로
    assert [x["error"]["code"] for x in res if not x["ok"]] == [
        "chat_room_not_found", "chat_peer_inactive", "chat_person_invalid", "chat_person_invalid", "chat_person_invalid"]
    assert [x["roomId"] for x in res[2:7]] == [not_mine, off_d, None, None, None]
    assert count_messages(chat) == before + 3
    for x, cid in zip((res[0], res[1], res[7]), ("fwd-t-00001", "fwd-t-00002", "fwd-t-00008"), strict=True):
        m = x["message"]
        assert m["roomId"] == x["roomId"] and m["clientId"] == cid and m["kind"] == "text"
        assert m["text"] == "고친 글" and m["editedAt"] is None and m["sender"]["id"] == chat.id("c-amy")
        assert m["id"] != orig["id"]
    assert res[0]["roomId"] == g2 and res[7]["roomId"] == src  # 원본 방 자신도 됨
    # 사람 대상(1:1 없음) = 1:1 만들어 거기로 · chat_room 두 사람
    fay_d = res[1]["roomId"]
    assert chat.room("c-fay", fay_d)["kind"] == "direct"
    for login in ("c-amy", "c-fay"):
        rooms = [f[1]["room"] for f in chat_frames(conns[login]) if f[0] == "chat_room"]
        assert [x["id"] for x in rooms] == [fay_d]
    assert [f for f in chat_frames(conns["c-ben"]) if f[0] == "chat_room"] == []
    # 사람 대상(1:1 있고 내가 숨김) = 그 방 · 내 숨김 풂 · 그 1:1 방 + 그 사람 = 메시지 1 · 두 결과 같은 message.id
    chat.client.post(f"/api/chat/rooms/{fay_d}/hide", headers=chat.h("c-amy"))
    assert chat.room("c-amy", fay_d) is None
    chat.tick()
    before = count_messages(chat)
    r = fwd(chat, "c-amy", orig["id"], [person_t(chat, "c-fay", "fwd-h-00001"), room_t(fay_d, "fwd-h-00002")])
    res = r.json()["results"]
    assert r.status_code == 200 and [x["ok"] for x in res] == [True, True]
    assert res[0]["roomId"] == res[1]["roomId"] == fay_d and res[0]["message"]["id"] == res[1]["message"]["id"]
    assert count_messages(chat) == before + 1
    assert member(chat, fay_d, "c-amy")["hidden_at"] is None and chat.room("c-amy", fay_d) is not None
    # 앞이 방 · 뒤가 사람이어도 하나
    r = fwd(chat, "c-amy", orig["id"], [room_t(fay_d, "fwd-h-00003"), person_t(chat, "c-fay", "fwd-h-00004")])
    res = r.json()["results"]
    assert res[0]["message"]["id"] == res[1]["message"]["id"] and count_messages(chat) == before + 2
    # 전부 실패도 200
    r = fwd(chat, "c-amy", orig["id"], [room_t(not_mine, "fwd-f-00001"), person_t(chat, "c-off", "fwd-f-00002")])
    assert r.status_code == 200 and [x["ok"] for x in r.json()["results"]] == [False, False]


# ------------------------------------------------------------------ 전달 — 다시 보내기 · SSE · 푸시 · 읽음(HTTP → 가짜 APNs)
def test_chat_forward_retry_sse_push_read(env, caplog):
    chat, apns, _ = env
    src = chat.direct("c-amy", "c-ben").json()["id"]
    orig = chat.send("c-ben", src, "전달할 글 원문").json()
    g = chat.group("c-amy", ["c-ben", "c-cat", "c-dan"], title="오후 회의").json()["id"]
    chat.client.put(f"/api/chat/rooms/{g}/mute", json={"muted": True}, headers=chat.h("c-cat"))  # 알림 끔
    d_eve = chat.direct("c-amy", "c-eve").json()["id"]
    later = chat.group("c-ben", ["c-cat", "c-dan"]).json()["id"]  # 처음엔 멤버 아님 → 그 대상만 실패
    settle(chat.c)
    apns.requests.clear()
    conns = {x: listen(chat.c, chat.id(x)) for x in ("c-amy", "c-ben", "c-cat", "c-dan", "c-eve", "c-fay")}
    unread_before = chat.room("c-dan", g)["unread"]
    targets = [room_t(g, "fwd-r-00001"), room_t(d_eve, "fwd-r-00002"), room_t(later, "fwd-r-00003")]
    chat.tick()
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        r = fwd(chat, "c-amy", orig["id"], targets)
        settle(chat.c)
    assert r.status_code == 200, r.json()
    res = r.json()["results"]
    assert [x["ok"] for x in res] == [True, True, False]
    ids = {res[0]["message"]["id"], res[1]["message"]["id"]}
    # SSE chat_message = 대상 방 지금 멤버 연결만(대상마다)
    got = {x: sorted(f[1]["message"]["id"] for f in chat_frames(c) if f[0] == "chat_message") for x, c in conns.items()}
    assert got == {"c-amy": sorted(ids), "c-ben": [res[0]["message"]["id"]], "c-cat": [res[0]["message"]["id"]],
                   "c-dan": [res[0]["message"]["id"]], "c-eve": [res[1]["message"]["id"]], "c-fay": []}
    # 가짜 APNs = 대상 방 받는 사람 합(보낸 나 · 알림 끈 사람 빼고) · 제목 · 본문 = 보내기와 같음(「전달」 글자 없음)
    assert sorted(apns.tokens()) == sorted([tok("c-ben"), tok("c-dan"), tok("c-eve")])
    alerts = {q["token"]: q["payload"]["aps"]["alert"] for q in apns.requests}
    assert alerts == {tok("c-ben"): {"title": "가람 · 오후 회의", "body": "전달할 글 원문"},
                      tok("c-dan"): {"title": "가람 · 오후 회의", "body": "전달할 글 원문"},
                      tok("c-eve"): {"title": "가람", "body": "전달할 글 원문"}}
    assert {q["payload"]["messageId"] for q in apns.requests} == ids
    assert "이벤트 루프 없음" not in caplog.text
    # 로그 = id 만
    assert "채팅 전달" in caplog.text
    for secret in ("전달할 글 원문", "가람", "나래", "오후 회의"):
        assert secret not in caplog.text
    # 내 읽음 = 그 메시지 · 대상 방 다른 멤버 안 읽음 +1
    assert member(chat, g, "c-amy")["last_read_message_id"] == res[0]["message"]["id"]
    assert member(chat, d_eve, "c-amy")["last_read_message_id"] == res[1]["message"]["id"]
    assert chat.room("c-dan", g)["unread"] == unread_before + 1 and chat.room("c-amy", g)["unread"] == 0
    # 같은 요청 두 번 = 메시지 수 그대로 · 결과 = 처음 것 · SSE · 푸시 다시 0
    n = count_messages(chat)
    apns.requests.clear()
    r2 = fwd(chat, "c-amy", orig["id"], targets)
    settle(chat.c)
    res2 = r2.json()["results"]
    assert [x["ok"] for x in res2] == [True, True, False]
    assert res2[0]["message"] == res[0]["message"] and res2[1]["message"] == res[1]["message"]
    assert count_messages(chat) == n and apns.requests == []
    assert all(chat_frames(c) == [] for c in conns.values())
    # 첫 요청에서 실패한 대상만 두 번째에 만들어짐
    chat.client.post(f"/api/chat/rooms/{later}/members", json={"accountIds": [chat.id("c-amy")]}, headers=chat.h("c-ben"))
    settle(chat.c)
    for c in conns.values():
        chat_frames(c)
    apns.requests.clear()
    r3_ = fwd(chat, "c-amy", orig["id"], targets)
    settle(chat.c)
    res3 = r3_.json()["results"]
    assert [x["ok"] for x in res3] == [True, True, True]
    assert res3[0]["message"]["id"] == res[0]["message"]["id"] and res3[2]["roomId"] == later
    assert count_messages(chat) == n + 2  # 초대 시스템 줄 1 + 새 전달본 1
    assert sorted(apns.tokens()) == sorted([tok("c-ben"), tok("c-cat"), tok("c-dan")])
    assert [f[1]["message"]["id"] for f in chat_frames(conns["c-cat"]) if f[0] == "chat_message"] == [
        res3[2]["message"]["id"]]


# ------------------------------------------------------------------ 전달 — 첨부 · 지우기(D-66)
def test_chat_forward_attachments_delete(env):
    chat, _, folder = env
    src = chat.direct("c-amy", "c-ben").json()["id"]
    g = chat.group("c-amy", ["c-cat", "c-dan"]).json()["id"]
    pid = upload(chat, "c-amy", src).json()["photoId"]
    pm = chat.send("c-amy", src, None, photoId=pid).json()
    vid = up_video(chat, "c-amy", src).json()["videoId"]
    vm = chat.send("c-amy", src, None, videoId=vid).json()
    files = chat_files(folder)
    assert len(files) == 3  # 사진 1 + 동영상 본 파일 + 썸네일
    # 사진 → 그룹 · 사람(1:1 새로) / 동영상 → 그룹 — 남의 첨부도 됨(나래가 가람 사진을 받아 전달하는 길은 아래)
    rp = fwd(chat, "c-amy", pm["id"], [room_t(g, "fwd-p-00001"), person_t(chat, "c-eve", "fwd-p-00002")]).json()["results"]
    rv = fwd(chat, "c-amy", vm["id"], [room_t(g, "fwd-v-00001")]).json()["results"]
    assert all(x["ok"] for x in [*rp, *rv])
    assert chat_files(folder) == files  # 파일 복사 0
    with chat.c.repo.tx() as tx:
        src_p, src_v = tx.chat_photo(pid), tx.chat_photo(vid)
        copies = {x["message"]["id"]: tx.chat_photo((x["message"]["photo"] or x["message"]["video"])["id"])
                  for x in [*rp, *rv]}
        idx = tx.con.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'chat_photo_file'").fetchall()
    assert len(idx) == 1
    for (mid, row), x in zip(copies.items(), [*rp, *rv], strict=True):
        s = src_v if row["kind"] == "video" else src_p
        assert row["id"] not in (pid, vid) and row["room_id"] == x["roomId"] and row["message_id"] == mid
        assert (row["file_name"], row["thumb_file_name"]) == (s["file_name"], s["thumb_file_name"])
        assert row["account_id"] == chat.id("c-amy") and row["sha256"] == s["sha256"]
    gp, ep, gv = rp[0]["message"]["photo"]["id"], rp[1]["message"]["photo"]["id"], rv[0]["message"]["video"]
    assert rv[0]["message"]["kind"] == "video" and rv[0]["message"]["text"] is None
    assert gv == {"id": gv["id"], "width": 1280, "height": 720, "durationMs": 170000}
    # 대상 방 멤버가 새 첨부 id 로 열림(사진 · 동영상 Range 206 · 썸네일) · 원본 방에만 있는 사람 = 404
    h_cat = chat.h("c-cat")
    assert chat.client.get(f"/api/chat/photos/{gp}", headers=h_cat).content == JPEG
    assert chat.client.get(f"/api/chat/photos/{ep}", headers=chat.h("c-eve")).status_code == 200
    r = chat.client.get(f"/api/chat/videos/{gv['id']}", headers={**h_cat, "Range": "bytes=0-1"})
    assert r.status_code == 206 and r.content == r3.MP4[:2]
    assert chat.client.get(f"/api/chat/videos/{gv['id']}/thumbnail", headers=h_cat).content == r3.THUMB
    for path in (f"/api/chat/photos/{gp}", f"/api/chat/videos/{gv['id']}", f"/api/chat/videos/{gv['id']}/thumbnail"):
        assert chat.client.get(path, headers=chat.h("c-ben")).status_code == 404
    assert chat.client.get(f"/api/chat/photos/{pid}", headers=h_cat).status_code == 404  # 원본 첨부는 원본 방 것
    # 남의 첨부 전달(나래 → 나래 · 라온 1:1) — 새 행의 올린 사람 = 전달한 나래
    rb = fwd(chat, "c-ben", pm["id"], [person_t(chat, "c-dan", "fwd-b-00001")]).json()["results"][0]
    with chat.c.repo.tx() as tx:
        assert tx.chat_photo(rb["message"]["photo"]["id"])["account_id"] == chat.id("c-ben")
    assert chat.client.get(f"/api/chat/photos/{rb['message']['photo']['id']}", headers=chat.h("c-dan")).status_code == 200

    def delete(login, mid):
        assert chat.client.delete(f"/api/chat/messages/{mid}", headers=chat.h(login)).status_code == 200

    # 동영상: 원본을 지움 → 원본 첨부 404 · 전달본 본 파일 · 썸네일 열림 · 파일 남음 → 전달본까지 지움 → 둘 다 없어짐
    vfiles = [folder / "chat" / src_v["file_name"], folder / "chat" / src_v["thumb_file_name"]]
    delete("c-amy", vm["id"])
    for path in (f"/api/chat/videos/{vid}", f"/api/chat/videos/{vid}/thumbnail"):
        assert chat.client.get(path, headers=chat.h("c-ben")).status_code == 404
    assert all(f.is_file() for f in vfiles)
    assert chat.client.get(f"/api/chat/videos/{gv['id']}", headers=h_cat).status_code == 200
    assert chat.client.get(f"/api/chat/videos/{gv['id']}/thumbnail", headers=h_cat).status_code == 200
    delete("c-amy", rv[0]["message"]["id"])
    assert not any(f.exists() for f in vfiles)  # 본 파일 + 썸네일 둘 다
    # 사진: 전달본을 먼저 지워도 원본 열림 · 마지막 참조(원본)를 지울 때 파일 없어짐
    pfile = folder / "chat" / src_p["file_name"]
    delete("c-amy", rp[0]["message"]["id"])
    delete("c-amy", rp[1]["message"]["id"])
    assert chat.client.get(f"/api/chat/photos/{pid}", headers=chat.h("c-ben")).status_code == 200 and pfile.is_file()
    assert chat.client.get(f"/api/chat/photos/{gp}", headers=h_cat).status_code == 404
    delete("c-amy", pm["id"])
    assert pfile.is_file()  # 나래의 전달본이 아직 가리킴
    assert chat.client.get(f"/api/chat/photos/{rb['message']['photo']['id']}", headers=chat.h("c-dan")).status_code == 200
    delete("c-ben", rb["message"]["id"])
    assert not pfile.exists() and chat_files(folder) == []
    # 원본 첨부 파일이 없음 = 400 chat_not_forwardable(동영상은 썸네일만 없어도)
    pid2 = upload(chat, "c-amy", src).json()["photoId"]
    pm2 = chat.send("c-amy", src, None, photoId=pid2).json()
    vid2 = up_video(chat, "c-amy", src).json()["videoId"]
    vm2 = chat.send("c-amy", src, None, videoId=vid2).json()
    with chat.c.repo.tx() as tx:
        (folder / "chat" / tx.chat_photo(pid2)["file_name"]).unlink()
        (folder / "chat" / tx.chat_photo(vid2)["thumb_file_name"]).unlink()
    for mid in (pm2["id"], vm2["id"]):
        r = fwd(chat, "c-amy", mid, [room_t(g, f"fwd-gone-{mid:03d}")])
        assert (r.status_code, code(r)) == (400, "chat_not_forwardable")


def test_chat_forward_vs_last_delete_race(env, monkeypatch):
    """W3-2 — 전달이 원본 첨부를 확인한 직후 작성자가 마지막 참조를 지우러 와도 파일 없는 전달본이 안 생긴다.

    전달이 원본 확인(첨부 행 · 파일)을 마친 뒤 · 새 첨부 행을 넣기 직전 자리에서 삭제를 다른 스레드(다른 연결)로
    띄우고 0.5초 기다린다 — 전달이 쓰기 잠금을 먼저 잡았으면 삭제는 전달 커밋까지 막히고(그 사이 끝나지 않음),
    끝난 뒤 남은 참조(전달본)를 세어 파일을 남긴다. 잠금이 없으면 삭제가 파일을 지운 뒤 전달본이 들어간다.
    """
    chat, _, folder = env
    src = chat.direct("c-amy", "c-ben").json()["id"]
    g = chat.group("c-ben", ["c-cat", "c-dan"]).json()["id"]
    pid = upload(chat, "c-amy", src).json()["photoId"]
    pm = chat.send("c-amy", src, None, photoId=pid).json()
    pfile = folder / "chat" / chat_files(folder)[0]
    svc, amy, ben = chat.c.chat, chat.p["c-amy"][0], chat.p["c-ben"][0]
    real, deleter, raced = Tx.add_chat_photo, None, []

    def add_chat_photo(self, **kw):
        nonlocal deleter
        if threading.current_thread() is threading.main_thread() and deleter is None:
            deleter = threading.Thread(target=svc.delete, args=(amy, pm["id"]))
            deleter.start()
            deleter.join(0.5)
            raced.append(deleter.is_alive())
        return real(self, **kw)

    monkeypatch.setattr(Tx, "add_chat_photo", add_chat_photo)
    res = svc.forward(ben, pm["id"], [room_t(g, "fwd-race-0001")])
    monkeypatch.setattr(Tx, "add_chat_photo", real)
    deleter.join(15)
    assert raced == [True]  # 전달 tx 가 잠금을 쥔 동안 삭제는 끝나지 못함(직렬화)
    assert res[0]["ok"] and not deleter.is_alive()
    assert chat.client.get(f"/api/chat/photos/{pid}", headers=chat.h("c-ben")).status_code == 404  # 원본은 지워짐
    assert pfile.is_file()  # 전달본이 아직 가리킴 → 파일 남음
    assert chat.client.get(f"/api/chat/photos/{res[0]['message']['photo']['id']}", headers=chat.h("c-cat")).content == JPEG


def test_chat_forward_photo_disabled(tmp_path):
    """PROC_PHOTO_DIR 빔 = 첨부 전달 409 photo_disabled · 텍스트 전달은 됨."""
    with TestClient(create_app(make_settings(tmp_path))) as client:
        c = client.app.state.container
        c.clock.set(T0)
        chat = Chat(client, c, seed_people(c))
        d = chat.direct("c-amy", "c-ben").json()["id"]
        g = chat.group("c-amy", ["c-cat", "c-dan"]).json()["id"]
        with c.repo.tx() as tx:
            at = "2026-10-21T02:00:00.000+00:00"
            pid = tx.add_chat_photo(room_id=d, account_id=chat.id("c-amy"), file_name="x.jpg", bytes=3, sha256="0",
                                    width=1, height=1, created_at=at)
            mid = tx.add_chat_message(room_id=d, account_id=chat.id("c-amy"), kind="photo", photo_id=pid,
                                      client_id="seed-photo-01", created_at=at, updated_at=at)
            tx.update_chat_photo(pid, message_id=mid)
        r = fwd(chat, "c-amy", mid, [room_t(g, "fwd-dis-0001")])
        assert (r.status_code, code(r)) == (409, "photo_disabled")
        text = chat.send("c-amy", d, "글은 됨").json()
        r = fwd(chat, "c-amy", text["id"], [room_t(g, "fwd-dis-0002")])
        assert r.status_code == 200 and r.json()["results"][0]["ok"] is True


def test_chat_forward_index_migration(tmp_path):
    """r3 모양 DB(인덱스 없음)에서 시작 → chat_photo_file 인덱스 생김 · 두 번 열어도 하나."""
    from app.repository.db import Database

    path = tmp_path / "r3.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE chat_photo (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, account_id INTEGER NOT NULL,
            message_id INTEGER, file_name TEXT NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, width INTEGER,
            height INTEGER, created_at TEXT NOT NULL, deleted_at TEXT, kind TEXT NOT NULL DEFAULT 'photo',
            duration_ms INTEGER, thumb_file_name TEXT);
    """)
    con.commit()
    con.close()
    for _ in range(2):
        Database(path)
    con = sqlite3.connect(path)
    idx = con.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'chat_photo_file'").fetchall()
    con.close()
    assert len(idx) == 1 and "file_name" in idx[0][0]
