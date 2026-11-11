"""직원 채팅 API 20(SPEC-007 §6.2 · 1판 14 + r3 4 + r4 전달 1 + r5 모아보기 1) — Bearer · 다섯 역할 모두 · 가짜 판에서도 됨.

경로는 모두 `async def` — SSE(`send_to_account` 의 `asyncio.Queue`) · 푸시(`PushService._dispatch` 의 이벤트 루프)가
루프 스레드에서 돌아야 한다. 동기 `def` 면 스레드풀에서 돌아 푸시가 「이벤트 루프 없음」으로 0 이 된다(§6.1).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.datastructures import UploadFile

from app.api.deps import Actor, Ctr
from app.api.docs import INVALID, T_CHAT, UNAUTHORIZED, binary, errors
from app.api.photos import FORM_OVERHEAD
from app.domain.errors import BadRequest
from app.schemas.actions import OkResponse
from app.schemas.chat import (
    DirectRequest,
    EditRequest,
    ForwardRequest,
    ForwardResponse,
    GroupRequest,
    MembersRequest,
    Message,
    MessageList,
    MuteRequest,
    MuteResponse,
    PeopleList,
    PhotoUploadResponse,
    ReadRequest,
    ReadResponse,
    Room,
    RoomList,
    SendRequest,
    VideoUploadResponse,
)
from app.service.chat import GRID, PAGE, VIDEO_MAX_BYTES
from app.service.id_photo import MAX_BYTES
from app.service.passport_scan import PhotoTooLarge

router = APIRouter(prefix="/api/chat", tags=[T_CHAT])

# ------------------------------------------------------------------ 문서(OpenAPI) 전용 — 요청 처리와 무관
RoomId = Annotated[int, Path(description="대화방 id")]
MessageId = Annotated[int, Path(description="메시지 id")]
PhotoId = Annotated[int, Path(description="사진 id(업로드 응답의 photoId · Message.photo.id)")]
VideoId = Annotated[int, Path(description="동영상 id(업로드 응답의 videoId · Message.video.id)")]

_COMMON = (
    "\n\n**누가**: 로그인한 직원 누구나(admin · doctor · nurse · coordinator · counselor — 역할 검사 없음). "
    "가짜 판(`PROC_FAKE_BOARD`)에서도 그대로 동작한다(실 DB 에 쓴다)."
)
_SSE = (
    "SSE 는 `GET /api/board/stream` 연결에 실린다(`event: <이름>` + `data: <JSON>` · `id:` 줄 없음 · 계정 단위로 그 계정의 "
    "모든 연결에)."
)
ROOM_404 = (404, "chat_room_not_found", "방이 없거나 · 내가 그 방 지금 멤버가 아닐 때(나간 방 포함 · 없는 것처럼 보인다)")
MSG_404 = (404, "chat_message_not_found",
           "메시지가 없거나 · 그 방 지금 멤버가 아니거나 · 내가 들어오기 전 메시지일 때(없는 것처럼 보인다)")
PHOTO_OFF = (409, "photo_disabled", "서버에 사진 저장 폴더(env `PROC_PHOTO_DIR`)가 설정되지 않았을 때")
FORM_400 = (400, "http_error", "multipart 본문을 읽을 수 없거나 · 파일 · 칸 수 한도를 넘었거나 · "
            "파일 아닌 칸 하나가 1MB(1024 × 1024 바이트)를 넘을 때(Starlette 파서 오류)")


def _int(v: object, name: str) -> int:
    try:
        return int(str(v))
    except ValueError:
        raise BadRequest("invalid_request", f"{name}: 정수여야 해요") from None


_D_PEOPLE: dict[str, Any] = dict(
    summary="대화 상대 후보 목록",
    description="""새 1:1 · 그룹 · 초대 · 전달 때 고를 수 있는 직원 목록.

- 활성(`active`) + 로그인 가능(비밀번호 있음) 계정 중 **나를 뺀** 것 · `{id, name, role}` 만.
- 차례 = 이름 문자열 코드포인트 순(가나다 순과 다름 — 라틴 < 한글 · 대문자 < 소문자) · 같으면 id 순.
- 읽기 전용 · SSE · 푸시 없음.""" + _COMMON,
    responses=errors(UNAUTHORIZED),
)


@router.get("/people", response_model=PeopleList, **_D_PEOPLE)
async def people(c: Ctr, actor: Actor) -> PeopleList:
    return PeopleList.model_validate({"items": c.chat.people(actor)})


_D_ROOMS: dict[str, Any] = dict(
    summary="내 방 목록",
    description="""내가 지금 멤버인 방 목록 + 안 읽은 방 수.

- 나간 그룹은 없다. 숨긴 1:1 은 숨긴 뒤 새 메시지가 오기 전까지 빠진다.
- 차례 = 마지막 메시지 시각(없으면 만든 시각) 최근 것 먼저 · 같으면 id 큰 것 먼저.
- Room 은 **보는 계정 기준**으로 만든다(`name` · `muted` · `unread` · `members[].me` · `lastMessage`).
- `lastMessage` 는 내가 들어온 뒤 메시지만(들어오기 전 것이 마지막이면 null).
- `unreadRooms` = items 중 `unread > 0` 인 방 수(알림 끈 방도 센다).
- 읽기 전용 · SSE · 푸시 없음.""" + _COMMON,
    responses=errors(UNAUTHORIZED),
)


@router.get("/rooms", response_model=RoomList, **_D_ROOMS)
async def rooms(c: Ctr, actor: Actor) -> RoomList:
    return RoomList.model_validate(c.chat.rooms(actor))


_D_OPEN_DIRECT: dict[str, Any] = dict(
    summary="1:1 열기(없으면 만들기)",
    description="""상대와의 1:1 방을 돌려준다. 같은 두 사람 = 늘 같은 방 하나.

