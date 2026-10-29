"""직원 채팅(SPEC-007) — 1:1 · 그룹 · 텍스트 · 사진 · 동영상 · 글 수정(r3) · 전달(r4). 다섯 역할 같은 권한 · 가짜 판에서도 됨.

법적 검토 필요: 직원 채팅 — 고객 정보가 메시지 · 사진으로 오갈 수 있음(보존 기간 없음 · 열람 로그 없음 · 잠금 화면에 본문 앞부분)

- 권한: 그 방 지금 멤버(left_at null)만. 아니면 방 · 메시지 · 사진이 **없는 것처럼** 404(§2 · OQ-903).
- 시각: 채팅 표는 clock.to_db_ms(UTC · 밀리초) · API 는 clock.iso_ms(KST · 밀리초). 시각은 쓰는 트랜잭션 안에서 잡고
  커밋까지 await 가 없다(핸들러 async def · 이 서비스는 동기) → 시각 순서 = 커밋 순서 = id 순서(§3).
- 안 읽음 = id > last_read_message_id(시각이 아니라 id · §5). 방에 들어올 때(만들기 · 처음 추가 · 다시 초대) = 그 순간
  방의 마지막 메시지 id(D9-43 · D9-45).
- 들어온 뒤 대화만(r5 · D9-69 · §4.6): 멤버는 id > from_message_id(들어올 때 마지막 id) 인 메시지 · 첨부만 본다. 경계 안은
  없는 것처럼(목록에 없음 · 그 id 로 부르면 404). 읽기 길 V1 ~ V12 — 목록 · since · 미리보기 · 첨부 열기 · 전달 원본 ·
  모아보기 · 고치기 · 지우기 · SSE · 푸시 받는 사람(_seers). 안 읽음은 last_read ≥ from 이라 그대로.
- SSE · 푸시는 커밋 뒤(`send` · `push` 는 container 가 꽂는다 — 띄우기와 같은 꼴). 로그엔 id 만(본문 · 이름 없음 · §6.1).
"""

import hashlib
import logging
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO

from app.config import Settings
from app.domain.clock import Clock, iso_ms, parse, to_db_ms
from app.domain.errors import BadRequest, Conflict, DomainError, Forbidden, NotFound
from app.domain.models import Account
from app.repository.repo import Repository, Tx
from app.service.id_photo import MAX_BYTES
from app.service.passport_scan import PhotoTooLarge

log = logging.getLogger("procedure.chat")

MAX_TEXT = 2000  # 코드 포인트(len) — 스키마 max_length 를 쓰면 invalid_request 로 바뀐다(§5)
MAX_TITLE = 40
GROUP_MIN, GROUP_MAX = 2, 19  # 만들 때 고르는 다른 사람 수(나 포함 3 ~ 20)
ROOM_MAX = 20  # 지금 멤버 상한(추가 뒤)
PAGE = 50
GRID = 60  # 모아보기 한 쪽(r5 · §6.2 #20 · OQ-965 — 격자 3칸 × 20줄)
PREVIEW = 100  # 미리보기 · 푸시 본문 앞부분(OQ-915)
INACTIVE = " (비활성)"
JPEG = b"\xff\xd8\xff"
PHOTO_SUBDIR = "chat"  # PROC_PHOTO_DIR/chat/ — 신분증(바로 아래)과 섞지 않는다
# 동영상(r3 · §9.2) — 변환 뒤 본 파일 90MB(코디 처분 D-58: 운영 앞단 본문 한도 100MB 에 multipart 덧붙는 것까지) · 3분
VIDEO_MAX_BYTES = 90 * 1024 * 1024
VIDEO_MAX_MS = 180000
FORWARD_MAX = 10  # 전달 대상 한 번에(D9-63)
MP4_BOX = b"ftyp"  # MP4 머리 = 4 ~ 8 바이트
CHUNK = 1024 * 1024  # 임시 파일 → 저장 자리 조각 복사

Event = tuple[int, str, dict[str, Any]]  # (받는 계정 id, 이벤트 이름, 데이터)


def candidate(a: Account | None) -> bool:
    """상대 후보(§2) — active + 로그인 가능(비밀번호 있음)."""
    return a is not None and a.active and bool(a.password_hash)


def room_name(room: dict[str, Any], member_ids: list[int], accounts: dict[int, Account], viewer_id: int) -> str:
    """§4.5 — 1:1 = 상대 이름(+ 비활성) · 그룹 = 제목 · 이름 없는 그룹 = 보는 사람 뺀 지금 멤버 이름 가나다 순 「, 」."""
    others = [accounts[i] for i in member_ids if i != viewer_id and i in accounts]
    if room["kind"] == "direct":
        peer = others[0] if others else None
        return (peer.name + ("" if peer.active else INACTIVE)) if peer else ""
    if room["title"]:
        return room["title"]
    return ", ".join(sorted(a.name for a in others))


