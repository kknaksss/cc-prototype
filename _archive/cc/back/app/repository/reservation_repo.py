"""예약관리 줄(SPEC-002 §3.1 `ResvRequest`) 저장소 — 관제 DB 의 `resv_request` 테이블."""

import json

from app.repository.db import Database
from app.repository.state_repo import StateRepository


def _dump(o) -> str:
    return json.dumps(o, ensure_ascii=False)


class ReservationRepository:
    def __init__(self, db: Database):
        self.db = db

    def all(self) -> list[dict]:
        with self.db.connect() as con:
            return [json.loads(r[0]) for r in con.execute("SELECT doc FROM resv_request ORDER BY id")]

    def save(self, rows: list[dict], version: int) -> None:
        """바뀐 줄(새 줄 포함)과 version 을 한 트랜잭션으로."""
        with self.db.connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO resv_request (id, group_id, doc) VALUES (?, ?, ?)",
                [(r["id"], r["groupId"], _dump(r)) for r in rows],
            )
            StateRepository._set_meta(con, "version", version)

    def clear(self) -> None:
        with self.db.connect() as con:
            con.execute("DELETE FROM resv_request")
