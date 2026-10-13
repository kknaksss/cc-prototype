"""현황판 — §5.2 GET /api/board · §5.3 조작."""

from fastapi import APIRouter

from app.api.deps import Ctr
from app.schemas.requests import CheckInBody, PlaceBody, StaffRoom, UndoBody

router = APIRouter(prefix="/api/board", tags=["board"])


@router.get("")
def get_board(c: Ctr) -> dict:
    return c.board.board()


@router.post("/assign")
def assign(body: StaffRoom, c: Ctr) -> dict:
    return c.board.assign(body.staffId, body.room)


@router.post("/complete")
def complete(body: StaffRoom, c: Ctr) -> dict:
    return c.board.complete(body.staffId, body.room)


@router.post("/remove-staff")
def remove_staff(body: StaffRoom, c: Ctr) -> dict:
    return c.board.remove_staff(body.staffId, body.room)


@router.post("/place")
def place(body: PlaceBody, c: Ctr) -> dict:
    return c.board.place(body.scheduleId, body.room)


@router.post("/check-in")
def check_in(body: CheckInBody, c: Ctr) -> dict:
    order = [s.model_dump() for s in body.order] if body.order else None
    return c.board.check_in(body.scheduleId, body.name, order)


@router.post("/undo")
def undo(body: UndoBody, c: Ctr) -> dict:
    return c.board.undo(body.version)
