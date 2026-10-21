"""front 계약 — 로그인 · 조작 · 기타 요청/응답(SPEC-003 §7.1 · §7.3 · §7.4)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


# §7.1 로그인 — 아이디 + 비밀번호(OQ-601 닫음 · 정상 로그인)
class LoginRequest(_Req):
    id: str
    password: str


Role = Literal["admin", "doctor", "nurse"]


class LoginResponse(BaseModel):
    token: str
    expiresAt: str
    id: str
    role: Role
    name: str
    staffId: int | None


class MeResponse(BaseModel):
    id: str
    role: Role
    name: str
    staffId: int | None


# §7.3 조작
class TargetAll(_Req):
    kind: Literal["all"]


class TargetOne(_Req):
    kind: Literal["one"]
    doctorId: int


class CreateCallRequest(_Req):
    procedureIds: list[int]
    target: Annotated[TargetAll | TargetOne, Field(discriminator="kind")]


class AcceptRequest(_Req):
    """doctor = 생략하면 자기 원장(SPEC-004 §3.4) · admin = 필수(없으면 400 invalid_request)."""

    doctorId: int | None = None


class OkResponse(BaseModel):
    ok: Literal[True] = True


class StartResponse(OkResponse):
    flowStepChanged: bool


class CallCreatedResponse(BaseModel):
    callId: int


class AcceptResponse(BaseModel):
    acceptedProcedureIds: list[int]


# SPEC-004 §5-1.1 푸시 기기
class DeviceRequest(_Req):
    token: str = Field(pattern=r"^[0-9a-fA-F]{32,200}$")  # APNs 기기 토큰(16진)


# §7.4 기타
class KosTokens(BaseModel):
    open: bool
    internal: bool


class HealthResponse(BaseModel):
    ok: bool
    kos: KosTokens


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """모든 오류 응답 `{error:{code, message}}`."""

    error: ErrorBody


# 409 코드(도메인 예외) — §7.3 표
CONFLICT_CODES = (
    "visit_home",
    "anesthesia_running",
    "anesthesia_not_running",
    "procedure_not_waiting",
    "no_procedures",
    "doctor_not_listed",
    "nothing_to_accept",
    "doctor_mismatch",
    "not_designated_call",
    "call_not_accepted",
    "no_doctor",
    "procedure_not_started",
    "procedures_not_done",
)
