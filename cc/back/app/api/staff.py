"""로그인 · 직원 첫 화면 · 의사 진료 시작/완료 — §5.2 · §5.3 · §6."""

from fastapi import APIRouter

from app.api.deps import Ctr
from app.schemas.requests import LoginBody, ScheduleBody

router = APIRouter(prefix="/api", tags=["staff"])


@router.get("/staff")
def list_staff(c: Ctr) -> list[dict]:
    return c.staff.accounts()


@router.post("/login")
def login(body: LoginBody, c: Ctr) -> dict:
    return c.staff.login(body.staffId)


@router.get("/staff/{staff_id}/home")
def home(staff_id: str, c: Ctr) -> dict:
    return c.staff.home(staff_id)


@router.post("/staff/{staff_id}/start")
def start(staff_id: str, body: ScheduleBody, c: Ctr) -> dict:
    return c.board.doctor_start(staff_id, body.scheduleId)


@router.post("/staff/{staff_id}/finish")
def finish(staff_id: str, body: ScheduleBody, c: Ctr) -> dict:
    return c.board.doctor_finish(staff_id, body.scheduleId)
