"""시드 스냅샷 ↔ 상태. 스냅샷에는 시각을 「기준 시각 − 오프셋(초)」으로만 둔다(SPEC-001 §4.1-4 · §4.2).

초기화 때 모든 시각을 「지금 − 오프셋」으로 다시 계산한다 — 시연 시각과 상관없이 경과 타이머가 시드 때와 같게 보인다.
"""

import copy


def _off(base_ms: int, ms: int | None) -> int | None:
    return None if ms is None else round((base_ms - ms) / 1000)


def _abs(now_ms: int, off: int | None) -> int | None:
    return None if off is None else now_ms - off * 1000


def state_to_snapshot(state: dict, base_ms: int) -> dict:
    s = copy.deepcopy(state)
    for c in s["customers"]:
        c["sinceOffset"] = _off(base_ms, c.pop("since", None))
        c["doneAtOffset"] = _off(base_ms, c.pop("doneAt", None))
    for h in s["history"]:
        h["startedAtOffset"] = _off(base_ms, h.pop("startedAt", None))
        h["completedAtOffset"] = _off(base_ms, h.pop("completedAt", None))
    return s


def snapshot_to_state(snap_state: dict, now_ms: int) -> dict:
    s = copy.deepcopy(snap_state)
    for c in s["customers"]:
        c["since"] = _abs(now_ms, c.pop("sinceOffset", None))
        c["doneAt"] = _abs(now_ms, c.pop("doneAtOffset", None))
    for h in s["history"]:
        h["startedAt"] = _abs(now_ms, h.pop("startedAtOffset", None))
        h["completedAt"] = _abs(now_ms, h.pop("completedAtOffset", None))
    return s
