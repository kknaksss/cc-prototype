from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import Actor, Ctr, require_real_board
from app.api.docs import FAKE_BOARD, INVALID, T_BOARD, UNAUTHORIZED, errors
from app.schemas.actions import BoardOrderRequest, BoardOrderResponse
from app.schemas.board import BoardSnapshot

router = APIRouter(prefix="/api/board", tags=[T_BOARD])

STREAM_DESCRIPTION = """
현황판 실시간 스트림(Server-Sent Events · `text/event-stream`). 브라우저 `EventSource` 가 헤더를 못 싣기 때문에
**인증은 `Authorization` 헤더가 아니라 쿼리 `?token=<로그인 토큰>`** 이다. 토큰이 없거나 틀리거나 만료 · 비활성 · 역할이
바뀌었으면 연결 전에 `401 unauthorized`(JSON). 다섯 역할 모두 연결할 수 있다.

응답 헤더: `Cache-Control: no-cache` · `X-Accel-Buffering: no` · `Connection: keep-alive`.
연결 목록은 서버 메모리(프로세스 1개)다.

### `deviceId`(선택 · 앱)
`POST /api/devices` 로 받은 자기 기기 id 를 붙이면 그 기기의 `lastSeenAt` 을 지금으로 고치고, 이 연결이 그 기기의
`online` 연결이 되며 `display` 이벤트를 받는다. 남의 계정 기기 · 없는 id 는 오류 없이 무시한다(기기 없는 연결로 취급).

### 프레임
1. **연결 직후 첫 프레임** — 재연결 간격 + 지금 전체 스냅샷:
   ```
   retry: 3000
   event: board
   id: <version>
   data: <BoardEvent JSON>

   ```
2. **`event: board`** — 모든 연결에. `id:` 줄 = `version`. `data` = 전체 스냅샷(`GET /api/board` 와 같은 모양) + `version`
   (발행할 때마다 1 씩 는다 · 서버 메모리 · 재시작하면 0 부터). 늘 **전체**를 보내므로 클라이언트는 받은 것으로 갈아 끼운다.
   발행 때: ccc 조작(마취 · 호출 · 수락 · 시작 · 종료 · 되돌리기 · 귀가 대기 · 카드 순서) 직후 ·
   KOS 조회 · 반영으로 상태가 바뀐 뒤 ·
   폴백 — 마지막 발행 뒤 env `KOS_POLL_SCHEDULE_SEC`(기본 10초) 동안 발행이 없었으면 한 번(1초마다 확인 · 경과 시간 ·
   「확인이 필요」 갱신. 다른 발행이 잦으면 이 발행은 없다) · 날짜가 바뀌어 전날 카드를 내릴 때.
3. **`event: notification`** — 그 계정의 연결에만 · `id:` 줄 없음 · version 안 올림.
   `data: {"unread": <int>}` = 오늘(KST) 안 읽은 알림 수. 그 계정에 새 알림 행(원장 호출 `doctor_call` · 상담사 호출
   `counselor_call`)이 생긴 뒤 보낸다.
4. **`event: display`** — 그 `deviceId` 로 연 연결에만(같은 계정 다른 기기 · 웹 연결은 안 받음) · `id:` 줄 없음.
   `data: {"requestId": <int>, "deviceId": <int>, "kind": "questionnaire"|"scan", "reservationId": <int>, "qrUrl"?: <str>}` —
   `POST /api/display-requests` 로 이 기기에 띄우기를 보냈을 때. `qrUrl` 은 문진 종류에만 있다(고객 문진 웹 링크).
   푸시도 같이 가므로 앱은 `requestId` 로 한 번만 연다.
5. **채팅 이벤트** — 그 계정의 연결에만 · `id:` 줄 없음: `chat_room` · `chat_message` · `chat_message_edited` ·
   `chat_message_deleted` · `chat_read` · `chat_room_removed`. 본문은 「채팅」 태그 문서 참고.
6. **`: ping`** — 15초 동안 보낼 것이 없으면 주석 줄 `: ping` 을 보낸다(연결 유지 · 무시하면 된다).

`event: notification` · `display` · 채팅 이벤트의 `data` 는 JSON 한 줄(한글 그대로 · `ensure_ascii` 없음).
가짜 스냅샷 모드(env `PROC_FAKE_BOARD`)면 `board` 본문은 지어낸 스냅샷이다.
"""


