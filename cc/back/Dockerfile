# cc/back — FastAPI 이미지(arm64 · DEC-003). 데이터(data/ · 시나리오 · 직원 · 키)는 넣지 않는다 — 런타임에 마운트
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
COPY --chown=app:app docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CC_BACK_PORT=8600 \
    CC_DB_PATH=/data/cc.db \
    CC_SCENARIO_DIR=/scenario \
    CC_KOS_STAFF_PATH=/secrets/kos-staff/kos-staff.json \
    CC_FRONT_ORIGIN=https://ccc.medisolveai.xyz
USER 10001
EXPOSE 8600
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8600"]
