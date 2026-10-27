"""SQLite 파일 하나(D-15) — 연결 · 스키마(SPEC-003 §3.2). 시각은 UTC ISO 문자열 · json 열은 문자열."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
-- KOS 원천(조회 때 덮어씀)
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY, kos_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role_tags TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 0, is_doctor INTEGER NOT NULL DEFAULT 0, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS room (
    id INTEGER PRIMARY KEY, kos_id TEXT NOT NULL UNIQUE, zone_kos_id TEXT, title TEXT NOT NULL,
    "order" INTEGER NOT NULL DEFAULT 0, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS customer (
    id INTEGER PRIMARY KEY, kos_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, phonetic_name TEXT, nationality TEXT,
    is_new INTEGER NOT NULL DEFAULT 0, chart_number TEXT, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS visit (
    id INTEGER PRIMARY KEY, kos_id TEXT NOT NULL UNIQUE, customer_id INTEGER REFERENCES customer(id),
    zone_kos_id TEXT, flow_step TEXT, flow_step_at TEXT, order_memo TEXT, room_id INTEGER REFERENCES room(id),
    room_assigned_at TEXT, kos_updated_at TEXT, synced_at TEXT, seen_at TEXT,
    present INTEGER NOT NULL DEFAULT 1,          -- 마지막 일정 조회에 있었나(KOS 기준 「일정 존재」)
    home_requested_at TEXT,                      -- ccc 열: [귀가 대기] 누른 시각
    open_task_seqs TEXT NOT NULL DEFAULT '[]'    -- KOS 에서 끝나지 않은 작업 sequence(종류 무관 · [귀가 대기] 취소 대상)
);
CREATE TABLE IF NOT EXISTS procedure (
    id INTEGER PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visit(id), kos_sequence INTEGER NOT NULL,
    kos_order INTEGER, title TEXT NOT NULL, kos_status TEXT, payment_required INTEGER NOT NULL DEFAULT 0,
    doctor_staff_ids TEXT NOT NULL DEFAULT '[]', assignee_staff_ids TEXT NOT NULL DEFAULT '[]',
    doctor_assigned_at TEXT, doctor_call_at TEXT, completed_at TEXT, synced_at TEXT,
    present INTEGER NOT NULL DEFAULT 1,          -- KOS 작업 목록에 있나(빠지면 0 · 행은 남김)
    started_at TEXT, started_event_id INTEGER,   -- ccc 열
    room_kos_id TEXT,                            -- 작업에 들어간 방(KOS tasks[].room.id) — 호출 전 방 넣기 판단
    kind TEXT NOT NULL DEFAULT 'procedure',      -- procedure(KOS PROCEDURE) | etc(ETCETERA) — etc + 방 = 「방 배정」
    UNIQUE (visit_id, kos_sequence)
);
-- ccc 원천
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY, login_id TEXT NOT NULL UNIQUE, role TEXT NOT NULL,   -- admin | doctor | nurse
    name TEXT NOT NULL, staff_id INTEGER REFERENCES staff(id),                  -- 의사만(KOS 원장)
    active INTEGER NOT NULL DEFAULT 1, card INTEGER NOT NULL DEFAULT 0,        -- card = PoC 계정(어드민 · 의사 1 · 간호사)
    password_hash TEXT,                                                         -- bcrypt · 없으면 로그인 불가
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device (                                         -- 원장 호출 푸시 기기(SPEC-004 §5-1.1)
    id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES account(id), token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS push_log (  -- 원장 호출 푸시 내역 · 쌓기만(event_log 와 같은 원칙)
    id INTEGER PRIMARY KEY, call_id INTEGER NOT NULL, visit_id INTEGER, account_id INTEGER, role TEXT,
    device_id INTEGER, token_tail TEXT,                                     -- 기기 토큰은 끝 6자리만
    category TEXT,                                                          -- CALL(의사 · 알림에서 수락) | null
    status TEXT NOT NULL,                                                   -- sent | failed | skipped_no_key | token_removed
    apns_status INTEGER, apns_reason TEXT, apns_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, sent_at TEXT
);
CREATE TABLE IF NOT EXISTS anesthesia (
    id INTEGER PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visit(id), started_at TEXT NOT NULL, ended_at TEXT,
    start_event_id INTEGER, end_event_id INTEGER
);
CREATE TABLE IF NOT EXISTS doctor_call (
    id INTEGER PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visit(id), kind TEXT NOT NULL,
    target_staff_id INTEGER REFERENCES staff(id), created_at TEXT NOT NULL, event_id INTEGER,
    reassigned_from_call_id INTEGER REFERENCES doctor_call(id)
);
CREATE TABLE IF NOT EXISTS doctor_call_item (
    call_id INTEGER NOT NULL REFERENCES doctor_call(id), procedure_id INTEGER NOT NULL REFERENCES procedure(id),
    PRIMARY KEY (call_id, procedure_id)
);
CREATE TABLE IF NOT EXISTS call_accept (
    id INTEGER PRIMARY KEY, call_id INTEGER NOT NULL REFERENCES doctor_call(id),
    procedure_id INTEGER NOT NULL REFERENCES procedure(id), doctor_staff_id INTEGER NOT NULL REFERENCES staff(id),
    accepted_at TEXT NOT NULL, event_id INTEGER
);
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, type TEXT NOT NULL, visit_id INTEGER,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS kos_op (
    id INTEGER PRIMARY KEY, event_id INTEGER, visit_id INTEGER NOT NULL REFERENCES visit(id), seq INTEGER NOT NULL,
    api TEXT NOT NULL, path TEXT NOT NULL, body TEXT NOT NULL, expect TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
    checks INTEGER NOT NULL DEFAULT 0,           -- sent 뒤 expect 가 안 맞은 조회 횟수(2 면 재전송)
    last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS kos_op_visit ON kos_op (visit_id, seq);
CREATE TABLE IF NOT EXISTS kos_token (
    kind TEXT PRIMARY KEY, token TEXT NOT NULL, expires_at TEXT, account_kos_id TEXT
);
CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY, last_ok_at TEXT, last_error TEXT
);
CREATE TABLE IF NOT EXISTS board_order (     -- 카드 드래그 순서 · 하루 1행(SPEC-003 0.4.0 §3.2 · §5.12) · 전날 행은 안 읽는다
    day TEXT PRIMARY KEY,                    -- KST 날짜 YYYY-MM-DD
    visit_ids TEXT NOT NULL DEFAULT '[]',    -- 귀가 대기 아닌 카드의 visit id(앞에서부터)
    updated_at TEXT NOT NULL, updated_by TEXT NOT NULL, event_id INTEGER
);
"""

