"""front 계약 — 요청 본문(SPEC-001 0.2.0 §5.3 · §7)."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

StepKind = Literal["consult", "doctor_consult", "procedure"]


class StepItem(BaseModel):
    """접수 단계 — 후보 묶음(`bundleId`, 다음 1장 연결) 또는 직접(`kind` — 상담 · 원장 상담)."""
    bundleId: str | None = None
    kind: StepKind | None = None
    label: str | None = None  # 상담 · 원장 상담은 비우면 기본 이름

    @model_validator(mode="after")
    def _one(self):
        if not self.bundleId and not self.kind:
            raise ValueError("bundleId 또는 kind 가 필요해요")
        return self


class ProcedureItem(BaseModel):
    label: str = Field(min_length=1)


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
    """시술 추가 — 후보 묶음 id 목록(같은 묶음을 두 번 주면 2장). `items` 는 이름만 있는 직접 추가."""
    scheduleId: str
    bundleIds: list[str] = []
    items: list[ProcedureItem] = []


class ReorderBody(BaseModel):
    scheduleId: str
    stepIds: list[str]


class UndoBody(BaseModel):
    version: int


class LoginBody(BaseModel):
    staffId: str
    password: str | None = None  # 시안대로 받기만 하고 검증하지 않는다(D-26)
