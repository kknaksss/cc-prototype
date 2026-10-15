"""예약관리 — /api/reservations (SPEC-002 §3.2). 조작은 {version} + SSE."""

from fastapi import APIRouter

from app.api.deps import Ctr
from app.schemas.requests import ChangeRequestBody

router = APIRouter(prefix="/api/reservations", tags=["reservations"])


@router.get("")
def list_reservations(c: Ctr) -> dict:
    return c.reservations.read()


@router.post("/demo/request")
def demo_request(c: Ctr) -> dict:
    return c.reservations.demo_request()


@router.post("/demo/modify")
def demo_modify(c: Ctr) -> dict:
    return c.reservations.demo_modify()


@router.post("/{rid}/register")
def register(rid: int, c: Ctr) -> dict:
    return c.reservations.register(rid)


@router.post("/{rid}/change-request")
def change_request(rid: int, body: ChangeRequestBody, c: Ctr) -> dict:
    return c.reservations.change_request(rid, body.reason)