- 없으면 만든다 — 두 사람 모두 멤버로 넣고(읽은 데까지 = 0) · SSE `chat_room` 을 **두 사람** 각자에게(각자 기준 Room).
- 이미 있고 내가 숨겼으면 숨김을 풀고 SSE `chat_room` 을 **나에게만**.
- 이미 있고 숨기지 않았으면 아무것도 바꾸지 않는다(SSE 없음).
- **멱등** — 여러 번 불러도 같은 방. 상대가 비활성이면 열 수 없다(`chat_person_invalid`).
- 푸시 없음. 시스템 줄 없음.

""" + _SSE + _COMMON,
    responses=errors(INVALID, UNAUTHORIZED,
                     (400, "chat_person_invalid",
                      "상대가 나 자신이거나 · 없는 계정 · 비활성 · 비밀번호 없는(로그인 불가) 계정일 때")),
)


@router.post("/rooms/direct", response_model=Room, **_D_OPEN_DIRECT)
async def open_direct(body: DirectRequest, c: Ctr, actor: Actor) -> Room:
    return Room.model_validate(c.chat.open_direct(actor, body.accountId))


_D_CREATE_GROUP: dict[str, Any] = dict(
    summary="그룹 만들기",
    description="""새 그룹 방을 만든다(나 + 고른 사람 2 ~ 19명 = 3 ~ 20명).

- **멱등 아님** — 같은 사람들이어도 부를 때마다 새 방.
- `title` 은 앞뒤 공백을 뺀 뒤 40자까지 · 비면 null(이름 없는 그룹 — 방 이름은 멤버 이름 나열).
- 시스템 줄 한 줄을 쓴다. text = `<나>님이 <A>님, <B>님을 초대했습니다`(낫표 없음 · accountIds 차례 · 그때 이름).
- SSE: `chat_room`(멤버 전원 · 각자 기준 Room) · `chat_message`(`{roomId, message}` — 시스템 줄 · 멤버 전원).
- 푸시 없음(시스템 줄은 푸시하지 않는다) · 시스템 줄은 안 읽음에 세지 않는다.
- 검사 차례: title 길이 → 나 자신 · 중복 → 인원 수 → 계정 상태.

""" + _SSE + _COMMON,
    responses=errors(
        INVALID, (400, "invalid_request", "title 이 앞뒤 공백을 뺀 뒤 40자를 넘을 때"), UNAUTHORIZED,
        (400, "chat_person_invalid", "accountIds 에 나 자신 · 중복 · 없는 계정 · 비활성 · 로그인 불가 계정이 있을 때"),
        (400, "chat_group_size", "accountIds 가 2개보다 적거나 19개보다 많을 때(나 포함 3 ~ 20명)")),
)


@router.post("/rooms", response_model=Room, **_D_CREATE_GROUP)
async def create_group(body: GroupRequest, c: Ctr, actor: Actor) -> Room:
    return Room.model_validate(c.chat.create_group(actor, body.accountIds, body.title))


_D_ADD_MEMBERS: dict[str, Any] = dict(
    summary="그룹에 초대(참여자 추가)",
    description="""그룹에 사람을 더한다. 지금 멤버 누구나 할 수 있다. 응답 = 내 기준 Room.

- 그룹만(1:1 = `chat_group_only`). 추가 뒤 지금 멤버 20명까지.
- 나간 사람도 다시 초대할 수 있다(같은 멤버 행을 되살림 · 숨김 해제).
- 들어온 사람은 **들어온 뒤 대화만** 본다 — 경계 = 그 순간 방의 마지막 메시지 id(다시 초대돼도 옛 대화는 안 보임) · 읽은
  데까지도 같은 값.
- 시스템 줄 한 줄. text = `<나>님이 <A>님, <B>님을 초대했습니다`(낫표 없음 · accountIds 차례).
- SSE: `chat_room`(새 멤버 포함 지금 멤버 전원 · 각자 기준) · `chat_message`(시스템 줄 · 그 줄을 볼 수 있는 지금 멤버 = 새
  멤버 포함 전원).
- 푸시 없음. **멱등 아님** — 같은 사람을 다시 보내면 이미 멤버라 `chat_person_invalid`.

""" + _SSE + _COMMON,
    responses=errors(
        INVALID, UNAUTHORIZED,
        (400, "chat_group_only", "1:1 방일 때"),
        (400, "chat_person_invalid", "accountIds 에 중복 · 이미 지금 멤버 · 없는 계정 · 비활성 · 로그인 불가 계정이 있을 때"),
        ROOM_404,
        (409, "chat_room_full", "추가하면 지금 멤버가 20명을 넘을 때")),
)


@router.post("/rooms/{room_id}/members", response_model=Room, **_D_ADD_MEMBERS)
async def add_members(room_id: RoomId, body: MembersRequest, c: Ctr, actor: Actor) -> Room:
    return Room.model_validate(c.chat.add_members(actor, room_id, body.accountIds))


_D_LEAVE: dict[str, Any] = dict(
    summary="그룹 나가기",
    description="""그룹에서 나간다(1:1 은 나갈 수 없다 — 숨기기를 쓴다).

- 내 멤버 행에 나간 시각을 남긴다(행은 지우지 않음). 남은 사람이 0명이어도 방은 남는다.
- 시스템 줄 한 줄. text = `<내 이름> 님이 나갔어요`(낫표 없음 · 이름 뒤 빈칸 있음).
- SSE: `chat_room_removed`(`{roomId}` · 나에게) · `chat_room`(남은 멤버 각자 기준) · `chat_message`(시스템 줄 · 남은 멤버 중
  볼 수 있는 사람).
- 푸시 없음.
- **멱등 아님** — 다시 부르면 이미 멤버가 아니라 404 `chat_room_not_found`.

