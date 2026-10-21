"""로그인 · 직원 첫 화면 · 단계 시작/종료(본인) — §5.2 · §5.3 · §7."""

from fastapi import APIRouter

from app.api.deps import Ctr
from app.schemas.requests import LoginBody, StepBody

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
def start(staff_id: str, body: StepBody, c: Ctr) -> dict:
    return c.board.start(staff_id, body.stepId)


@router.post("/staff/{staff_id}/finish")
def finish(staff_id: str, body: StepBody, c: Ctr) -> dict:
    return c.board.finish(staff_id, body.stepId)
