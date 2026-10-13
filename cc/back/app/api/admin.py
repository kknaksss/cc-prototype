"""초기화 — §4.2 · §5.4."""

from fastapi import APIRouter

from app.api.deps import Ctr

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/reset")
def reset(c: Ctr) -> dict:
    return c.board.reset()
