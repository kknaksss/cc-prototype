"""환자 상세 — §5.5."""

from fastapi import APIRouter

from app.api.deps import Ctr

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("/{schedule_id}")
def patient(schedule_id: str, c: Ctr) -> dict:
    return c.patients.detail(schedule_id)