""" + _SSE + _COMMON,
    responses=errors(INVALID, UNAUTHORIZED, (400, "chat_group_only", "1:1 방일 때(1:1 은 숨기기)"), ROOM_404),
)


@router.post("/rooms/{room_id}/leave", response_model=OkResponse, **_D_LEAVE)
async def leave(room_id: RoomId, c: Ctr, actor: Actor) -> OkResponse:
    c.chat.leave(actor, room_id)
    return OkResponse()


_D_HIDE: dict[str, Any] = dict(
    summary="1:1 목록에서 숨기기",
    description="""1:1 방을 **내 목록에서만** 숨긴다(상대 쪽은 그대로 · 메시지는 지우지 않음).

- 숨긴 뒤 그 방에 새 메시지가 오면 다시 목록에 보인다(그때 SSE `chat_room` 이 나에게). 숨긴 동안에도 푸시는 받는다(알림
  끄기와 별개).
- 숨긴 1:1 은 `unreadRooms` 에 세지 않는다.
- SSE: `chat_room_removed`(`{roomId}` · 내 계정 연결 전부 — 다른 기기 목록에서도 뺀다).
- 다시 불러도 200(숨긴 시각만 지금으로 바뀌고 같은 SSE 를 다시 낸다). 1:1 열기(`POST /rooms/direct`)로 숨김을 풀 수 있다.

""" + _SSE + _COMMON,
    responses=errors(INVALID, UNAUTHORIZED, (400, "chat_direct_only", "그룹 방일 때(그룹은 나가기)"), ROOM_404),
)


@router.post("/rooms/{room_id}/hide", response_model=OkResponse, **_D_HIDE)
async def hide(room_id: RoomId, c: Ctr, actor: Actor) -> OkResponse:
    c.chat.hide(actor, room_id)
    return OkResponse()


_D_MUTE: dict[str, Any] = dict(
    summary="방 알림 끄기 · 켜기",
    description="""이 방에서 **나만** 알림을 끄거나 켠다(1:1 · 그룹 모두).

- 끄면 그 방 새 메시지 푸시를 받지 않는다. 메시지 · SSE · 안 읽음 수는 그대로.
- SSE: `chat_room`(나에게만 · `muted` 가 바뀐 Room).
- **멱등** — 같은 값을 다시 보내도 200(SSE 는 다시 낸다).

""" + _SSE + _COMMON,
    responses=errors(INVALID, UNAUTHORIZED, ROOM_404),
)


@router.put("/rooms/{room_id}/mute", response_model=MuteResponse, **_D_MUTE)
async def mute(room_id: RoomId, body: MuteRequest, c: Ctr, actor: Actor) -> MuteResponse:
    return MuteResponse(muted=c.chat.mute(actor, room_id, body.muted))


_D_MESSAGES: dict[str, Any] = dict(
    summary="메시지 목록(쪽 넘김 · 바뀐 것 메우기)",
    description="""방의 메시지를 한 쪽씩 돌려준다. **items 차례 = 오래된 것 위(id 오름차순)**.

**주의 — `since` 값은 URL 인코딩해서 보낸다.** `updatedAt` 에는 `+09:00` 이 붙어 있어 `+` 를 그대로 쿼리에 넣으면
공백으로 읽혀 400 `invalid_request` 가 난다. `+` 는 `%2B` 로 인코딩(예: `since=2026-01-01T10%3A00%3A00.000%2B09%3A00`).

**주의 — 지운 메시지는 `deletedAt` 에 지운 시각이 들어 있고** text · photo · video 만 null 이다(`deletedAt == null` 로
거르면 지운 메시지를 놓친다).

세 꼴(`before` · `since` 는 함께 못 씀):
- 아무것도 없음 = 가장 최근 `limit` 개.
- `before=<id>` = id 가 그보다 작은 것 중 가장 최근 `limit` 개(위로 더 불러오기).
- `since=<시각>` = `updatedAt >= since`(경계 포함)인 것 중 가장 최근 `limit` 개 — 새 메시지 · 고친 것 · 지운 것을 메운다.
  경계가 겹쳐 같은 메시지가 다시 올 수 있으니 앱이 id 로 겹침을 지운다. 응답 Message 의 `updatedAt` 값을 다음 `since`
  에 쓰면 된다(URL 인코딩 필수 — 위 주의).
  이 꼴은 **조건에 맞는 것 중 가장 최근 `limit`(≤ 50) 개만** 돌려주고 `before` 와 같이 쓸 수 없다. `hasMore=true` 면 그보다
  오래된 변경을 이 꼴로 더 받을 길이 없으니, 처음 꼴(인자 없음)과 `before` 로 목록을 다시 불러온다.

- 세 꼴 모두 **내가 들어온 뒤 메시지만**(들어오기 전 것은 없는 것처럼 · 경계에 닿으면 `hasMore=false`).
- `hasMore` = 같은 조건으로 더 오래된 것이 남았으면 true.
- 지운 메시지도 나온다(`deletedAt` = 지운 시각 · text · photo · video = null). 시스템 줄도 나온다.
- 읽음 처리는 하지 않는다(`POST /rooms/{room_id}/read` 를 따로 부른다). 읽기 전용.""" + _COMMON,
    responses=errors(
        INVALID,
        (400, "invalid_request",
         "`before` 와 `since` 를 함께 보냈거나 · `since` 를 시각으로 읽을 수 없을 때(`+` 를 인코딩하지 않은 경우 포함)"),
        UNAUTHORIZED, ROOM_404),
)


@router.get("/rooms/{room_id}/messages", response_model=MessageList, **_D_MESSAGES)
async def messages(room_id: RoomId, c: Ctr, actor: Actor,
                   before: int | None = Query(None, description="이 id 보다 작은(오래된) 메시지만. since 와 함께 못 씀"),
                   since: str | None = Query(
                       None, description="ISO-8601 시각 — updatedAt 이 이 시각 이상(경계 포함)인 메시지만. "
                                         "오프셋이 없으면 UTC 로 읽는다. "
                                         "`+` 는 `%2B` 로 URL 인코딩해야 한다(안 하면 공백이 되어 400). "
                                         "before 와 함께 못 씀"),
                   limit: int = Query(PAGE, ge=1, le=PAGE, description="한 쪽 최대 개수(1 ~ 50 · 기본 50)")) -> MessageList:
    """오래된 것 위. `since` 는 clock.parse 로 읽어 UTC 밀리초로 바꿔 `updated_at >= since`(경계 포함 · 앱이 id 로 겹침 지움)."""
    return MessageList.model_validate(c.chat.messages(actor, room_id, before, since, limit))


_D_ATTACHMENTS: dict[str, Any] = dict(
    summary="사진 · 동영상 모아보기",
    description="""방의 사진 · 동영상 메시지만 한 쪽씩. **items 차례 = 최근 것 위(id 내림차순)** — 메시지 목록과 반대.

