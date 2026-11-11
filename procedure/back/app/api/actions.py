"""조작 API(SPEC-003 §7.3) — 응답은 `{ok…}` 만. 화면은 뒤따르는 SSE `board` 로 바뀐다(§7.5)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.api.deps import Actor, Ctr, require_real_board
from app.api.docs import FAKE_BOARD, INVALID, T_ACTIONS, UNAUTHORIZED, errors
from app.schemas.actions import (
    AcceptRequest,
    AcceptResponse,
    CallCreatedResponse,
    CreateCallRequest,
    OkResponse,
    StartResponse,
)

router = APIRouter(prefix="/api", tags=[T_ACTIONS], dependencies=[Depends(require_real_board)])

VisitId = Annotated[int, Path(description="카드(visit) id — 스냅샷 `cards[].visitId`")]
CallId = Annotated[int, Path(description="호출 id — 스냅샷 `calls[].callId` 또는 `procedures[].call.id`")]
ProcedureId = Annotated[int, Path(description="시술 id — 스냅샷 `cards[].procedures[].id`")]

COMMON = """
**공통**: 다섯 역할 모두(역할 검사 없음) · 가짜 스냅샷 모드면 `403 fake_board`. 응답은 결과만 — 화면은 응답 뒤 모든 연결에
가는 SSE `board`(전체 스냅샷)로 바뀐다. ccc 상태를 먼저 바꾸고 응답하며, KOS 쓰기는 기다리지 않는다
(아래 KOS op 는 반영 큐 `kos_op` 에 쌓여 KOS 루프가 뒤에서 보내고 일정 조회로 확인한다 · 3번 실패하면 카드 `kos.status`=failed ·
KOS 연동 env 가 없는 서버면 보내지 않고 쌓이기만 한다).
조작 1번 = event_log 1줄.
"""

ERR_VISIT_404 = (404, "not_found", "visit 이 없거나 지금 현황판 카드가 아닐 때")
ERR_PROC_404 = (404, "not_found",
                "시술이 없거나 · KOS 목록에서 빠졌거나 · 「방 배정」 작업이거나 · 그 카드가 지금 현황판에 없을 때")
ERR_CALL_404 = (404, "not_found", "호출 id 가 없을 때")
ERR_HOME = (409, "visit_home", "귀가 대기 카드일 때")
BASE = (INVALID, UNAUTHORIZED, FAKE_BOARD)


@router.post(
    "/visits/{visit_id}/anesthesia/start", response_model=OkResponse,
    summary="마취 시작",
    description=COMMON + """
카드에 마취 시작 시각(지금)을 남긴다. 마취는 ccc 에만 있는 기록이다 — **KOS 쓰기 없음** · 푸시 없음.
event_log `anes_start`. 이미 진행 중이면 `409 anesthesia_running`(반복 호출은 두 번째부터 409).
""",
    responses=errors(*BASE, ERR_VISIT_404, ERR_HOME, (409, "anesthesia_running", "이미 진행 중인 마취가 있을 때")),
)
async def anesthesia_start(visit_id: VisitId, c: Ctr, actor: Actor) -> OkResponse:
    c.actions.anesthesia_start(actor.login_id, visit_id)
    return OkResponse()


@router.post(
    "/visits/{visit_id}/anesthesia/end", response_model=OkResponse,
    summary="마취 종료",
    description=COMMON + """
진행 중인 마취를 끝낸다(종료 시각 = 지금). **KOS 쓰기 없음** · 푸시 없음. event_log `anes_end`.
진행 중 마취가 없으면 `409 anesthesia_not_running`. 귀가 대기 카드도 막지 않는다(진행 중 마취가 있으면 끝낸다).
""",
    responses=errors(*BASE, ERR_VISIT_404, (409, "anesthesia_not_running", "진행 중인 마취가 없을 때")),
)
async def anesthesia_end(visit_id: VisitId, c: Ctr, actor: Actor) -> OkResponse:
    c.actions.anesthesia_end(actor.login_id, visit_id)
    return OkResponse()


@router.post(
    "/visits/{visit_id}/calls", response_model=CallCreatedResponse,
    summary="의사 호출 — 고른 시술로 전체 · 지정 호출 만들기",
    description=COMMON + """
고른 대기 시술로 원장 호출을 새로 만든다. 같은 시술이 들어간 앞 호출은 그대로 두고, 이 새 호출이 그 시술의 **유효 호출**이 된다
(가장 최근 호출). 반복 호출 = 매번 새 호출(멱등 아님).

