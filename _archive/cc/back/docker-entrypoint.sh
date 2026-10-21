#!/bin/sh
# DB(CC_DB_PATH — PVC)가 비어 있으면 시드를 한 번 만든다: seed.json 이 있으면 그것, 없으면 시나리오(CC_SCENARIO_DIR)로 build.
# 이미 상태가 있으면 건너뛴다. 시드를 못 만들어도 서버는 띄운다(빈 현황판 — 로그 확인).
set -e
python -m app.seed ensure || echo "[entrypoint] seed ensure 실패 — 시나리오(CC_SCENARIO_DIR)·직원(CC_KOS_STAFF_PATH) 마운트를 확인하세요" >&2
exec "$@"
