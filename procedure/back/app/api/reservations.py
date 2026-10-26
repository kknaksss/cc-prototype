"""예약 현황 API(SPEC-005 §7) — HTTP 만. 규칙 · KOS 호출은 service 가 한다.

GET 넷(§7.2 ~ §7.4)은 `PROC_FAKE_BOARD` 면 지어낸 값 · 조작 11개(§7.5)는 `require_real_board`(403 fake_board).
역할은 네 개 모두 ○(§7.1 · D-30) — 로그인만 본다.
"""

from fastapi import APIRouter, Depends

from app.api.deps import Actor, Ctr, require_real_board
from app.schemas.actions import OkResponse
from app.schemas.reservations import (
    CancelRequest,
    CounselorCallRequest,
    CreateReservationRequest,
    CreateReservationResponse,
    CustomerSearch,
    IdentityRequest,
    MemoRequest,
    MoveRequest,
    PersonalRequest,
    ReceptionRequest,
    ReceptionResponse,
    RemarkRequest,
    ReservationBoard,
    ReservationDetail,
    ReservationForm,
    RouteRequest,
)
from app.service import fake_reservations as fake

router = APIRouter(prefix="/api", tags=["reservations"])
write = [Depends(require_real_board)]


# ------------------------------------------------------------------ 조회(§7.2 ~ §7.4) — /board · /form 이 /{id} 보다 먼저
@router.get("/reservations/board", response_model=ReservationBoard)
async def board(c: Ctr, _: Actor, date: str | None = None) -> ReservationBoard:
    if c.settings.proc_fake_board:
        return fake.board(c.clock.now(), date)
    return await c.resv.board(date)


@router.get("/reservations/form", response_model=ReservationForm)
async def form(c: Ctr, _: Actor, date: str | None = None, groupId: int | None = None,  # noqa: N803 — 계약 이름
               start: str | None = None) -> ReservationForm:
    if c.settings.proc_fake_board:
        return fake.form(c.clock.now(), date, groupId, start)
    return await c.resv.form(date, groupId, start)


@router.get("/reservations/{reservation_id}", response_model=ReservationDetail)
async def detail(reservation_id: int, c: Ctr, _: Actor) -> ReservationDetail:
    if c.settings.proc_fake_board:
        return fake.detail(c.clock.now(), reservation_id)
    return await c.resv.detail(reservation_id)


@router.get("/customers/search", response_model=CustomerSearch)
async def search(c: Ctr, _: Actor, name: str | None = None, phone: str | None = None, birth: str | None = None,
                 chart: str | None = None, page: int = 1) -> CustomerSearch:
    if c.settings.proc_fake_board:
        return fake.search(name, phone, birth, chart, page)
    return await c.resv.search(name, phone, birth, chart, page)


# ------------------------------------------------------------------ 조작(§7.5)
@router.post("/reservations", response_model=CreateReservationResponse, dependencies=write)
async def create(body: CreateReservationRequest, c: Ctr, actor: Actor) -> CreateReservationResponse:
    return await c.resv.create(actor, body)


@router.post("/reservations/{reservation_id}/move", response_model=OkResponse, dependencies=write)
async def move(reservation_id: int, body: MoveRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.move(actor, reservation_id, body)
    return OkResponse()


@router.post("/reservations/{reservation_id}/cancel", response_model=OkResponse, dependencies=write)
async def cancel(reservation_id: int, body: CancelRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.cancel(actor, reservation_id, body.reason)
    return OkResponse()


@router.put("/reservations/{reservation_id}/memo", response_model=OkResponse, dependencies=write)
async def memo(reservation_id: int, body: MemoRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.memo(actor, reservation_id, body.memo)
    return OkResponse()


@router.put("/reservations/{reservation_id}/route", response_model=OkResponse, dependencies=write)
async def route(reservation_id: int, body: RouteRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.route(actor, reservation_id, body.consultationRequired)
    return OkResponse()


@router.post("/reservations/{reservation_id}/reception", response_model=ReceptionResponse, dependencies=write)
async def reception(reservation_id: int, body: ReceptionRequest, c: Ctr, actor: Actor) -> ReceptionResponse:
    return ReceptionResponse(flowStep=await c.reception.run(actor, reservation_id, body.roomId))


@router.post("/reservations/{reservation_id}/counselor-call", response_model=OkResponse, dependencies=write)
async def counselor_call(reservation_id: int, body: CounselorCallRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.reception.counselor_call(actor, reservation_id, body.staffId)
    return OkResponse()


@router.post("/reservations/{reservation_id}/discharge", response_model=OkResponse, dependencies=write)
async def discharge(reservation_id: int, c: Ctr, actor: Actor) -> OkResponse:
    await c.reception.discharge(actor, reservation_id)
    return OkResponse()


@router.put("/customers/{customer_id}/personal", response_model=OkResponse, dependencies=write)
async def personal(customer_id: int, body: PersonalRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.personal(actor, customer_id, body.personal)
    return OkResponse()


@router.put("/customers/{customer_id}/remark", response_model=OkResponse, dependencies=write)
async def remark(customer_id: int, body: RemarkRequest, c: Ctr, actor: Actor) -> OkResponse:
    await c.resv.remark(actor, customer_id, body.memo)
    return OkResponse()


@router.put("/customers/{customer_id}/identity", response_model=OkResponse, dependencies=write)
async def identity(customer_id: int, body: IdentityRequest, c: Ctr, actor: Actor) -> OkResponse:
    c.resv.identity(actor, customer_id, body.status)
    return OkResponse()