- ccc: 고른 시술의 `kosStatus` = WAITING(즉시) · event_log `call_create`.
- **KOS op**(순서대로): ① 카드 방을 고른 작업에 넣기 `change-tasks-room`(이미 다 그 방이면 보내지 않음) →
  ② 담당자 = 시스템 계정 `change-tasks-assignees` → ③ 호출 `call-tasks-doctors`.
- **푸시**(커밋 뒤 · 응답을 기다리게 하지 않음): 받는 계정 = active `admin` 전원 + 전체 호출이면 active `doctor` 전원 ·
  지정 호출이면 그 원장의 `doctor` 계정. 누른 계정이 doctor 면 자기 자신은 뺀다. `doctor_call` 알림을 끈 계정은 뺀다.
  받는 계정마다 알림 행 1개(+ 그 계정 SSE `notification {unread}`) · 기기마다 APNs 푸시(제목 「원장 호출」 · 원장 기기는
  알림에서 바로 수락하는 category `CALL`). APNs 설정이 없으면 보내지 않고 기록만 한다.
""",
    responses=errors(
        *BASE, ERR_VISIT_404,
        (404, "not_found", "`procedureIds` 에 그 카드의 시술이 아닌 id(「방 배정」 포함)가 있을 때"),
        ERR_HOME,
        (409, "no_procedures", "`procedureIds` 가 빈 배열일 때"),
        (409, "procedure_not_waiting", "고른 시술 중 대기(`wait`)가 아닌 것이 있을 때"),
        (409, "doctor_not_listed", "지정 호출의 `doctorId` 가 원장 목록에 없을 때"),
    ),
)
async def create_call(visit_id: VisitId, body: CreateCallRequest, c: Ctr, actor: Actor) -> CallCreatedResponse:
    doctor_id = getattr(body.target, "doctorId", None)
    call_id = c.actions.create_call(actor.login_id, visit_id, body.procedureIds, body.target.kind, doctor_id)
    return CallCreatedResponse(callId=call_id)


@router.post(
    "/calls/{call_id}/accept", response_model=AcceptResponse,
    summary="호출 수락 — 받을 시술 전부를 원장에게",
    description="""
그 호출에서 아직 수락 안 된 대기 시술(그 호출이 유효 호출인 것) **전부**를 한 원장이 수락한다.
가짜 스냅샷 모드면 `403 fake_board`. 응답 뒤 SSE `board`(모든 연결).

**역할**(검사 순서: 역할 403 → 404 → `not_your_call` 403 → 409):
- `doctor` — 자기 원장으로만. `doctorId` 생략(또는 자기 staffId) — 생략해도 **본문은 `{}` 로 보내야 한다**(본문 없이
  보내면 `400 invalid_request`). 다른 값 = `403 doctor_forbidden`.
  다른 원장을 지정한 호출 = `403 not_your_call`.
- `admin` · `coordinator` · `counselor` — 원장을 골라 `doctorId` **필수**(없으면 `400 invalid_request`).
  지정 호출에 다른 원장 = `409 doctor_mismatch`.
- `nurse` — 수락 불가 `403 role_forbidden`.

**헤더 `X-Accept-Source`(선택)** — 수락이 어디서 왔는지 event_log 에만 남긴다: `push`(앱 알림 액션) · `app` · `web`
(대소문자 무시). 없거나 그 밖 값이면 `Origin` 헤더가 있으면 `web` · 없으면 `app`. 응답 · 권한에는 영향 없다.

