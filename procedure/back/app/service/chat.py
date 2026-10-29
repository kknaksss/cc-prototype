"""직원 채팅(SPEC-007) — 1:1 · 그룹 · 텍스트 · 사진 1장. 다섯 역할 모두 같은 권한 · 가짜 판에서도 된다(KOS 없음).

법적 검토 필요: 직원 채팅 — 고객 정보가 메시지 · 사진으로 오갈 수 있음(보존 기간 없음 · 열람 로그 없음 · 잠금 화면에 본문 앞부분)

- 권한: 그 방 지금 멤버(left_at null)만. 아니면 방 · 메시지 · 사진이 **없는 것처럼** 404(§2 · OQ-903).
- 시각: 채팅 표는 clock.to_db_ms(UTC · 밀리초) · API 는 clock.iso_ms(KST · 밀리초). 시각은 쓰는 트랜잭션 안에서 잡고
  커밋까지 await 가 없다(핸들러 async def · 이 서비스는 동기) → 시각 순서 = 커밋 순서 = id 순서(§3).
- 안 읽음 = id > last_read_message_id(시각이 아니라 id · §5). 방에 들어올 때(만들기 · 처음 추가 · 다시 초대) = 그 순간
  방의 마지막 메시지 id(D9-43 · D9-45).
- SSE · 푸시는 커밋 뒤(`send` · `push` 는 container 가 꽂는다 — 띄우기와 같은 꼴). 로그엔 id 만(본문 · 이름 없음 · §6.1).
"""