- 내가 들어온 뒤 메시지만 · 지운 메시지 · 지운 첨부는 빠진다. 모양은 Message 그대로.
- `before=<id>` = id 가 그보다 작은 것(더 오래된 쪽). `hasMore` = 더 오래된 것이 남았으면 true.
- 파일이 실제로 있는지는 보지 않는다 — 열 때(`GET /photos/{id}` · `/videos/{id}` · `/videos/{id}/thumbnail`) 없으면 404.
- 새 SSE 없음(앱은 `chat_message` · `chat_message_deleted` 로 고친다). 열람 로그 없음. 읽기 전용.""" + _COMMON,
    responses=errors(INVALID, UNAUTHORIZED, ROOM_404),
)


@router.get("/rooms/{room_id}/attachments", response_model=MessageList, **_D_ATTACHMENTS)
async def attachments(room_id: RoomId, c: Ctr, actor: Actor,
                      before: int | None = Query(None, description="이 id 보다 작은(오래된) 메시지만"),
                      limit: int = Query(GRID, ge=1, le=GRID, description="한 쪽 최대 개수(1 ~ 60 · 기본 60)")) -> MessageList:
    """모아보기(r5 · §6.2 #20) — 사진 · 동영상 메시지만 · 최근 것 위 · 내 경계 밖만 · 파일은 #14 · #17 · #18 로 연다."""
    return MessageList.model_validate(c.chat.attachments(actor, room_id, before, limit))


_D_POST_MESSAGE: dict[str, Any] = dict(
    summary="메시지 보내기",
    description="""글 · 사진 · 동영상 중 **하나**를 보낸다. 응답 = 만든 Message.

- `text`(1 ~ 2000 코드 포인트) **또는** `photoId` **또는** `videoId` — 둘 이상 = `invalid_request` · 아무것도 없거나 글이
  공백만 = `chat_message_empty`.
- 사진 · 동영상은 먼저 `POST /photos` · `POST /videos` 로 올린 id — **내가 · 이 방에 · 올렸고 · 아직 어느 메시지에도 안
  붙은** 것만.
- 1:1 상대가 비활성이면 보낼 수 없다(409). 그룹은 막지 않는다(혼자 남은 그룹 포함).
- **멱등(clientId)** — 같은 계정 · 같은 `clientId` 가 이미 있으면 새로 만들지 않고 그 메시지를 200 으로 돌려준다(SSE · 푸시
  다시 없음). clientId 는 계정 하나에서 모든 방을 통틀어 하나 — 다른 방에서 쓴 값이면 그 방의 옛 메시지가 돌아온다.
- 쓰는 것: 메시지 · 방 마지막 메시지 시각 · 내 읽은 데까지 = 이 메시지 · 이 방을 숨긴 멤버는 다시 보임.
- SSE(커밋 뒤): `chat_message`(`{roomId, message}` · 그 방 지금 멤버 중 볼 수 있는 사람 — 보낸 사람 포함) · 숨겼다가 다시
  보이게 된 멤버에게 `chat_room`.
- 푸시(APNs · 커밋 뒤 비동기): 받는 사람 = 지금 멤버 − 보낸 사람 − 알림 끈 사람 − 비활성 계정 − 이 메시지를 못 보는 사람 →
  그 계정 기기 전부. 제목 = 1:1 은 보낸 사람 이름 · 그룹은 `보낸 사람 · 방 이름` · 본문 = 글 앞 100자(넘으면 `…` · 줄바꿈은
  공백) · 사진은 `사진` · 동영상은 `동영상` · payload `{kind: "chat", roomId, messageId}` · 만료 1일 · 알림
  목록(notification) 행은 쓰지 않는다. APNs 키가 없으면 보내지 않고 기록만.
- 검사 차례: 형식 · 내용 · 길이(400) → 방 멤버(404) → clientId 다시 보내기(200) → 첨부(400) → 비활성 상대(409).

""" + _SSE + _COMMON,
    responses=errors(
        INVALID, (400, "invalid_request", "text · photoId · videoId 를 둘 이상 보냈을 때"), UNAUTHORIZED,
        (400, "chat_message_empty", "text · photoId · videoId 가 모두 없거나 text 가 공백만일 때"),
        (400, "chat_message_too_long", "text 가 2000 코드 포인트를 넘을 때"),
        (400, "chat_photo_invalid",
         "photoId 가 없거나 · 동영상이거나 · 남이 · 다른 방에 올렸거나 · 이미 붙었거나 · 지운 것일 때"),
        (400, "chat_video_invalid",
         "videoId 가 없거나 · 사진이거나 · 남이 · 다른 방에 올렸거나 · 이미 붙었거나 · 지운 것일 때"),
        ROOM_404,
        (409, "chat_peer_inactive", "1:1 상대가 비활성 계정일 때")),
)


@router.post("/rooms/{room_id}/messages", response_model=Message, **_D_POST_MESSAGE)
async def post_message(room_id: RoomId, body: SendRequest, c: Ctr, actor: Actor) -> Message:
    return Message.model_validate(c.chat.post(actor, room_id, body.clientId, body.text, body.photoId, body.videoId))


_D_EDIT_MESSAGE: dict[str, Any] = dict(
    summary="내 글 고치기",
    description="""내가 보낸 **글(text) 메시지**의 본문을 바꾼다. 시한 없음 · 이력 없음. 응답 = 고친 Message.

- `editedAt` = `updatedAt` = 지금(서버 값 — 앱이 `since` 에 써도 된다).
- 새 메시지 · 안 읽음 · 방 마지막 메시지 시각 · 방 순서 · 푸시는 바뀌지 않는다.
- SSE(커밋 뒤): `chat_message_edited`(`{roomId, message}` · 그 방 지금 멤버 중 이 메시지를 볼 수 있는 사람 — 고친 사람 포함).
- 지금과 같은 글이면 아무것도 바꾸지 않고 그대로 200(`editedAt` 그대로 · SSE 없음).
- 비활성 상대의 1:1 에서도 고칠 수 있다.
- 검사 차례: 내용 · 길이(400) → 메시지 · 멤버(404) → 남의 메시지(403) → 글이 아님 · 지운 것 · 시스템 줄(400 `chat_not_editable`).

""" + _SSE + _COMMON,
    responses=errors(
        INVALID, UNAUTHORIZED,
        (400, "chat_message_empty", "text 가 공백만일 때"),
        (400, "chat_message_too_long", "text 가 2000 코드 포인트를 넘을 때"),
        (400, "chat_not_editable", "내 사진 · 동영상 · 지운 메시지이거나 · 시스템 줄(누가 만들었든)일 때"),
        (403, "chat_not_yours", "남이 보낸 메시지(시스템 줄 아님)일 때"),
        MSG_404),
)


@router.patch("/messages/{message_id}", response_model=Message, **_D_EDIT_MESSAGE)
async def edit_message(message_id: MessageId, body: EditRequest, c: Ctr, actor: Actor) -> Message:
    """수정(r3) — 내 글만 · SSE chat_message_edited · 푸시 없음 · 응답 Message 의 updatedAt 은 서버 값(앱이 since 에 써도 됨)."""
    return Message.model_validate(c.chat.edit(actor, message_id, body.text))


_D_DELETE_MESSAGE: dict[str, Any] = dict(
    summary="내 메시지 지우기",
    description="""내가 보낸 메시지(글 · 사진 · 동영상)를 지운다 — 소프트 삭제.

- 메시지 행은 남고 본문이 비워진다(`deletedAt` · `updatedAt` = 지금 · text · photo · video = null). 첨부 행도 지움 표시.
- 첨부 파일(동영상 = 본 파일 + 썸네일)은 같은 파일을 가리키는 안 지운 첨부(전달본 포함)가 하나도 없을 때만 디스크에서 지운다.
- 방 마지막 메시지 시각 · 순서는 그대로. 푸시 없음.
- SSE(커밋 뒤): `chat_message_deleted`(`{roomId, messageId, updatedAt}` · 그 방 지금 멤버 중 이 메시지를 볼 수 있는 사람).
- 이미 지운 메시지 = 아무것도 안 하고 200(SSE 없음).
- 검사 차례: 메시지 · 멤버(404) → 남의 것 · 시스템 줄(403) → 이미 지움(200).

""" + _SSE + _COMMON,
    responses=errors(INVALID, UNAUTHORIZED,
                     (403, "chat_not_yours", "남이 보낸 메시지이거나 · 시스템 줄(내가 생기게 한 것 포함)일 때"), MSG_404),
)


@router.delete("/messages/{message_id}", response_model=OkResponse, **_D_DELETE_MESSAGE)
async def delete_message(message_id: MessageId, c: Ctr, actor: Actor) -> OkResponse:
    c.chat.delete(actor, message_id)
    return OkResponse()


_D_FORWARD_MESSAGE: dict[str, Any] = dict(
    summary="메시지 전달",
    description="""한 메시지를 1 ~ 10곳(방 또는 사람)에 같은 내용의 **새 메시지**로 보낸다(보낸 사람 = 나 · 「전달됨」 표시 없음).

- 원본: 내가 지금 멤버인 방의 · 내가 들어온 뒤 메시지. 시스템 줄 · 지운 메시지 · 지운 첨부 · 파일이 없는 첨부는 전달할 수
  없다(400). 남의 메시지도 전달할 수 있다.
- 대상: `roomId`(내가 지금 멤버인 방) 또는 `accountId`(그 사람과의 1:1 — 없으면 만들고 · 내가 숨겼으면 숨김 풂).
- 사진 · 동영상 = 대상마다 새 첨부 행 · 같은 파일(복사 없음). 글 = 같은 본문.
- **대상별 실패는 `results` 에만**(`ok:false` + `error{code, message}`) — 전부 실패해도 200. 대상별 오류 코드:
  `chat_person_invalid`(400) · `chat_room_not_found`(404) · `chat_peer_inactive`(409).
- 결과 차례 = 요청 targets 차례 그대로. 한 요청에서 같은 방이 두 번 되면(예: roomId 와 그 1:1 의 accountId) 뒤 것은 앞
  결과가 **성공(`ok:true`)이었을 때만** 그 결과를 그대로 싣는다(새로 안 만듦). 앞 결과가 실패면 뒤 것은 다시 처리한다.
- **멱등(대상마다 clientId)** — 같은 계정 · 같은 clientId 가 이미 있으면 그 메시지를 결과로(SSE · 푸시 없음 · 숨김을
  풀었으면 `chat_room` 만).
- 한 트랜잭션. SSE(커밋 뒤): 만든 메시지마다 `chat_message`(그 방 볼 수 있는 지금 멤버) · 새로 만든 1:1 이면 두 사람에게 ·
  숨김이 풀린 사람에게 `chat_room`.
- 푸시: 만든 메시지마다 보내기와 같은 규칙.
- 검사 차례: 형식 · 개수 · 중복(400) → 원본 없음 · 멤버 아님(404) → 전달할 수 없는 원본(400) · 사진 저장 꺼짐(409) → 대상별 결과.

""" + _SSE + _COMMON,
    responses=errors(
        INVALID,
        (400, "invalid_request", "targets 가 0개이거나 10개를 넘을 때 · 같은 roomId · accountId · clientId 가 두 번 있을 때 · "
                                 "한 대상에 roomId · accountId 를 둘 다 · 둘 다 안 보냈을 때"),
        UNAUTHORIZED,
        (400, "chat_not_forwardable",
         "원본이 시스템 줄 · 지운 메시지이거나 · 첨부 행이 없거나 지웠거나 · 파일이 디스크에 없을 때"),
        MSG_404,
        (409, "photo_disabled", "원본이 사진 · 동영상인데 서버에 사진 저장 폴더(env `PROC_PHOTO_DIR`)가 설정되지 않았을 때")),
)


@router.post("/messages/{message_id}/forward", response_model=ForwardResponse, **_D_FORWARD_MESSAGE)
async def forward_message(message_id: MessageId, body: ForwardRequest, c: Ctr, actor: Actor) -> ForwardResponse:
    """전달(r4 · §6.2 #19) — 대상마다 새 메시지 · 대상별 실패는 결과에(전부 실패도 200) · 결과 = 요청 대상 차례 그대로."""
    targets = [t.model_dump() for t in body.targets]
    return ForwardResponse.model_validate({"results": c.chat.forward(actor, message_id, targets)})


_D_READ: dict[str, Any] = dict(
    summary="읽음 표시",
    description="""이 방을 `messageId` 까지 읽었다고 적는다.

- 읽은 데까지 = max(지금 값, min(messageId, 방 마지막 메시지 id)) — 줄어들지 않는다. 마지막으로 본 시각 = 지금.
- `messageId = 0`(빈 방) = 아무것도 바꾸지 않고 지금 값을 200 으로(SSE 없음).
- 응답 `unreadRooms` = 내 방 목록에 든 방 중 안 읽은 게 있는 방 수(알림 끈 방도 센다 · 숨긴 1:1 은 안 셈).
- SSE(messageId > 0 일 때): `chat_read`(`{roomId, lastViewedAt, lastReadMessageId, unreadRooms}` · **내 계정 연결 전부** —
  다른 기기 배지 지우기용 · 남에게는 안 감).
- 같은 값으로 다시 불러도 200(마지막으로 본 시각만 갱신 · SSE 다시 냄). 푸시 없음.

""" + _SSE + _COMMON,
    responses=errors(INVALID, UNAUTHORIZED, ROOM_404),
)


@router.post("/rooms/{room_id}/read", response_model=ReadResponse, **_D_READ)
async def read(room_id: RoomId, body: ReadRequest, c: Ctr, actor: Actor) -> ReadResponse:
    return ReadResponse.model_validate(c.chat.read(actor, room_id, body.messageId))


_PHOTO_FORM = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["roomId", "photo", "width", "height"],
    "properties": {
        "roomId": {"type": "integer", "description": "보낼 방 id(내가 지금 멤버인 방). 정수 문자열"},
        "photo": {"type": "string", "format": "binary",
                  "description": "JPEG 파일(앞 바이트 `FF D8 FF` 로 확인) · 5MB(5 × 1024 × 1024 바이트) 이하"},
        "width": {"type": "integer", "description": "사진 가로(앱이 잰 값 · 서버는 범위를 보지 않고 그대로 저장). 정수 문자열"},
        "height": {"type": "integer", "description": "사진 세로(앱이 잰 값 · 서버는 범위를 보지 않고 그대로 저장). 정수 문자열"},
    }}}}}}


