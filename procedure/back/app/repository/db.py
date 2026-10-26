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


MIGRATIONS = (("procedure", "room_kos_id", "TEXT"), ("visit", "open_task_seqs", "TEXT NOT NULL DEFAULT '[]'"),
              ("procedure", "kind", "TEXT NOT NULL DEFAULT 'procedure'"), ("account", "password_hash", "TEXT"))


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)
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
