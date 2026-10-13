"""시안 로직 이식 — 캡처 없이 도는 순수 시험."""

from app.domain import board as B

DR = {"kind": "doctor", "label": "원장 진료", "role": "의사"}
TR = {"kind": "treat", "label": "리쥬란", "role": "코디"}


def _state():
    return {
        "customers": [{"scheduleId": "a", "name": "A", "room": "c01", "order": [DR, TR], "step": 0, "since": 0,
                       "prev": None, "done": False}],
        "staff": [{"staffId": "d", "name": "D", "role": "의사", "queue": [], "home": "office"},
                  {"staffId": "k", "name": "K", "role": "코디", "queue": ["c09"], "home": "desk"}],
        "resv": [], "history": [],
    }


def test_wait_then_consult_then_complete():
    s = _state()
    assert B.status_of(s, "c01") == {"key": "wait", "label": "원장 대기"}
    s = B.commit(s, B.assign("d", "c01"), 1000)
    assert B.status_of(s, "c01") == {"key": "consult", "label": "원장 진료"}
    assert s["customers"][0]["since"] == 1000  # 상태 바뀌면 타이머 리셋
    assert s["staff"][1]["queue"] == []  # 고객 없는 방은 큐에서 정리
    s = B.commit(s, B.complete("d", "c01"), 2000)
    assert s["customers"][0]["step"] == 1
    assert B.status_of(s, "c01") == {"key": "wait", "label": "코디 대기 · 리쥬란"}
    assert s["history"][-1]["kind"] == "doctor" and s["history"][-1]["completedAt"] == 2000


def test_complete_wrong_role_only_dequeues():
    s = B.commit(_state(), B.assign("k", "c01"), 1)
    s = B.commit(s, B.complete("k", "c01"), 2)
    assert s["customers"][0]["step"] == 0 and s["staff"][1]["queue"] == []


def test_sleep_returns_to_prev():
    s = _state()
    s["customers"][0]["order"] = [{"kind": "sleep", "label": "수면", "role": "의사"}]
    s = B.commit(s, B.place("a", "s01"), 1)
    assert s["customers"][0]["prev"] == "c01"
    s = B.commit(s, B.assign("d", "s01"), 2)
    s = B.commit(s, B.complete("d", "s01"), 3)
    assert s["customers"][0]["done"] is True
