"""WORK-011 WP-BE3 — 직원 채팅 r3: 수정 · 동영상 · Range · 썸네일(SPEC-007 0.3.0 §13.1 r3 줄 · 코디 처분 r3).

모두 실 router(TestClient · async def)로 부르고 받는 쪽(가짜 APNs · 허브 연결 큐 · 디스크)에서 단언한다 — 리뷰 r3
「조용히 통과하는 자리」(videoId 만 보내기 · 사진 갈래 kind 검사 · Content-Length 로 먼저 거르기 · 수정 = 푸시 0)는
서비스를 직접 불러 대신하지 않는다. 동영상 · 썸네일 바이트는 모양만 맞춘 가짜(단색 · 고객 영상 아님).
"""

import logging
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.formparsers import MultiPartParser

from app.main import create_app
from app.service.chat import VIDEO_MAX_BYTES
from app.service.id_photo import MAX_BYTES
from tests import test_chat_push as cp
from tests.chat_env import Chat, seed_people
from tests.conftest import make_settings
from tests.helpers import T0
from tests.test_push import tok

env = cp.env  # 가짜 APNs · 기기 · PROC_PHOTO_DIR 이 있는 실 앱(test_chat_push 와 같은 바탕)
settle, listen, chat_frames, upload, JPEG = cp.settle, cp.listen, cp.chat_frames, cp.upload, cp.JPEG

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00\x00\x00\x00mp42isom" + bytes(range(256)) * 8  # 모양만 MP4(ftyp 상자)
THUMB = b"\xff\xd8\xff\xe0" + b"\x11" * 500  # 모양만 JPEG


def code(r) -> str:
    return r.json()["error"]["code"]


def up_video(chat, login, room, video=MP4, thumb=THUMB, *, headers=None, **fields):
    data = {"roomId": str(room), "width": "1280", "height": "720", "durationMs": "170000", **fields}
    data = {k: v for k, v in data.items() if v is not None}
    files = {"video": ("v.mp4", video, "video/mp4"), "thumb": ("t.jpg", thumb, "image/jpeg")}
    files = {k: v for k, v in files.items() if v[1] is not None}
    return chat.client.post("/api/chat/videos", data=data, files=files, headers={**chat.h(login), **(headers or {})})


def patch(chat, login, mid, body):
    return chat.client.patch(f"/api/chat/messages/{mid}", json=body, headers=chat.h(login))


def chat_files(folder: Path) -> list[str]:
    d = folder / "chat"
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


