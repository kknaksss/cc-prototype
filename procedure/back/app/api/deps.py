from typing import Annotated

from fastapi import Depends, Request

from app.container import Container
from app.domain.errors import Forbidden
from app.domain.models import Account


def get_container(request: Request) -> Container:
    return request.app.state.container


Ctr = Annotated[Container, Depends(get_container)]


def require_login(request: Request) -> Account:
    """`Authorization: Bearer <ccc 토큰>` → 로그인 계정(SPEC-004 §3.2). 틀리면 401 unauthorized."""
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else None
    return get_container(request).auth.verify(token)


Actor = Annotated[Account, Depends(require_login)]


def require_real_board(request: Request, _: Actor) -> None:
    """검사 순서(SPEC-004 §3.4): 401(로그인) → 403 fake_board → 역할 403 → 404 → 409."""
    # 가짜 스냅샷(PROC_FAKE_BOARD) 이 켜져 있으면 조작을 막는다(리뷰 W13) — 화면은 가짜인데 실 DB · KOS 에 쓰지 않게
    if get_container(request).settings.proc_fake_board:
        raise Forbidden("fake_board", "가짜 스냅샷(PROC_FAKE_BOARD) 중에는 조작할 수 없어요")
