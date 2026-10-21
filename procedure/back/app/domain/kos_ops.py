"""KOS 반영 표(SPEC-003 §8) — ccc 조작 → op(경로 · 본문 · 확인 조건). 보내기 · 확인은 app/kos 가 한다.

경로: internal = `{KOS_INTERNAL_API_BASE}/tenants/{tenantId}/<path>` · open = `{KOS_OPEN_API_BASE}/<path>`.
`$SYSTEM` = 시스템 계정 id(보낼 때 sign-in 응답 id 로 바꾼다 — D-11 · D-24).
"""

from dataclasses import dataclass
from typing import Any

SYSTEM = "$SYSTEM"

PATH_CANCEL = "schedule/v1/commands/cancel-flow-tasks"
PATH_ROOM = "schedule/flow/v1/commands/change-tasks-room"
PATH_ASSIGNEES = "schedule/flow/v1/commands/change-tasks-assignees"
PATH_CALL = "schedule/flow/v1/commands/call-tasks-doctors"
PATH_DOCTORS = "schedule/flow/v1/commands/change-tasks-doctors"
PATH_COMPLETE = "schedule/flow/v1/commands/change-tasks-complete"
PATH_FLOW_STEP = "schedule/open/v1/commands/change-flow-step"


@dataclass(frozen=True)
class OpSpec:
    api: str
    path: str
    body: dict[str, Any]
    expect: dict[str, Any]


def room_op(schedule_id: str, sequences: list[int], room_kos_id: str) -> OpSpec:
    """고른 시술 작업에 카드 방(「방 배정」 ETCETERA 작업의 방)을 넣는다 — 방 없는 작업은 호출이 400 roomId NotFound."""
    return OpSpec("internal", PATH_ROOM, {"scheduleId": schedule_id, "sequences": sequences, "roomId": room_kos_id},
                  {"tasks": sequences, "roomId": room_kos_id})


def call_ops(schedule_id: str, sequences: list[int]) -> list[OpSpec]:
    """[의사 호출](전체 · 지정) · [다른 원장에게] — (방 → ) 담당자 = 시스템 계정 → 호출(OQ-501: 지정도 같은 요청)."""
    return [
        OpSpec("internal", PATH_ASSIGNEES, {"scheduleId": schedule_id, "sequences": sequences, "assigneeIds": [SYSTEM]},
               {"tasks": sequences, "assigneesContain": SYSTEM}),
        OpSpec("internal", PATH_CALL, {"scheduleId": schedule_id, "sequences": sequences},
               {"tasks": sequences, "status": "WAITING"}),
    ]


def accept_op(schedule_id: str, sequences: list[int], doctor_kos_id: str) -> OpSpec:
    return OpSpec("internal", PATH_DOCTORS, {"scheduleId": schedule_id, "sequences": sequences, "doctorIds": [doctor_kos_id]},
                  {"tasks": sequences, "doctorsContain": doctor_kos_id, "status": "READY"})


def complete_op(schedule_id: str, sequence: int) -> OpSpec:
    return OpSpec("internal", PATH_COMPLETE, {"scheduleId": schedule_id, "sequences": [sequence], "complete": True},
                  {"tasks": [sequence], "status": "DONE"})


def cancel_tasks_op(schedule_id: str, sequences: list[int]) -> OpSpec:
    """[귀가 대기] ① 남은 비시술 작업(「방 배정」 등) 일괄 취소 — 방 빼기는 시술 현황에서 한다(사용자 결정 · 1차 HAR)."""
    return OpSpec("internal", PATH_CANCEL, {"scheduleId": schedule_id, "sequences": sequences, "reason": "CANCEL"},
                  {"tasks": sequences, "status": "CANCELED"})


def flow_step_op(schedule_id: str, step: str) -> OpSpec:
    return OpSpec("open", PATH_FLOW_STEP, {"scheduleId": schedule_id, "step": step}, {"flowStep": step})


def touches_flow_step(op_path: str) -> bool:
    return op_path == PATH_FLOW_STEP


def touched_sequences(op_body: dict[str, Any]) -> set[int]:
    return set(op_body.get("sequences") or [])


def resolve(value: Any, system_kos_id: str | None) -> Any:
    """본문 · 확인 조건 안의 `$SYSTEM` 을 시스템 계정 id 로 바꾼다."""
    if value == SYSTEM:
        return system_kos_id
    if isinstance(value, list):
        return [resolve(v, system_kos_id) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, system_kos_id) for k, v in value.items()}
    return value