_D_UPLOAD_PHOTO: dict[str, Any] = dict(
    summary="채팅 사진 올리기",
    description="""보내기 전에 사진 파일을 올린다(`multipart/form-data`). 응답 `photoId` 를 보내기의 `photoId` 로 쓴다.

- 서버 폴더 `PROC_PHOTO_DIR/chat/` 에 무작위 이름으로 저장 + 첨부 행 1개. 이 단계에서는 메시지가 없다(SSE · 푸시 없음).
- 메시지에 붙기 전에는 **올린 사람만** 열 수 있다. 붙지 않은 사진을 지우는 처리는 없다.
- `Content-Length` 가 5MB + 64KB 를 넘으면 본문을 읽기 전에 413. 파일 1개 · 칸 10개까지.
- **멱등 아님** — 부를 때마다 새 사진 id.
- 검사 차례: 크기(Content-Length) → photo 칸 → 숫자 칸 → 실제 크기 → JPEG → 방 멤버 → 저장 폴더.""" + _COMMON,
    responses=errors(
        (400, "invalid_request", "photo 칸이 파일이 아니거나 없을 때 · roomId · width · height 가 정수가 아니거나 없을 때"),
        FORM_400, UNAUTHORIZED,
        (400, "chat_photo_type", "JPEG 가 아닐 때"),
        ROOM_404, PHOTO_OFF,
        (413, "photo_too_large", "Content-Length 가 5MB + 64KB 를 넘거나 · 사진이 5MB 를 넘을 때")),
)


