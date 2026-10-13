"""현황판 상태(덧씌움 모델, D-21) · 참조 데이터(KOS 모양) 저장소."""

import json
import sqlite3

from app.repository.db import Database


def _dump(o) -> str:
    return json.dumps(o, ensure_ascii=False)


class StateRepository:
    def __init__(self, db: Database):
        self.db = db

    # ── 현황판 상태 ──
    def load_state(self) -> dict:
        with self.db.connect() as con:
            return self._load(con)

    @staticmethod
    def _load(con: sqlite3.Connection) -> dict:
        def rows(sql: str) -> list[dict]:
            return [json.loads(r[0]) for r in con.execute(sql)]

        seq = con.execute("SELECT value FROM meta WHERE key = 'stepSeq'").fetchone()
        return {
            "customers": rows("SELECT doc FROM customer ORDER BY seq"),
            "steps": rows("SELECT doc FROM step ORDER BY seq"),
            "staff": rows("SELECT doc FROM staff ORDER BY seq"),
            "resv": rows("SELECT doc FROM resv ORDER BY seq"),
            "log": rows("SELECT doc FROM log ORDER BY seq"),
            "stepSeq": json.loads(seq[0]) if seq else 0,
        }

    def save_state(self, state: dict, meta: dict | None = None) -> None:
        """상태 전체를 한 트랜잭션으로 갈아 끼운다(데이터가 작다 — 수십 행)."""
        with self.db.connect() as con:
            self._save(con, state)
            for k, v in (meta or {}).items():
                self._set_meta(con, k, v)

    @staticmethod
    def _save(con: sqlite3.Connection, state: dict) -> None:
        con.execute("DELETE FROM customer")
        con.execute("DELETE FROM staff")
        con.execute("DELETE FROM resv")
        con.execute("DELETE FROM step")
        con.execute("DELETE FROM log")
        con.executemany(
            "INSERT INTO customer (seq, schedule_id, doc) VALUES (?, ?, ?)",
            [(i, c["scheduleId"], _dump(c)) for i, c in enumerate(state["customers"])],
        )
        con.executemany(
            "INSERT INTO staff (seq, staff_id, doc) VALUES (?, ?, ?)",
            [(i, s["staffId"], _dump(s)) for i, s in enumerate(state["staff"])],
        )
        con.executemany(
            "INSERT INTO resv (seq, schedule_id, doc) VALUES (?, ?, ?)",
            [(i, r["scheduleId"], _dump(r)) for i, r in enumerate(state["resv"])],
        )
        con.executemany(
            "INSERT INTO step (seq, step_id, schedule_id, doc) VALUES (?, ?, ?, ?)",
            [(i, s["stepId"], s["scheduleId"], _dump(s)) for i, s in enumerate(state["steps"])],
        )
        con.executemany(
            "INSERT INTO log (seq, schedule_id, doc) VALUES (?, ?, ?)",
            [(i, x.get("scheduleId"), _dump(x)) for i, x in enumerate(state["log"])],
        )
        StateRepository._set_meta(con, "stepSeq", state.get("stepSeq", 0))

    # ── meta(version · 되돌리기 스냅샷 · 시드 정보) ──
    def get_meta(self, key: str, default=None):
        with self.db.connect() as con:
            row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key: str, value) -> None:
        with self.db.connect() as con:
            self._set_meta(con, key, value)

    @staticmethod
    def _set_meta(con: sqlite3.Connection, key: str, value) -> None:
        if value is None:
            con.execute("DELETE FROM meta WHERE key = ?", (key,))
        else:
            con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, _dump(value)))

    # ── 참조 데이터(KOS 모양 그대로, 이름 치환본) ──
    def replace_reference(self, docs: dict[str, dict[str, dict]]) -> None:
        with self.db.connect() as con:
            con.execute("DELETE FROM reference")
            con.executemany(
                "INSERT INTO reference (kind, id, doc) VALUES (?, ?, ?)",
                [(kind, rid, _dump(doc)) for kind, items in docs.items() for rid, doc in items.items()],
            )

    def get_reference(self, kind: str, rid: str) -> dict | None:
        with self.db.connect() as con:
            row = con.execute("SELECT doc FROM reference WHERE kind = ? AND id = ?", (kind, rid)).fetchone()
        return json.loads(row[0]) if row else None

    def all_reference(self) -> dict[str, dict[str, dict]]:
        out: dict[str, dict[str, dict]] = {}
        with self.db.connect() as con:
            for kind, rid, doc in con.execute("SELECT kind, id, doc FROM reference ORDER BY kind, id"):
                out.setdefault(kind, {})[rid] = json.loads(doc)
        return out