# ------------------------------------------------------------------ 수정
def test_chat_edit(env, caplog):
    chat, apns, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat", "c-dan"]).json()["id"]
    m = chat.send("c-amy", g, "처음 글").json()
    chat.read("c-ben", g, m["id"])
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-dan"))  # 나간 사람 = SSE 0
    other = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]  # 방 순서 확인용(이 방이 위)
    settle(chat.c)
    apns.requests.clear()
    before = {x: chat.room(x, g) for x in ("c-amy", "c-ben", "c-cat")}
    unread_rooms = {x: chat.rooms(x)["unreadRooms"] for x in ("c-amy", "c-ben", "c-cat")}
    order = [r["id"] for r in chat.rooms("c-amy")["items"]]
    conns = {x: listen(chat.c, chat.id(x)) for x in ("c-amy", "c-ben", "c-cat", "c-dan", "c-fay")}
    chat.tick(5)
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        r = patch(chat, "c-amy", m["id"], {"text": "고친 글"})
        settle(chat.c)
    assert r.status_code == 200
    e = r.json()
    assert e["text"] == "고친 글" and e["id"] == m["id"] and e["createdAt"] == m["createdAt"]
    assert e["editedAt"] == e["updatedAt"] == "2026-10-21T11:00:00.005+09:00" and e["updatedAt"] > m["updatedAt"]
    assert m["editedAt"] is None
    # since 로 고친 것이 나옴(앱은 응답 Message 의 서버 updatedAt 을 써도 된다 · 코디 처분 W-6)
    latest = chat.msgs("c-ben", g).json()["items"][-1]["updatedAt"]  # 고치기 전 받은 것 중 가장 늦은 서버 값
    assert latest < e["updatedAt"]
    got = chat.msgs("c-ben", g, since=latest).json()["items"]
    edited = next(x for x in got if x["id"] == m["id"])
    assert edited == e and edited["text"] == "고친 글" and edited["editedAt"] == e["editedAt"]
    # SSE chat_message_edited = 지금 멤버 연결만(나간 사람 · 다른 계정 0) · id: 줄 없음
    for x in ("c-amy", "c-ben", "c-cat"):
        fs = chat_frames(conns[x])
        assert [(f[0], f[1]) for f in fs] == [("chat_message_edited", {"roomId": g, "message": e})]
        assert "\nid:" not in fs[0][2] and not fs[0][2].startswith("id:")
    assert chat_frames(conns["c-dan"]) == [] and chat_frames(conns["c-fay"]) == []
    # 푸시 0(HTTP 경로 → 가짜 APNs 요청 0) · 안 읽음 · unreadRooms · 방 lastMessageAt · 순서 그대로 · 미리보기 = 고친 글
    assert apns.requests == [] and "이벤트 루프 없음" not in caplog.text
    for x in ("c-amy", "c-ben", "c-cat"):
        now = chat.room(x, g)
        assert (now["unread"], now["lastMessageAt"]) == (before[x]["unread"], before[x]["lastMessageAt"])
        assert chat.rooms(x)["unreadRooms"] == unread_rooms[x]
    assert before["c-cat"]["unread"] == 1 and before["c-ben"]["unread"] == 0
    assert [r["id"] for r in chat.rooms("c-amy")["items"]] == order and order[0] == other
    # 로그 = id 만(본문 없음)
    text = "\n".join(x.getMessage() for x in caplog.records)
    assert f"message={m['id']}" in text and "고친 글" not in text and "처음 글" not in text
    # 같은 글 = 200 · 아무것도 안 바꿈 · SSE 0
    chat.tick(5)
    same = patch(chat, "c-amy", m["id"], {"text": "고친 글"})
    assert same.status_code == 200 and same.json() == e
    assert all(chat_frames(c) == [] for c in conns.values())
    # 2000 코드 포인트(이모지) = 됨 · 2001 = chat_message_too_long · 공백만 = chat_message_empty
    assert patch(chat, "c-amy", m["id"], {"text": "😀" * 2000}).status_code == 200
    r = patch(chat, "c-amy", m["id"], {"text": "가" * 2001})
    assert (r.status_code, code(r)) == (400, "chat_message_too_long")
    r = patch(chat, "c-amy", m["id"], {"text": " \n "})
    assert (r.status_code, code(r)) == (400, "chat_message_empty")
    # text 없음 · 모르는 키 = invalid_request
    assert code(patch(chat, "c-amy", m["id"], {})) == "invalid_request"
    assert code(patch(chat, "c-amy", m["id"], {"text": "x", "photoId": 1})) == "invalid_request"
    # 멤버 아님 · 나간 사람 · 없음 = 404
    for login, mid in (("c-fay", m["id"]), ("c-dan", m["id"]), ("c-amy", 9999)):
        r = patch(chat, login, mid, {"text": "x"})
        assert (r.status_code, code(r)) == (404, "chat_message_not_found")
    chat.c.hub._conns.clear()


def test_chat_edit_not_yours_not_editable(env):
    """코디 처분 W-5 — 남의 글 · 사진 · 동영상 · 지운 것 = 403 chat_not_yours 먼저 ·
    내 사진 · 동영상 · 지운 것 · 시스템 줄 = 400 chat_not_editable."""
    chat, _, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": [chat.id("c-dan")]}, headers=chat.h("c-amy"))
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-cat"))
    sys_mine, sys_other = [x["id"] for x in chat.msgs("c-amy", g).json()["items"] if x["kind"] == "system"]

    def msg(login, kind):
        if kind == "text":
            return chat.send(login, g, "글").json()["id"]
        if kind == "photo":
            return chat.send(login, g, None, photoId=upload(chat, login, g).json()["photoId"]).json()["id"]
        return chat.send(login, g, None, videoId=up_video(chat, login, g).json()["videoId"]).json()["id"]

    def deleted(login):
        mid = msg(login, "text")
        chat.client.delete(f"/api/chat/messages/{mid}", headers=chat.h(login))
        return mid

    theirs = [msg("c-ben", "text"), msg("c-ben", "photo"), msg("c-ben", "video"), deleted("c-ben")]
    mine = [msg("c-amy", "photo"), msg("c-amy", "video"), deleted("c-amy"), sys_mine, sys_other]
    for mid in theirs:
        r = patch(chat, "c-amy", mid, {"text": "고침"})
        assert (r.status_code, code(r)) == (403, "chat_not_yours"), mid
    for mid in mine:
        r = patch(chat, "c-amy", mid, {"text": "고침"})
        assert (r.status_code, code(r)) == (400, "chat_not_editable"), mid
        assert r.json()["error"]["message"] == "글만 고칠 수 있어요"
    # 삭제는 1판 그대로(시스템 줄 = 403)
    assert code(chat.client.delete(f"/api/chat/messages/{sys_mine}", headers=chat.h("c-amy"))) == "chat_not_yours"


