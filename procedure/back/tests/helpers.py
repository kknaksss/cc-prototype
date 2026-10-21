"""시험용 행 넣기 — KOS 값은 모양만 맞춘 가짜(id · 이름 전부 지어냄)."""

from datetime import UTC, datetime, timedelta

from app.repository.repo import Repository

T0 = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)  # KST 11:00


def seed_staff(repo: Repository, system_kos_id: str = "sys-0", exclude: frozenset[str] = frozenset({"anes-0"})) -> dict:
    """원장 3명 + 시스템 계정 + 마취용 + 비활성 원장 + 간호사."""
    rows = {
        "A": ("doc-a", "가 원장", ["DOCTOR"], True),
        "B": ("doc-b", "나 원장", ["DOCTOR"], True),
        "C": ("doc-c", "다 원장", ["DOCTOR", "ADMIN"], True),
        "SYS": (system_kos_id, "시스템", ["DOCTOR", "ADMIN"], True),
        "ANES": ("anes-0", "마취용", ["DOCTOR"], True),
        "OFF": ("doc-off", "쉬는 원장", ["DOCTOR"], False),
        "NURSE": ("nurse-0", "간호", ["NURSE"], True),
    }
    ids = {}
    with repo.tx() as tx:
        for key, (kos, name, tags, active) in rows.items():
            ids[key] = tx.upsert("staff", kos, {"name": name, "role_tags": tags, "active": active})
        tx.set_doctor_flags(system_kos_id, set(exclude))
    return ids


def seed_visit(repo: Repository, n: int = 1, *, flow: str = "PROCEDURE_WAITING", procs: int = 3, room: bool = True,
               doctors: dict[int, list[int]] | None = None, at: datetime = T0) -> dict:
    """visit 하나 + 시술 procs 개(sequence 1..). doctors = {sequence: [staff id]}."""
    with repo.tx() as tx:
        room_id = tx.upsert("room", f"room-{n}", {"zone_kos_id": "zone-4", "title": f"A-룸{n}", "order": n}) if room else None
        cust = tx.upsert("customer", f"cust-{n}", {"name": f"고객{n}", "phonetic_name": None, "nationality": "KR",
                                                    "is_new": True, "chart_number": f"C{n:04d}"})
        vid = tx.upsert("visit", f"sch-{n}", {"customer_id": cust, "zone_kos_id": "zone-4", "flow_step": flow,
                                              "flow_step_at": at, "order_memo": "메모", "room_id": room_id,
                                              "room_assigned_at": at + timedelta(minutes=n), "present": True})
        pids = []
        for seq in range(1, procs + 1):
            pids.append(tx.upsert_procedure(vid, seq, {"kos_order": seq, "title": f"시술{seq}", "kos_status": "NOT_STARTED",
                                                       "payment_required": False,
                                                       "doctor_staff_ids": (doctors or {}).get(seq, [])}))
    return {"visit": vid, "procs": pids, "room": room_id}


def admin(login_id: str = "t"):
    """service 를 바로 부르는 시험용 admin 계정 값(DB 행 아님)."""
    from app.domain.models import Account

    return Account(0, login_id, "admin", "관리자", None, True, True)