class ChatService:
    def __init__(self, repo: Repository, clock: Clock, settings: Settings):
        self.repo = repo
        self.clock = clock
        self.s = settings
        self.send: Callable[[int, str, dict[str, Any]], int] = lambda account_id, event, data: 0  # container → 허브
        self.push: Callable[[int], None] = lambda message_id: None  # container → PushService.schedule_chat

    # ------------------------------------------------------------------ 모양
    def _accounts(self, tx: Tx) -> dict[int, Account]:
        return {a.id: a for a in tx.accounts()}

    def _member(self, tx: Tx, room_id: int, actor: Account) -> dict[str, Any]:
        """지금 멤버면 방 행 — 아니면(없음 · 나감) 404."""
        room = tx.chat_room(room_id)
        me = tx.chat_member(room_id, actor.id) if room else None
        if room is None or me is None or me["left_at"] is not None:
            raise NotFound("대화방을 찾을 수 없어요", "chat_room_not_found")
        return room

    @staticmethod
    def _sees(me: dict[str, Any] | None, message_id: int) -> bool:
        """이 멤버 행이 그 메시지를 보나(r5 · §4.6) — 지금 멤버 + 경계 밖(id > from_message_id)."""
        return me is not None and me["left_at"] is None and message_id > me["from_message_id"]

    @staticmethod
    def _seers(members: list[dict[str, Any]], message_id: int) -> list[int]:
        """SSE · 푸시 받는 사람(r5 · §4.6 V9 · V10 · 처분 FAIL-1) — 지금 멤버 중 그 메시지를 볼 수 있는 사람."""
        return [m["account_id"] for m in members if m["from_message_id"] < message_id]

    @staticmethod
    def _sender(a: Account | None, account_id: int) -> dict[str, Any]:
        if a is None:
            return {"id": account_id, "name": "", "role": "admin", "active": False}
        return {"id": a.id, "name": a.name, "role": a.role, "active": a.active}

    def _message(self, m: dict[str, Any], accounts: dict[int, Account], photo: dict[str, Any] | None = None) -> dict[str, Any]:
        """Message(§6.1) — 첨부 행(photo)은 사진 · 동영상 같은 표. 지운 것 = text · photo · video null."""
        deleted = m["deleted_at"] is not None
        attached = not deleted and m["photo_id"] is not None
        width, height = (photo["width"], photo["height"]) if photo else (None, None)
        ref = video = None
        if m["kind"] == "photo" and attached:
            ref = {"id": m["photo_id"], "width": width, "height": height}
        if m["kind"] == "video" and attached:
            video = {"id": m["photo_id"], "width": width, "height": height,
                     "durationMs": photo["duration_ms"] if photo else None}
        return {"id": m["id"], "roomId": m["room_id"], "clientId": m["client_id"],
                "sender": self._sender(accounts.get(m["account_id"]), m["account_id"]), "kind": m["kind"],
                "text": None if deleted else m["body"], "photo": ref, "video": video,
                "createdAt": iso_ms(parse(m["created_at"])), "updatedAt": iso_ms(parse(m["updated_at"])),
                "editedAt": iso_ms(parse(m["edited_at"])), "deletedAt": iso_ms(parse(m["deleted_at"]))}

    def _messages(self, tx: Tx, rows: list[dict[str, Any]], accounts: dict[int, Account]) -> list[dict[str, Any]]:
        return [self._message(m, accounts, tx.chat_photo(m["photo_id"]) if m["photo_id"] else None) for m in rows]

    def _room(self, tx: Tx, room: dict[str, Any], viewer_id: int, accounts: dict[int, Account]) -> dict[str, Any]:
        """Room(§6.1) — 보는 계정 기준. members = 「나」 맨 위 · 나머지 이름 가나다 순(OQ-936)."""
        rows = tx.chat_members(room["id"])
        ids = [r["account_id"] for r in rows]
        me = tx.chat_member(room["id"], viewer_id)
        members = []
        for i in ids:
            a = accounts.get(i)
            if a is not None:
                members.append({"id": a.id, "name": a.name, "role": a.role, "active": a.active, "me": a.id == viewer_id})
        members.sort(key=lambda x: (not x["me"], x["name"]))
        last = tx.last_chat_message(room["id"])
        preview = None
        if last is not None and last["id"] > (me["from_message_id"] if me else 0):  # 경계 안 = null(r5 · §4.5)
            sender = accounts.get(last["account_id"])
            deleted = last["deleted_at"] is not None
            text = None if deleted or last["kind"] in ("photo", "video") or last["body"] is None else last["body"][:PREVIEW]
            preview = {"id": last["id"], "senderId": last["account_id"], "senderName": sender.name if sender else "",
                       "mine": last["account_id"] == viewer_id, "kind": last["kind"], "text": text, "deleted": deleted,
                       "createdAt": iso_ms(parse(last["created_at"]))}
        last_read = me["last_read_message_id"] if me else 0
        return {"id": room["id"], "kind": room["kind"], "title": room["title"],
                "name": room_name(room, ids, accounts, viewer_id), "members": members, "memberCount": len(members),
                "muted": bool(me["muted"]) if me else False, "unread": tx.chat_unread(room["id"], viewer_id, last_read),
                "lastMessage": preview, "lastMessageAt": iso_ms(parse(room["last_message_at"])),
                "createdAt": iso_ms(parse(room["created_at"]))}

    @staticmethod
    def _visible(row: dict[str, Any]) -> bool:
        """내 목록(§6.2 #2) — 숨기지 않았거나 숨긴 뒤 새 메시지(last_message_at > hidden_at)."""
        hidden = row["me_hidden_at"]
        return hidden is None or (row["last_message_at"] is not None and row["last_message_at"] > hidden)

    def _rooms(self, tx: Tx, account_id: int, accounts: dict[int, Account]) -> list[dict[str, Any]]:
        return [self._room(tx, r, account_id, accounts) for r in tx.chat_rooms_of(account_id) if self._visible(r)]

    def _unread_rooms(self, tx: Tx, account_id: int) -> int:
        """`unreadRooms` — 내 목록에 든 방 중 unread > 0(알림 끈 방도 셈 · 숨긴 1:1 은 목록에 없으므로 안 셈)."""
        return sum(1 for r in tx.chat_rooms_of(account_id)
                   if self._visible(r) and tx.chat_unread(r["id"], account_id, r["me_last_read"]) > 0)

    def _room_events(self, tx: Tx, room: dict[str, Any], to: list[int], accounts: dict[int, Account]) -> list[Event]:
        """`chat_room` — 받는 계정마다 그 계정 기준으로 만든 Room(§7)."""
        return [(i, "chat_room", {"room": self._room(tx, room, i, accounts)}) for i in to]

    def _emit(self, events: list[Event]) -> None:
        for account_id, event, data in events:
            self.send(account_id, event, data)

    def _join(self, tx: Tx, room_id: int, account_id: int, at: str) -> None:
        """방에 들어옴(만들기 · 처음 추가 · 다시 초대) — 읽은 데까지 = 보이는 경계 = 그 순간 방의 마지막 메시지(D9-43 · D9-45 ·
        D9-69). 다시 초대도 경계를 덮는다(옛 대화 안 보임)."""
        last = tx.last_chat_message(room_id)
        last_id = last["id"] if last else 0
        if tx.chat_member(room_id, account_id) is None:
            tx.add_chat_member(room_id=room_id, account_id=account_id, joined_at=at, last_viewed_at=at,
                               last_read_message_id=last_id, from_message_id=last_id)
        else:
            tx.update_chat_member(room_id, account_id, joined_at=at, left_at=None, hidden_at=None, last_viewed_at=at,
                                  last_read_message_id=last_id, from_message_id=last_id)

    @staticmethod
    def _invited(actor: Account, account_ids: list[int], accounts: dict[int, Account]) -> str:
        """초대 시스템 줄(r5 · §4.4 · D9-68) — 「A님이 B님, C님을 초대했습니다」(고른 차례 · 이름과 「님」 사이 빈칸 없음)."""
        names = ", ".join(f"{accounts[i].name}님" for i in account_ids)
        return f"{actor.name}님이 {names}을 초대했습니다"

    def _system(self, tx: Tx, room_id: int, actor: Account, body: str, at: str) -> int:
        """시스템 줄(§4.4) — 그때 이름으로 body 에 써 둔다 · 푸시 · 안 읽음 없음."""
        mid = tx.add_chat_message(room_id=room_id, account_id=actor.id, kind="system", body=body, created_at=at,
                                  updated_at=at)
        tx.update_chat_room(room_id, last_message_at=at)
        return mid

    # ------------------------------------------------------------------ #1 · #2
    def people(self, actor: Account) -> list[dict[str, Any]]:
        """§2 상대 후보 — active + 비밀번호 있음 · 나 빼고 · 이름 가나다 순 · {id, name, role} 만."""
        with self.repo.tx() as tx:
            accounts = tx.accounts()
        out = [a for a in accounts if a.id != actor.id and candidate(a)]
        return [{"id": a.id, "name": a.name, "role": a.role} for a in sorted(out, key=lambda a: (a.name, a.id))]

    def rooms(self, actor: Account) -> dict[str, Any]:
        with self.repo.tx() as tx:
            items = self._rooms(tx, actor.id, self._accounts(tx))
        return {"items": items, "unreadRooms": sum(1 for r in items if r["unread"] > 0)}

    # ------------------------------------------------------------------ #3 · #4 방 만들기
    def _open_direct(self, tx: Tx, actor: Account, account_id: int, at: str,
                     accounts: dict[int, Account]) -> tuple[int, bool, list[int]]:
        """1:1 열기 · 만들기 · 내 숨김 풂(같은 tx 안 — #3 · 전달 사람 대상 r4). (방 id, 새로 만들었나, chat_room 받을 사람)."""
        if account_id == actor.id or not candidate(accounts.get(account_id)):
            raise BadRequest("chat_person_invalid", "대화할 수 없는 직원이에요")
        lo, hi = sorted((actor.id, account_id))
        room_id, created = tx.add_direct_room(f"{lo}:{hi}", actor.id, at)
        to: list[int] = []
        if created:
            for i in (actor.id, account_id):
                self._join(tx, room_id, i, at)
            to = [actor.id, account_id]
        elif (tx.chat_member(room_id, actor.id) or {}).get("hidden_at") is not None:
            tx.update_chat_member(room_id, actor.id, hidden_at=None)
            to = [actor.id]
        if created:
            log.info("채팅 1:1 만듦 room=%d account=%d", room_id, actor.id)
        return room_id, created, to

    def open_direct(self, actor: Account, account_id: int) -> dict[str, Any]:
        """1:1 열기(§4.1) — 같은 두 사람 = 같은 방 · 내가 숨겼으면 다시 보임."""
        at = to_db_ms(self.clock.now())
        with self.repo.tx() as tx:
            accounts = self._accounts(tx)
            room_id, _, to = self._open_direct(tx, actor, account_id, at, accounts)
            room = tx.chat_room(room_id)
            assert room is not None
            out = self._room(tx, room, actor.id, accounts)
            events = self._room_events(tx, room, to, accounts)
        self._emit(events)
        return out

    def create_group(self, actor: Account, account_ids: list[int], title: str | None) -> dict[str, Any]:
        """그룹(§4.2) — 다른 사람 2 ~ 19 · 같은 사람들이어도 매번 새 방 · 이름 비면 null.

        만들면 초대 시스템 줄 한 줄(r5 · §4.4 · D9-68 · OQ-963 — [새 대화] · 1:1 [초대] 같은 길) · SSE chat_message 멤버 전원 ·
        푸시 없음(시스템 줄).
        """
        title = (title or "").strip() or None
        if title is not None and len(title) > MAX_TITLE:
            raise BadRequest("invalid_request", f"title: 그룹 이름은 {MAX_TITLE}자까지예요")
        if actor.id in account_ids or len(set(account_ids)) != len(account_ids):
            raise BadRequest("chat_person_invalid", "대화할 수 없는 직원이 있어요")
        if not GROUP_MIN <= len(account_ids) <= GROUP_MAX:
            raise BadRequest("chat_group_size", f"그룹은 나 포함 {GROUP_MIN + 1} ~ {GROUP_MAX + 1}명이에요")
        at = to_db_ms(self.clock.now())
        with self.repo.tx() as tx:
            accounts = self._accounts(tx)
            if not all(candidate(accounts.get(i)) for i in account_ids):
                raise BadRequest("chat_person_invalid", "대화할 수 없는 직원이 있어요")
            room_id = tx.add_chat_room(kind="group", title=title, created_by=actor.id, created_at=at)
            for i in (actor.id, *account_ids):
                self._join(tx, room_id, i, at)
            mid = self._system(tx, room_id, actor, self._invited(actor, account_ids, accounts), at)
            room = tx.chat_room(room_id)
            assert room is not None
            out = self._room(tx, room, actor.id, accounts)
            msg = self._message(tx.chat_message(mid) or {}, accounts)
            events = [*self._room_events(tx, room, [actor.id, *account_ids], accounts),
                      *((i, "chat_message", {"roomId": room_id, "message": msg})
                        for i in self._seers(tx.chat_members(room_id), mid))]
        log.info("채팅 그룹 만듦 room=%d account=%d members=%d", room_id, actor.id, len(account_ids) + 1)
        self._emit(events)
        return out

    # ------------------------------------------------------------------ #5 ~ #8 방 바꾸기
    def add_members(self, actor: Account, room_id: int, account_ids: list[int]) -> dict[str, Any]:
        """초대(= 참여자 추가 · §4.2 · §4.7) — 누구나 · 지금 멤버 아님 · 추가 뒤 ≤ 20 · 시스템 줄 한 줄 · 나간 사람 = 같은 행 다시
        (경계도 다시 — 들어온 뒤 대화만 · D9-69)."""
        now = self.clock.now()
        at = to_db_ms(now)
        with self.repo.tx() as tx:
            room = self._member(tx, room_id, actor)
            if room["kind"] != "group":
                raise BadRequest("chat_group_only", "1:1 에는 참여자를 더할 수 없어요")
            accounts = self._accounts(tx)
            current = [r["account_id"] for r in tx.chat_members(room_id)]
            if (len(set(account_ids)) != len(account_ids) or any(i in current for i in account_ids)
                    or not all(candidate(accounts.get(i)) for i in account_ids)):
                raise BadRequest("chat_person_invalid", "추가할 수 없는 직원이 있어요")
            if len(current) + len(account_ids) > ROOM_MAX:
                raise Conflict("chat_room_full", f"{ROOM_MAX}명까지 함께할 수 있어요")
            for i in account_ids:
                self._join(tx, room_id, i, at)
            mid = self._system(tx, room_id, actor, self._invited(actor, account_ids, accounts), at)
            room = tx.chat_room(room_id)
            assert room is not None
            members = [*current, *account_ids]
            out = self._room(tx, room, actor.id, accounts)
            msg = self._message(tx.chat_message(mid) or {}, accounts)
            events = [*self._room_events(tx, room, members, accounts),
                      *((i, "chat_message", {"roomId": room_id, "message": msg})
                        for i in self._seers(tx.chat_members(room_id), mid))]
        log.info("채팅 초대 room=%d account=%d added=%d", room_id, actor.id, len(account_ids))
        self._emit(events)
        return out

    def leave(self, actor: Account, room_id: int) -> None:
        """그룹 나가기(§4.2) — left_at · 시스템 줄 · 남은 사람이 0 이어도 방 행은 남음."""
        at = to_db_ms(self.clock.now())
        with self.repo.tx() as tx:
            room = self._member(tx, room_id, actor)
            if room["kind"] != "group":
                raise BadRequest("chat_group_only", "1:1 은 나갈 수 없어요 — 목록에서 숨겨 주세요")
            tx.update_chat_member(room_id, actor.id, left_at=at)
            mid = self._system(tx, room_id, actor, f"{actor.name} 님이 나갔어요", at)
            room = tx.chat_room(room_id)
            assert room is not None
            accounts = self._accounts(tx)
            members = tx.chat_members(room_id)
            rest = [r["account_id"] for r in members]
            msg = self._message(tx.chat_message(mid) or {}, accounts)
            events = [(actor.id, "chat_room_removed", {"roomId": room_id}),
                      *self._room_events(tx, room, rest, accounts),
                      *((i, "chat_message", {"roomId": room_id, "message": msg}) for i in self._seers(members, mid))]
        log.info("채팅 나감 room=%d account=%d", room_id, actor.id)
        self._emit(events)

    def hide(self, actor: Account, room_id: int) -> None:
        """1:1 목록에서 숨기기(§4.3) — 내 hidden_at 만 · 새 메시지가 오면 다시 보임 · 상대 쪽 그대로."""
        at = to_db_ms(self.clock.now())
        with self.repo.tx() as tx:
            room = self._member(tx, room_id, actor)
            if room["kind"] != "direct":
                raise BadRequest("chat_direct_only", "1:1 만 숨길 수 있어요 — 그룹은 나가기")
            tx.update_chat_member(room_id, actor.id, hidden_at=at)
        self._emit([(actor.id, "chat_room_removed", {"roomId": room_id})])

    def mute(self, actor: Account, room_id: int, muted: bool) -> bool:
        """방마다 내 알림 끄기(§4.3) — 끄면 그 방 푸시 · 앱 안 배너 없음. SSE chat_room = 나만."""
        with self.repo.tx() as tx:
            room = self._member(tx, room_id, actor)
            tx.update_chat_member(room_id, actor.id, muted=muted)
            events = self._room_events(tx, room, [actor.id], self._accounts(tx))
        self._emit(events)
        return muted

    # ------------------------------------------------------------------ #9 ~ #12 메시지
    def messages(self, actor: Account, room_id: int, before: int | None, since: str | None, limit: int) -> dict[str, Any]:
        """§5 페이지 — 처음 = 최근 limit · before = id < before · since = updated_at >= since(parse 뒤 UTC ms 로 비교).

        세 꼴 모두 내 경계 밖(id > from_message_id)만(r5 · §4.6 V1 · V2) — 경계에 닿으면 hasMore false.
        """
        if before is not None and since is not None:
            raise BadRequest("invalid_request", "before · since 는 하나만 보내요")
        since_db = None
        if since is not None:
            at = parse(since)
            if at is None:
                raise BadRequest("invalid_request", "since: 시각을 읽을 수 없어요")
            since_db = to_db_ms(at)
        with self.repo.tx() as tx:
            self._member(tx, room_id, actor)
            me = tx.chat_member(room_id, actor.id)
            assert me is not None
            rows, more = tx.chat_messages(room_id, after_id=me["from_message_id"], before=before, since=since_db,
                                          limit=limit)
            items = self._messages(tx, rows, self._accounts(tx))
        return {"items": items, "hasMore": more}

    def attachments(self, actor: Account, room_id: int, before: int | None, limit: int) -> dict[str, Any]:
        """모아보기(r5 · §6.2 #20 · D9-67) — 사진 · 동영상 메시지만 · 최근 것 위 · 내 경계 밖만 · Message 모양 그대로.

        지운 메시지 · 지운 첨부 빠짐 · 파일은 보지 않는다(열 때 #14 · #17 · #18 이 404). 열람 로그 없음.
        """
        with self.repo.tx() as tx:
            self._member(tx, room_id, actor)
            me = tx.chat_member(room_id, actor.id)
            assert me is not None
            rows, more = tx.chat_attachments(room_id, after_id=me["from_message_id"], before=before, limit=limit)
            items = self._messages(tx, rows, self._accounts(tx))
        return {"items": items, "hasMore": more}

    def _check_peer(self, tx: Tx, room: dict[str, Any], actor: Account, accounts: dict[int, Account]) -> None:
        """비활성 상대 1:1 = 새 메시지 없음(D9-42) — 보내기 · 전달 대상(r4)."""
        if room["kind"] == "direct":
            peer = next((accounts.get(m["account_id"]) for m in tx.chat_members(room["id"]) if m["account_id"] != actor.id),
                        None)
            if peer is None or not peer.active:
                raise Conflict("chat_peer_inactive", "비활성 계정이에요")

    def _insert(self, tx: Tx, room: dict[str, Any], actor: Account, accounts: dict[int, Account], *, kind: str,
                body: str | None, attach: int | None, client_id: str, at: str,
                also: list[int] | tuple[int, ...] = ()) -> tuple[int, dict[str, Any], list[Event]]:
        """새 메시지 한 줄(보내기 · 전달 r4 같이 씀) — 넣기 · 첨부 붙이기 · 방 last_message_at · 내 읽음 · 숨김 다시 보임.

        (메시지 id, Message, 커밋 뒤 낼 이벤트). also = chat_room 을 더 받을 사람(전달이 열거나 만든 1:1).
        """
        room_id = room["id"]
        members = tx.chat_members(room_id)
        mid = tx.add_chat_message(room_id=room_id, account_id=actor.id, kind=kind, body=body, photo_id=attach,
                                  client_id=client_id, created_at=at, updated_at=at)
        if attach is not None:
            tx.update_chat_photo(attach, message_id=mid)
        prev = room["last_message_at"]
        tx.update_chat_room(room_id, last_message_at=at)
        tx.update_chat_member(room_id, actor.id, last_viewed_at=at, last_read_message_id=mid)
        # 숨긴 1:1 이 이 메시지로 다시 보이는 사람(§4.3) — 그 사람에게 chat_room
        shown = [m["account_id"] for m in members
                 if m["hidden_at"] is not None and (prev is None or prev <= m["hidden_at"]) and at > m["hidden_at"]]
        to = [*also, *(i for i in shown if i not in also)]
        fresh = tx.chat_room(room_id)
        assert fresh is not None
        msg = self._messages(tx, [tx.chat_message(mid) or {}], accounts)[0]
        events = [*self._room_events(tx, fresh, to, accounts),
                  *((i, "chat_message", {"roomId": room_id, "message": msg}) for i in self._seers(members, mid))]
        return mid, msg, events

    def post(self, actor: Account, room_id: int, client_id: str, text: str | None, photo_id: int | None,
             video_id: int | None = None) -> dict[str, Any]:
        """보내기(§5) — 같은 계정 · 같은 clientId = 처음 것 그대로(SSE · 푸시 다시 안 함) · 커밋 뒤 SSE · 푸시.

        첨부 id 는 사진 · 동영상 같은 표(chat_photo) — 첨부 kind 가 메시지 kind 와 달라도 「보낼 수 없는」 것(§6.2 #10).
        """
        if sum(x is not None for x in (text, photo_id, video_id)) > 1:
            raise BadRequest("invalid_request", "text · photoId · videoId 는 하나만 보내요")
        attach = photo_id if photo_id is not None else video_id
        kind = "photo" if photo_id is not None else "video" if video_id is not None else "text"
        if attach is None and (text is None or not text.strip()):
            raise BadRequest("chat_message_empty", "보낼 내용이 없어요")
        if text is not None and len(text) > MAX_TEXT:
            raise BadRequest("chat_message_too_long", f"메시지는 {MAX_TEXT}자까지예요")
        now = self.clock.now()
        at = to_db_ms(now)
        with self.repo.tx() as tx:
            room = self._member(tx, room_id, actor)
            accounts = self._accounts(tx)
            old = tx.chat_message_by_client(actor.id, client_id)
            if old is not None:  # 다시 보내기(D9-16) — 새로 만들지 않는다
                return self._messages(tx, [old], accounts)[0]
            if attach is not None:
                p = tx.chat_photo(attach)
                if (p is None or p["kind"] != kind or p["account_id"] != actor.id or p["room_id"] != room_id
                        or p["message_id"] is not None or p["deleted_at"] is not None):
                    if kind == "video":
                        raise BadRequest("chat_video_invalid", "보낼 수 없는 동영상이에요")
                    raise BadRequest("chat_photo_invalid", "보낼 수 없는 사진이에요")
            self._check_peer(tx, room, actor, accounts)
            mid, msg, events = self._insert(tx, room, actor, accounts, kind=kind,
                                            body=None if attach is not None else text, attach=attach,
                                            client_id=client_id, at=at)
        log.info("채팅 보냄 room=%d message=%d account=%d", room_id, mid, actor.id)
        self._emit(events)
        self.push(mid)
        return msg

    def forward(self, actor: Account, message_id: int, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """전달(r4 · §5 · D9-62 ~ D9-64) — 고른 곳(1 ~ 10)마다 같은 내용의 새 메시지(보낸 사람 = 나 · 「전달됨」 없음).

        오류 차례(코디 처분 W-4): 모양 · 개수 · 중복 400 → 원본 없음 · 원본 방 지금 멤버 아님 404 → 시스템 줄 · 지운 것 ·
        첨부 행 지움 · 파일 없음 400 chat_not_forwardable(폴더 빔 = 409 photo_disabled). 대상별 실패는 결과에만(200).
        대상마다 clientId(D9-16) — 다시 보내면 만든 대상은 처음 것(SSE · 푸시 다시 없음). 같은 방이 두 번 되면 앞 대상 하나.
        첨부 = 대상마다 새 chat_photo 행 · 같은 파일(복사 0 · D9-64). 한 tx(첫머리에 쓰기 잠금 · W3-2) · 커밋 뒤 만든
        메시지마다 SSE · 푸시.
        """
        if not 1 <= len(targets) <= FORWARD_MAX:
            raise BadRequest("invalid_request", f"targets: 1 ~ {FORWARD_MAX}곳이에요")
        for key in ("roomId", "accountId", "clientId"):
            vals = [t[key] for t in targets if t.get(key) is not None]
            if len(set(vals)) != len(vals):
                raise BadRequest("invalid_request", f"targets: 같은 {key} 가 두 번 있어요")
        at = to_db_ms(self.clock.now())
        made: list[int] = []
        events: list[Event] = []
        with self.repo.tx() as tx:
            # 원본(첨부 행 · 파일) 확인을 쓰기 잠금 안에서 — delete 가 잠금(UPDATE) 뒤 남은 참조를 세는 것과 같은 순서라
            # 「확인 → 남이 마지막 참조 지움 · unlink → 같은 file_name 새 행」(파일 없는 전달본)이 안 생긴다(W3-2)
            tx.lock_write()
            m = tx.chat_message(message_id)
            me = tx.chat_member(m["room_id"], actor.id) if m else None
            if m is None or not self._sees(me, m["id"]):  # 멤버 아님 · 나감 · 내 경계 안(r5 · OQ-969) = 없는 것
                raise NotFound("메시지를 찾을 수 없어요", "chat_message_not_found")
            unfit = BadRequest("chat_not_forwardable", "전달할 수 없는 메시지예요")
            if m["kind"] == "system" or m["deleted_at"] is not None:
                raise unfit
            src = None
            if m["kind"] in ("photo", "video"):
                src = tx.chat_photo(m["photo_id"]) if m["photo_id"] else None
                if src is None or src["deleted_at"] is not None:
                    raise unfit
                folder = self._folder()
                if folder is None:
                    raise Conflict("photo_disabled", "사진 저장이 꺼져 있어요")
                if not all((folder / n).is_file() for n in (src["file_name"], src["thumb_file_name"]) if n):
                    raise unfit
            accounts = self._accounts(tx)
            done: dict[int, dict[str, Any]] = {}  # 방 id → 이 요청에서 이미 낸 성공 결과
            results: list[dict[str, Any]] = []
            for t in targets:
                room_id = t.get("roomId")
                try:
                    also: list[int] = []
                    if room_id is None:
                        aid = t["accountId"]
                        if aid == actor.id or not candidate(accounts.get(aid)):
                            raise BadRequest("chat_person_invalid", "대화할 수 없는 직원이에요")
                        lo, hi = sorted((actor.id, aid))
                        existing = tx.chat_room_by_key(f"{lo}:{hi}")
                        if existing is not None and existing["id"] in done:
                            results.append(done[existing["id"]])
                            continue
                        room_id, _, also = self._open_direct(tx, actor, aid, at, accounts)
                    elif room_id in done:
                        results.append(done[room_id])
                        continue
                    room = self._member(tx, room_id, actor)
                    old = tx.chat_message_by_client(actor.id, t["clientId"])
                    if old is not None:  # 다시 보내기 — 처음 것 그대로(SSE · 푸시 없음 · 숨김을 풀었으면 chat_room 만)
                        msg = self._messages(tx, [old], accounts)[0]
                        events += self._room_events(tx, tx.chat_room(room_id) or room, also, accounts)
                    else:
                        self._check_peer(tx, room, actor, accounts)
                        attach = None
                        if src is not None:
                            attach = tx.add_chat_photo(
                                room_id=room_id, account_id=actor.id, kind=src["kind"], file_name=src["file_name"],
                                thumb_file_name=src["thumb_file_name"], bytes=src["bytes"], sha256=src["sha256"],
                                width=src["width"], height=src["height"], duration_ms=src["duration_ms"], created_at=at)
                        mid, msg, ev = self._insert(tx, room, actor, accounts, kind=m["kind"],
                                                    body=None if src is not None else m["body"], attach=attach,
                                                    client_id=t["clientId"], at=at, also=also)
                        made.append(mid)
                        events += ev
                    done[room_id] = {"ok": True, "roomId": msg["roomId"], "message": msg}
                    results.append(done[room_id])
                except DomainError as e:
                    results.append({"ok": False, "roomId": room_id, "error": {"code": e.code, "message": e.message}})
        log.info("채팅 전달 room=%d message=%d account=%d targets=%d ok=%d made=%d", m["room_id"], message_id, actor.id,
                 len(targets), sum(1 for r in results if r["ok"]), len(made))
        self._emit(events)
        for mid in made:
            self.push(mid)
        return results

    def delete(self, actor: Account, message_id: int) -> None:
        """삭제(§5) — 내 것만 · 소프트(body null · deleted_at · updated_at) · 첨부 행 지움 · 이미 지운 것 = 그대로 200.

        파일(동영상 = 본 파일 + 썸네일)은 같은 file_name 을 가리키는 안 지운 첨부 행이 하나도 없을 때만 지운다(전달본 · r4 ·
        D9-66) — 셈은 tx 안 · 지우기는 커밋 뒤.
        """
        at = to_db_ms(self.clock.now())
        with self.repo.tx() as tx:
            m = tx.chat_message(message_id)
            me = tx.chat_member(m["room_id"], actor.id) if m else None
            if m is None or not self._sees(me, m["id"]):  # 멤버 아님 · 나감 · 내 경계 안(r5 · OQ-969) = 없는 것
                raise NotFound("메시지를 찾을 수 없어요", "chat_message_not_found")
            if m["account_id"] != actor.id or m["kind"] == "system":
                raise Forbidden("chat_not_yours", "내 메시지만 지울 수 있어요")
            if m["deleted_at"] is not None:
                return
            tx.update_chat_message(message_id, body=None, deleted_at=at, updated_at=at)
            photo = tx.chat_photo(m["photo_id"]) if m["photo_id"] else None
            if photo is not None and photo["deleted_at"] is None:
                tx.update_chat_photo(photo["id"], deleted_at=at)
            last_ref = photo is not None and tx.chat_photo_live_refs(photo["file_name"]) == 0
            members = self._seers(tx.chat_members(m["room_id"]), message_id)  # 볼 수 있는 사람만(r5 · V9)
        if last_ref:
            path = self._folder()
            if path is not None:
                for name in (photo["file_name"], photo["thumb_file_name"]):
                    if name:
                        (path / name).unlink(missing_ok=True)
        log.info("채팅 지움 room=%d message=%d account=%d", m["room_id"], message_id, actor.id)
        data = {"roomId": m["room_id"], "messageId": message_id, "updatedAt": iso_ms(parse(at))}
        self._emit([(i, "chat_message_deleted", data) for i in members])

    def edit(self, actor: Account, message_id: int, text: str) -> dict[str, Any]:
        """수정(r3 · §5 · D9-55) — 내 텍스트만 · 시한 없음 · body = 새 글 · edited_at = updated_at = 지금(since 로 메워짐).

        새 메시지 · 안 읽음 · 방 last_message_at · 순서 · 푸시는 그대로(self.push 를 부르지 않는다) · 커밋 뒤
        chat_message_edited 를 그 메시지를 볼 수 있는 지금 멤버에게(r5). 같은 글 = 그대로 200(SSE 없음).
        오류 차례(코디 처분 W-5): 멤버 아님 · 내 경계 안(r5) 404 →
        남의 사진 · 동영상 · 지운 것 · 글 403 chat_not_yours → 내 사진 · 동영상 · 지운 것 · 시스템 줄 400 chat_not_editable.
        """
        if not text.strip():
            raise BadRequest("chat_message_empty", "고칠 내용이 없어요")
        if len(text) > MAX_TEXT:
            raise BadRequest("chat_message_too_long", f"메시지는 {MAX_TEXT}자까지예요")
        at = to_db_ms(self.clock.now())
        with self.repo.tx() as tx:
            m = tx.chat_message(message_id)
            me = tx.chat_member(m["room_id"], actor.id) if m else None
            if m is None or not self._sees(me, m["id"]):  # 멤버 아님 · 나감 · 내 경계 안(r5 · OQ-969) = 없는 것
                raise NotFound("메시지를 찾을 수 없어요", "chat_message_not_found")
            if m["kind"] != "system" and m["account_id"] != actor.id:
                raise Forbidden("chat_not_yours", "내 메시지만 고칠 수 있어요")
            if m["kind"] != "text" or m["deleted_at"] is not None:
                raise BadRequest("chat_not_editable", "글만 고칠 수 있어요")
            accounts = self._accounts(tx)
            if m["body"] == text:
                return self._messages(tx, [m], accounts)[0]
            tx.update_chat_message(message_id, body=text, edited_at=at, updated_at=at)
            msg = self._messages(tx, [tx.chat_message(message_id) or {}], accounts)[0]
            members = self._seers(tx.chat_members(m["room_id"]), message_id)  # 볼 수 있는 사람만(r5 · V9)
        log.info("채팅 고침 room=%d message=%d account=%d", m["room_id"], message_id, actor.id)
        self._emit([(i, "chat_message_edited", {"roomId": m["room_id"], "message": msg}) for i in members])
        return msg

    def read(self, actor: Account, room_id: int, message_id: int) -> dict[str, Any]:
        """읽음(§5) — last_read = max(지금, min(messageId, 방 마지막 id)) · last_viewed_at = 지금.

        messageId 0(빈 방) = 아무것도 안 바꿈 · 200(코디 처분 W2-2).
        """
        at = to_db_ms(self.clock.now())
        with self.repo.tx() as tx:
            self._member(tx, room_id, actor)
            me = tx.chat_member(room_id, actor.id)
            assert me is not None
            if message_id > 0:
                last = tx.last_chat_message(room_id)
                upto = max(me["last_read_message_id"], min(message_id, last["id"] if last else 0))
                tx.update_chat_member(room_id, actor.id, last_viewed_at=at, last_read_message_id=upto)
                me = tx.chat_member(room_id, actor.id)
                assert me is not None
            out = {"lastViewedAt": iso_ms(parse(me["last_viewed_at"])), "lastReadMessageId": me["last_read_message_id"],
                   "unreadRooms": self._unread_rooms(tx, actor.id)}
        if message_id > 0:
            self._emit([(actor.id, "chat_read", {"roomId": room_id, **out})])
        return out

    # ------------------------------------------------------------------ #13 · #14 사진(§9)
    def _folder(self) -> Path | None:
        return Path(self.s.proc_photo_dir) / PHOTO_SUBDIR if self.s.proc_photo_dir else None

    def upload(self, actor: Account, room_id: int, data: bytes, width: int, height: int) -> int:
        """`PROC_PHOTO_DIR/chat/<무작위>.jpg` 에 바로 쓰기(임시 파일 없음) + chat_photo 1행.

        메시지에 붙기 전엔 올린 사람만 연다(id 가 순번이라).
        """
        if len(data) > MAX_BYTES:
            raise PhotoTooLarge("photo_too_large", "사진이 5MB 를 넘어요")
        if not data.startswith(JPEG):
            raise BadRequest("chat_photo_type", "JPEG 사진만 보낼 수 있어요")
        with self.repo.tx() as tx:
            self._member(tx, room_id, actor)
        folder = self._folder()
        if folder is None:
            raise Conflict("photo_disabled", "사진 저장이 꺼져 있어요")
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{secrets.token_hex(16)}.jpg"
        (folder / name).write_bytes(data)
        with self.repo.tx() as tx:
            photo_id = tx.add_chat_photo(room_id=room_id, account_id=actor.id, file_name=name, bytes=len(data),
                                         sha256=hashlib.sha256(data).hexdigest(), width=width, height=height,
                                         created_at=to_db_ms(self.clock.now()))
        log.info("채팅 사진 올림 room=%d photo=%d account=%d", room_id, photo_id, actor.id)
        return photo_id

    def _attachment(self, actor: Account, attach_id: int, kind: str, missing: NotFound) -> tuple[dict[str, Any], Path]:
        """첨부 열기 권한(§6.2 #14 · #17 · #18) — 붙기 전 = 올린 사람만 · 붙은 뒤 = 그 방 지금 멤버이고 붙은 메시지가 내 경계
        밖(r5 · V5) · 지움 · 종류 다름 = 404.

        (행, 폴더) — 파일이 있는지는 부르는 쪽이 본다(행 있고 파일 없음 = 404). 열람 로그 없음(D9-23).
        """
        with self.repo.tx() as tx:
            p = tx.chat_photo(attach_id)
            if p is None or p["deleted_at"] is not None or p["kind"] != kind:
                raise missing
            if p["message_id"] is None:
                if p["account_id"] != actor.id:
                    raise missing
            else:
                if not self._sees(tx.chat_member(p["room_id"], actor.id), p["message_id"]):
                    raise missing
        folder = self._folder()
        if folder is None:
            raise Conflict("photo_disabled", "사진 저장이 꺼져 있어요")
        return p, folder

    def photo(self, actor: Account, photo_id: int) -> bytes:
        """사진 열기 — 동영상 id = 없는 것(404 chat_photo_not_found · §6.2)."""
        missing = NotFound("사진을 찾을 수 없어요", "chat_photo_not_found")
        p, folder = self._attachment(actor, photo_id, "photo", missing)
        path = folder / p["file_name"]
        if not path.is_file():
            raise missing
        return path.read_bytes()

    # ------------------------------------------------------------------ #16 ~ #18 동영상(§9.2 · r3)
    def upload_video(self, actor: Account, room_id: int, video: BinaryIO, thumb: bytes, width: int, height: int,
                     duration_ms: int) -> int:
        """`PROC_PHOTO_DIR/chat/<무작위>.mp4`(본 파일) + `<무작위>.jpg`(앱이 만든 썸네일) + chat_photo 1행(kind = video).

        video = multipart 가 흘린 임시 파일(전역 spool 한도 5MB + 64KB 보다 커서 디스크) — 메모리에 다 올리지 않고 1MB 씩
        조각 복사하며 90MB 를 넘으면 그 자리에서 멈추고 쓰던 파일을 지운다. 붙기 전엔 올린 사람만 연다.
        """
        if duration_ms < 1:
            raise BadRequest("invalid_request", "durationMs: 1 이상이어야 해요")
        if duration_ms > VIDEO_MAX_MS:
            raise BadRequest("chat_video_too_long", "3분 이하 동영상만 보낼 수 있어요")
        if len(thumb) > MAX_BYTES:
            raise PhotoTooLarge("photo_too_large", "사진이 5MB 를 넘어요")
        if not thumb.startswith(JPEG):
            raise BadRequest("chat_photo_type", "JPEG 사진만 보낼 수 있어요")
        video.seek(0)
        head = video.read(8)
        if head[4:8] != MP4_BOX:
            raise BadRequest("chat_video_type", "MP4 동영상만 보낼 수 있어요")
        with self.repo.tx() as tx:
            self._member(tx, room_id, actor)
        folder = self._folder()
        if folder is None:
            raise Conflict("photo_disabled", "사진 저장이 꺼져 있어요")
        folder.mkdir(parents=True, exist_ok=True)
        name, thumb_name = f"{secrets.token_hex(16)}.mp4", f"{secrets.token_hex(16)}.jpg"
        digest, size = hashlib.sha256(), 0
        video.seek(0)
        try:
            with (folder / name).open("wb") as out:
                while chunk := video.read(CHUNK):
                    size += len(chunk)
                    if size > VIDEO_MAX_BYTES:
                        raise PhotoTooLarge("chat_video_too_large", "동영상이 90MB 를 넘어요")
                    digest.update(chunk)
                    out.write(chunk)
            (folder / thumb_name).write_bytes(thumb)
            with self.repo.tx() as tx:
                video_id = tx.add_chat_photo(room_id=room_id, account_id=actor.id, kind="video", file_name=name,
                                             thumb_file_name=thumb_name, bytes=size, sha256=digest.hexdigest(),
                                             width=width, height=height, duration_ms=duration_ms,
                                             created_at=to_db_ms(self.clock.now()))
        except BaseException:
            for n in (name, thumb_name):
                (folder / n).unlink(missing_ok=True)
            raise
        log.info("채팅 동영상 올림 room=%d video=%d account=%d", room_id, video_id, actor.id)
        return video_id

    def _video_file(self, actor: Account, video_id: int, thumb: bool) -> Path:
        missing = NotFound("동영상을 찾을 수 없어요", "chat_video_not_found")
        p, folder = self._attachment(actor, video_id, "video", missing)
        name = p["thumb_file_name"] if thumb else p["file_name"]
        path = folder / name if name else None
        if path is None or not path.is_file():
            raise missing
        return path

    def video_path(self, actor: Account, video_id: int) -> Path:
        """본 파일 자리 — 끊어 받기(Range)는 router 의 FileResponse 가 한다. 사진 id = 없는 것(404 chat_video_not_found)."""
        return self._video_file(actor, video_id, thumb=False)

    def video_thumb(self, actor: Account, video_id: int) -> bytes:
        """썸네일 JPEG — 본 파일과 같은 권한."""
        return self._video_file(actor, video_id, thumb=True).read_bytes()
