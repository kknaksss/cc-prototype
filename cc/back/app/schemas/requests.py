"""front 계약 — 요청 본문(SPEC-001 §5.3 · §6 · cc/front/lib/types.ts)."""

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["의사", "상담사", "코디"]
StepKind = Literal["consult", "doctor", "treat", "sleep", "calm"]


class OrderStep(BaseModel):
    kind: StepKind
    label: str = Field(min_length=1)
    role: Role


class StaffRoom(BaseModel):
    staffId: str
    room: str


class PlaceBody(BaseModel):
    scheduleId: str
    room: str


class CheckInBody(BaseModel):
    scheduleId: str | None = None
    name: str | None = None  # 현장 접수(scheduleId null) 때
    order: list[OrderStep] | None = None


class UndoBody(BaseModel):
    version: int


class ScheduleBody(BaseModel):
    scheduleId: str


class LoginBody(BaseModel):
    staffId: str
    password: str | None = None  # 시안대로 받기만 하고 검증하지 않는다(D-26)