def test_chat_edit_inactive_peer(env):
    """비활성 상대 1:1 — 보내기는 409 지만 고치기는 된다(새 글이 아니다 · OQ-947)."""
    chat, _, _ = env
    d = chat.direct("c-amy", "c-fay").json()["id"]
    m = chat.send("c-amy", d, "전").json()
    with chat.c.repo.tx() as tx:
        tx.update_account(chat.id("c-fay"), T0, active=False)
    assert code(chat.send("c-amy", d, "새 글")) == "chat_peer_inactive"
    r = patch(chat, "c-amy", m["id"], {"text": "후"})
    assert r.status_code == 200 and r.json()["text"] == "후"


# ------------------------------------------------------------------ 동영상 올리기
def test_chat_video_upload(env, caplog):
    chat, _, folder = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        r = up_video(chat, "c-amy", g)
    assert r.status_code == 200 and set(r.json()) == {"videoId"}
    vid = r.json()["videoId"]
    with chat.c.repo.tx() as tx:
        row = tx.chat_photo(vid)
    assert row["kind"] == "video" and row["duration_ms"] == 170000 and (row["width"], row["height"]) == (1280, 720)
    assert row["message_id"] is None and row["bytes"] == len(MP4)
    assert re.fullmatch(r"[0-9a-f]{32}\.mp4", row["file_name"]) and re.fullmatch(r"[0-9a-f]{32}\.jpg", row["thumb_file_name"])
    assert (folder / "chat" / row["file_name"]).read_bytes() == MP4
    assert (folder / "chat" / row["thumb_file_name"]).read_bytes() == THUMB
    assert chat_files(folder) == sorted([row["file_name"], row["thumb_file_name"]])  # 파일 2개 · 신분증 자리와 안 섞임
    assert not list(folder.glob("*.mp4")) and not list(folder.glob("*.jpg"))
    assert row["file_name"] not in caplog.text and "가람" not in caplog.text
    # 경계 — 3분 = 됨 · 180001 = chat_video_too_long · 0 · 정수 아님 · 칸 없음 = invalid_request
    assert up_video(chat, "c-amy", g, durationMs="180000").status_code == 200
    r = up_video(chat, "c-amy", g, durationMs="180001")
    assert (r.status_code, code(r)) == (400, "chat_video_too_long")
    assert r.json()["error"]["message"] == "3분 이하 동영상만 보낼 수 있어요"
    kept = chat_files(folder)
    bad = [up_video(chat, "c-amy", g, durationMs="0"), up_video(chat, "c-amy", g, durationMs="1.5"),
           up_video(chat, "c-amy", g, width="x")]
    bad += [up_video(chat, "c-amy", g, **{k: None}) for k in ("roomId", "width", "height", "durationMs")]
    bad += [up_video(chat, "c-amy", g, video=None), up_video(chat, "c-amy", g, thumb=None)]
    assert [(x.status_code, code(x)) for x in bad] == [(400, "invalid_request")] * len(bad)
    # 머리 — MP4 아님 = chat_video_type · 썸네일 JPEG 아님 = chat_photo_type
    r = up_video(chat, "c-amy", g, video=b"\x1aE\xdf\xa3" + b"\x00" * 100)  # webm 머리
    assert (r.status_code, code(r)) == (400, "chat_video_type")
    r = up_video(chat, "c-amy", g, thumb=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
    assert (r.status_code, code(r)) == (400, "chat_photo_type")
    # 썸네일 5MB = 됨 · 넘음 = 413 photo_too_large
    assert up_video(chat, "c-amy", g, thumb=b"\xff\xd8\xff" + b"\x00" * (MAX_BYTES - 3)).status_code == 200
    kept = chat_files(folder)
    r = up_video(chat, "c-amy", g, thumb=b"\xff\xd8\xff" + b"\x00" * (MAX_BYTES - 2))
    assert (r.status_code, code(r)) == (413, "photo_too_large")
    # 멤버 아님 = 404
    r = up_video(chat, "c-dan", g)
    assert (r.status_code, code(r)) == (404, "chat_room_not_found")
    assert chat_files(folder) == kept  # 실패한 올리기는 파일을 남기지 않는다
    # 전역 spool 한도 그대로(신분증 · 채팅 사진과 같은 값)
    assert MultiPartParser.spool_max_size == MAX_BYTES + 64 * 1024


def test_chat_video_too_large(env):
    """90MB(코디 처분 D-58) — 정확히 90MB = 됨 · 넘음 = 413 chat_video_too_large
    (실제 바이트 · Content-Length 먼저) · 쓰던 파일 지움."""
    chat, _, folder = env
    d = chat.direct("c-amy", "c-ben").json()["id"]
    big = MP4 + b"\x00" * (VIDEO_MAX_BYTES - len(MP4))
    assert len(big) == 90 * 1024 * 1024
    assert up_video(chat, "c-amy", d, video=big).status_code == 200
    kept = chat_files(folder)
    r = up_video(chat, "c-amy", d, video=big + b"\x00")  # Content-Length 는 문턱 아래 → 받은 뒤 조각 복사에서 멈춤
    assert (r.status_code, code(r)) == (413, "chat_video_too_large")
    assert r.json()["error"]["message"] == "동영상이 90MB 를 넘어요"
    assert chat_files(folder) == kept  # 반쯤 쓴 .mp4 없음
    # Content-Length 로 먼저 — 본문을 읽기 전에 413(작은 본문 + 큰 머리)
    limit = VIDEO_MAX_BYTES + MAX_BYTES + 64 * 1024
    for n, want in ((limit + 1, 413), (limit, 400)):
        r = chat.client.post("/api/chat/videos", content=b"x", headers={**chat.h("c-amy"), "Content-Length": str(n),
                             "Content-Type": "multipart/form-data; boundary=zz"})
        assert r.status_code == want, (n, r.text)
    assert code(r) != "chat_video_too_large"  # 문턱 = 그 값까지는 읽어 본다(모양이 틀려 400)


def test_chat_video_spools_to_disk(env, monkeypatch):
    """5MB + 64KB 넘는 video 칸은 Starlette 임시 파일로 흐르고(메모리에 다 안 올림) 요청 뒤 닫힌다(임시 파일 남지 않음)."""
    chat, _, _ = env
    d = chat.direct("c-amy", "c-ben").json()["id"]
    seen = []
    real = chat.c.chat.upload_video

    def spy(actor, room_id, video, *a):
        seen.append((video, video._rolled))  # _rolled = 디스크로 넘어감(SpooledTemporaryFile)
        return real(actor, room_id, video, *a)

    monkeypatch.setattr(chat.c.chat, "upload_video", spy)
    assert up_video(chat, "c-amy", d, video=MP4 + b"\x00" * (6 * 1024 * 1024)).status_code == 200
    assert up_video(chat, "c-amy", d, video=b"nope" * 4).status_code == 400  # 실패해도 닫음
    assert [rolled for _, rolled in seen] == [True, False] and all(f.closed for f, _ in seen)


def test_chat_video_disabled(tmp_path):
    """PROC_PHOTO_DIR 빔 = 동영상 올리기 · 열기 · 썸네일 모두 409 photo_disabled."""
    with TestClient(create_app(make_settings(tmp_path))) as client:
        c = client.app.state.container
        c.clock.set(T0)
        chat = Chat(client, c, seed_people(c))
        d = chat.direct("c-amy", "c-ben").json()["id"]
        r = up_video(chat, "c-amy", d)
        assert (r.status_code, code(r)) == (409, "photo_disabled")
        with c.repo.tx() as tx:
            vid = tx.add_chat_photo(room_id=d, account_id=chat.id("c-amy"), kind="video", file_name="x.mp4",
                                    thumb_file_name="x.jpg", bytes=3, sha256="0", width=1, height=1, duration_ms=1,
                                    created_at="2026-10-21T02:00:00.000+00:00")
        for path in (f"/api/chat/videos/{vid}", f"/api/chat/videos/{vid}/thumbnail"):
            r = client.get(path, headers=chat.h("c-amy"))
            assert (r.status_code, code(r)) == (409, "photo_disabled")


# ------------------------------------------------------------------ 동영상 보내기 · 열기
def test_chat_video_send_open(env):
    chat, _, folder = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    other = chat.direct("c-amy", "c-dan").json()["id"]
    vid = up_video(chat, "c-amy", g).json()["videoId"]
    pid = upload(chat, "c-amy", g).json()["photoId"]
    # 붙기 전 = 올린 사람만(본 파일 · 썸네일)
    assert chat.client.get(f"/api/chat/videos/{vid}", headers=chat.h("c-amy")).status_code == 200
    for path in (f"/api/chat/videos/{vid}", f"/api/chat/videos/{vid}/thumbnail"):
        r = chat.client.get(path, headers=chat.h("c-ben"))
        assert (r.status_code, code(r)) == (404, "chat_video_not_found")
    # 잘못 붙이기 — 사진 id 를 videoId 로 · 동영상 id 를 photoId 로 · 둘 다 · 글 + 동영상 · 남이 올림 · 다른 방
    assert code(chat.send("c-amy", g, None, videoId=pid)) == "chat_video_invalid"
    assert code(chat.send("c-amy", g, None, photoId=vid)) == "chat_photo_invalid"
    assert code(chat.send("c-amy", g, None, photoId=pid, videoId=vid)) == "invalid_request"
    assert code(chat.send("c-amy", g, "글", videoId=vid)) == "invalid_request"
    assert code(chat.send("c-ben", g, None, videoId=vid)) == "chat_video_invalid"
    assert code(chat.send("c-amy", other, None, videoId=vid)) == "chat_video_invalid"
    assert code(chat.send("c-amy", g, None, videoId=9999)) == "chat_video_invalid"
    # {clientId, videoId} 만 = 200(코디 처분 W-4 — 빈 검사에 videoId · HTTP 경로)
    r = chat.client.post(f"/api/chat/rooms/{g}/messages", json={"clientId": "video-000001", "videoId": vid},
                         headers=chat.h("c-amy"))
    assert r.status_code == 200, r.json()
    m = r.json()
    assert m["kind"] == "video" and m["text"] is None and m["photo"] is None and m["editedAt"] is None
    assert m["video"] == {"id": vid, "width": 1280, "height": 720, "durationMs": 170000}
    assert chat.msgs("c-ben", g).json()["items"][-1] == m
    assert code(chat.send("c-amy", g, None, videoId=vid)) == "chat_video_invalid"  # 이미 붙음
    # 붙은 뒤 = 멤버 · Range 끊어 받기(FileResponse)
    h = chat.h("c-ben")
    r = chat.client.get(f"/api/chat/videos/{vid}", headers={**h, "Range": "bytes=0-1"})
    assert r.status_code == 206 and r.content == MP4[:2] and r.headers["content-range"] == f"bytes 0-1/{len(MP4)}"
    assert r.headers["content-type"] == "video/mp4" and r.headers["accept-ranges"] == "bytes"
    assert r.headers["cache-control"] == "no-store" and r.headers["content-disposition"] == "inline"
    r = chat.client.get(f"/api/chat/videos/{vid}", headers={**h, "Range": "bytes=100-"})
    assert r.status_code == 206 and r.content == MP4[100:]
    r = chat.client.get(f"/api/chat/videos/{vid}", headers=h)
    assert r.status_code == 200 and r.content == MP4 and r.headers["accept-ranges"] == "bytes"
    assert r.headers["cache-control"] == "no-store" and r.headers["content-disposition"] == "inline"
    r = chat.client.get(f"/api/chat/videos/{vid}", headers={**h, "Range": f"bytes={len(MP4)}-{len(MP4) + 10}"})
    assert r.status_code == 416
    r = chat.client.get(f"/api/chat/videos/{vid}/thumbnail", headers=h)
    assert r.status_code == 200 and r.content == THUMB and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "no-store" and r.headers["content-disposition"] == "inline"
    # 멤버 아님 · 나간 사람 = 404
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-cat"))
    for login in ("c-dan", "c-cat"):
        for path in (f"/api/chat/videos/{vid}", f"/api/chat/videos/{vid}/thumbnail"):
            assert code(chat.client.get(path, headers=chat.h(login))) == "chat_video_not_found"
    # 종류 다름 = 없는 것 — 사진 id 로 동영상 · 동영상 id 로 사진
    chat.send("c-amy", g, None, photoId=pid)
    for path in (f"/api/chat/videos/{pid}", f"/api/chat/videos/{pid}/thumbnail"):
        r = chat.client.get(path, headers=chat.h("c-amy"))
        assert (r.status_code, code(r)) == (404, "chat_video_not_found")
    r = chat.client.get(f"/api/chat/photos/{vid}", headers=chat.h("c-amy"))
    assert (r.status_code, code(r)) == (404, "chat_photo_not_found")
    assert chat.client.get(f"/api/chat/photos/{pid}", headers=chat.h("c-amy")).status_code == 200  # 사진은 그대로
    # Bearer 헤더만 — 헤더 없음 · ?token= = 401
    token = chat.h("c-amy")["Authorization"].removeprefix("Bearer ")
    for path in (f"/api/chat/videos/{vid}", f"/api/chat/videos/{vid}/thumbnail"):
        assert chat.client.get(path).status_code == 401
        assert chat.client.get(f"{path}?token={token}").status_code == 401
    # 열람 · 올리기 event_log 0
    with chat.c.repo.tx() as tx:
        assert tx.events() == []
        row = tx.chat_photo(vid)
    # 행 있고 파일 없음 = 404(썸네일 · 본 파일 따로)
    (folder / "chat" / row["thumb_file_name"]).unlink()
    assert code(chat.client.get(f"/api/chat/videos/{vid}/thumbnail", headers=h)) == "chat_video_not_found"
    assert chat.client.get(f"/api/chat/videos/{vid}", headers=h).status_code == 200
    (folder / "chat" / row["file_name"]).unlink()
    assert code(chat.client.get(f"/api/chat/videos/{vid}", headers=h)) == "chat_video_not_found"


# ------------------------------------------------------------------ 동영상 지우기 · 푸시 · 미리보기
def test_chat_video_delete_push_preview(env):
    chat, apns, folder = env
    d = chat.direct("c-amy", "c-ben").json()["id"]
    vid = up_video(chat, "c-amy", d).json()["videoId"]
    m = chat.send("c-amy", d, None, videoId=vid).json()
    settle(chat.c)
    assert [(r["token"], r["payload"]["aps"]["alert"]) for r in apns.requests] == [(tok("c-ben"), {"title": "가람",
                                                                                                   "body": "동영상"})]
    assert apns.requests[0]["payload"]["messageId"] == m["id"]
    room = chat.room("c-ben", d)
    assert room["unread"] == 1 and chat.rooms("c-ben")["unreadRooms"] == 1  # 안 읽음 셈 ○
    p = room["lastMessage"]
    assert (p["kind"], p["text"], p["mine"], p["deleted"]) == ("video", None, False, False)
    with chat.c.repo.tx() as tx:
        row = tx.chat_photo(vid)
    files = [folder / "chat" / row["file_name"], folder / "chat" / row["thumb_file_name"]]
    assert all(f.is_file() for f in files)
    chat.tick()
    assert chat.client.delete(f"/api/chat/messages/{m['id']}", headers=chat.h("c-amy")).status_code == 200
    assert not any(f.exists() for f in files)  # 본 파일 + 썸네일 둘 다
    with chat.c.repo.tx() as tx:
        assert tx.chat_photo(vid)["deleted_at"] == "2026-10-21T02:00:00.001+00:00"
    got = chat.msgs("c-ben", d).json()["items"][-1]
    assert got["video"] is None and got["photo"] is None and got["text"] is None and got["deletedAt"]
    for login in ("c-amy", "c-ben"):
        for path in (f"/api/chat/videos/{vid}", f"/api/chat/videos/{vid}/thumbnail"):
            assert chat.client.get(path, headers=chat.h(login)).status_code == 404
    assert chat.room("c-ben", d)["lastMessage"]["deleted"] is True
    assert code(chat.send("c-amy", d, None, videoId=vid)) == "chat_video_invalid"  # 지운 것은 다시 못 붙임


# ------------------------------------------------------------------ 들어올 때 읽음 · 빈 방 읽음 · 1판 값(r3 이 문서로 고정한 값)
def test_chat_join_read_r3(env):
    """D9-45 — 만든 사람 · 처음 추가 · 다시 초대 모두 unread 0(메시지 3개 있는 그룹)."""
    chat, _, _ = env
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    assert chat.room("c-amy", g)["unread"] == 0
    for t in ("하나", "둘", "셋"):
        chat.send("c-ben", g, t)
    chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": [chat.id("c-dan")]}, headers=chat.h("c-amy"))
    assert chat.room("c-dan", g)["unread"] == 0
    chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h("c-dan"))
    for t in ("넷", "다섯"):
        chat.send("c-ben", g, t)
    chat.client.post(f"/api/chat/rooms/{g}/members", json={"accountIds": [chat.id("c-dan")]}, headers=chat.h("c-cat"))
    assert chat.room("c-dan", g)["unread"] == 0 and chat.rooms("c-dan")["unreadRooms"] == 0


