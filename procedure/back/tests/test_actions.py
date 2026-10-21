"""WP2 — 조작 API(§7.3): 전이(§5.10) · 409 코드 표 · event_log · kos_op(보내지는 않음 · §8)."""

import pytest

from app.domain.kos_ops import PATH_ASSIGNEES, PATH_CALL, PATH_COMPLETE, PATH_DOCTORS, PATH_FLOW_STEP, PATH_ROOM, SYSTEM
from tests.helpers import seed_staff, seed_visit


@pytest.fixture
def world(ctr):
    s = seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, doctors={3: [s["C"]]})
    return s, v


def post(client, auth, path, body=None):
    return client.post(path, json=body, headers=auth)


def code(r):
    return r.status_code, r.json().get("error", {}).get("code")


def ops(ctr):
    with ctr.repo.tx() as tx:
        return tx.ops()


def events(ctr):
    with ctr.repo.tx() as tx:
        return [e["type"] for e in tx.events()]


def test_requires_login(client, world):
    _, v = world
    assert client.post(f"/api/visits/{v['visit']}/anesthesia/start").status_code == 401


def test_full_flow(client, auth, ctr, world):
    s, v = world
    vid, (p1, p2, p3) = v["visit"], v["procs"]
    # 마취 시작 · 종료(KOS 없음)
    assert post(client, auth, f"/api/visits/{vid}/anesthesia/start").json() == {"ok": True}
    assert code(post(client, auth, f"/api/visits/{vid}/anesthesia/start")) == (409, "anesthesia_running")
    assert post(client, auth, f"/api/visits/{vid}/anesthesia/end").json() == {"ok": True}
    assert code(post(client, auth, f"/api/visits/{vid}/anesthesia/end")) == (409, "anesthesia_not_running")
    assert ops(ctr) == []
    # 호출 → assignees · call 두 op
    r = post(client, auth, f"/api/visits/{vid}/calls", {"procedureIds": [p1, p2], "target": {"kind": "all"}})
    c1 = r.json()["callId"]
    o = ops(ctr)
    # 방 넣기(카드 방 → 고른 작업) → 담당자 → 호출
    assert [(x.path, x.seq) for x in o] == [(PATH_ROOM, 1), (PATH_ASSIGNEES, 2), (PATH_CALL, 3)]
    assert o[0].body == {"scheduleId": "sch-1", "sequences": [1, 2], "roomId": "room-1"}
    assert o[0].expect == {"tasks": [1, 2], "roomId": "room-1"}
    assert o[1].body == {"scheduleId": "sch-1", "sequences": [1, 2], "assigneeIds": [SYSTEM]}
    assert o[2].expect == {"tasks": [1, 2], "status": "WAITING"} and all(x.status == "pending" for x in o)
    # [시작] 꺼짐(미수락)
    assert code(post(client, auth, f"/api/procedures/{p1}/start")) == (409, "call_not_accepted")
    # 수락
    assert code(post(client, auth, f"/api/calls/{c1}/accept", {"doctorId": s["SYS"]})) == (409, "doctor_not_listed")
    assert post(client, auth, f"/api/calls/{c1}/accept", {"doctorId": s["A"]}).json() == {"acceptedProcedureIds": [p1, p2]}
    assert code(post(client, auth, f"/api/calls/{c1}/accept", {"doctorId": s["A"]})) == (409, "nothing_to_accept")
    acc = ops(ctr)[-1]
    assert acc.path == PATH_DOCTORS and acc.body["doctorIds"] == ["doc-a"] and acc.expect["status"] == "READY"
    # 첫 [시작] → flow-step PROCEDURE
    assert post(client, auth, f"/api/procedures/{p1}/start").json() == {"ok": True, "flowStepChanged": True}
    assert ops(ctr)[-1].path == PATH_FLOW_STEP and ops(ctr)[-1].body == {"scheduleId": "sch-1", "step": "PROCEDURE"}
    assert code(post(client, auth, f"/api/procedures/{p1}/start")) == (409, "procedure_not_waiting")
    assert post(client, auth, f"/api/procedures/{p3}/start").json() == {"ok": True, "flowStepChanged": False}
    # 진행 중 시술은 호출 대상 아님
    r = post(client, auth, f"/api/visits/{vid}/calls", {"procedureIds": [p1], "target": {"kind": "all"}})
    assert code(r) == (409, "procedure_not_waiting")
    # [종료]
    assert code(post(client, auth, f"/api/procedures/{p2}/finish")) == (409, "procedure_not_started")
    assert post(client, auth, f"/api/procedures/{p1}/finish").json() == {"ok": True}
    assert ops(ctr)[-1].path == PATH_COMPLETE and ops(ctr)[-1].body["sequences"] == [1]
    assert code(post(client, auth, f"/api/visits/{vid}/home")) == (409, "procedures_not_done")
    for pid, step in ((p2, "start"), (p2, "finish"), (p3, "finish")):
        assert post(client, auth, f"/api/procedures/{pid}/{step}").status_code == 200
    # [귀가 대기]
    assert post(client, auth, f"/api/visits/{vid}/home").json() == {"ok": True}
    assert ops(ctr)[-1].body == {"scheduleId": "sch-1", "step": "PROCEDURE_DONE"}
    assert code(post(client, auth, f"/api/visits/{vid}/home")) == (409, "visit_home")
    assert code(post(client, auth, f"/api/visits/{vid}/anesthesia/start")) == (409, "visit_home")
    card = client.get("/api/board", headers=auth).json()["cards"][0]
    assert card["state"] == "home" and card["homeAt"] and card["kos"]["status"] == "pending"
    assert events(ctr) == ["anes_start", "anes_end", "call_create", "call_accept", "proc_start", "proc_start", "proc_finish",
                           "proc_start", "proc_finish", "proc_finish", "home"]
    assert [x.seq for x in ops(ctr)] == list(range(1, 10))


