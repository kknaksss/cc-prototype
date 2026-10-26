"""procedure backend — FastAPI 앱 팩토리. 실행: `uv run uvicorn app.main:create_app --factory --port 8700`.

모듈 import 때 앱을 만들지 않는다 — 시험이 실 env · 실 DB 를 건드리지 않게(리뷰 W12).
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import actions, auth, board, devices, interpret
from app.config import Settings, get_settings
from app.container import Container, build_container
from app.domain.errors import DomainError
from app.schemas.actions import HealthResponse, KosTokens

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청 URL(테넌트 id)을 로그에 남기지 않는다


class DropQueryString(logging.Filter):
    """uvicorn 접근 로그에서 쿼리 문자열을 지운다 — SSE · 통역 WS 의 `?token=` 이 로그에 남지 않게(리뷰 F3 · SPEC-004 §4.2).

    HTTP 줄은 (client, method, path, …), WebSocket 줄은 (client, path, status) — 자리가 달라 「/ 로 시작하는 인자」를 다 본다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(a.split("?", 1)[0] if isinstance(a, str) and a.startswith("/") and "?" in a else a
                                for a in args)
        return True


def install_log_filters() -> None:
    for name in ("uvicorn.access", "uvicorn.error"):  # WebSocket 접속 줄은 uvicorn.error 로 찍힌다
        logger = logging.getLogger(name)
        if not any(isinstance(f, DropQueryString) for f in logger.filters):
            logger.addFilter(DropQueryString())


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    install_log_filters()
    settings = settings or get_settings()
    container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # 서버 시작: DB(만들 때 생성) → KOS 토큰 · 직원 · 방 → 조회 · 반영 루프(§2.2). KOS env 가 비면 루프 없음
        if container.kos is not None:
            container.kos.start()
        else:
            logging.getLogger("procedure").warning("KOS env 가 비어 조회 · 반영 루프를 띄우지 않음")
        beat = asyncio.create_task(container.heartbeat())  # 조회와 상관없이 10초마다 board 발행 · 날짜 바뀌면 전날 카드 내림
        yield
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat
        if container.kos is not None:
            await container.kos.stop()
        if container.push.client is not None:
            await container.push.client.aclose()

    app = FastAPI(title="procedure backend", version="0.1.0", lifespan=lifespan)
    app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.proc_front_origin],
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],  # PUT = 카드 순서(§7.3)
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []))
        return _error(400, "invalid_request", f"{where}: {first.get('msg', '요청 형식이 맞지 않아요')}")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, "not_found" if exc.status_code == 404 else "http_error", str(exc.detail))

    for r in (auth.router, board.router, actions.router, interpret.router, devices.router):
        app.include_router(r)

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        open_, internal = app.state.container.kos_tokens()
        return HealthResponse(ok=True, kos=KosTokens(open=open_, internal=internal))

    return app

