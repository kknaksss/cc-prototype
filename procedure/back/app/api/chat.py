"""직원 채팅 API 18(SPEC-007 §6.2 · 1판 14 + r3 4) — Bearer · 다섯 역할 모두 · 가짜 판에서도 됨(require_real_board 안 씀).

경로는 모두 `async def` — SSE(`send_to_account` 의 `asyncio.Queue`) · 푸시(`PushService._dispatch` 의 이벤트 루프)가
루프 스레드에서 돌아야 한다. 동기 `def` 면 스레드풀에서 돌아 푸시가 「이벤트 루프 없음」으로 0 이 된다(§6.1).
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.datastructures import UploadFile

from app.api.deps import Actor, Ctr
from app.api.photos import FORM_OVERHEAD
from app.domain.errors import BadRequest
from app.schemas.actions import OkResponse
from app.schemas.chat import (
    DirectRequest,
    EditRequest,
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
from app.service.chat import PAGE, VIDEO_MAX_BYTES
from app.service.id_photo import MAX_BYTES
from app.service.passport_scan import PhotoTooLarge

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _int(v: object, name: str) -> int:
    try:
        return int(str(v))
    except ValueError:
        raise BadRequest("invalid_request", f"{name}: 정수여야 해요") from None


@router.get("/people", response_model=PeopleList)
async def people(c: Ctr, actor: Actor) -> PeopleList:
    return PeopleList.model_validate({"items": c.chat.people(actor)})


@router.get("/rooms", response_model=RoomList)
async def rooms(c: Ctr, actor: Actor) -> RoomList:
    return RoomList.model_validate(c.chat.rooms(actor))


@router.post("/rooms/direct", response_model=Room)
async def open_direct(body: DirectRequest, c: Ctr, actor: Actor) -> Room:
    return Room.model_validate(c.chat.open_direct(actor, body.accountId))


@router.post("/rooms", response_model=Room)
async def create_group(body: GroupRequest, c: Ctr, actor: Actor) -> Room:
    return Room.model_validate(c.chat.create_group(actor, body.accountIds, body.title))


@router.post("/rooms/{room_id}/members", response_model=Room)
async def add_members(room_id: int, body: MembersRequest, c: Ctr, actor: Actor) -> Room:
    return Room.model_validate(c.chat.add_members(actor, room_id, body.accountIds))


@router.post("/rooms/{room_id}/leave", response_model=OkResponse)
async def leave(room_id: int, c: Ctr, actor: Actor) -> OkResponse:
    c.chat.leave(actor, room_id)
    return OkResponse()


@router.post("/rooms/{room_id}/hide", response_model=OkResponse)
async def hide(room_id: int, c: Ctr, actor: Actor) -> OkResponse:
    c.chat.hide(actor, room_id)
    return OkResponse()


@router.put("/rooms/{room_id}/mute", response_model=MuteResponse)
async def mute(room_id: int, body: MuteRequest, c: Ctr, actor: Actor) -> MuteResponse:
    return MuteResponse(muted=c.chat.mute(actor, room_id, body.muted))


@router.get("/rooms/{room_id}/messages", response_model=MessageList)
async def messages(room_id: int, c: Ctr, actor: Actor, before: int | None = None, since: str | None = None,
                   limit: int = Query(PAGE, ge=1, le=PAGE)) -> MessageList:
    """오래된 것 위. `since` 는 clock.parse 로 읽어 UTC 밀리초로 바꿔 `updated_at >= since`(경계 포함 · 앱이 id 로 겹침 지움)."""
    return MessageList.model_validate(c.chat.messages(actor, room_id, before, since, limit))


@router.post("/rooms/{room_id}/messages", response_model=Message)
async def post_message(room_id: int, body: SendRequest, c: Ctr, actor: Actor) -> Message:
    return Message.model_validate(c.chat.post(actor, room_id, body.clientId, body.text, body.photoId, body.videoId))


@router.patch("/messages/{message_id}", response_model=Message)
async def edit_message(message_id: int, body: EditRequest, c: Ctr, actor: Actor) -> Message:
    """수정(r3) — 내 글만 · SSE chat_message_edited · 푸시 없음 · 응답 Message 의 updatedAt 은 서버 값(앱이 since 에 써도 됨)."""
    return Message.model_validate(c.chat.edit(actor, message_id, body.text))


@router.delete("/messages/{message_id}", response_model=OkResponse)
async def delete_message(message_id: int, c: Ctr, actor: Actor) -> OkResponse:
    c.chat.delete(actor, message_id)
    return OkResponse()


@router.post("/rooms/{room_id}/read", response_model=ReadResponse)
async def read(room_id: int, body: ReadRequest, c: Ctr, actor: Actor) -> ReadResponse:
    return ReadResponse.model_validate(c.chat.read(actor, room_id, body.messageId))


@router.post("/photos", response_model=PhotoUploadResponse)
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


@router.get("/photos/{photo_id}")
async def open_photo(photo_id: int, c: Ctr, actor: Actor) -> Response:
    """열기 — Bearer 헤더만(쿠키 · `?token=` 없음) · 캐시 안 함 · 열람 로그 없음(D9-23) · 앱은 메모리에만 둔다."""
    # 법적 검토 필요: 직원 채팅 — 고객 정보가 메시지 · 사진으로 오갈 수 있음(보존 기간 없음 · 열람 로그 없음 · 잠금 화면에 본문 앞부분)  # noqa: E501
    return Response(c.chat.photo(actor, photo_id), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})


@router.post("/videos", response_model=VideoUploadResponse)
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


@router.get("/videos/{video_id}")
async def open_video(video_id: int, c: Ctr, actor: Actor) -> FileResponse:
    """열기(r3) — Bearer 헤더만 · Range 끊어 받기(206 · 416 · Accept-Ranges = Starlette FileResponse) · 캐시 안 함 ·
    열람 로그 없음(D9-23 · D9-53) · 앱 재생기는 디스크에 남기지 않는다."""
    # 법적 검토 필요: 직원 채팅 — 고객 정보가 메시지 · 사진으로 오갈 수 있음(보존 기간 없음 · 열람 로그 없음 · 잠금 화면에 본문 앞부분)  # noqa: E501
    return FileResponse(c.chat.video_path(actor, video_id), media_type="video/mp4",
                        headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})


@router.get("/videos/{video_id}/thumbnail")
async def open_video_thumb(video_id: int, c: Ctr, actor: Actor) -> Response:
    """썸네일(r3) — 앱이 만들어 올린 JPEG · 본 파일과 같은 권한."""
    return Response(c.chat.video_thumb(actor, video_id), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})
