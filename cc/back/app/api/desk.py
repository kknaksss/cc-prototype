"""데스크 조작 — /api/desk/* (SPEC-001 0.2.0 §5.3). 성공하면 {version} + SSE + log."""

from fastapi import APIRouter

from app.api.deps import Ctr
from app.schemas.requests import (
    AddProceduresBody,
    AssignBody,
    CheckInBody,
    PlaceBody,
    ReorderBody,
    ScheduleBody,
    StepBody,
    UndoBody,
)

router = APIRouter(prefix="/api/desk", tags=["desk"])


@router.post("/check-in")
def check_in(body: CheckInBody, c: Ctr) -> dict:
    return c.board.check_in(body.scheduleId, [s.model_dump() for s in body.steps])


@router.post("/place")
def place(body: PlaceBody, c: Ctr) -> dict:
    return c.board.place(body.scheduleId, body.room)


@router.post("/move-sleep")
def move_sleep(body: PlaceBody, c: Ctr) -> dict:
    return c.board.move_sleep(body.scheduleId, body.room)


@router.post("/return-room")
def return_room(body: ScheduleBody, c: Ctr) -> dict:
    return c.board.return_room(body.scheduleId)


@router.post("/assign")
def assign(body: AssignBody, c: Ctr) -> dict:
    return c.board.assign(body.stepId, body.staffId)


@router.post("/unassign")
def unassign(body: StepBody, c: Ctr) -> dict:
    return c.board.unassign(body.stepId)


@router.post("/add-procedures")
def add_procedures(body: AddProceduresBody, c: Ctr) -> dict:
    return c.board.add_procedures(body.scheduleId, [i.model_dump() for i in body.items])


@router.post("/reorder")
def reorder(body: ReorderBody, c: Ctr) -> dict:
    return c.board.reorder(body.scheduleId, body.stepIds)


@router.post("/payment-complete")
def payment_complete(body: ScheduleBody, c: Ctr) -> dict:
    return c.board.payment_complete(body.scheduleId)


@router.post("/discharge")
def discharge(body: ScheduleBody, c: Ctr) -> dict:
    return c.board.discharge(body.scheduleId)


@router.post("/undo")
def undo(body: UndoBody, c: Ctr) -> dict:
    return c.board.undo(body.version)
