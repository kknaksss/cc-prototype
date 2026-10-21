"""환자 상세(§3.4) · 시술 후보(§5.4)."""

from fastapi import APIRouter

from app.api.deps import Ctr

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("/{schedule_id}")
def patient(schedule_id: str, c: Ctr, staffId: str | None = None) -> dict:  # noqa: N803 — 쿼리 이름(camelCase 계약)
    return c.patients.detail(schedule_id, staffId)


@router.get("/{schedule_id}/procedure-candidates")
def candidates(schedule_id: str, c: Ctr) -> list[dict]:
    return c.patients.candidates(schedule_id)
