"""SQLite 파일 하나(D-28) — 연결 · 스키마."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS reference (
    kind TEXT NOT NULL,
    id   TEXT NOT NULL,
    doc  TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS customer (
    seq INTEGER NOT NULL, schedule_id TEXT PRIMARY KEY, doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staff (
    seq INTEGER NOT NULL, staff_id TEXT PRIMARY KEY, doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resv (
    seq INTEGER PRIMARY KEY, schedule_id TEXT, doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS step (
    seq INTEGER NOT NULL, step_id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL, doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS log (
    seq INTEGER PRIMARY KEY, schedule_id TEXT, doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