def test_designated_call_and_reassign(client, auth, ctr, world):
    s, v = world
    vid, (p1, p2, _) = v["visit"], v["procs"]
    body = {"procedureIds": [p1], "target": {"kind": "one", "doctorId": s["ANES"]}}
    assert code(post(client, auth, f"/api/visits/{vid}/calls", body)) == (409, "doctor_not_listed")
    body["target"]["doctorId"] = s["B"]
    c1 = post(client, auth, f"/api/visits/{vid}/calls", body).json()["callId"]
    assert code(post(client, auth, f"/api/calls/{c1}/accept", {"doctorId": s["A"]})) == (409, "doctor_mismatch")
    c2 = post(client, auth, f"/api/calls/{c1}/reassign-all").json()["callId"]
    assert code(post(client, auth, f"/api/calls/{c1}/reassign-all")) == (409, "nothing_to_accept")
    assert code(post(client, auth, f"/api/calls/{c2}/reassign-all")) == (409, "not_designated_call")
    calls = client.get("/api/board", headers=auth).json()["calls"]
    assert [(c["callId"], c["kind"]) for c in calls] == [(c2, "all")]
    assert post(client, auth, f"/api/calls/{c2}/accept", {"doctorId": s["C"]}).json() == {"acceptedProcedureIds": [p1]}
    assert events(ctr) == ["call_create", "call_reassign_all", "call_accept"]
    # 호출 3(방 · 담당자 · 호출) + 다른 원장에게 3(방은 이미 같음 → confirmed · 안 보냄) + 수락 1
    assert [(o.path == PATH_ROOM, o.status) for o in ops(ctr)][:4] == [(True, "pending"), (False, "pending"), (False, "pending"),
                                                                     (True, "confirmed")]
    assert len(ops(ctr)) == 7
    # 빈 목록 · 남의 시술 · 없는 id
    assert code(post(client, auth, f"/api/visits/{vid}/calls", {"procedureIds": [], "target": {"kind": "all"}})) == (
        409, "no_procedures")
    assert code(post(client, auth, "/api/visits/999/calls", {"procedureIds": [p2], "target": {"kind": "all"}})) == (
        404, "not_found")
    assert code(post(client, auth, "/api/calls/999/accept", {"doctorId": s["A"]})) == (404, "not_found")
    assert code(post(client, auth, f"/api/visits/{vid}/calls", {"procedureIds": "x"})) == (400, "invalid_request")


def test_no_doctor(client, auth, world):
    _, v = world
    assert code(post(client, auth, f"/api/procedures/{v['procs'][0]}/start")) == (409, "no_doctor")
