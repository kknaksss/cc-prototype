"""초기화 — §4.2 · §5.4. SPEC-002 §3.2: 예약관리 줄도 비운다."""

from fastapi import APIRouter

from app.api.deps import Ctr

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/reset")
def reset(c: Ctr) -> dict:
    return c.reservations.reset()