# 예약 현황(SPEC-005 §3.2) — 시술 현황 SCHEMA 뒤에 따로 둔다(옛 DB 파일에도 CREATE IF NOT EXISTS 로 생긴다)
RESV_SCHEMA = """
-- KOS 사본(조회 때 덮어씀)
CREATE TABLE IF NOT EXISTS zone (
    id INTEGER PRIMARY KEY, kos_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL, "order" INTEGER NOT NULL DEFAULT 0,
    is_default INTEGER NOT NULL DEFAULT 0, present INTEGER NOT NULL DEFAULT 1, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS reservation_group (
    id INTEGER PRIMARY KEY, kos_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL, "order" INTEGER NOT NULL DEFAULT 0,
    interval_minutes INTEGER NOT NULL DEFAULT 30,
    capacities TEXT NOT NULL DEFAULT '[]',      -- 켜진 구역만 [{zoneKosId, capacity}]
    timetable TEXT NOT NULL DEFAULT '{}',       -- 요일 → {enabled, start, end, breakStart, breakEnd}(KST HH:MM)
    close_buffer_min INTEGER, present INTEGER NOT NULL DEFAULT 1, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS reservation (       -- KOS 일정 1건 = 예약 1건
    id INTEGER PRIMARY KEY, kos_id TEXT NOT NULL UNIQUE, customer_id INTEGER REFERENCES customer(id),
    day TEXT, zone_kos_id TEXT, status TEXT, flow_step TEXT, flow_step_at TEXT, reception_at TEXT,
    resources TEXT NOT NULL DEFAULT '[]', consultation_required INTEGER NOT NULL DEFAULT 0,
    sedation_required INTEGER NOT NULL DEFAULT 0, counselor TEXT, assignee TEXT, memo TEXT, funnel TEXT,
    connected_channel TEXT, desired_discharge_at TEXT, purchase_ids TEXT NOT NULL DEFAULT '[]',
    prescription_ids TEXT NOT NULL DEFAULT '[]', tasks TEXT NOT NULL DEFAULT '[]', room_kos_id TEXT, room_title TEXT,
    kos_updated_at TEXT, present INTEGER NOT NULL DEFAULT 1, synced_at TEXT
);
CREATE INDEX IF NOT EXISTS reservation_day ON reservation (day);
CREATE TABLE IF NOT EXISTS reservation_slot (
    group_kos_id TEXT NOT NULL, zone_kos_id TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT,
    capacity INTEGER, reservation_count INTEGER, synced_at TEXT,
    PRIMARY KEY (group_kos_id, zone_kos_id, start_at)
);
CREATE TABLE IF NOT EXISTS notice (
    id INTEGER PRIMARY KEY, kos_id TEXT NOT NULL UNIQUE, content TEXT NOT NULL DEFAULT '', released_at TEXT,
    deleted INTEGER NOT NULL DEFAULT 0, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS funnel_code (
    id INTEGER PRIMARY KEY, kos_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, "order" INTEGER NOT NULL DEFAULT 0,
    closed INTEGER NOT NULL DEFAULT 0, is_default INTEGER NOT NULL DEFAULT 0, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS etc_task_def (
    id INTEGER PRIMARY KEY, kos_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT
);
-- ccc 만의 것(추가만)
CREATE TABLE IF NOT EXISTS identity_check (    -- 신분 확인 표시(표시만 · 접수 조건 아님 — D-45)
    id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customer(id), status TEXT NOT NULL,
    method TEXT NOT NULL, device TEXT, checked_at TEXT NOT NULL, actor TEXT NOT NULL, event_id INTEGER
);
CREATE TABLE IF NOT EXISTS questionnaire_history (   -- 문진 방문별 이력(D-24)
    id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customer(id), reservation_id INTEGER,
    kos_submitted_at TEXT NOT NULL, answers TEXT NOT NULL DEFAULT '[]', fetched_at TEXT NOT NULL,
    UNIQUE (customer_id, kos_submitted_at)
);
"""


MIGRATIONS = (("procedure", "room_kos_id", "TEXT"), ("visit", "open_task_seqs", "TEXT NOT NULL DEFAULT '[]'"),
              ("procedure", "kind", "TEXT NOT NULL DEFAULT 'procedure'"), ("account", "password_hash", "TEXT"),
              ("customer", "gender", "TEXT"))


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)
            con.executescript(RESV_SCHEMA)
            for table, column, kind in MIGRATIONS:  # 이미 있는 DB 파일(compose 볼륨)에 새 열을 더한다
                cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
                if column not in cols:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """요청 하나 = 트랜잭션 하나."""
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
