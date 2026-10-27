"""조작 API(SPEC-003 §7.3) — 응답은 `{ok…}` 만. 화면은 뒤따르는 SSE `board` 로 바뀐다(§7.5)."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import Actor, Ctr, require_real_board
from app.schemas.actions import (
    AcceptRequest,
    AcceptResponse,
    CallCreatedResponse,
    CreateCallRequest,
    OkResponse,
    StartResponse,
)

router = APIRouter(prefix="/api", tags=["actions"], dependencies=[Depends(require_real_board)])


@router.post("/visits/{visit_id}/anesthesia/start", response_model=OkResponse)
async def anesthesia_start(visit_id: int, c: Ctr, actor: Actor) -> OkResponse:
    c.actions.anesthesia_start(actor.login_id, visit_id)
    return OkResponse()


@router.post("/visits/{visit_id}/anesthesia/end", response_model=OkResponse)
async def anesthesia_end(visit_id: int, c: Ctr, actor: Actor) -> OkResponse:
    c.actions.anesthesia_end(actor.login_id, visit_id)
    return OkResponse()


@router.post("/visits/{visit_id}/calls", response_model=CallCreatedResponse)
async def create_call(visit_id: int, body: CreateCallRequest, c: Ctr, actor: Actor) -> CallCreatedResponse:
    doctor_id = getattr(body.target, "doctorId", None)
    call_id = c.actions.create_call(actor.login_id, visit_id, body.procedureIds, body.target.kind, doctor_id)
    return CallCreatedResponse(callId=call_id)


@router.post("/calls/{call_id}/accept", response_model=AcceptResponse)
async def accept(call_id: int, body: AcceptRequest, c: Ctr, actor: Actor, request: Request) -> AcceptResponse:
    return AcceptResponse(acceptedProcedureIds=c.actions.accept(actor, call_id, body.doctorId, source=accept_source(request)))


def accept_source(request: Request) -> str:
    """수락이 어디서 왔나 — 선택 헤더 `X-Accept-Source: push`(앱이 알림 액션에서 넣음).

    헤더가 없으면 브라우저(Origin 있음) = web · 그 밖 = app.
    """
    value = request.headers.get("x-accept-source", "").strip().lower()
    if value in ("push", "app", "web"):
        return value
    return "web" if request.headers.get("origin") else "app"


@router.post("/calls/{call_id}/reassign-all", response_model=CallCreatedResponse)
async def reassign_all(call_id: int, c: Ctr, actor: Actor) -> CallCreatedResponse:
    return CallCreatedResponse(callId=c.actions.reassign_all(actor.login_id, call_id))


@router.post("/procedures/{procedure_id}/start", response_model=StartResponse)
async def start(procedure_id: int, c: Ctr, actor: Actor) -> StartResponse:
    return StartResponse(flowStepChanged=c.actions.start(actor.login_id, procedure_id))


@router.post("/procedures/{procedure_id}/finish", response_model=OkResponse)
async def finish(procedure_id: int, c: Ctr, actor: Actor) -> OkResponse:
    c.actions.finish(actor.login_id, procedure_id)
    return OkResponse()


@router.post("/procedures/{procedure_id}/undo-start", response_model=StartResponse)
async def undo_start(procedure_id: int, c: Ctr, actor: Actor) -> StartResponse:
    """[시작] 되돌리기(§5.13) — flowStepChanged = 고객을 시술 대기로 돌렸나."""
    return StartResponse(flowStepChanged=c.actions.undo_start(actor.login_id, procedure_id))


@router.post("/procedures/{procedure_id}/undo-finish", response_model=OkResponse)
async def undo_finish(procedure_id: int, c: Ctr, actor: Actor) -> OkResponse:
    """[종료] 되돌리기(§5.13)."""
    c.actions.undo_finish(actor.login_id, procedure_id)
    return OkResponse()


@router.post("/visits/{visit_id}/home", response_model=OkResponse)
async def home(visit_id: int, c: Ctr, actor: Actor) -> OkResponse:
    c.actions.home(actor.login_id, visit_id)
    return OkResponse()