- ccc: 수락 기록 · 시술 집도의 = 그 원장 · `kosStatus` = READY(즉시) · event_log `call_accept`(최근 수락 목록의 원천).
- **KOS op**: 집도의 넣기 `change-tasks-doctors`(1개). 푸시 없음.
- 반복: 이미 다 수락됐으면 `409 nothing_to_accept`.
""",
    responses=errors(
        *BASE,
        (400, "invalid_request",
         "본문이 없을 때(`{}` 라도 필요) · `admin` · `coordinator` · `counselor` 가 `doctorId` 없이 보냈을 때"),
        (403, "role_forbidden", "`nurse` 계정일 때"),
        (403, "doctor_forbidden", "`doctor` 계정이 자기와 다른 `doctorId` 를 보냈을 때"),
        (403, "not_your_call", "`doctor` 계정인데 다른 원장을 지정한 호출일 때"),
        ERR_CALL_404,
        (409, "doctor_not_listed", "수락할 원장(`doctorId` 또는 doctor 자신)이 원장 목록에 없을 때"),
        (409, "doctor_mismatch", "지정 호출인데 `doctorId` 가 지정 원장이 아닐 때(admin · coordinator · counselor)"),
        (409, "nothing_to_accept",
         "받을 시술이 남지 않았을 때(이미 수락 · 시작 · 다른 호출로 넘어감 · 카드가 귀가 대기 · 사라짐)"),
    ),
)
async def accept(call_id: CallId, body: AcceptRequest, c: Ctr, actor: Actor, request: Request) -> AcceptResponse:
    return AcceptResponse(acceptedProcedureIds=c.actions.accept(actor, call_id, body.doctorId, source=accept_source(request)))


def accept_source(request: Request) -> str:
    """수락이 어디서 왔나 — 선택 헤더 `X-Accept-Source: push`(앱이 알림 액션에서 넣음).

    헤더가 없으면 브라우저(Origin 있음) = web · 그 밖 = app.
    """
    value = request.headers.get("x-accept-source", "").strip().lower()
    if value in ("push", "app", "web"):
        return value
    return "web" if request.headers.get("origin") else "app"


@router.post(
    "/calls/{call_id}/reassign-all", response_model=CallCreatedResponse,
    summary="다른 원장에게 — 지정 호출을 전체 호출로 다시",
    description=COMMON + """
지정 호출의 아직 받을 시술로 **전체 호출**을 새로 만든다(기존 지정 호출 행은 그대로 · 새 호출이 유효 호출이 됨).
반복: 첫 번째 뒤에는 그 시술의 유효 호출이 새 전체 호출로 바뀌어, 같은 `call_id` 로 다시 보내면 `409 nothing_to_accept`.

- ccc: 그 시술 `kosStatus` = WAITING · event_log `call_reassign_all`.
- **KOS op**: [의사 호출] 과 같음(방 → 담당자 → 호출).
- **푸시**: [의사 호출] 의 전체 호출과 같은 규칙(admin 전원 + doctor 전원 · 누른 doctor 자신 제외 · 알림 끈 계정 제외).
""",
    responses=errors(
        *BASE, ERR_CALL_404,
        (409, "not_designated_call", "지정 호출(`kind=one`)이 아닐 때"),
        (409, "nothing_to_accept", "그 호출에 받을 시술이 남지 않았을 때(카드가 귀가 대기 · 사라짐 포함)"),
    ),
)
async def reassign_all(call_id: CallId, c: Ctr, actor: Actor) -> CallCreatedResponse:
    return CallCreatedResponse(callId=c.actions.reassign_all(actor.login_id, call_id))


@router.post(
    "/procedures/{procedure_id}/start", response_model=StartResponse,
    summary="시술 시작",
    description=COMMON + """
시술 [시작] — ccc 시작 시각 = 지금(시술 상태 `doing`). event_log `proc_start`.

- 조건: 귀가 대기 아님 · 그 시술이 대기 · 유효 호출이 있으면 수락됨 / 호출된 적 없으면 원장 목록의 집도의가 있음.
- 그 고객의 첫 [시작](고객 단계가 시술 대기)이면 고객 단계 = 시술 진행 + **KOS op** `change-flow-step`(PROCEDURE) ·
  응답 `flowStepChanged=true`. 아니면 KOS 쓰기 없음 · false. 푸시 없음.
- 반복: 두 번째부터 `409 procedure_not_waiting`.
""",
    responses=errors(
        *BASE, ERR_PROC_404, ERR_HOME,
        (409, "procedure_not_waiting", "시술이 대기(`wait`)가 아닐 때"),
        (409, "call_not_accepted", "유효 호출이 아직 수락되지 않았을 때"),
        (409, "no_doctor", "호출된 적 없고 원장 목록의 집도의도 없을 때"),
    ),
)
async def start(procedure_id: ProcedureId, c: Ctr, actor: Actor) -> StartResponse:
    return StartResponse(flowStepChanged=c.actions.start(actor.login_id, procedure_id))


@router.post(
    "/procedures/{procedure_id}/finish", response_model=OkResponse,
    summary="시술 종료",
    description=COMMON + """
진행 중 시술 [종료] — `kosStatus` = DONE · 완료 시각 = 지금(상태 `done`). event_log `proc_finish`.

