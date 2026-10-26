"""SPEC-004 WP1 — 계정 · 권한(§3 · §8.1): 역할 행렬(3 × 8 + 순서) · 수락 규칙 · 토큰 · 계정 · actor."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.service.auth import _b64, _unb64
from tests.conftest import PW, make_settings
from tests.helpers import T0, seed_staff, seed_visit

IDS = {"admin": "admin1", "doctor": "doctor1", "nurse": "nurse1"}


@pytest.fixture
def env(tmp_path):
    s = make_settings(tmp_path, ccc_admin_id=IDS["admin"], ccc_doctor_id=IDS["doctor"], ccc_doctor_kos_account_id="doc-a",
                      ccc_nurse_id=IDS["nurse"], ccc_nurse_name="간호 A")
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        c.clock.set(T0)
        staff = seed_staff(c.repo)
        c.accounts.sync()  # 직원 조회 뒤와 같은 자리
        yield client, c, staff


def login(client, role):
    body = client.post("/api/auth/login", json={"id": IDS[role], "password": PW[role]}).json()
    return {"Authorization": f"Bearer {body['token']}"}, body


def counts(c):
    with c.repo.tx() as tx:
        return len(tx.events()), len(tx.ops()), len(tx.world().calls), len(tx.world().accepts)


# ------------------------------------------------------------------ 역할 행렬(3 × 8)
OPS = ["anes_start", "anes_end", "call", "reassign", "accept", "start", "finish", "home"]


def prepare(c, staff, n, op):
    """그 조작이 성공할 수 있는 상태의 카드를 만든다 → (경로, 본문)."""
    v = seed_visit(c.repo, n, procs=1, doctors={1: [staff["A"]]})
    vid, pid = v["visit"], v["procs"][0]
    a = c.actions
    if op == "anes_start":
        return f"/api/visits/{vid}/anesthesia/start", None
    if op == "anes_end":
        a.anesthesia_start("setup", vid)
        return f"/api/visits/{vid}/anesthesia/end", None
    if op == "call":
        return f"/api/visits/{vid}/calls", {"procedureIds": [pid], "target": {"kind": "all"}}
    if op == "reassign":
        call = a.create_call("setup", vid, [pid], "one", staff["A"])
        return f"/api/calls/{call}/reassign-all", None
    if op == "accept":
        call = a.create_call("setup", vid, [pid], "all", None)
        return f"/api/calls/{call}/accept", {"doctorId": staff["A"]}
    if op == "start":
        return f"/api/procedures/{pid}/start", None
    if op == "finish":
        a.start("setup", pid)
        return f"/api/procedures/{pid}/finish", None
    a.start("setup", pid)
    a.finish("setup", pid)
    return f"/api/visits/{vid}/home", None


@pytest.mark.parametrize("role", ["admin", "doctor", "nurse"])
def test_role_matrix(env, role):
    client, c, staff = env
    auth, _ = login(client, role)
    for n, op in enumerate(OPS, start=1):
        path, body = prepare(c, staff, n, op)
        before = counts(c)
        r = client.post(path, json=body, headers=auth)
        if role == "nurse" and op == "accept":
            assert (r.status_code, r.json()["error"]["code"]) == (403, "role_forbidden"), op
            assert counts(c) == before  # 403 이면 DB · event_log · kos_op 변화 0
        else:
            assert r.status_code == 200, (role, op, r.json())
    # 조회 · SSE 도 세 역할 모두
    assert client.get("/api/board", headers=auth).status_code == 200
    # 카드 순서(PUT /api/board/order · SPEC-004 §3.4 표 줄) — 세 역할 모두 · actor = 로그인 아이디
    ids = [x["visitId"] for x in client.get("/api/board", headers=auth).json()["cards"] if x["state"] != "home"]
    r = client.put("/api/board/order", json={"visitIds": ids[::-1]}, headers=auth)
    assert r.status_code == 200 and r.json() == {"ok": True, "visitIds": ids[::-1]}, (role, r.json())
    with c.repo.tx() as tx:
        assert tx.events("board_order")[-1]["actor"] == IDS[role]


def test_forbidden_before_conflict_and_not_found(env):
    client, c, staff = env
    v = seed_visit(c.repo, 1, procs=1)
    call = c.actions.create_call("setup", v["visit"], [v["procs"][0]], "all", None)
    nurse, _ = login(client, "nurse")
    doctor, _ = login(client, "doctor")
    # 이미 받을 것이 없는 호출(409 자리)이어도 역할 403 이 먼저
    c.actions.accept(c.auth.verify(login(client, "admin")[1]["token"]), call, staff["A"])
    r = client.post(f"/api/calls/{call}/accept", json={}, headers=nurse)
    assert (r.status_code, r.json()["error"]["code"]) == (403, "role_forbidden")
    # 없는 호출(404 자리)이어도 요청만 보고 아는 403 이 먼저
    r = client.post("/api/calls/999/accept", json={"doctorId": staff["B"]}, headers=doctor)
    assert (r.status_code, r.json()["error"]["code"]) == (403, "doctor_forbidden")
    r = client.post("/api/calls/999/accept", json={}, headers=doctor)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")


# ------------------------------------------------------------------ 수락 규칙(§3.4)
def code(r):
    return r.status_code, r.json().get("error", {}).get("code")


def test_accept_rules(env):
    client, c, staff = env
    doctor, me = login(client, "doctor")
    admin, _ = login(client, "admin")
    nurse, _ = login(client, "nurse")
    assert me["role"] == "doctor" and me["staffId"] == staff["A"]

    def new_call(n, kind="all", target=None):
        v = seed_visit(c.repo, n, procs=1)
        return c.actions.create_call("setup", v["visit"], [v["procs"][0]], kind, target), v["procs"][0]

    call, pid = new_call(1)  # ① doctor 본문 없음 → 자기 원장
    assert client.post(f"/api/calls/{call}/accept", json={}, headers=doctor).json() == {"acceptedProcedureIds": [pid]}
    with c.repo.tx() as tx:
        assert tx.world().accepts[-1].doctor_staff_id == staff["A"]
    call, pid = new_call(2)  # ② doctor 자기와 같음
    assert client.post(f"/api/calls/{call}/accept", json={"doctorId": staff["A"]}, headers=doctor).status_code == 200
    call, _ = new_call(3)  # ③ doctor 자기와 다름
    assert code(client.post(f"/api/calls/{call}/accept", json={"doctorId": staff["B"]}, headers=doctor)) == (
        403, "doctor_forbidden")
    call, _ = new_call(4, "one", staff["B"])  # ④ 남의 지정 호출
    assert code(client.post(f"/api/calls/{call}/accept", json={}, headers=doctor)) == (403, "not_your_call")
    call, _ = new_call(5)  # ⑥ admin doctorId 없음 → 400
    assert code(client.post(f"/api/calls/{call}/accept", json={}, headers=admin)) == (400, "invalid_request")
    call, _ = new_call(6, "one", staff["B"])  # ⑦ admin 지정 불일치 → 409
    assert code(client.post(f"/api/calls/{call}/accept", json={"doctorId": staff["C"]}, headers=admin)) == (
        409, "doctor_mismatch")
    call, _ = new_call(7)  # ⑧ nurse
    assert code(client.post(f"/api/calls/{call}/accept", json={"doctorId": staff["A"]}, headers=nurse)) == (
        403, "role_forbidden")
    # ⑤ 자기 원장이 원장 목록에 없음(비활성 등) → 409 doctor_not_listed(계정은 그대로라 로그인은 유효)
    with c.repo.tx() as tx:
        tx.con.execute("UPDATE staff SET is_doctor = 0 WHERE id = ?", (staff["A"],))
    assert code(client.post(f"/api/calls/{call}/accept", json={}, headers=doctor)) == (409, "doctor_not_listed")


# ------------------------------------------------------------------ 토큰(§3.2)
def test_token_claims_and_db_checks(env):
    client, c, staff = env
    doctor, body = login(client, "doctor")
    claims = json.loads(_unb64(body["token"].rsplit(".", 1)[0]))
    assert claims["sub"] == IDS["doctor"] and claims["role"] == "doctor" and claims["staffId"] == staff["A"]
    assert client.get("/api/auth/me", headers=doctor).json() == {"id": IDS["doctor"], "role": "doctor", "name": "가 원장",
                                                                  "staffId": staff["A"]}
    # DB 역할이 토큰과 다르면 401
    with c.repo.tx() as tx:
        tx.con.execute("UPDATE account SET role = 'nurse' WHERE login_id = ?", (IDS["doctor"],))
    assert client.get("/api/auth/me", headers=doctor).status_code == 401
    # 비활성 → 401
    nurse, _ = login(client, "nurse")
    with c.repo.tx() as tx:
        tx.con.execute("UPDATE account SET active = 0 WHERE login_id = ?", (IDS["nurse"],))
    assert client.get("/api/board", headers=nurse).status_code == 401
    # 없는 계정(서명은 맞음) → 401
    forged = _b64(json.dumps({"sub": "ghost", "role": "admin", "staffId": None, "exp": 9_999_999_999}).encode())
    ghost = {"Authorization": f"Bearer {forged}.{c.auth._sign(forged)}"}
    assert client.get("/api/auth/me", headers=ghost).status_code == 401
    # SSE 도 같은 검증 — 세 역할 모두 연결(토큰이 맞으면 401 아님)
    admin, ab = login(client, "admin")
    assert c.auth.verify(ab["token"]).role == "admin"


def test_login_response_and_password_accounts(env):
    """OQ-601 — 비밀번호가 있는 계정(어드민 · PoC 의사 · 간호사)만 로그인 · 그 밖 원장은 해시 없음 → 401."""
    client, c, staff = env
    _, body = login(client, "admin")
    assert set(body) == {"token", "expiresAt", "id", "role", "name", "staffId"} and body["staffId"] is None
    assert login(client, "nurse")[1]["name"] == "간호 A" and login(client, "doctor")[1]["name"] == "가 원장"
    with c.repo.tx() as tx:
        hashed = {a.login_id: a.password_hash for a in tx.accounts()}
    assert hashed[f"doctor-{staff['B']}"] is None and hashed[IDS["doctor"]].startswith("$2")  # bcrypt
    assert PW["doctor"] not in json.dumps(hashed)  # 평문 0
    r = client.post("/api/auth/login", json={"id": f"doctor-{staff['B']}", "password": ""})
    assert (r.status_code, r.json()["error"]["code"]) == (401, "invalid_credentials")
    assert client.get("/api/auth/accounts").status_code == 404  # 공개 계정 목록 제거
    c.accounts.sync()  # env 가 같으면 해시를 다시 만들지 않는다
    with c.repo.tx() as tx:
        assert tx.account(IDS["doctor"]).password_hash == hashed[IDS["doctor"]]


# ------------------------------------------------------------------ 계정(§3.1)
def test_doctor_rows_follow_doctor_list(env):
    client, c, staff = env
    with c.repo.tx() as tx:
        docs = {a.staff_id: a for a in tx.accounts() if a.role == "doctor"}
    assert set(docs) == {staff["A"], staff["B"], staff["C"]}  # 원장 목록 한 명당 1행(시스템 · 마취용 · 비활성 제외)
    assert [a.card for a in docs.values()].count(True) == 1 and docs[staff["A"]].login_id == IDS["doctor"]
    with c.repo.tx() as tx:  # B 가 원장 목록에서 빠짐
        tx.con.execute("UPDATE staff SET active = 0 WHERE id = ?", (staff["B"],))
        tx.set_doctor_flags("sys-0", {"anes-0"})
    c.accounts.sync()
    with c.repo.tx() as tx:
        b = next(a for a in tx.accounts() if a.staff_id == staff["B"])
    assert b.active is False  # 행은 남김


def test_no_env_no_login(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, ccc_admin_password=""))) as client:  # 비밀번호 env 가 비면 못 들어온다
        assert client.post("/api/auth/login", json={"id": "tester", "password": ""}).status_code == 401


def test_doctor_card_not_made_when_kos_account_not_listed(tmp_path):
    s = make_settings(tmp_path, ccc_admin_id="a", ccc_doctor_id="d", ccc_doctor_kos_account_id="anes-0")  # 제외 계정
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        seed_staff(c.repo)
        c.accounts.sync()
        r = client.post("/api/auth/login", json={"id": "d", "password": PW["doctor"]})
        assert r.status_code == 401  # 의사 계정(카드)이 없다


# ------------------------------------------------------------------ actor(§3.5)
def test_actor_is_login_id_and_accept_by_role(env):
    client, c, staff = env
    v = seed_visit(c.repo, 1, procs=1, doctors={1: [staff["A"]]})
    nurse, _ = login(client, "nurse")
    doctor, _ = login(client, "doctor")
    admin, _ = login(client, "admin")
    client.post(f"/api/visits/{v['visit']}/anesthesia/start", headers=nurse)
    call = client.post(f"/api/visits/{v['visit']}/calls", json={"procedureIds": v["procs"], "target": {"kind": "all"}},
                       headers=admin).json()["callId"]
    client.post(f"/api/calls/{call}/accept", json={}, headers=doctor)
    with c.repo.tx() as tx:
        ev = tx.events()
    assert [(e["type"], e["actor"]) for e in ev] == [("anes_start", IDS["nurse"]), ("call_create", IDS["admin"]),
                                                    ("call_accept", IDS["doctor"])]
    assert ev[-1]["payload"]["byRole"] == "doctor"
