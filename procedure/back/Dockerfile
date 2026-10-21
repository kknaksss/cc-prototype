# procedure/back — FastAPI 이미지(arm64 · GHCR procedure-back). 데이터 · 비밀은 넣지 않는다(DB = /data 볼륨 · env = 런타임)
# 배포(WP10):
# - env = k8s Secret(KOS_* · CCC_* · PROC_SESSION_SECRET · SONIOX_API_KEY · APNS_*) · PROC_FRONT_ORIGIN = 배포 주소
# - APNs 키 = Secret 을 파일로 마운트(예: /run/secrets/apns.p8 · uid 10001 이 읽을 수 있게) → APNS_KEY_PATH 에 그 경로
# - 프로세스 1개(uvicorn 워커 1 · replica 1) — SSE 연결 목록 · 푸시 태스크가 메모리에 있다(SPEC-003 §7.5)
# - ingress 가 /api/board/stream(SSE) 을 버퍼링하지 않고 · /api/interpret 는 WebSocket 업그레이드
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app

FROM python:3.12-slim
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /data && chown app:app /data
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PROC_BACK_PORT=8700 \
    PROC_DB_PATH=/data/procedure.db
USER 10001
EXPOSE 8700
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8700"]