def test_chat_empty_room_read_r3(env):
    """W2-2 — 메시지 0 방: since 없이 = 빈 목록 · read {messageId: 0} = 200 · 값 그대로 · SSE chat_read 0."""
    chat, _, _ = env
    room = chat.direct("c-amy", "c-ben").json()["id"]
    conns = [listen(chat.c, chat.id("c-amy")), listen(chat.c, chat.id("c-amy"))]
    assert chat.msgs("c-amy", room).json() == {"items": [], "hasMore": False}
    with chat.c.repo.tx() as tx:
        before = tx.chat_member(room, chat.id("c-amy"))
    chat.tick(10)
    r = chat.read("c-amy", room, 0)
    assert r.status_code == 200 and r.json()["lastReadMessageId"] == 0
    with chat.c.repo.tx() as tx:
        assert tx.chat_member(room, chat.id("c-amy")) == before
    assert all(chat_frames(c) == [] for c in conns)
    chat.c.hub._conns.clear()


def test_chat_r1_values(env):
    """1판 코드 값(SPEC-007 0.3.0 이 문서로 고정) — 비활성 1:1 이름 · 혼자 남은 그룹 이름 ·
    숨긴 1:1 다시 열기 · 사진 width 필수."""
    chat, _, _ = env
    d = chat.direct("c-amy", "c-fay").json()["id"]
    with chat.c.repo.tx() as tx:
        tx.update_account(chat.id("c-fay"), T0, active=False)
    assert chat.room("c-amy", d)["name"] == "바다 (비활성)"
    g = chat.group("c-amy", ["c-ben", "c-cat"]).json()["id"]
    for x in ("c-ben", "c-cat"):
        chat.client.post(f"/api/chat/rooms/{g}/leave", headers=chat.h(x))
    assert chat.room("c-amy", g)["name"] == ""
    # 숨긴 1:1 다시 열기 = 내 hidden_at 만 지움 · chat_room 은 나에게만 · 읽음 그대로
    h = chat.direct("c-amy", "c-ben").json()["id"]
    m = chat.send("c-ben", h, "숨기기 전").json()
    for x in ("c-amy", "c-ben"):
        chat.client.post(f"/api/chat/rooms/{h}/hide", headers=chat.h(x))
    conns = {x: listen(chat.c, chat.id(x)) for x in ("c-amy", "c-ben")}
    assert chat.direct("c-amy", "c-ben").json()["unread"] == 1
    with chat.c.repo.tx() as tx:
        me, peer = tx.chat_member(h, chat.id("c-amy")), tx.chat_member(h, chat.id("c-ben"))
    assert me["hidden_at"] is None and peer["hidden_at"] is not None and me["last_read_message_id"] < m["id"]
    assert [f[0] for f in chat_frames(conns["c-amy"])] == ["chat_room"] and chat_frames(conns["c-ben"]) == []
    chat.c.hub._conns.clear()
    # 사진 width 없음 = 400 invalid_request
    r = chat.client.post("/api/chat/photos", data={"roomId": str(h), "height": "30"},
                         files={"photo": ("p.jpg", JPEG, "image/jpeg")}, headers=chat.h("c-amy"))
    assert (r.status_code, code(r)) == (400, "invalid_request")


