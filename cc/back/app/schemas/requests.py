"""front 계약 — 요청 본문(SPEC-001 0.2.0 §5.3 · §7)."""

from typing import Literal

from pydantic import BaseModel, Field

StepKind = Literal["consult", "doctor_consult", "procedure"]


class StepItem(BaseModel):
    kind: StepKind
    label: str | None = None  # 상담 · 원장 상담은 비우면 기본 이름
    ticketId: str | None = None
    kosSequence: int | None = None


class ProcedureItem(BaseModel):
    label: str = Field(min_length=1)
    ticketId: str | None = None
    kosSequence: int | None = None


class CheckInBody(BaseModel):
    scheduleId: str
    steps: list[StepItem] = []


class PlaceBody(BaseModel):
    scheduleId: str
    room: str


class ScheduleBody(BaseModel):
    scheduleId: str


class AssignBody(BaseModel):
    stepId: str
    staffId: str


class StepBody(BaseModel):
    stepId: str


class AddProceduresBody(BaseModel):
    scheduleId: str
    items: list[ProcedureItem]


class ReorderBody(BaseModel):
    scheduleId: str
    stepIds: list[str]


class UndoBody(BaseModel):
    version: int


class LoginBody(BaseModel):
    staffId: str
    password: str | None = None  # 시안대로 받기만 하고 검증하지 않는다(D-26)