@router.post("/photos", response_model=PhotoUploadResponse, openapi_extra=_PHOTO_FORM, **_D_UPLOAD_PHOTO)
async def upload_photo(request: Request, c: Ctr, actor: Actor) -> PhotoUploadResponse:
    """multipart — roomId · photo(JPEG ≤ 5MB) · width · height. Content-Length 로 먼저 거르고 메모리에서만 읽는다
    (멀티파트 spool 한도는 api/photos.py 전역 값 그대로 — 여기서 다시 바꾸지 않는다)."""
    size = request.headers.get("content-length")
    if size and size.isdigit() and int(size) > MAX_BYTES + FORM_OVERHEAD:
        raise PhotoTooLarge("photo_too_large", "사진이 5MB 를 넘어요")
    form = await request.form(max_files=1, max_fields=10)
    photo = form.get("photo")
    if not isinstance(photo, UploadFile):
        await form.close()
        raise BadRequest("invalid_request", "photo: 사진 파일이어야 해요")
    data = await photo.read(MAX_BYTES + 1)
    await form.close()
    room_id = _int(form.get("roomId"), "roomId")
    width, height = _int(form.get("width"), "width"), _int(form.get("height"), "height")
    return PhotoUploadResponse(photoId=c.chat.upload(actor, room_id, data, width, height))


