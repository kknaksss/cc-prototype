"""저장소 — sqlite 행 ↔ 도메인 값. sqlite 는 이 파일 밖으로 나가지 않는다.

`with repo.tx() as tx:` 하나 = 트랜잭션 하나(요청 하나 · 조회 반영 한 번).
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from app.domain.clock import parse, to_db
from app.domain.models import (
    Accept,
    AcceptLog,
    Account,
    Anesthesia,
    Call,
    Customer,
    KosOp,
    Procedure,
    Room,
    Staff,
    Visit,
    World,
)
from app.repository.db import Database

RECENT_ACCEPTS = 3


def _val(v: Any) -> Any:
    if isinstance(v, datetime):
        return to_db(v)
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return int(v)
    return v


def _staff(r: sqlite3.Row) -> Staff:
    return Staff(r["id"], r["kos_id"], r["name"], json.loads(r["role_tags"]), bool(r["active"]), bool(r["is_doctor"]))


def _room(r: sqlite3.Row) -> Room:
    return Room(r["id"], r["kos_id"], r["zone_kos_id"], r["title"], r["order"])


def _customer(r: sqlite3.Row) -> Customer:
    return Customer(r["id"], r["kos_id"], r["name"], r["phonetic_name"], r["nationality"], bool(r["is_new"]),
                    r["chart_number"])


def _visit(r: sqlite3.Row) -> Visit:
    return Visit(r["id"], r["kos_id"], r["customer_id"], r["zone_kos_id"], r["flow_step"], parse(r["flow_step_at"]),
                 r["order_memo"], r["room_id"], parse(r["room_assigned_at"]), bool(r["present"]),
                 parse(r["home_requested_at"]), json.loads(r["open_task_seqs"] or "[]"))


def _procedure(r: sqlite3.Row) -> Procedure:
    return Procedure(r["id"], r["visit_id"], r["kos_sequence"], r["kos_order"], r["title"], r["kos_status"],
                     bool(r["payment_required"]), json.loads(r["doctor_staff_ids"]), json.loads(r["assignee_staff_ids"]),
                     parse(r["doctor_assigned_at"]), parse(r["doctor_call_at"]), parse(r["completed_at"]),
                     bool(r["present"]), parse(r["started_at"]), r["room_kos_id"], r["kind"])


def _account(r: sqlite3.Row) -> Account:
    return Account(r["id"], r["login_id"], r["role"], r["name"], r["staff_id"], bool(r["active"]), bool(r["card"]),
                   r["password_hash"])


def _op(r: sqlite3.Row) -> KosOp:
    return KosOp(r["id"], r["event_id"], r["visit_id"], r["seq"], r["api"], r["path"], json.loads(r["body"]),
                 json.loads(r["expect"]), r["status"], r["attempts"], r["checks"], r["last_error"])


class Tx:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    # ---------------------------------------------------------------- 공통
    def _insert(self, table: str, fields: dict[str, Any]) -> int:
        cols = ", ".join(f'"{k}"' for k in fields)
        marks = ", ".join("?" for _ in fields)
        cur = self.con.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", [_val(v) for v in fields.values()])
        return int(cur.lastrowid or 0)

    def _update(self, table: str, row_id: int, fields: dict[str, Any], key: str = "id") -> None:
        if not fields:
            return
        sets = ", ".join(f'"{k}" = ?' for k in fields)
        self.con.execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", [*(_val(v) for v in fields.values()), row_id])

    # ---------------------------------------------------------------- 읽기
    def world(self) -> World:
        q = self.con.execute
        calls = {r["id"]: Call(r["id"], r["visit_id"], r["kind"], r["target_staff_id"], parse(r["created_at"]),
                               r["reassigned_from_call_id"])
                 for r in q("SELECT * FROM doctor_call ORDER BY id")}
        for r in q("SELECT call_id, procedure_id FROM doctor_call_item ORDER BY call_id, procedure_id"):
            calls[r["call_id"]].procedure_ids.append(r["procedure_id"])
        recent = []
        for r in q("SELECT * FROM event_log WHERE type = 'call_accept' ORDER BY id DESC LIMIT ?", (RECENT_ACCEPTS,)):
            p = json.loads(r["payload"])
            recent.append(AcceptLog(parse(r["at"]), r["visit_id"], p.get("doctorId"), len(p.get("procedureIds", []))))
        sync = self.sync_state("schedules")
        return World(
            staff={r["id"]: _staff(r) for r in q("SELECT * FROM staff")},
            rooms={r["id"]: _room(r) for r in q("SELECT * FROM room")},
            customers={r["id"]: _customer(r) for r in q("SELECT * FROM customer")},
            visits={r["id"]: _visit(r) for r in q("SELECT * FROM visit")},
            procedures={r["id"]: _procedure(r) for r in q("SELECT * FROM procedure")},
            anesthesia=[Anesthesia(r["id"], r["visit_id"], parse(r["started_at"]), parse(r["ended_at"]))
                        for r in q("SELECT * FROM anesthesia")],
            calls=calls,
            accepts=[Accept(r["id"], r["call_id"], r["procedure_id"], r["doctor_staff_id"], parse(r["accepted_at"]))
                     for r in q("SELECT * FROM call_accept")],
            ops=[_op(r) for r in q("SELECT * FROM kos_op ORDER BY visit_id, seq")],
            recent_accepts=recent,
            sync_ok_at=sync[0],
            sync_error=sync[1],
        )

    def staff_by_kos(self) -> dict[str, Staff]:
        return {r["kos_id"]: _staff(r) for r in self.con.execute("SELECT * FROM staff")}

    def visit_by_kos(self) -> dict[str, Visit]:
        return {r["kos_id"]: _visit(r) for r in self.con.execute("SELECT * FROM visit")}

    def procedures_of(self, visit_id: int) -> dict[int, Procedure]:
        rows = self.con.execute("SELECT * FROM procedure WHERE visit_id = ?", (visit_id,))
        return {r["kos_sequence"]: _procedure(r) for r in rows}

    def events(self, type_: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM event_log", ()
        if type_:
            sql, args = sql + " WHERE type = ?", (type_,)
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in self.con.execute(sql + " ORDER BY id", args)]

    # ---------------------------------------------------------------- ccc 조작
    def add_event(self, at: datetime, actor: str, type_: str, visit_id: int | None, payload: dict[str, Any]) -> int:
        return self._insert("event_log", {"at": at, "actor": actor, "type": type_, "visit_id": visit_id, "payload": payload})

    def start_anesthesia(self, visit_id: int, at: datetime, event_id: int) -> int:
        return self._insert("anesthesia", {"visit_id": visit_id, "started_at": at, "start_event_id": event_id})

    def end_anesthesia(self, anes_id: int, at: datetime, event_id: int) -> None:
        self._update("anesthesia", anes_id, {"ended_at": at, "end_event_id": event_id})

    def add_call(self, visit_id: int, kind: str, target: int | None, at: datetime, event_id: int,
                 procedure_ids: list[int], reassigned_from: int | None = None) -> int:
        call_id = self._insert("doctor_call", {"visit_id": visit_id, "kind": kind, "target_staff_id": target, "created_at": at,
                                               "event_id": event_id, "reassigned_from_call_id": reassigned_from})
        for pid in procedure_ids:
            self._insert("doctor_call_item", {"call_id": call_id, "procedure_id": pid})
        return call_id

    def set_event_payload(self, event_id: int, payload: dict[str, Any]) -> None:
        self._update("event_log", event_id, {"payload": payload})

    def add_accept(self, call_id: int, procedure_id: int, doctor_id: int, at: datetime, event_id: int) -> int:
        return self._insert("call_accept", {"call_id": call_id, "procedure_id": procedure_id, "doctor_staff_id": doctor_id,
                                            "accepted_at": at, "event_id": event_id})

    def update_procedure(self, procedure_id: int, **fields: Any) -> None:
        self._update("procedure", procedure_id, fields)

    def update_visit(self, visit_id: int, **fields: Any) -> None:
        self._update("visit", visit_id, fields)

    # ---------------------------------------------------------------- 카드 순서(SPEC-003 §5.12)
    def board_order(self, day: str) -> list[int]:
        """그날 순서 목록 — 행이 없으면 빈 목록(순서 없음 → 전부 입실순)."""
        r = self.con.execute("SELECT visit_ids FROM board_order WHERE day = ?", (day,)).fetchone()
        return [int(x) for x in json.loads(r["visit_ids"])] if r else []

    def put_board_order(self, day: str, visit_ids: list[int], at: datetime, actor: str, event_id: int) -> None:
        """그날 행을 통째로 바꾼다(마지막 쓰기가 이긴다)."""
        self.con.execute("INSERT OR REPLACE INTO board_order (day, visit_ids, updated_at, updated_by, event_id) "
                         "VALUES (?, ?, ?, ?, ?)", (day, _val(visit_ids), to_db(at), actor, event_id))

    # ---------------------------------------------------------------- KOS 반영 대기열
    def add_op(self, event_id: int | None, visit_id: int, api: str, path: str, body: dict[str, Any],
               expect: dict[str, Any], at: datetime, status: str = "pending") -> int:
        seq = self.con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM kos_op WHERE visit_id = ?", (visit_id,)).fetchone()[0]
        return self._insert("kos_op", {"event_id": event_id, "visit_id": visit_id, "seq": seq, "api": api, "path": path,
                                       "body": body, "expect": expect, "status": status, "attempts": 0, "checks": 0,
                                       "created_at": at, "updated_at": at})

    def ops(self, statuses: tuple[str, ...] | None = None) -> list[KosOp]:
        sql, args = "SELECT * FROM kos_op", ()
        if statuses:
            sql += f" WHERE status IN ({', '.join('?' for _ in statuses)})"
            args = statuses
        return [_op(r) for r in self.con.execute(sql + " ORDER BY visit_id, seq", args)]

    def block_ops_after(self, visit_id: int, seq: int, at: datetime, error: str) -> list[int]:
        """같은 visit 에서 seq 뒤의 대기(pending · sent) op 을 막힘(failed)으로 → 그 id."""
        rows = self.con.execute("SELECT id FROM kos_op WHERE visit_id = ? AND seq > ? AND status IN ('pending', 'sent')",
                                (visit_id, seq)).fetchall()
        ids = [int(r["id"]) for r in rows]
        for op_id in ids:
            self.update_op(op_id, at, status="failed", last_error=error)
        return ids

    def update_op(self, op_id: int, at: datetime, **fields: Any) -> None:
        self._update("kos_op", op_id, {**fields, "updated_at": at})

    # ---------------------------------------------------------------- KOS 원천 upsert
    def upsert(self, table: str, kos_id: str, fields: dict[str, Any]) -> int:
        row = self.con.execute(f"SELECT id FROM {table} WHERE kos_id = ?", (kos_id,)).fetchone()
        if row:
            self._update(table, row["id"], fields)
            return int(row["id"])
        return self._insert(table, {"kos_id": kos_id, **fields})

    def upsert_procedure(self, visit_id: int, sequence: int, fields: dict[str, Any]) -> int:
        row = self.con.execute("SELECT id FROM procedure WHERE visit_id = ? AND kos_sequence = ?",
                               (visit_id, sequence)).fetchone()
        if row:
            self._update("procedure", row["id"], fields)
            return int(row["id"])
        return self._insert("procedure", {"visit_id": visit_id, "kos_sequence": sequence, **fields})

    def mark_absent_procedures(self, visit_id: int, keep_sequences: set[int]) -> None:
        for r in self.con.execute("SELECT id, kos_sequence FROM procedure WHERE visit_id = ?", (visit_id,)).fetchall():
            if r["kos_sequence"] not in keep_sequences:
                self._update("procedure", r["id"], {"present": 0})

    def mark_absent_visits(self, keep_ids: set[int]) -> None:
        for r in self.con.execute("SELECT id FROM visit WHERE present = 1").fetchall():
            if r["id"] not in keep_ids:
                self._update("visit", r["id"], {"present": 0})

    def drop_visits_synced_before(self, at: datetime) -> int:
        cur = self.con.execute("UPDATE visit SET present = 0 WHERE present = 1 AND synced_at IS NOT NULL AND synced_at < ?",
                               (to_db(at),))
        return cur.rowcount

    def set_doctor_flags(self, system_kos_id: str | None, exclude: set[str]) -> None:
        """원장 목록(§4.6) = DOCTOR 태그 · 활성 · 시스템 계정 아님 · 제외 목록 아님.

        시스템 계정 id 를 모르면 갱신하지 않는다(이전 값 유지 — 리뷰 W7).
        """
        if not system_kos_id:
            return
        for r in self.con.execute("SELECT id, kos_id, role_tags, active FROM staff").fetchall():
            ok = ("DOCTOR" in json.loads(r["role_tags"]) and bool(r["active"])
                  and r["kos_id"] != system_kos_id and r["kos_id"] not in exclude)
            self._update("staff", r["id"], {"is_doctor": ok})

    # ---------------------------------------------------------------- 계정(SPEC-004 §3.1)
    def account(self, login_id: str) -> Account | None:
        r = self.con.execute("SELECT * FROM account WHERE login_id = ?", (login_id,)).fetchone()
        return _account(r) if r else None

    def accounts(self) -> list[Account]:
        return [_account(r) for r in self.con.execute("SELECT * FROM account ORDER BY id")]

    def put_account(self, login_id: str, at: datetime, *, role: str, name: str, staff_id: int | None, active: bool,
                    card: bool) -> int:
        """login_id 로 upsert."""
        fields = {"role": role, "name": name, "staff_id": staff_id, "active": active, "card": card, "updated_at": at}
        r = self.con.execute("SELECT id FROM account WHERE login_id = ?", (login_id,)).fetchone()
        if r:
            self._update("account", r["id"], fields)
            return int(r["id"])
        return self._insert("account", {"login_id": login_id, **fields, "created_at": at})

    def update_account(self, account_id: int, at: datetime, **fields: Any) -> None:
        self._update("account", account_id, {**fields, "updated_at": at})

    # ---------------------------------------------------------------- 푸시 기기(SPEC-004 §5-1.1)
    def put_device(self, account_id: int, token: str, at: datetime) -> None:
        """같은 토큰이 다른 계정에 있으면 지금 계정으로 옮긴다(한 기기 = 마지막 로그인 계정)."""
        r = self.con.execute("SELECT id FROM device WHERE token = ?", (token,)).fetchone()
        if r:
            self._update("device", r["id"], {"account_id": account_id, "updated_at": at})
        else:
            self._insert("device", {"account_id": account_id, "token": token, "created_at": at, "updated_at": at})

    def delete_device(self, token: str, account_id: int | None = None) -> None:
        """account_id 를 주면 그 계정의 토큰일 때만 지운다."""
        if account_id is None:
            self.con.execute("DELETE FROM device WHERE token = ?", (token,))
        else:
            self.con.execute("DELETE FROM device WHERE token = ? AND account_id = ?", (token, account_id))

    def devices_of(self, account_ids: list[int]) -> list[tuple[int, int, str]]:
        """[(device id, account id, token)]."""
        if not account_ids:
            return []
        marks = ", ".join("?" for _ in account_ids)
        rows = self.con.execute(f"SELECT id, account_id, token FROM device WHERE account_id IN ({marks}) ORDER BY id",
                                account_ids)
        return [(r["id"], r["account_id"], r["token"]) for r in rows]

    def add_push_log(self, **fields: Any) -> int:
        """원장 호출 푸시 내역 — 쌓기만(고치거나 지우지 않는다)."""
        return self._insert("push_log", fields)

    def push_logs(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.con.execute("SELECT * FROM push_log ORDER BY id")]

    def device_tokens(self, account_ids: list[int]) -> list[str]:
        if not account_ids:
            return []
        marks = ", ".join("?" for _ in account_ids)
        rows = self.con.execute(f"SELECT token FROM device WHERE account_id IN ({marks}) ORDER BY id", account_ids)
        return [r["token"] for r in rows]

    # ---------------------------------------------------------------- 토큰 · 동기화 상태
    def token(self, kind: str) -> tuple[str, datetime | None, str | None] | None:
        r = self.con.execute("SELECT * FROM kos_token WHERE kind = ?", (kind,)).fetchone()
        return (r["token"], parse(r["expires_at"]), r["account_kos_id"]) if r else None

    def save_token(self, kind: str, token: str, expires_at: datetime | None, account_kos_id: str | None) -> None:
        self.con.execute("INSERT OR REPLACE INTO kos_token (kind, token, expires_at, account_kos_id) VALUES (?, ?, ?, ?)",
                         (kind, token, to_db(expires_at), account_kos_id))

    def drop_token(self, kind: str) -> None:
        self.con.execute("DELETE FROM kos_token WHERE kind = ?", (kind,))

    def sync_state(self, key: str) -> tuple[datetime | None, str | None]:
        r = self.con.execute("SELECT * FROM sync_state WHERE key = ?", (key,)).fetchone()
        return (parse(r["last_ok_at"]), r["last_error"]) if r else (None, None)

    def set_sync(self, key: str, ok_at: datetime | None, error: str | None) -> None:
        prev_ok, _ = self.sync_state(key)
        self.con.execute("INSERT OR REPLACE INTO sync_state (key, last_ok_at, last_error) VALUES (?, ?, ?)",
                         (key, to_db(ok_at or prev_ok), error))


class Repository:
    def __init__(self, db: Database):
        self.db = db

    @contextmanager
    def tx(self) -> Iterator[Tx]:
        with self.db.connect() as con:
            yield Tx(con)

    def world(self) -> World:
        with self.tx() as tx:
            return tx.world()

    def world_and_order(self, day: str) -> tuple[World, list[int]]:
        """스냅샷용 — 같은 트랜잭션에서 World 와 그날 카드 순서."""
        with self.tx() as tx:
            return tx.world(), tx.board_order(day)
