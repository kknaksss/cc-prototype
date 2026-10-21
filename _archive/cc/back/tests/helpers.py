"""API 시험 도우미."""


def board(client):
    return client.get("/api/board").json()


def ok(r):
    assert r.status_code == 200, r.json()
    return r.json()


def err(r, code):
    assert r.status_code == 400, r.json()
    assert r.json()["error"]["code"] == code, r.json()
    return r.json()


def staff_of(client, role):
    return [s for s in board(client)["staff"] if s["role"] == role]


def customer(client, sid):
    return next(c for c in board(client)["customers"] if c["scheduleId"] == sid)


def booked(client, is_new=True):
    return [r for r in board(client)["resv"] if r["st"] == "booked" and r["isNew"] is is_new]


def check_in(client, sid, steps):
    return ok(client.post("/api/desk/check-in", json={"scheduleId": sid, "steps": steps}))


def place(client, sid, room):
    return client.post("/api/desk/place", json={"scheduleId": sid, "room": room})


def step(client, sid, kind=None, i=0):
    ss = [s for s in customer(client, sid)["steps"] if kind is None or s["kind"] == kind]
    return ss[i]


def assign(client, step_id, staff_id):
    return client.post("/api/desk/assign", json={"stepId": step_id, "staffId": staff_id})


def start(client, staff_id, step_id):
    return client.post(f"/api/staff/{staff_id}/start", json={"stepId": step_id})


def finish(client, staff_id, step_id):
    return client.post(f"/api/staff/{staff_id}/finish", json={"stepId": step_id})


def consult_done(client, sid, room="c01", counselor_id="c2"):
    """접수(상담) → 방 → 상담사 배정 → 시작 · 종료 = 상담 완료 이벤트 적용."""
    check_in(client, sid, [{"kind": "consult"}])
    ok(place(client, sid, room))
    st = step(client, sid, "consult")
    ok(assign(client, st["stepId"], counselor_id))
    ok(start(client, counselor_id, st["stepId"]))
    ok(finish(client, counselor_id, st["stepId"]))
