"""cc PoC backend — FastAPI 앱. 실행: `uv run uvicorn app.main:app --port 8600`."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, board, events, interpret, patients, staff
from app.config import Settings, get_settings
from app.container import Container, build_container
from app.domain.errors import DomainError


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="cc PoC backend", version="0.1.0")
    app.state.container = container or build_container(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cc_front_origin],
        allow_methods=["GET", "POST", "OPTIONS"],
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

    for r in (board.router, staff.router, patients.router, admin.router, events.router, interpret.router):
        app.include_router(r)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": app.state.container.board.version()}

    return app


app = create_app()