import hashlib
import logging
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.clock import Clock, iso_ms, parse, to_db_ms
from app.domain.errors import BadRequest, Conflict, Forbidden, NotFound
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
PREVIEW = 100  # 미리보기 · 푸시 본문 앞부분(OQ-915)
INACTIVE = " (비활성)"
JPEG = b"\xff\xd8\xff"
PHOTO_SUBDIR = "chat"  # PROC_PHOTO_DIR/chat/ — 신분증(바로 아래)과 섞지 않는다

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
    def _sender(a: Account | None, account_id: int) -> dict[str, Any]:
        if a is None:
            return {"id": account_id, "name": "", "role": "admin", "active": False}
        return {"id": a.id, "name": a.name, "role": a.role, "active": a.active}

    def _message(self, m: dict[str, Any], accounts: dict[int, Account], photo: dict[str, Any] | None = None) -> dict[str, Any]:
        deleted = m["deleted_at"] is not None
        ref = None
        if m["kind"] == "photo" and not deleted and m["photo_id"] is not None:
            ref = {"id": m["photo_id"], "width": photo["width"] if photo else None, "height": photo["height"] if photo else None}
        return {"id": m["id"], "roomId": m["room_id"], "clientId": m["client_id"],
                "sender": self._sender(accounts.get(m["account_id"]), m["account_id"]), "kind": m["kind"],
                "text": None if deleted else m["body"], "photo": ref, "createdAt": iso_ms(parse(m["created_at"])),
                "updatedAt": iso_ms(parse(m["updated_at"])), "deletedAt": iso_ms(parse(m["deleted_at"]))}

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
        if last is not None:
            sender = accounts.get(last["account_id"])
            deleted = last["deleted_at"] is not None
            text = None if deleted or last["kind"] == "photo" or last["body"] is None else last["body"][:PREVIEW]
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
        """방에 들어옴(만들기 · 처음 추가 · 다시 초대) — 읽은 데까지 = 그 순간 방의 마지막 메시지(D9-43 · D9-45)."""
        last = tx.last_chat_message(room_id)
        last_id = last["id"] if last else 0
        if tx.chat_member(room_id, account_id) is None:
            tx.add_chat_member(room_id=room_id, account_id=account_id, joined_at=at, last_viewed_at=at,
                               last_read_message_id=last_id)
        else:
            tx.update_chat_member(room_id, account_id, joined_at=at, left_at=None, hidden_at=None, last_viewed_at=at,
                                  last_read_message_id=last_id)

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
    def open_direct(self, actor: Account, account_id: int) -> dict[str, Any]:
        """1:1 열기(§4.1) — 같은 두 사람 = 같은 방 · 내가 숨겼으면 다시 보임."""
        at = to_db_ms(self.clock.now())
        with self.repo.tx() as tx:
            accounts = self._accounts(tx)
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
            room = tx.chat_room(room_id)
            assert room is not None
            out = self._room(tx, room, actor.id, accounts)
            events = self._room_events(tx, room, to, accounts)
        if created:
            log.info("채팅 1:1 만듦 room=%d account=%d", room_id, actor.id)
        self._emit(events)
        return out

    def create_group(self, actor: Account, account_ids: list[int], title: str | None) -> dict[str, Any]:
        """그룹(§4.2) — 다른 사람 2 ~ 19 · 같은 사람들이어도 매번 새 방 · 이름 비면 null."""
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
            room = tx.chat_room(room_id)
            assert room is not None
            out = self._room(tx, room, actor.id, accounts)
            events = self._room_events(tx, room, [actor.id, *account_ids], accounts)
        log.info("채팅 그룹 만듦 room=%d account=%d members=%d", room_id, actor.id, len(account_ids) + 1)
        self._emit(events)
        return out

    # ------------------------------------------------------------------ #5 ~ #8 방 바꾸기
    def add_members(self, actor: Account, room_id: int, account_ids: list[int]) -> dict[str, Any]:
        """참여자 추가(§4.2) — 누구나 · 지금 멤버 아님 · 추가 뒤 ≤ 20 · 시스템 줄 한 줄 · 나간 사람 = 같은 행 다시."""
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
            names = ", ".join(f"{accounts[i].name} 님" for i in account_ids)
            mid = self._system(tx, room_id, actor, f"{actor.name} 님이 {names}을 초대했어요", at)
            room = tx.chat_room(room_id)
            assert room is not None
            members = [*current, *account_ids]
            out = self._room(tx, room, actor.id, accounts)
            msg = self._message(tx.chat_message(mid) or {}, accounts)
            events = [*self._room_events(tx, room, members, accounts),
                      *((i, "chat_message", {"roomId": room_id, "message": msg}) for i in members)]
        log.info("채팅 참여자 추가 room=%d account=%d added=%d", room_id, actor.id, len(account_ids))
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
            rest = [r["account_id"] for r in tx.chat_members(room_id)]
            msg = self._message(tx.chat_message(mid) or {}, accounts)
            events = [(actor.id, "chat_room_removed", {"roomId": room_id}),
                      *self._room_events(tx, room, rest, accounts),
                      *((i, "chat_message", {"roomId": room_id, "message": msg}) for i in rest)]
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
        """§5 페이지 — 처음 = 최근 limit · before = id < before · since = updated_at >= since(parse 뒤 UTC ms 로 비교)."""
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
            rows, more = tx.chat_messages(room_id, before=before, since=since_db, limit=limit)
            items = self._messages(tx, rows, self._accounts(tx))
        return {"items": items, "hasMore": more}

    def post(self, actor: Account, room_id: int, client_id: str, text: str | None, photo_id: int | None) -> dict[str, Any]:
        """보내기(§5) — 같은 계정 · 같은 clientId = 처음 것 그대로(SSE · 푸시 다시 안 함) · 커밋 뒤 SSE · 푸시."""
        if text is not None and photo_id is not None:
            raise BadRequest("invalid_request", "text · photoId 는 하나만 보내요")
        if photo_id is None and (text is None or not text.strip()):
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
            if photo_id is not None:
                p = tx.chat_photo(photo_id)
                if (p is None or p["account_id"] != actor.id or p["room_id"] != room_id or p["message_id"] is not None
                        or p["deleted_at"] is not None):
                    raise BadRequest("chat_photo_invalid", "보낼 수 없는 사진이에요")
            members = tx.chat_members(room_id)
            if room["kind"] == "direct":
                peer = next((accounts.get(m["account_id"]) for m in members if m["account_id"] != actor.id), None)
                if peer is None or not peer.active:
                    raise Conflict("chat_peer_inactive", "비활성 계정이에요")
            mid = tx.add_chat_message(room_id=room_id, account_id=actor.id, kind="photo" if photo_id else "text",
                                      body=None if photo_id else text, photo_id=photo_id, client_id=client_id,
                                      created_at=at, updated_at=at)
            if photo_id is not None:
                tx.update_chat_photo(photo_id, message_id=mid)
            prev = room["last_message_at"]
            tx.update_chat_room(room_id, last_message_at=at)
            tx.update_chat_member(room_id, actor.id, last_viewed_at=at, last_read_message_id=mid)
            # 숨긴 1:1 이 이 메시지로 다시 보이는 사람(§4.3) — 그 사람에게 chat_room
            shown = [m["account_id"] for m in members
                     if m["hidden_at"] is not None and (prev is None or prev <= m["hidden_at"]) and at > m["hidden_at"]]
            room = tx.chat_room(room_id)
            assert room is not None
            msg = self._messages(tx, [tx.chat_message(mid) or {}], accounts)[0]
            events = [*self._room_events(tx, room, shown, accounts),
                      *((m["account_id"], "chat_message", {"roomId": room_id, "message": msg}) for m in members)]
        log.info("채팅 보냄 room=%d message=%d account=%d", room_id, mid, actor.id)
        self._emit(events)
        self.push(mid)
        return msg

    def delete(self, actor: Account, message_id: int) -> None:
        """삭제(§5) — 내 것만 · 소프트(body null · deleted_at · updated_at) · 사진이면 파일 지움 · 이미 지운 것 = 그대로 200."""
        at = to_db_ms(self.clock.now())
        with self.repo.tx() as tx:
            m = tx.chat_message(message_id)
            me = tx.chat_member(m["room_id"], actor.id) if m else None
            if m is None or me is None or me["left_at"] is not None:
                raise NotFound("메시지를 찾을 수 없어요", "chat_message_not_found")
            if m["account_id"] != actor.id or m["kind"] == "system":
                raise Forbidden("chat_not_yours", "내 메시지만 지울 수 있어요")
            if m["deleted_at"] is not None:
                return
            tx.update_chat_message(message_id, body=None, deleted_at=at, updated_at=at)
            photo = tx.chat_photo(m["photo_id"]) if m["photo_id"] else None
            if photo is not None and photo["deleted_at"] is None:
                tx.update_chat_photo(photo["id"], deleted_at=at)
            members = [r["account_id"] for r in tx.chat_members(m["room_id"])]
        if photo is not None:
            path = self._folder()
            if path is not None:
                (path / photo["file_name"]).unlink(missing_ok=True)
        log.info("채팅 지움 room=%d message=%d account=%d", m["room_id"], message_id, actor.id)
        data = {"roomId": m["room_id"], "messageId": message_id, "updatedAt": iso_ms(parse(at))}
        self._emit([(i, "chat_message_deleted", data) for i in members])

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

    def photo(self, actor: Account, photo_id: int) -> bytes:
        """열기 — 붙기 전 = 올린 사람만 · 붙은 뒤 = 그 방 지금 멤버만 · 지움 · 파일 없음 = 404 · 열람 로그 없음(D9-23)."""
        missing = NotFound("사진을 찾을 수 없어요", "chat_photo_not_found")
        with self.repo.tx() as tx:
            p = tx.chat_photo(photo_id)
            if p is None or p["deleted_at"] is not None:
                raise missing
            if p["message_id"] is None:
                if p["account_id"] != actor.id:
                    raise missing
            else:
                me = tx.chat_member(p["room_id"], actor.id)
                if me is None or me["left_at"] is not None:
                    raise missing
        folder = self._folder()
        if folder is None:
            raise Conflict("photo_disabled", "사진 저장이 꺼져 있어요")
        path = folder / p["file_name"]
        if not path.is_file():
            raise missing
        return path.read_bytes()