_ATTACH_RULE = """- 열 수 있는 사람: 메시지에 붙기 전 = 올린 사람만 · 붙은 뒤 = 그 방 지금 멤버이고
  그 메시지가 내가 들어온 뒤 것일 때.
- 지운 첨부 · 종류가 다른 id · 파일이 디스크에 없음 = 404(없는 것처럼).
- `Authorization: Bearer` 헤더만(쿠키 · `?token=` 없음) · `Cache-Control: no-store` · `Content-Disposition: inline` · 열람
  로그 없음."""


_D_OPEN_PHOTO: dict[str, Any] = dict(
    summary="채팅 사진 열기",
    description="""채팅 사진 파일(JPEG 바이트)을 돌려준다.

""" + _ATTACH_RULE + "\n- 동영상 id 로 부르면 404 `chat_photo_not_found`." + _COMMON,
    responses={**binary("image/jpeg", "사진 JPEG 원본(올린 바이트 그대로)"),
               **errors(INVALID, UNAUTHORIZED,
                        (404, "chat_photo_not_found",
                         "사진이 없거나 · 지웠거나 · 동영상 id 이거나 · 열 권한이 없거나 · 파일이 없을 때"),
                        PHOTO_OFF)},
)


@router.get("/photos/{photo_id}", **_D_OPEN_PHOTO)
async def open_photo(photo_id: PhotoId, c: Ctr, actor: Actor) -> Response:
    """열기 — Bearer 헤더만(쿠키 · `?token=` 없음) · 캐시 안 함 · 열람 로그 없음(D9-23) · 앱은 메모리에만 둔다."""
    # 법적 검토 필요: 직원 채팅 — 고객 정보가 메시지 · 사진으로 오갈 수 있음(보존 기간 없음 · 열람 로그 없음 · 잠금 화면에 본문 앞부분)  # noqa: E501
    return Response(c.chat.photo(actor, photo_id), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})


_VIDEO_FORM = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["roomId", "video", "thumb", "width", "height", "durationMs"],
    "properties": {
        "roomId": {"type": "integer", "description": "보낼 방 id(내가 지금 멤버인 방). 정수 문자열"},
        "video": {"type": "string", "format": "binary",
                  "description": "MP4 파일(5 ~ 8번째 바이트(0부터 세면 4 ~ 7)가 `ftyp` 인지로 확인) · "
                                 "90MB(90 × 1024 × 1024 바이트) 이하"},
        "thumb": {"type": "string", "format": "binary",
                  "description": "앱이 만든 썸네일 JPEG(앞 바이트 `FF D8 FF`) · 5MB 이하"},
        "width": {"type": "integer",
                  "description": "동영상 가로(앱이 잰 값 · 서버는 범위를 보지 않고 그대로 저장). 정수 문자열"},
        "height": {"type": "integer",
                   "description": "동영상 세로(앱이 잰 값 · 서버는 범위를 보지 않고 그대로 저장). 정수 문자열"},
        "durationMs": {"type": "integer", "minimum": 1, "maximum": 180000,
                       "description": "길이(밀리초 · 앱이 잰 값). 1 ~ 180000(3분). 정수 문자열"},
    }}}}}}


_D_UPLOAD_VIDEO: dict[str, Any] = dict(
    summary="채팅 동영상 올리기",
    description="""보내기 전에 동영상 + 썸네일을 올린다(`multipart/form-data`). 응답 `videoId` 를 보내기의 `videoId` 로 쓴다.

- 서버 폴더 `PROC_PHOTO_DIR/chat/` 에 본 파일(.mp4) · 썸네일(.jpg)을 무작위 이름으로 저장 + 첨부 행 1개(사진과 같은 표 ·
  종류 = 동영상). 서버는 변환하지 않는다. SSE · 푸시 없음.
- 메시지에 붙기 전에는 **올린 사람만** 열 수 있다.
- `Content-Length` 가 90MB + 5MB + 64KB 를 넘으면 본문을 읽기 전에 413. 저장하며 90MB 를 넘으면 그 자리에서 멈추고 쓰던
  파일을 지운다. 파일 2개 · 칸 10개까지.
- **멱등 아님** — 부를 때마다 새 동영상 id.
- 검사 차례: 크기(Content-Length) → video · thumb 칸 → 숫자 칸 → 길이 → 썸네일 크기 · JPEG → MP4 → 방 멤버 → 저장 폴더 →
  저장 중 크기.""" + _COMMON,
    responses=errors(
        (400, "invalid_request", "video · thumb 칸이 파일이 아니거나 없을 때 · "
                                 "roomId · width · height · durationMs 가 정수가 아니거나 없을 때 · durationMs < 1 일 때"),
        FORM_400, UNAUTHORIZED,
        (400, "chat_video_too_long", "durationMs 가 180000(3분)을 넘을 때"),
        (400, "chat_photo_type", "thumb 가 JPEG 가 아닐 때"),
        (400, "chat_video_type", "video 가 MP4 가 아닐 때"),
        ROOM_404, PHOTO_OFF,
        (413, "chat_video_too_large", "Content-Length 가 90MB + 5MB + 64KB 를 넘거나 · 동영상이 90MB 를 넘을 때"),
        (413, "photo_too_large", "thumb 가 5MB 를 넘을 때")),
)


