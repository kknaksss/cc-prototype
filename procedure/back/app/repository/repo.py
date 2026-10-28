"""저장소 — sqlite 행 ↔ 도메인 값. sqlite 는 이 파일 밖으로 나가지 않는다.

`with repo.tx() as tx:` 하나 = 트랜잭션 하나(요청 하나 · 조회 반영 한 번).
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from app.domain.clock import parse, to_db
from app.domain.models import (
    Accept,
    AcceptLog,
    Account,
    Anesthesia,
    Call,
    Customer,
    Device,
    DisplayRequest,
    FunnelCode,
    IdentityCheck,
    KosOp,
    Notice,
    Procedure,
    Reservation,
    ResvGroup,
    ResvSlot,
    Room,
    Staff,
    Visit,
    World,
    Zone,
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
                    r["chart_number"], r["gender"])


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


def _device(r: sqlite3.Row) -> Device:
    return Device(r["id"], r["account_id"], r["token"], r["name"], r["kind"], parse(r["last_seen_at"]), r["install_id"])


def _display(r: sqlite3.Row) -> DisplayRequest:
    return DisplayRequest(r["id"], r["reservation_id"], r["customer_id"], r["kind"], r["device_id"], r["status"],
                          r["created_by"], parse(r["created_at"]), parse(r["expires_at"]), parse(r["opened_at"]),
                          parse(r["closed_at"]), r["qr_nonce"])


def live_devices(devices: list[Device]) -> list[Device]:
    """옛 행 가리기(E2E batch 2 #1) — 어떤 계정에 installId 있는 행이 있으면 그 계정의 installId 없는 옛 행 중
    같은 kind(옛 행 kind 가 비었으면 어느 kind 든)는 뺀다. 지우지는 않는다(targets · 푸시 대상에서만 뺌)."""
    installed: dict[int, set[str | None]] = {}
    for d in devices:
        if d.install_id:
            installed.setdefault(d.account_id, set()).add(d.kind)
    return [d for d in devices if d.install_id or d.account_id not in installed
            or (d.kind is not None and d.kind not in installed[d.account_id])]


def _op(r: sqlite3.Row) -> KosOp:
    return KosOp(r["id"], r["event_id"], r["visit_id"], r["seq"], r["api"], r["path"], json.loads(r["body"]),
                 json.loads(r["expect"]), r["status"], r["attempts"], r["checks"], r["last_error"])


def _json(v: str | None, default: Any) -> Any:
    return json.loads(v) if v else default


def _reservation(r: sqlite3.Row) -> Reservation:
    return Reservation(
        r["id"], r["kos_id"], r["customer_id"], r["day"], r["zone_kos_id"], r["status"], r["flow_step"],
        parse(r["flow_step_at"]), parse(r["reception_at"]), _json(r["resources"], []), bool(r["consultation_required"]),
        bool(r["sedation_required"]), _json(r["counselor"], None), _json(r["assignee"], None), r["memo"],
        _json(r["funnel"], None), r["connected_channel"], parse(r["desired_discharge_at"]), _json(r["purchase_ids"], []),
        _json(r["prescription_ids"], []), _json(r["tasks"], []), r["room_kos_id"], r["room_title"], bool(r["present"]))


def _group(r: sqlite3.Row) -> ResvGroup:
    return ResvGroup(r["id"], r["kos_id"], r["title"], r["order"], r["interval_minutes"], _json(r["capacities"], []),
                     _json(r["timetable"], {}), bool(r["present"]))


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

    def started_event_id(self, procedure_id: int) -> int | None:
        r = self.con.execute("SELECT started_event_id FROM procedure WHERE id = ?", (procedure_id,)).fetchone()
        return r["started_event_id"] if r else None

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
    def put_device(self, account_id: int, token: str, at: datetime, *, name: str | None = None,
                   kind: str | None = None, install_id: str | None = None) -> int:
        """같은 토큰이 다른 계정에 있으면 지금 계정으로 옮긴다(한 기기 = 마지막 로그인 계정). 이름 · 종류는 보낸 것만 고친다.

        install_id 가 오면(E2E batch 1 #1) 같은 설치의 옛 행에 새 토큰을 바꿔 끼운다 — 행 · deviceId 하나 유지.
        새 토큰이 이미 다른 행에 있으면 그 행은 지운다(토큰은 유일).
        """
        by_token = self.con.execute("SELECT id FROM device WHERE token = ?", (token,)).fetchone()
        by_install = self.con.execute("SELECT id FROM device WHERE install_id = ? ORDER BY id DESC LIMIT 1",
                                      (install_id,)).fetchone() if install_id else None
        extra = {k: v for k, v in (("name", name), ("kind", kind), ("install_id", install_id)) if v is not None}
        if by_install:
            if by_token and by_token["id"] != by_install["id"]:
                self.con.execute("DELETE FROM device WHERE id = ?", (by_token["id"],))
            self._update("device", by_install["id"], {"account_id": account_id, "token": token, **extra, "updated_at": at,
                                                      "last_seen_at": at})
            return int(by_install["id"])
        if by_token:
            self._update("device", by_token["id"], {"account_id": account_id, **extra, "updated_at": at, "last_seen_at": at})
            return int(by_token["id"])
        return self._insert("device", {"account_id": account_id, "token": token, **extra, "created_at": at,
                                       "updated_at": at, "last_seen_at": at})

    def device(self, device_id: int) -> Device | None:
        r = self.con.execute("SELECT * FROM device WHERE id = ?", (device_id,)).fetchone()
        return _device(r) if r else None

    def devices(self) -> list[Device]:
        return [_device(r) for r in self.con.execute("SELECT * FROM device ORDER BY id")]

    def touch_device(self, device_id: int, at: datetime) -> None:
        self._update("device", device_id, {"last_seen_at": at})

    def delete_device(self, token: str, account_id: int | None = None) -> None:
        """account_id 를 주면 그 계정의 토큰일 때만 지운다."""
        if account_id is None:
            self.con.execute("DELETE FROM device WHERE token = ?", (token,))
        else:
            self.con.execute("DELETE FROM device WHERE token = ? AND account_id = ?", (token, account_id))

    def devices_of(self, account_ids: list[int]) -> list[tuple[int, int, str]]:
        """[(device id, account id, token)] — 가려진 옛 행(installId 없음 · E2E batch 2 #1)은 빼고(푸시 대상)."""
        if not account_ids:
            return []
        wanted = set(account_ids)
        return [(d.id, d.account_id, d.token) for d in live_devices(self.devices()) if d.account_id in wanted]

    def add_push_log(self, **fields: Any) -> int:
        """푸시 내역 — 쌓기만(고치거나 지우지 않는다)."""
        return self._insert("push_log", fields)

    # ---------------------------------------------------------------- 알림 · 설정(SPEC-004 §5-4)
    def add_notification(self, **fields: Any) -> int:
        return self._insert("notification", fields)

    def notifications(self, account_id: int, since: datetime, limit: int) -> list[dict[str, Any]]:
        rows = self.con.execute("SELECT * FROM notification WHERE account_id = ? AND created_at >= ? "
                                "ORDER BY created_at DESC, id DESC LIMIT ?", (account_id, to_db(since), limit))
        return [dict(r) for r in rows]

    def unread_count(self, account_id: int, since: datetime) -> int:
        r = self.con.execute("SELECT COUNT(*) AS n FROM notification WHERE account_id = ? AND created_at >= ? "
                             "AND read_at IS NULL", (account_id, to_db(since))).fetchone()
        return int(r["n"])

    def mark_read(self, account_id: int, at: datetime, *, ids: list[int] | None = None, call_id: int | None = None,
                  reservation_id: int | None = None) -> int:
        """그 계정의 안 읽은 행만 — ids · callId · reservationId 가 다 없으면 전부."""
        where, args = ["account_id = ?", "read_at IS NULL"], [account_id]
        if ids is not None:
            where.append(f"id IN ({', '.join('?' for _ in ids) or 'NULL'})")
            args += ids
        if call_id is not None:
            where.append("call_id = ?")
            args.append(call_id)
        if reservation_id is not None:
            where.append("reservation_id = ?")
            args.append(reservation_id)
        cur = self.con.execute(f"UPDATE notification SET read_at = ? WHERE {' AND '.join(where)}", [to_db(at), *args])
        return cur.rowcount

    def notification_settings(self, account_id: int) -> dict[str, bool]:
        rows = self.con.execute("SELECT kind, enabled FROM notification_setting WHERE account_id = ?", (account_id,))
        return {r["kind"]: bool(r["enabled"]) for r in rows}

    def put_notification_setting(self, account_id: int, kind: str, enabled: bool, at: datetime) -> None:
        self.con.execute("INSERT INTO notification_setting (account_id, kind, enabled, updated_at) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT (account_id, kind) DO UPDATE SET enabled = excluded.enabled, "
                         "updated_at = excluded.updated_at", (account_id, kind, int(enabled), to_db(at)))

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

    # ---------------------------------------------------------------- 예약 현황 사본(SPEC-005 §3.2)
    def called_sequences(self) -> dict[str, set[int]]:
        """visit.kos_id → ccc 가 호출한 procedure 의 kos_sequence(`Rules._called` 와 같은 원천 — §5.9 잇는 키)."""
        out: dict[str, set[int]] = {}
        rows = self.con.execute("SELECT DISTINCT v.kos_id, p.kos_sequence FROM doctor_call_item i "
                                "JOIN procedure p ON p.id = i.procedure_id JOIN visit v ON v.id = p.visit_id")
        for r in rows:
            out.setdefault(r["kos_id"], set()).add(int(r["kos_sequence"]))
        return out

    def zones(self, present_only: bool = True) -> list[Zone]:
        sql = "SELECT * FROM zone" + (" WHERE present = 1" if present_only else "") + ' ORDER BY "order", id'
        return [Zone(r["id"], r["kos_id"], r["title"], r["order"], bool(r["is_default"]), bool(r["present"]))
                for r in self.con.execute(sql)]

    def resv_groups(self, present_only: bool = True) -> list[ResvGroup]:
        sql = "SELECT * FROM reservation_group" + (" WHERE present = 1" if present_only else "") + ' ORDER BY "order", id'
        return [_group(r) for r in self.con.execute(sql)]

    def mark_absent_kos(self, table: str, keep_kos_ids: set[str]) -> None:
        """1시간 목록(zone · reservation_group)에서 빠진 행 — present = 0(행은 남김)."""
        for r in self.con.execute(f"SELECT id, kos_id FROM {table} WHERE present = 1").fetchall():
            if r["kos_id"] not in keep_kos_ids:
                self._update(table, r["id"], {"present": 0})

    def reservations(self, day: str | None = None, present_only: bool = True) -> list[Reservation]:
        sql, args = "SELECT * FROM reservation WHERE 1 = 1", []
        if day is not None:
            sql, args = sql + " AND day = ?", [day]
        if present_only:
            sql += " AND present = 1"
        return [_reservation(r) for r in self.con.execute(sql + " ORDER BY id", args)]

    def reservation(self, reservation_id: int) -> Reservation | None:
        r = self.con.execute("SELECT * FROM reservation WHERE id = ?", (reservation_id,)).fetchone()
        return _reservation(r) if r else None

    def reservation_id_of(self, kos_id: str) -> int | None:
        r = self.con.execute("SELECT id FROM reservation WHERE kos_id = ?", (kos_id,)).fetchone()
        return int(r["id"]) if r else None

    def mark_absent_reservations(self, day: str, keep_ids: set[int]) -> None:
        for r in self.con.execute("SELECT id FROM reservation WHERE day = ? AND present = 1", (day,)).fetchall():
            if r["id"] not in keep_ids:
                self._update("reservation", r["id"], {"present": 0})

    def replace_slots(self, start: datetime, end: datetime, rows: list[dict[str, Any]], at: datetime) -> None:
        """그 날짜 슬롯 사본을 통째로 바꾼다."""
        self.con.execute("DELETE FROM reservation_slot WHERE start_at >= ? AND start_at < ?", (to_db(start), to_db(end)))
        for row in rows:
            self.con.execute("INSERT OR REPLACE INTO reservation_slot (group_kos_id, zone_kos_id, start_at, end_at, capacity, "
                             "reservation_count, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (row["group"], row["zone"], to_db(row["start"]), to_db(row["end"]), row["capacity"],
                              row["count"], to_db(at)))

    def slots(self, start: datetime, end: datetime) -> list[ResvSlot]:
        rows = self.con.execute("SELECT * FROM reservation_slot WHERE start_at >= ? AND start_at < ?", (to_db(start), to_db(end)))
        return [ResvSlot(r["group_kos_id"], r["zone_kos_id"], parse(r["start_at"]), parse(r["end_at"]), r["capacity"],
                         r["reservation_count"]) for r in rows]

    def replace_notices(self, start: datetime, end: datetime, rows: list[dict[str, Any]], at: datetime) -> None:
        keep = set()
        for row in rows:
            keep.add(row["kos_id"])
            self.upsert("notice", row["kos_id"], {"content": row["content"], "released_at": row["released_at"], "deleted": False,
                                                  "synced_at": at})
        for r in self.con.execute("SELECT id, kos_id FROM notice WHERE deleted = 0 AND released_at >= ? AND released_at < ?",
                                  (to_db(start), to_db(end))).fetchall():
            if r["kos_id"] not in keep:
                self._update("notice", r["id"], {"deleted": 1})

    def notices(self, start: datetime, end: datetime) -> list[Notice]:
        rows = self.con.execute("SELECT * FROM notice WHERE deleted = 0 AND released_at >= ? AND released_at < ? "
                                "ORDER BY released_at, id", (to_db(start), to_db(end)))
        return [Notice(r["id"], r["kos_id"], r["content"], parse(r["released_at"])) for r in rows]

    def notice_row(self, *, id_: int | None = None, kos_id: str | None = None) -> Notice | None:
        """ccc 행 하나(지운 행 포함) — 행 id 또는 kos_id 로."""
        if id_ is None and kos_id is None:
            return None
        r = self.con.execute("SELECT * FROM notice WHERE " + ("id = ?" if id_ is not None else "kos_id = ?"),
                             (id_ if id_ is not None else kos_id,)).fetchone()
        return Notice(r["id"], r["kos_id"], r["content"], parse(r["released_at"])) if r else None

    def funnel_codes(self) -> list[FunnelCode]:
        return [FunnelCode(r["id"], r["kos_id"], r["name"], r["order"], bool(r["closed"]), bool(r["is_default"]))
                for r in self.con.execute('SELECT * FROM funnel_code ORDER BY "order", id')]

    def etc_task_defs(self) -> list[tuple[str, str, bool]]:
        """[(kos_id, title, deleted)]."""
        return [(r["kos_id"], r["title"], bool(r["deleted"])) for r in self.con.execute("SELECT * FROM etc_task_def ORDER BY id")]

    def customer(self, customer_id: int) -> Customer | None:
        r = self.con.execute("SELECT * FROM customer WHERE id = ?", (customer_id,)).fetchone()
        return _customer(r) if r else None

    def customers(self, ids: set[int] | None = None) -> dict[int, Customer]:
        out = {r["id"]: _customer(r) for r in self.con.execute("SELECT * FROM customer")}
        return out if ids is None else {k: v for k, v in out.items() if k in ids}

    def rooms(self) -> list[Room]:
        return [_room(r) for r in self.con.execute('SELECT * FROM room ORDER BY "order", title, id')]

    def staff(self) -> list[Staff]:
        return [_staff(r) for r in self.con.execute("SELECT * FROM staff ORDER BY name, id")]

    def add_identity_check(self, customer_id: int, status: str, at: datetime, actor: str, event_id: int, *,
                           method: str = "web_manual", device: str | None = None, photo_id: int | None = None) -> int:
        return self._insert("identity_check", {"customer_id": customer_id, "status": status, "method": method,
                                               "device": device, "checked_at": at, "actor": actor, "event_id": event_id,
                                               "photo_id": photo_id})

    def last_identity_check(self, customer_id: int) -> IdentityCheck | None:
        r = self.con.execute("SELECT * FROM identity_check WHERE customer_id = ? ORDER BY id DESC LIMIT 1",
                             (customer_id,)).fetchone()
        return IdentityCheck(r["customer_id"], r["status"], r["method"], parse(r["checked_at"]), r["actor"], r["device"],
                             r["photo_id"]) if r else None

    # ---------------------------------------------------------------- 신분증 사진(SPEC-004 §7.4)
    # 법적 검토 필요: 신분증 이미지 · 주민번호 처리
    def add_id_photo(self, **fields: Any) -> int:
        return self._insert("id_photo", fields)

    def id_photo(self, photo_id: int) -> dict[str, Any] | None:
        r = self.con.execute("SELECT * FROM id_photo WHERE id = ?", (photo_id,)).fetchone()
        return dict(r) if r else None

    def update_id_photo(self, photo_id: int, **fields: Any) -> None:
        self._update("id_photo", photo_id, fields)

    # ---------------------------------------------------------------- 띄우기 요청(SPEC-004 §5-3)
    def add_display(self, **fields: Any) -> int:
        return self._insert("display_request", fields)

    def display(self, request_id: int) -> DisplayRequest | None:
        r = self.con.execute("SELECT * FROM display_request WHERE id = ?", (request_id,)).fetchone()
        return _display(r) if r else None

    def display_by_hash(self, token_hash: str) -> DisplayRequest | None:
        r = self.con.execute("SELECT * FROM display_request WHERE qr_token_hash = ?", (token_hash,)).fetchone()
        return _display(r) if r else None

    def displays(self, *, reservation_id: int | None = None, device_id: int | None = None,
                 statuses: tuple[str, ...] | None = None, kind: str | None = None,
                 since: datetime | None = None) -> list[DisplayRequest]:
        where, args = ["1 = 1"], []
        for col, v in (("reservation_id", reservation_id), ("device_id", device_id), ("kind", kind)):
            if v is not None:
                where.append(f"{col} = ?")
                args.append(v)
        if statuses is not None:
            where.append(f"status IN ({', '.join('?' for _ in statuses)})")
            args += list(statuses)
        if since is not None:
            where.append("created_at >= ?")
            args.append(to_db(since))
        rows = self.con.execute(f"SELECT * FROM display_request WHERE {' AND '.join(where)} ORDER BY id", args)
        return [_display(r) for r in rows]

    def update_display(self, request_id: int, **fields: Any) -> None:
        self._update("display_request", request_id, fields)

    def expire_displays(self, now: datetime, fill_min: float | None = None) -> int:
        """여는 시한이 지난 pending → expired. 스캔 종류 opened 는 그대로(쓰는 중).

        fill_min 을 주면 문진 종류 opened 도 opened_at + fill_min 이 지나면 expired(쓰는 시한 · SPEC-006 §3.2).
        """
        n = self.con.execute("UPDATE display_request SET status = 'expired', closed_at = ? "
                             "WHERE status = 'pending' AND expires_at <= ?", (to_db(now), to_db(now))).rowcount
        if fill_min is not None:
            cutoff = to_db(now - timedelta(minutes=fill_min))
            n += self.con.execute("UPDATE display_request SET status = 'expired', closed_at = ? WHERE status = 'opened' "
                                  "AND kind = 'questionnaire' AND opened_at <= ?", (to_db(now), cutoff)).rowcount
        return n

    def last_questionnaire_at(self, customer_id: int) -> str | None:
        r = self.con.execute("SELECT kos_submitted_at FROM questionnaire_history WHERE customer_id = ? ORDER BY id DESC LIMIT 1",
                             (customer_id,)).fetchone()
        return r["kos_submitted_at"] if r else None

    def add_questionnaire(self, customer_id: int, reservation_id: int | None, submitted_at: str, answers: list,
                          at: datetime) -> bool:
        cur = self.con.execute("INSERT OR IGNORE INTO questionnaire_history (customer_id, reservation_id, kos_submitted_at, "
                               "answers, fetched_at) VALUES (?, ?, ?, ?, ?)",
                               (customer_id, reservation_id, submitted_at, _val(answers), to_db(at)))
        return cur.rowcount > 0

    def put_app_questionnaire(self, customer_id: int, reservation_id: int | None, submitted_at: str, answers: list,
                              at: datetime, *, language: str | None, device_id: int | None,
                              display_request_id: int | None, source: str = "app_submit") -> int:
        """제출 이력(SPEC-004 §6.15 ⑥ r2 · SPEC-006 §6.4) — 같은 제출본 행(read)이 있으면 그 행을 source 로 고친다 · 없으면 새 행.
        """
        fields = {"source": source, "language": language, "device_id": device_id,
                  "display_request_id": display_request_id}
        r = self.con.execute("SELECT id FROM questionnaire_history WHERE customer_id = ? AND kos_submitted_at = ?",
                             (customer_id, submitted_at)).fetchone()
        if r:
            self._update("questionnaire_history", r["id"], fields)
            return int(r["id"])
        return self._insert("questionnaire_history", {"customer_id": customer_id, "reservation_id": reservation_id,
                                                      "kos_submitted_at": submitted_at, "answers": answers,
                                                      "fetched_at": at, **fields})

    def latest_web_questionnaire(self, customer_id: int) -> dict[str, Any] | None:
        """그 고객의 가장 늦은 고객 웹 제출(web_submit) — 상세 「건강 정보」가 KOS 제출본보다 새로우면 이것을 쓴다."""
        r = self.con.execute("SELECT * FROM questionnaire_history WHERE customer_id = ? AND source = 'web_submit' "
                             "ORDER BY kos_submitted_at DESC, id DESC LIMIT 1", (customer_id,)).fetchone()
        return dict(r) if r else None

    def questionnaire_history(self, customer_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self.con.execute("SELECT * FROM questionnaire_history WHERE customer_id = ? ORDER BY id",
                                                  (customer_id,))]


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