- **KOS op**: 완료 `change-tasks-complete`(complete=true). 고객 단계는 바꾸지 않는다(귀가 대기는 [귀가 대기] 로). 푸시 없음.
- 반복: 두 번째부터 `409 procedure_not_started`(진행 중이 아님).
""",
    responses=errors(*BASE, ERR_PROC_404, (409, "procedure_not_started", "시술이 진행(`doing`) 중이 아닐 때")),
)
async def finish(procedure_id: ProcedureId, c: Ctr, actor: Actor) -> OkResponse:
    c.actions.finish(actor.login_id, procedure_id)
    return OkResponse()


@router.post(
    "/procedures/{procedure_id}/undo-start", response_model=StartResponse,
    summary="시작 되돌리기 — 진행 → 대기",
    description=COMMON + """
진행 중 시술을 대기로 되돌린다(ccc 시작 시각 지움). 호출 · 수락 · 집도의는 그대로. event_log `proc_undo_start`.

- 그 시술을 빼고 그 고객의 진행 · 완료 시술이 0 이고 고객 단계가 시술 진행이면 고객 단계 = 시술 대기 + **KOS op**
  `change-flow-step`(PROCEDURE_WAITING) · 응답 `flowStepChanged=true`. 아니면 KOS 쓰기 없음 · false. 푸시 없음.
- 반복: 두 번째부터 `409 procedure_not_doing`.
""",
    responses=errors(*BASE, ERR_PROC_404, ERR_HOME, (409, "procedure_not_doing", "시술이 진행(`doing`) 중이 아닐 때")),
)
async def undo_start(procedure_id: ProcedureId, c: Ctr, actor: Actor) -> StartResponse:
    """[시작] 되돌리기(§5.13) — flowStepChanged = 고객을 시술 대기로 돌렸나."""
    return StartResponse(flowStepChanged=c.actions.undo_start(actor.login_id, procedure_id))


@router.post(
    "/procedures/{procedure_id}/undo-finish", response_model=OkResponse,
    summary="종료 되돌리기 — 완료 → 진행",
    description=COMMON + """
완료 시술을 진행으로 되돌린다 — 완료 시각 지움 · `kosStatus` = READY(즉시) · 앞 [시작] 시각은 그대로. 고객 단계는 그대로.
event_log `proc_undo_finish`.

- **KOS op**: 완료 풀기 `change-tasks-complete`(complete=false). 푸시 없음.
- KOS 에서만 완료돼 ccc [시작] 시각이 없는 시술은 `409 procedure_not_started`.
- 반복: 두 번째부터 `409 procedure_not_done`.
""",
    responses=errors(
        *BASE, ERR_PROC_404, ERR_HOME,
        (409, "procedure_not_done", "시술이 완료(`done`)가 아닐 때"),
        (409, "procedure_not_started", "완료지만 ccc [시작] 시각이 없을 때(KOS 에서만 완료)"),
    ),
)
async def undo_finish(procedure_id: ProcedureId, c: Ctr, actor: Actor) -> OkResponse:
    """[종료] 되돌리기(§5.13)."""
    c.actions.undo_finish(actor.login_id, procedure_id)
    return OkResponse()


@router.post(
    "/visits/{visit_id}/home", response_model=OkResponse,
    summary="귀가 대기 — 시술이 모두 끝난 고객",
    description=COMMON + """
고객 단계 = 귀가 대기(PROCEDURE_DONE). 조건 = 시술(「방 배정」 제외)이 1개 이상이고 모두 완료. event_log `home`.

- **KOS op**(순서대로): ① 안 끝난 「방 배정」 작업이 있으면 취소 `cancel-flow-tasks`(reason CANCEL) →
  ② 단계 바꾸기 `change-flow-step`(PROCEDURE_DONE). 푸시 없음.
- 카드는 귀가 대기로 남다가 KOS 에서 데스크 귀가(COMPLETED)되면 조회에서 빠진다.
- 반복: 두 번째부터 `409 visit_home`.
""",
    responses=errors(
        *BASE, ERR_VISIT_404, ERR_HOME,
        (409, "procedures_not_done", "끝나지 않은 시술이 있거나 시술이 하나도 없을 때"),
    ),
)
async def home(visit_id: VisitId, c: Ctr, actor: Actor) -> OkResponse:
    c.actions.home(actor.login_id, visit_id)
    return OkResponse()
