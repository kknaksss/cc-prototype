"""직원 채팅 계약(SPEC-007 §6.1 · §6.2) — JSON 키 camelCase · 시각 = KST 오프셋 · 밀리초(clock.iso_ms)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from app.schemas.actions import Role

# 설명 문구에 되풀이해 쓰는 조각
_TS = "ISO-8601 · 밀리초 · KST 오프셋(예: `2026-01-02T09:30:15.123+09:00`)"
_ROLE = "계정 역할 — `admin` · `doctor` · `nurse` · `coordinator` · `counselor`"
_KIND = ("메시지 종류 — `text` = 글 · `photo` = 사진 1장 · `video` = 동영상 1개 · "
         "`system` = 시스템 줄(그룹 만들기 · 초대 · 나가기 때 서버가 쓰는 안내 줄)")
_CLIENT_ID = ("앱이 만든 메시지 고유 문자열(8 ~ 64자). 같은 계정 · 같은 clientId 로 다시 보내면 새로 만들지 않고 "
              "처음 만든 메시지를 그대로 돌려준다(SSE · 푸시 다시 없음). 계정 하나에서 모든 방을 통틀어 하나여야 한다 — "
              "다른 방에 같은 값을 쓰면 처음 방의 메시지가 돌아온다")


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ 모양(§6.1)
class Person(BaseModel):
    """대화 상대 후보 한 명."""

    id: int = Field(description="계정 id")
    name: str = Field(description="계정 이름")
    role: Role = Field(description=_ROLE)


class Member(BaseModel):
    """방의 지금 멤버 한 명(나간 사람은 없다)."""

    id: int = Field(description="계정 id")
    name: str = Field(description="계정 이름")
    role: Role = Field(description=_ROLE)
    active: bool = Field(description="계정이 활성이면 true. false = 비활성 계정(1:1 이면 새 메시지를 보낼 수 없다)")
    me: bool = Field(description="이 Room 을 받는 계정(요청한 사람) 본인이면 true")


class Preview(BaseModel):
    """방 목록의 마지막 메시지 미리보기."""

    id: int = Field(description="메시지 id")
    senderId: int = Field(description="보낸 계정 id. 시스템 줄이면 그 줄을 생기게 한 계정(만든 · 초대한 · 나간 사람)")
    senderName: str = Field(description="보낸 계정의 지금 이름. 계정을 찾을 수 없으면 빈 문자열")
    mine: bool = Field(description="요청한 계정이 보낸 메시지(시스템 줄 포함)면 true")
    kind: Literal["text", "photo", "video", "system"] = Field(description=_KIND)
    text: str | None = Field(  # 앞 100자 · 사진 · 동영상 · 지운 것 = null
        description="본문 앞 100자(코드 포인트 · 자른 표시 없음). 시스템 줄은 그 안내 문구. "
                    "null = 사진 · 동영상 · 지운 메시지")
    deleted: bool = Field(description="지운 메시지면 true(그때 text 는 null)")
    createdAt: str = Field(description=f"메시지를 만든 시각 — {_TS}")


class Room(BaseModel):
    """보는 계정마다 다르다(name · muted · unread · members[].me)."""

    id: int = Field(description="방 id")
    kind: Literal["direct", "group"] = Field(description="`direct` = 1:1(같은 두 사람 = 방 하나) · `group` = 그룹")
    title: str | None = Field(description="그룹 이름(만들 때 앞뒤 공백을 뺀 값). null = 1:1 이거나 이름 없이 만든 그룹")
    name: str = Field(
        description="화면에 보일 방 이름(보는 계정 기준) — 1:1 = 상대 이름(상대가 비활성이면 뒤에 ` (비활성)`) · "
                    "이름 있는 그룹 = title · 이름 없는 그룹 = 나를 뺀 지금 멤버 이름을 "
                    "코드포인트 순(라틴 < 한글 · 대문자 < 소문자)으로 `, ` 로 이은 것")
    members: list[Member] = Field(description="지금 멤버(나간 사람 없음). 차례 = 나 맨 위 · "
                                               "나머지는 이름 코드포인트 순(라틴 < 한글 · 대문자 < 소문자)")
    memberCount: int = Field(description="members 의 수(나 포함)")
    muted: bool = Field(description="보는 계정이 이 방 알림을 껐으면 true(그 방 푸시를 받지 않는다)")
    unread: int = Field(
        description="안 읽은 메시지 수 — 남이 보낸 · 시스템 줄이 아닌 · 지우지 않은 메시지 중 id 가 내 읽은 데까지"
                    "(lastReadMessageId)보다 큰 것")
    lastMessage: Preview | None = Field(
        description="방의 마지막 메시지(시스템 줄 · 지운 것 포함) 미리보기. null = 메시지가 없거나, 마지막 메시지가 내가 "
                    "들어오기 전 것(들어온 뒤 대화만 보인다)")
    lastMessageAt: str | None = Field(
        description=f"방에 마지막으로 새 메시지(시스템 줄 포함)가 생긴 시각 — {_TS}. 수정 · 삭제로는 바뀌지 않는다. "
                    "null = 메시지가 한 번도 없음")
    createdAt: str = Field(description=f"방을 만든 시각 — {_TS}")


class Sender(BaseModel):
    """메시지를 보낸 계정."""

    id: int = Field(description="계정 id. 시스템 줄이면 그 줄을 생기게 한 계정")
    name: str = Field(description="계정의 지금 이름. 계정을 찾을 수 없으면 빈 문자열")
    role: Role = Field(description=f"{_ROLE}. 계정을 찾을 수 없으면 `admin`")
    active: bool = Field(description="계정이 활성이면 true. 계정을 찾을 수 없으면 false")


class PhotoRef(BaseModel):
    """메시지에 붙은 사진 — 파일은 `GET /api/chat/photos/{id}`."""

    id: int = Field(description="사진 id(`GET /api/chat/photos/{id}` 로 연다)")
    width: int | None = Field(description="올릴 때 앱이 보낸 가로(서버는 검사하지 않음). 첨부 행을 찾지 못하면 null")
    height: int | None = Field(description="올릴 때 앱이 보낸 세로(서버는 검사하지 않음). 첨부 행을 찾지 못하면 null")


class VideoRef(BaseModel):
    """썸네일 = GET videos/{id}/thumbnail · 본 파일 = GET videos/{id}(r3)."""

    id: int = Field(description="동영상 id(`GET /api/chat/videos/{id}` · `/thumbnail` 로 연다)")
    width: int | None = Field(description="올릴 때 앱이 보낸 가로(서버는 검사하지 않음). 첨부 행을 찾지 못하면 null")
    height: int | None = Field(description="올릴 때 앱이 보낸 세로(서버는 검사하지 않음). 첨부 행을 찾지 못하면 null")
    durationMs: int | None = Field(description="길이(밀리초 · 앱이 잰 값 · 1 ~ 180000). 첨부 행을 찾지 못하면 null")


class Message(BaseModel):
    """메시지 한 개."""

    id: int = Field(description="메시지 id(방 안 시간 순서 = id 순서)")
    roomId: int = Field(description="메시지가 있는 방 id")
    clientId: str | None = Field(description=f"{_CLIENT_ID}. null = 시스템 줄")
    sender: Sender = Field(description="보낸 계정")
    kind: Literal["text", "photo", "video", "system"] = Field(description=_KIND)
    text: str | None = Field(description="본문(text · system). null = 사진 · 동영상 · 지운 메시지")
    photo: PhotoRef | None = Field(description="kind = `photo` 이고 지우지 않았을 때만. 그 밖에는 null")
    video: VideoRef | None = Field(description="kind = `video` 이고 지우지 않았을 때만. 그 밖에는 null")
    createdAt: str = Field(description=f"만든 시각 — {_TS}")
    updatedAt: str = Field(
        description=f"마지막으로 바뀐 시각(만들 때 = createdAt · 수정 · 삭제 때 갱신) — {_TS}. "
                    "메시지 목록의 `since` 에 넣어 바뀐 것만 받을 수 있다")
    editedAt: str | None = Field(description=f"마지막으로 고친 시각 — {_TS}. null = 고친 적 없음")
    deletedAt: str | None = Field(description=f"지운 시각 — {_TS}. null = 안 지움")


# ------------------------------------------------------------------ 경로(§6.2)
class PeopleList(BaseModel):
    """대화 상대 후보 목록."""

    items: list[Person] = Field(description="활성 · 로그인 가능(비밀번호 있음) 계정 중 나를 뺀 것. "
                                             "차례 = 이름 코드포인트 순(라틴 < 한글 · 대문자 < 소문자) · 같으면 id 순")


class RoomList(BaseModel):
    """내 방 목록."""

    items: list[Room] = Field(
        description="내가 지금 멤버인 방 중 숨기지 않았거나 숨긴 뒤 새 메시지가 온 방. "
                    "차례 = 마지막 메시지 시각(없으면 만든 시각) 최근 것 먼저 · 같으면 id 큰 것 먼저")
    unreadRooms: int = Field(description="items 중 unread > 0 인 방 수(알림 끈 방도 센다)")


class DirectRequest(_Req):
    """1:1 열기 요청."""

    accountId: StrictInt = Field(
        description="상대 계정 id(정수만 · 문자열 안 됨). 나 자신 · 비활성 · 로그인 불가 계정 = chat_person_invalid")


class GroupRequest(_Req):
    """그룹 만들기 요청."""

    accountIds: list[StrictInt] = Field(
        description="나를 뺀 다른 멤버 계정 id 2 ~ 19개(나 포함 3 ~ 20명 · 정수만). 중복 · 나 자신 안 됨. "
                    "차례 = 초대 시스템 줄 이름 차례")
    title: str | None = Field(None,  # 40자 넘음 = invalid_request(서비스가 앞뒤 공백을 뺀 뒤 센다)
                              description="그룹 이름(앞뒤 공백을 뺀 뒤 40자까지). null · 빈 문자열 · 공백만 = 이름 없는 그룹")


class MembersRequest(_Req):
    """초대(참여자 추가) 요청."""

    accountIds: list[StrictInt] = Field(
        min_length=1,
        description="더할 계정 id(1개 이상 · 중복 안 됨 · 지금 멤버 안 됨 · 활성 · 로그인 가능). "
                    "나간 사람도 다시 초대할 수 있다. 차례 = 초대 시스템 줄 이름 차례")


class MuteRequest(_Req):
    """방 알림 끄기 · 켜기 요청."""

    muted: StrictBool = Field(description="true = 이 방 알림 끄기(푸시 안 받음) · false = 켜기. JSON true/false 만")


class MuteResponse(BaseModel):
    """알림 설정 결과."""

    ok: Literal[True] = Field(True, description="늘 true")
    muted: bool = Field(description="저장된 값(요청한 muted 그대로)")


class MessageList(BaseModel):
    """메시지 한 쪽."""

    items: list[Message] = Field(
        description="메시지. 차례는 경로마다 다르다 — 메시지 목록 = 오래된 것 위(id 오름차순) · "
                    "모아보기 = 최근 것 위(id 내림차순)")
    hasMore: bool = Field(
        description="같은 조건으로 더 오래된(id 가 더 작은) 것이 남아 있으면 true. 내가 들어오기 전 메시지는 세지 않는다")


class SendRequest(_Req):
    """text · photoId · videoId 중 하나 — 둘 이상 · 아무것도 없음 · 길이는 서비스가 본다(2000 코드 포인트 · §5)."""

    clientId: str = Field(min_length=8, max_length=64, description=_CLIENT_ID)
    text: str | None = Field(
        None, description="글(1 ~ 2000 코드 포인트 · 앞뒤 공백만 = chat_message_empty). photoId · videoId 와 함께 못 씀")
    photoId: StrictInt | None = Field(
        None, description="`POST /api/chat/photos` 로 내가 이 방에 올린 · 아직 메시지에 안 붙은 사진 id. "
                          "text · videoId 와 함께 못 씀")
    videoId: StrictInt | None = Field(
        None, description="`POST /api/chat/videos` 로 내가 이 방에 올린 · 아직 메시지에 안 붙은 동영상 id. "
                          "text · photoId 와 함께 못 씀")


class EditRequest(_Req):
    """수정(r3 · §6.2 #15) — 길이 · 공백은 서비스가 본다(chat_message_too_long · chat_message_empty)."""

    text: str = Field(description="새 글(1 ~ 2000 코드 포인트 · 공백만 = chat_message_empty · 넘음 = chat_message_too_long)")


class ReadRequest(_Req):
    """읽음 요청."""

    messageId: StrictInt = Field(
        ge=0, description="여기까지 읽었다는 메시지 id(0 이상). 0 = 아무것도 바꾸지 않음(빈 방). "
                          "방 마지막 id 보다 크면 마지막 id 로 줄인다")


class ReadResponse(BaseModel):
    """읽음 결과."""

    ok: Literal[True] = Field(True, description="늘 true")
    lastViewedAt: str | None = Field(
        description=f"이 방을 마지막으로 본 시각 — {_TS}. messageId > 0 이면 지금 시각으로 바뀐다. null = 값 없음")
    lastReadMessageId: int = Field(description="읽은 데까지의 메시지 id(줄어들지 않는다)")
    unreadRooms: int = Field(description="내 방 목록에 든 방 중 안 읽은 메시지가 있는 방 수(알림 끈 방도 센다)")


class PhotoUploadResponse(BaseModel):
    """사진 올리기 결과."""

    photoId: int = Field(description="올린 사진 id — 보내기(`POST /api/chat/rooms/{room_id}/messages`)의 photoId 로 쓴다")


class VideoUploadResponse(BaseModel):
    """동영상 올리기 결과."""

    videoId: int = Field(description="올린 동영상 id — 보내기(`POST /api/chat/rooms/{room_id}/messages`)의 videoId 로 쓴다")


# ------------------------------------------------------------------ 전달(r4 · §6.2 #19)
class ForwardTarget(_Req):
    """방(roomId) 또는 사람(accountId) 중 하나 + 대상마다 clientId(보내기와 같은 규칙 · D9-16)."""

    roomId: StrictInt | None = Field(None, description="보낼 방 id(내가 지금 멤버인 방). accountId 와 둘 중 하나만")
    accountId: StrictInt | None = Field(
        None, description="보낼 사람 계정 id — 그 사람과의 1:1 을 열거나 만든다(내가 숨겼으면 다시 보임). roomId 와 둘 중 하나만")
    clientId: str = Field(min_length=8, max_length=64, description=f"이 대상에 만들 메시지의 clientId — {_CLIENT_ID}")

    @model_validator(mode="after")
    def _one(self) -> "ForwardTarget":
        if (self.roomId is None) == (self.accountId is None):
            raise ValueError("roomId · accountId 중 하나만 보내요")
        return self


class ForwardRequest(_Req):
    """대상 1 ~ 10 · 중복은 서비스가 본다(invalid_request)."""

    targets: list[ForwardTarget] = Field(
        description="전달할 곳 1 ~ 10개. 같은 roomId · 같은 accountId · 같은 clientId 가 두 번 있으면 invalid_request")


class ErrorBody(BaseModel):
    """전달 대상 하나의 실패 이유."""

    code: str = Field(
        description="오류 코드 — `chat_person_invalid`(대화할 수 없는 사람) · `chat_room_not_found`(멤버가 아닌 방) · "
                    "`chat_peer_inactive`(상대가 비활성인 1:1)")
    message: str = Field(description="사람이 읽는 한국어 문구(분기에 쓰지 않는다)")


class ForwardOk(BaseModel):
    """전달 성공 한 건."""

    ok: Literal[True] = Field(True, description="true = 이 대상에 보냄")
    roomId: int = Field(description="메시지가 들어간 방 id(accountId 대상이면 열거나 만든 1:1 방)")
    message: Message = Field(
        description="만든 메시지(보낸 사람 = 나 · 「전달됨」 표시 없음). 같은 clientId 로 다시 보냈으면 처음 만든 것. "
                    "한 요청에서 같은 방이 두 번 되면 앞 대상이 성공했을 때만 그 결과를 그대로 다시 싣는다"
                    "(앞이 실패면 다시 처리)")


class ForwardFail(BaseModel):
    """전달 실패 한 건."""

    ok: Literal[False] = Field(False, description="false = 이 대상에 못 보냄")
    roomId: int | None = Field(
        description="대상 방 id — roomId 대상이면 요청한 값 · accountId 대상이면 1:1 을 연 뒤 실패했을 때 그 방 id · "
                    "1:1 을 열기 전에 실패했으면 null")
    error: ErrorBody = Field(description="실패 이유")


class ForwardResponse(BaseModel):
    """전달 결과."""

    results: list[ForwardOk | ForwardFail] = Field(  # 요청 대상 차례 그대로
        description="대상마다 결과 하나 — 요청 targets 차례 그대로. 대상별 실패는 여기에만 싣고 응답은 200(전부 실패여도)")
