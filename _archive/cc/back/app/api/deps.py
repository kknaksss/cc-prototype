from typing import Annotated

from fastapi import Depends, Request

from app.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container


Ctr = Annotated[Container, Depends(get_container)]