# ------------------------------------------------------------------ 마이그레이션(1판 채팅 DB → r3 열)
def test_chat_migration_r3(tmp_path):
    """1판 모양 chat_message · chat_photo(r3 열 없음) DB 에서 시작 → 열 4개 생김 ·
    옛 행 그대로(kind = photo) · 두 번 열어도 그대로."""
    from app.repository.db import Database

    path = tmp_path / "r1.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE chat_message (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, account_id INTEGER NOT NULL,
            kind TEXT NOT NULL, body TEXT, photo_id INTEGER, client_id TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, deleted_at TEXT, UNIQUE (account_id, client_id));
        CREATE TABLE chat_photo (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, account_id INTEGER NOT NULL,
            message_id INTEGER, file_name TEXT NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, width INTEGER,
            height INTEGER, created_at TEXT NOT NULL, deleted_at TEXT);
        INSERT INTO chat_message (room_id, account_id, kind, photo_id, created_at, updated_at)
            VALUES (1, 1, 'photo', 1, '2026-10-21T02:00:00.000+00:00', '2026-10-21T02:00:00.000+00:00');
        INSERT INTO chat_photo (room_id, account_id, message_id, file_name, bytes, sha256, width, height, created_at)
            VALUES (1, 1, 1, 'a.jpg', 3, '0', 4, 3, '2026-10-21T02:00:00.000+00:00');
    """)
    con.commit()
    con.close()
    for _ in range(2):
        Database(path)
    con = sqlite3.connect(path)
    mcols = [r[1] for r in con.execute("PRAGMA table_info(chat_message)")]
    pcols = [r[1] for r in con.execute("PRAGMA table_info(chat_photo)")]
    m = con.execute("SELECT kind, edited_at FROM chat_message").fetchall()
    p = con.execute("SELECT kind, duration_ms, thumb_file_name, file_name FROM chat_photo").fetchall()
    con.close()
    assert mcols.count("edited_at") == 1
    assert [pcols.count(c) for c in ("kind", "duration_ms", "thumb_file_name")] == [1, 1, 1]
    assert m == [("photo", None)] and p == [("photo", None, None, "a.jpg")]


# ------------------------------------------------------------------ 법적 검토 주석(§14)
def test_chat_legal_comments():
    """§14 grep = 5(db · service · 사진 열기 · 푸시 본문 · 동영상 열기) — 이 시험 안에는 문구를 이어 붙여 셈에 안 들게."""
    back = Path(__file__).resolve().parents[1]
    phrase = "법적 검토 필요" + ": 직원 채팅"
    out = subprocess.run(["grep", "-rn", "--include=*.py", phrase, "app"], cwd=back,
                         capture_output=True, text=True).stdout.splitlines()
    assert len(out) == 5, out
    where = [line.split(":", 1)[0] for line in out]
    assert sorted(where) == ["app/api/chat.py", "app/api/chat.py", "app/repository/db.py", "app/service/chat.py",
                             "app/service/push.py"]


@pytest.mark.parametrize("path", ["app/api/chat.py"])
def test_chat_route_handlers_async(path):
    """라우트 핸들러 def = 0(W2-6 grep 과 같은 규칙 — @router. 바로 다음 줄)."""
    lines = (Path(__file__).resolve().parents[1] / path).read_text().splitlines()
    nxt = [lines[i + 1] for i, x in enumerate(lines) if x.startswith("@router.")]
    assert len(nxt) == 19 and all(x.startswith("async def ") for x in nxt)  # r4 전달 +1
