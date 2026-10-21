"""현황판 읽기 — GET /api/board (§5.2)."""

from fastapi import APIRouter

from app.api.deps import Ctr

router = APIRouter(prefix="/api", tags=["board"])


@router.get("/board")
def get_board(c: Ctr) -> dict:
    return c.board.board()
