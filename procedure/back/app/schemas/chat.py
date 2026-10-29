"""직원 채팅 계약(SPEC-007 §6.1 · §6.2) — JSON 키 camelCase · 시각 = KST 오프셋 · 밀리초(clock.iso_ms)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from app.schemas.actions import Role


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ 모양(§6.1)
class Person(BaseModel):
    id: int
    name: str
    role: Role


class Member(BaseModel):
    id: int
    name: str
    role: Role
    active: bool
    me: bool


class Preview(BaseModel):
    id: int
    senderId: int
    senderName: str
    mine: bool
    kind: Literal["text", "photo", "video", "system"]
    text: str | None  # 앞 100자 · 사진 · 동영상 · 지운 것 = null
    deleted: bool
    createdAt: str


class Room(BaseModel):
    """보는 계정마다 다르다(name · muted · unread · members[].me)."""

    id: int
    kind: Literal["direct", "group"]
    title: str | None
    name: str
    members: list[Member]
    memberCount: int
    muted: bool
    unread: int
    lastMessage: Preview | None
    lastMessageAt: str | None
    createdAt: str


class Sender(BaseModel):
    id: int
    name: str
    role: Role
    active: bool


class PhotoRef(BaseModel):
    id: int
    width: int | None
    height: int | None


class VideoRef(BaseModel):
    """썸네일 = GET videos/{id}/thumbnail · 본 파일 = GET videos/{id}(r3)."""

    id: int
    width: int | None
    height: int | None
    durationMs: int | None


class Message(BaseModel):
    id: int
    roomId: int
    clientId: str | None
    sender: Sender
    kind: Literal["text", "photo", "video", "system"]
    text: str | None
    photo: PhotoRef | None
    video: VideoRef | None
    createdAt: str
    updatedAt: str
    editedAt: str | None
    deletedAt: str | None


# ------------------------------------------------------------------ 경로(§6.2)
class PeopleList(BaseModel):
    items: list[Person]


class RoomList(BaseModel):
    items: list[Room]
    unreadRooms: int


class DirectRequest(_Req):
    accountId: StrictInt


class GroupRequest(_Req):
    accountIds: list[StrictInt]
    title: str | None = None  # 40자 넘음 = invalid_request(서비스가 앞뒤 공백을 뺀 뒤 센다)


class MembersRequest(_Req):
    accountIds: list[StrictInt] = Field(min_length=1)


class MuteRequest(_Req):
    muted: StrictBool


class MuteResponse(BaseModel):
    ok: Literal[True] = True
    muted: bool


class MessageList(BaseModel):
    items: list[Message]
    hasMore: bool


class SendRequest(_Req):
    """text · photoId · videoId 중 하나 — 둘 이상 · 아무것도 없음 · 길이는 서비스가 본다(2000 코드 포인트 · §5)."""

    clientId: str = Field(min_length=8, max_length=64)
    text: str | None = None
    photoId: StrictInt | None = None
    videoId: StrictInt | None = None


class EditRequest(_Req):
    """수정(r3 · §6.2 #15) — 길이 · 공백은 서비스가 본다(chat_message_too_long · chat_message_empty)."""

    text: str


class ReadRequest(_Req):
    messageId: StrictInt = Field(ge=0)


class ReadResponse(BaseModel):
    ok: Literal[True] = True
    lastViewedAt: str | None
    lastReadMessageId: int
    unreadRooms: int


class PhotoUploadResponse(BaseModel):
    photoId: int


class VideoUploadResponse(BaseModel):
    videoId: int


# ------------------------------------------------------------------ 전달(r4 · §6.2 #19)
class ForwardTarget(_Req):
    """방(roomId) 또는 사람(accountId) 중 하나 + 대상마다 clientId(보내기와 같은 규칙 · D9-16)."""

    roomId: StrictInt | None = None
    accountId: StrictInt | None = None
    clientId: str = Field(min_length=8, max_length=64)

    @model_validator(mode="after")
    def _one(self) -> "ForwardTarget":
        if (self.roomId is None) == (self.accountId is None):
            raise ValueError("roomId · accountId 중 하나만 보내요")
        return self


class ForwardRequest(_Req):
    """대상 1 ~ 10 · 중복은 서비스가 본다(invalid_request)."""

    targets: list[ForwardTarget]


class ErrorBody(BaseModel):
    code: str
    message: str


class ForwardOk(BaseModel):
    ok: Literal[True] = True
    roomId: int
    message: Message


class ForwardFail(BaseModel):
    ok: Literal[False] = False
    roomId: int | None
    error: ErrorBody


class ForwardResponse(BaseModel):
    results: list[ForwardOk | ForwardFail]  # 요청 대상 차례 그대로
