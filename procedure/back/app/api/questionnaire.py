"""QR 문진(SPEC-004 §6.15) — 다섯 역할 모두. deviceId 는 자기 계정 기기(아니면 404 device_not_found)."""

from fastapi import APIRouter, Depends

from app.api.deps import Actor, Ctr, require_real_board
from app.schemas.actions import OkResponse, QuestionnaireForm, QuestionnaireSubmit

router = APIRouter(prefix="/api/questionnaires", tags=["questionnaire"])


@router.get("/{reservation_id}", response_model=QuestionnaireForm)
async def load(reservation_id: int, c: Ctr, actor: Actor, lang: str | None = None,
               deviceId: int | None = None) -> QuestionnaireForm:  # noqa: N803 — 계약 이름
    return QuestionnaireForm.model_validate(await c.questionnaire.load(actor, reservation_id, lang, deviceId))


@router.post("/{reservation_id}", response_model=OkResponse, dependencies=[Depends(require_real_board)])
async def submit(reservation_id: int, body: QuestionnaireSubmit, c: Ctr, actor: Actor) -> OkResponse:
    await c.questionnaire.submit(actor, reservation_id, body.model_dump(exclude_unset=True), body.model_fields_set)
    return OkResponse()