@router.post("/videos", response_model=VideoUploadResponse, openapi_extra=_VIDEO_FORM, **_D_UPLOAD_VIDEO)
async def upload_video(request: Request, c: Ctr, actor: Actor) -> VideoUploadResponse:

    """multipart(r3 · §9.2) — roomId · video(MP4 ≤ 90MB) · thumb(JPEG ≤ 5MB) · width · height · durationMs(1 ~ 180000).

    Content-Length 로 먼저 거른다(앱은 청크 없이 싣는다 · D-58). 전역 spool 한도(api/photos.py)는 그대로 — video 칸은 그보다
    커서 Starlette 임시 파일로 흐르고, 서비스가 그 파일을 조각 복사한다. 끝나면 form.close() 로 임시 파일을 지운다.
    """
    size = request.headers.get("content-length")
    if size and size.isdigit() and int(size) > VIDEO_MAX_BYTES + MAX_BYTES + FORM_OVERHEAD:
        raise PhotoTooLarge("chat_video_too_large", "동영상이 90MB 를 넘어요")
    form = await request.form(max_files=2, max_fields=10)
    try:
        video, thumb = form.get("video"), form.get("thumb")
        if not isinstance(video, UploadFile) or not isinstance(thumb, UploadFile):
            raise BadRequest("invalid_request", "video · thumb: 파일이어야 해요")
        room_id = _int(form.get("roomId"), "roomId")
        width, height = _int(form.get("width"), "width"), _int(form.get("height"), "height")
        duration_ms = _int(form.get("durationMs"), "durationMs")
        data = await thumb.read(MAX_BYTES + 1)
        video_id = c.chat.upload_video(actor, room_id, video.file, data, width, height, duration_ms)
    finally:
        await form.close()
    return VideoUploadResponse(videoId=video_id)


_D_OPEN_VIDEO: dict[str, Any] = dict(
    summary="채팅 동영상 열기(Range 지원)",
    description="""채팅 동영상 본 파일(MP4)을 돌려준다. 끊어 받기(`Range`)를 지원한다(Starlette `FileResponse`).

- `Range` 없음 = 200 전체. `Range: bytes=<시작>-<끝>` 하나 = 206 + `Content-Range`. 여러 구간 = 206 `multipart/byteranges`.
- 시작이 파일 크기 이상 = 416(본문 없음 · `Content-Range: bytes */<크기>`) — 아래 오류 JSON 모양이 아니다.
- `Range` 형식이 틀림(단위가 bytes 아님 · 시작 ≥ 끝 등) = 400 **text/plain**(오류 JSON 아님).
- 응답 헤더: `Accept-Ranges: bytes` · `ETag` · `Last-Modified` · `Content-Length`. `If-Range` 가 맞지 않으면 200 전체.
""" + _ATTACH_RULE + "\n- 사진 id 로 부르면 404 `chat_video_not_found`." + _COMMON,
    responses={**binary("video/mp4", "동영상 MP4 전체(올린 바이트 그대로)"),
               206: {"description": "`Range` 로 요청한 구간(`Content-Range` 헤더). 여러 구간이면 `multipart/byteranges`",
                     "content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}}},
               416: {"description": "요청 구간의 시작이 파일 크기 이상 — 본문 없음 · `Content-Range: bytes */<크기>`"},
               **errors(INVALID, UNAUTHORIZED,
                        (404, "chat_video_not_found",
                         "동영상이 없거나 · 지웠거나 · 사진 id 이거나 · 열 권한이 없거나 · 파일이 없을 때"),
                        PHOTO_OFF)},
)


@router.get("/videos/{video_id}", **_D_OPEN_VIDEO)
async def open_video(video_id: VideoId, c: Ctr, actor: Actor) -> FileResponse:
    """열기(r3) — Bearer 헤더만 · Range 끊어 받기(206 · 416 · Accept-Ranges = Starlette FileResponse) · 캐시 안 함 ·
    열람 로그 없음(D9-23 · D9-53) · 앱 재생기는 디스크에 남기지 않는다."""
    # 법적 검토 필요: 직원 채팅 — 고객 정보가 메시지 · 사진으로 오갈 수 있음(보존 기간 없음 · 열람 로그 없음 · 잠금 화면에 본문 앞부분)  # noqa: E501
    return FileResponse(c.chat.video_path(actor, video_id), media_type="video/mp4",
                        headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})


_D_OPEN_VIDEO_THUMB: dict[str, Any] = dict(
    summary="채팅 동영상 썸네일 열기",
    description="""동영상을 올릴 때 앱이 함께 올린 썸네일 JPEG 를 돌려준다(서버가 만들지 않음). 권한은 본 파일과 같다.

""" + _ATTACH_RULE + "\n- 사진 id 로 부르면 404 `chat_video_not_found`." + _COMMON,
    responses={**binary("image/jpeg", "썸네일 JPEG(올린 바이트 그대로)"),
               **errors(INVALID, UNAUTHORIZED,
                        (404, "chat_video_not_found",
                         "동영상이 없거나 · 지웠거나 · 사진 id 이거나 · 열 권한이 없거나 · 썸네일 파일이 없을 때"),
                        PHOTO_OFF)},
)


@router.get("/videos/{video_id}/thumbnail", **_D_OPEN_VIDEO_THUMB)
async def open_video_thumb(video_id: VideoId, c: Ctr, actor: Actor) -> Response:
    """썸네일(r3) — 앱이 만들어 올린 JPEG · 본 파일과 같은 권한."""
    return Response(c.chat.video_thumb(actor, video_id), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})
