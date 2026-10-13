"""시드 스냅샷 ↔ 상태. 스냅샷에는 시각을 「저장 순간 − 오프셋(초)」으로만 둔다(SPEC-001 §6 — 0.1.0 §4.2 와 같은 방식).

초기화 때 모든 시각을 「지금 − 오프셋」으로 다시 계산한다 — 시연 시각과 상관없이 경과 타이머가 저장 때와 같게 보인다.
개원 전 시드(build)는 시각 값이 하나도 없다.
"""

import copy

TIME_FIELDS = {
    "customers": ("since", "receptionAt", "completedAt"),
    "steps": ("assignedAt", "startedAt", "endedAt"),
    "log": ("at",),
}


def state_to_snapshot(state: dict, base_ms: int) -> dict:
    s = copy.deepcopy(state)
    for coll, fields in TIME_FIELDS.items():
        for row in s.get(coll, []):
            for f in fields:
                v = row.pop(f, None)
                row[f + "Offset"] = None if v is None else round((base_ms - v) / 1000)
    return s


def snapshot_to_state(snap_state: dict, now_ms: int) -> dict:
    s = copy.deepcopy(snap_state)
    for coll, fields in TIME_FIELDS.items():
        rows = s.setdefault(coll, [])
        for row in rows:
            for f in fields:
                off = row.pop(f + "Offset", None)
                row[f] = None if off is None else now_ms - off * 1000
    s.setdefault("stepSeq", 0)
    return s
