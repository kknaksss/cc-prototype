"""읽기 · 조작 API · 로그인 · 초기화 · seed save — SPEC-001 §4.2 · §4.3 · §5 · §6."""

import json

import pytest


def _board(client):
    return client.get("/api/board").json()


def _staff(board, name_role):
    return next(s for s in board["staff"] if s["role"] == name_role)


def _customer(board, pred):
    return next(c for c in board["customers"] if pred(c))


def _doctor_wait(board):
    """원장 진료 단계에서 원장을 기다리는 고객."""
    return _customer(board, lambda c: not c["done"] and c["step"] < len(c["order"])
                     and c["order"][c["step"]]["kind"] == "doctor" and c["room"] != "lounge")


def test_board_shape(client):
    b = _board(client)
    assert set(b) >= {"customers", "staff", "resv", "rooms", "version"}
    c = b["customers"][0]
    assert set(c) >= {"scheduleId", "name", "room", "order", "step", "since", "prev", "done"}
    assert all(isinstance(x["since"], int) for x in b["customers"] if not x["done"])
    assert len(b["rooms"]) == 27  # 시안 LAYOUT 그대로 and {"id", "name"} <= set(b["rooms"][0])


def test_login_and_staff_list(client):
    accounts = client.get("/api/staff").json()
    assert accounts[0] == {"staffId": "desk", "name": "데스크", "role": "데스크"}
    assert {a["role"] for a in accounts[1:]} == {"의사", "코디"}
    assert client.post("/api/login", json={"staffId": "desk", "password": "x"}).json()["home"] == "/desk"
    doc = next(a for a in accounts if a["role"] == "의사")
    assert client.post("/api/login", json={"staffId": doc["staffId"]}).json() == {**doc, "home": "/staff"}
    r = client.post("/api/login", json={"staffId": "nobody"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "staff_not_found"
    r = client.post("/api/login", json={})
    assert r.status_code == 400 and "error" in r.json()


def test_assign_then_doctor_home(client):
    b = _board(client)
    cust = _doctor_wait(b)
    free_doc = next(s for s in b["staff"] if s["role"] == "의사" and not s["queue"])
    v0 = b["version"]
    r = client.post("/api/board/assign", json={"staffId": free_doc["staffId"], "room": cust["room"]})
    assert r.status_code == 200 and r.json()["version"] == v0 + 1
    home = client.get(f"/api/staff/{free_doc['staffId']}/home").json()
    assert home["current"]["scheduleId"] == cust["scheduleId"]
    assert home["current"]["state"] == "consult"
    # 바쁜 의사에게 배정하면 「다음」에 뜬다
    other = next(c for c in b["customers"] if not c["done"] and c["room"] not in ("lounge", cust["room"]))
    client.post("/api/board/assign", json={"staffId": free_doc["staffId"], "room": other["room"]})
    home = client.get(f"/api/staff/{free_doc['staffId']}/home").json()
    assert home["next"]["scheduleId"] == other["scheduleId"]
    assert "later" not in json.dumps(home)  # 예정 없음(D-24)


def test_complete_writes_history(client):
    b = _board(client)
    cust = _doctor_wait(b)
    doc = next(s for s in b["staff"] if s["role"] == "의사" and not s["queue"])
    client.post("/api/board/assign", json={"staffId": doc["staffId"], "room": cust["room"]})
    client.post("/api/board/complete", json={"staffId": doc["staffId"], "room": cust["room"]})
    b2 = _board(client)
    after = _customer(b2, lambda c: c["scheduleId"] == cust["scheduleId"])
    assert after["step"] == cust["step"] + 1
    home = client.get(f"/api/staff/{doc['staffId']}/home").json()
    assert cust["scheduleId"] in [d["scheduleId"] for d in home["done"]]
    assert _staff(b2, "의사") and doc["staffId"] not in [s["staffId"] for s in b2["staff"] if cust["room"] in s["queue"]]


def test_doctor_start_finish(client):
    b = _board(client)
    cust = _doctor_wait(b)
    doc = next(s for s in b["staff"] if s["role"] == "의사")
    client.post(f"/api/staff/{doc['staffId']}/start", json={"scheduleId": cust["scheduleId"]})
    b2 = _board(client)
    assert next(s for s in b2["staff"] if s["staffId"] == doc["staffId"])["queue"][0] == cust["room"]
    detail = client.get(f"/api/patients/{cust['scheduleId']}").json()
    assert detail["board"]["state"] == "consult"
    client.post(f"/api/staff/{doc['staffId']}/finish", json={"scheduleId": cust["scheduleId"]})
    after = next(c for c in _board(client)["customers"] if c["scheduleId"] == cust["scheduleId"])
    assert after["step"] == cust["step"] + 1  # 원장 진료 완료 → 다음 단계 직군 대기(그 방에 다른 직원이 있으면 시안대로 「시술」)
    assert doc["staffId"] not in [s["staffId"] for s in _board(client)["staff"] if cust["room"] in s["queue"]]
    codi = next(s for s in b["staff"] if s["role"] == "코디")
    r = client.post(f"/api/staff/{codi['staffId']}/start", json={"scheduleId": cust["scheduleId"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_doctor"


def test_check_in_place_undo(client):
    b = _board(client)
    booked = next(r for r in b["resv"] if r["st"] == "booked")
    r = client.post("/api/board/check-in", json={"scheduleId": booked["scheduleId"]})
    assert r.status_code == 200
    b2 = _board(client)
    c = _customer(b2, lambda x: x["scheduleId"] == booked["scheduleId"])
    assert c["room"] == "lounge" and c["step"] == 0 and c["order"]
    assert next(x for x in b2["resv"] if x["scheduleId"] == booked["scheduleId"])["st"] == "checked"
    again = client.post("/api/board/check-in", json={"scheduleId": booked["scheduleId"]})
    assert again.status_code == 409

    empty = next(rm["id"] for rm in b2["rooms"] if rm["id"].startswith("c")
                 and not any(x["room"] == rm["id"] and not x["done"] for x in b2["customers"]))
    v = client.post("/api/board/place", json={"scheduleId": c["scheduleId"], "room": empty}).json()["version"]
    assert _customer(_board(client), lambda x: x["scheduleId"] == c["scheduleId"])["room"] == empty
    r = client.post("/api/board/undo", json={"version": v})
    assert r.status_code == 200 and r.json()["version"] == v + 1
    assert _customer(_board(client), lambda x: x["scheduleId"] == c["scheduleId"])["room"] == "lounge"
    assert client.post("/api/board/undo", json={"version": v + 1}).status_code == 409  # 마지막 변경만


def test_walk_in(client):
    order = [{"kind": "consult", "label": "상담", "role": "상담사"}]
    r = client.post("/api/board/check-in", json={"scheduleId": None, "name": "현장 고객 1", "order": order})
    assert r.status_code == 200
    b = _board(client)
    c = _customer(b, lambda x: x["scheduleId"] == "walkin-1")
    assert c["room"] == "lounge" and c["order"] == order
    assert any(x["scheduleId"] == "walkin-1" and x["procedure"] == "현장 접수" for x in b["resv"])
    detail = client.get("/api/patients/walkin-1").json()
    assert detail["name"] == "현장 고객 1" and detail["route"][0]["task"] == "상담"
    assert client.post("/api/board/check-in", json={"scheduleId": None, "order": order}).status_code == 400


def test_errors(client):
    r = client.post("/api/board/assign", json={"staffId": "nobody", "room": "c01"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "staff_not_found"
    r = client.post("/api/board/place", json={"scheduleId": "x", "room": "zz"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unknown_room"
    assert client.get("/api/patients/nope").status_code == 404


def test_reset_returns_to_seed(client):
    before = _board(client)
    cust = _doctor_wait(before)
    doc = next(s for s in before["staff"] if s["role"] == "의사")
    client.post("/api/board/assign", json={"staffId": doc["staffId"], "room": cust["room"]})
    client.post("/api/board/complete", json={"staffId": doc["staffId"], "room": cust["room"]})
    r = client.post("/api/admin/reset")
    assert r.status_code == 200
    after = _board(client)
    strip = lambda b: [{k: v for k, v in c.items() if k != "since"} for c in b["customers"]]  # noqa: E731
    assert strip(after) == strip(before) and after["staff"] == before["staff"] and after["resv"] == before["resv"]
    assert after["version"] > before["version"]
    # 경과(지금 − since)는 시드 때와 같게(초 단위 반올림 · 시험 실행 시간 허용)
    for a, b0 in zip(after["customers"], before["customers"], strict=True):
        if not a["done"]:
            assert abs((after["now"] - a["since"]) - (before["now"] - b0["since"])) < 5000


def test_seed_save_then_reset(client, container):
    b = _board(client)
    cust = _doctor_wait(b)
    doc = next(s for s in b["staff"] if s["role"] == "의사" and not s["queue"])
    client.post("/api/board/assign", json={"staffId": doc["staffId"], "room": cust["room"]})
    from app.seed.__main__ import _backup, _write

    path = container.settings.seed_path
    old = _backup(path)
    _write(path, container.board.snapshot())
    assert old is not None and old.exists()
    client.post("/api/board/remove-staff", json={"staffId": doc["staffId"], "room": cust["room"]})
    client.post("/api/admin/reset")
    saved = next(s for s in _board(client)["staff"] if s["staffId"] == doc["staffId"])
    assert saved["queue"] == [cust["room"]]


@pytest.mark.parametrize("role", ["코디"])
def test_codi_home_matches_board(client, role):
    b = _board(client)
    codi = next(s for s in b["staff"] if s["role"] == role)
    home = client.get(f"/api/staff/{codi['staffId']}/home").json()
    here = {c["scheduleId"]: c for c in b["customers"] if not c["done"]}
    assert {p["scheduleId"] for p in home["patients"]} == set(here)
    assert all(p["room"] == here[p["scheduleId"]]["room"] for p in home["patients"])
    sinces = [p["since"] for p in home["patients"]]
    assert sinces == sorted(sinces)  # 경과 긴 순
    assert sum(home["summary"].values()) == len(here)