@router.get(
    "", response_model=BoardSnapshot,
    summary="현황판 스냅샷 — 오늘 카드 · 호출 · 원장 전체",
    description="""
오늘(KST) 시술 현황판 전체 스냅샷. 화면은 이 값만으로 그린다(버튼 켜짐 `can*` · 「확인이 필요」 등 규칙 계산은 서버가 한다).
SSE `board` 이벤트 본문과 같은 모양이다(`version` 만 없음).

- 다섯 역할 모두 부를 수 있다. 읽기만 한다(DB · KOS 쓰기 없음).
- 카드 = 오늘 KOS 일정 중 단계가 시술 대기 · 시술 진행 · 귀가 대기이고 방이 있는 것. `cards` 배열 순서가 화면 순서다.
- KOS 를 직접 부르지 않는다 — 서버 사본(KOS 조회 루프가 채움)으로 만든다. 사본이 언제 맞았는지는 `sync` 참고.
- 가짜 스냅샷 모드(env `PROC_FAKE_BOARD`)면 지어낸 스냅샷을 준다.
""",
    responses=errors(UNAUTHORIZED),
)
def board(c: Ctr, _: Actor) -> BoardSnapshot:
    return c.snapshot()


@router.put(
    "/order", response_model=BoardOrderResponse, dependencies=[Depends(require_real_board)],
    summary="카드 순서 저장 — 드래그한 화면 순서",
    description="""
오늘(KST) 카드 순서를 **통째로** 바꾼다(앞 순서를 덮어씀). 귀가 대기 카드는 순서에 넣지 않는다(늘 맨 뒤 · 귀가 대기 시각 순).

- 다섯 역할 모두(역할 검사 없음).
- 같은 id 두 번 = `400 invalid_request`. 지금 카드가 아닌 id(없는 visit · 사라진 카드 · 다른 날 · 귀가 대기)는 오류 없이 뺀다 —
  응답 `visitIds` = 실제로 저장된 목록. 빈 배열 = 오늘 순서 지움(입실 순으로 돌아감).
- 순서에 없는 카드는 순서 있는 카드 뒤에 입실 순으로 선다.
- 부작용: ccc DB 에 그날 순서 저장 · event_log(`board_order`) 1줄 · 응답 뒤 SSE `board` 1번(모든 연결). KOS 쓰기 없음 · 푸시 없음.
- 같은 요청을 다시 보내도 결과는 같다(멱등) — 다만 event_log 와 SSE `board` 는 매번 생긴다.
""",
    responses=errors(INVALID, UNAUTHORIZED, FAKE_BOARD),
)
async def board_order(body: BoardOrderRequest, c: Ctr, actor: Actor) -> BoardOrderResponse:
    """카드 드래그 순서 저장(SPEC-003 0.4.0 §7.3) — 세 역할 모두 · 응답 뒤 SSE `board` 1개(§7.5 ①)."""
    return BoardOrderResponse(visitIds=c.actions.board_order(actor.login_id, body.visitIds))


@router.get(
    "/stream",
    summary="현황판 SSE 스트림 — board · notification · display · 채팅 이벤트",
    description=STREAM_DESCRIPTION,
    responses={
        200: {"description": "SSE 스트림(끊길 때까지 이어짐) — 형식은 위 설명",
              "content": {"text/event-stream": {"schema": {"type": "string"}}}},
        **errors(INVALID, (401, "unauthorized", "`?token=` 이 없거나 · 서명이 틀리거나 · 만료됐거나 · 계정이 비활성이거나 · "
                                                "역할 · staffId 가 토큰 발급 뒤 바뀌었을 때")),
    },
)
async def stream(
    c: Ctr,
    token: str | None = Query(None, description="로그인 토큰(`POST /api/auth/login` 의 token). 헤더 대신 여기에 싣는다"),
    deviceId: int | None = Query(None, description=(  # noqa: N803
        "선택 · 앱 — 자기 계정 기기 id(`POST /api/devices` 응답). 주면 `display` 이벤트를 받고 그 기기가 online 이 된다. "
        "남의 기기 · 없는 id 는 무시")),
) -> StreamingResponse:
    """SSE(§7.5) — 인증은 `?token=`(EventSource 는 헤더를 못 싣는다). 틀리면 401.

    앱은 `deviceId` 를 붙인다(SPEC-004 §7.1) — 그 계정 기기면 last_seen_at · online · `display` 대상 · 아니면 무시.
    """
    actor = c.auth.verify(token)
    device = c.devices.own(actor, deviceId)
    return StreamingResponse(
        c.hub.frames(account_id=actor.id, device_id=device.id if device else None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
