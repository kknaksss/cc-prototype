"""SPEC-008 §6.1 · §6.2 · §7 외부 인증 · 제한 · 기록 — T23 ~ T28 · T31(+ 보정 1 N1). 키 · 이름 · 이메일은 지어낸 값."""

import logging

import pytest

from tests.conftest import ADMIN
from tests.ext_env import CHARTY, H_CHARTY, H_LINKY, LINKY, ext_calls, make_ext_env

IP = "203.0.113.7"  # 문서용 주소(RFC 5737)
LOOKUP = "/api/ext/customers/lookup"


@pytest.fixture
def env(tmp_path):
    c, fake, client = make_ext_env(tmp_path)
    mono = [5000.0]
    c.ext.rate.now_mono = lambda: mono[0]
    return c, fake, client, mono


def code(r):
    return r.json()["error"]["code"]


# ------------------------------------------------------------------ T23 키 인증
def test_t23_key_cases(env, tmp_path):
    c, fake, cl, _ = env
    bearer = {"Authorization": f"Bearer {cl.post('/api/auth/login', json=ADMIN).json()['token']}"}
    for h in ({}, {"X-Api-Key": ""}, {"X-Api-Key": "wrong"}, {"X-Api-Key": LINKY + " "}, bearer):
        r = cl.get("/api/ext/menu", headers={**h, "CF-Connecting-IP": f"198.51.100.{len(h) + len(str(h))}"})
        assert (r.status_code, code(r)) == (401, "ext_unauthorized")
    assert cl.get("/api/ext/menu", headers=H_LINKY).status_code == 200
    assert cl.get("/api/ext/menu", headers=H_CHARTY).status_code == 200
    assert [x["client"] for x in ext_calls(c) if x["status"] == 200] == ["linky", "charty"]


def test_t23_disabled_client(tmp_path):
    c, fake, cl = make_ext_env(tmp_path, proc_ext_key_charty="")
    r = cl.get("/api/ext/menu", headers=H_CHARTY)
    assert (r.status_code, code(r)) == (401, "ext_unauthorized")
    r = cl.get("/api/ext/menu", headers={"X-Api-Key": ""})
    assert r.status_code == 401  # 빈 env 와 빈 키가 같다고 보지 않는다
    assert cl.get("/api/ext/menu", headers=H_LINKY).status_code == 200


# ------------------------------------------------------------------ T24 직원 API 분리
def test_t24_staff_and_ext_separate(env):
    c, fake, cl, _ = env
    r = cl.get("/api/auth/me", headers=H_LINKY)
    assert r.status_code == 401 and code(r) == "unauthorized"
    token = cl.post("/api/auth/login", json=ADMIN).json()["token"]
    both = {**H_LINKY, "Authorization": f"Bearer {token}"}  # Bearer + 키 = 외부 권한만(직원 경로를 대신 열지 못함)
    assert cl.get("/api/ext/menu", headers=both).status_code == 200
    assert [x["client"] for x in ext_calls(c)][-1] == "linky"
    assert cl.get("/api/board", headers={"Authorization": f"Bearer {token}"}).status_code == 200  # 토큰 자체는 유효
    r = cl.get("/api/board", headers=H_LINKY)
    assert r.status_code == 401 and code(r) == "unauthorized"


# ------------------------------------------------------------------ T25 검사 순서
def test_t25_check_order(env):
    c, fake, cl, mono = env
    # 키 틀림 + 칸 틀림(필수 빠짐 · 모르는 키) → 401
    for body in ({}, {"name": "<이름>", "email": "a@example.com", "zzz": 1}):
        r = cl.post(LOOKUP, json=body, headers={"X-Api-Key": "wrong", "CF-Connecting-IP": "198.51.100.1"})
        assert (r.status_code, code(r)) == (401, "ext_unauthorized")
    # 키 틀림 + JSON 이 아닌 본문 → 400(본문 읽기가 먼저)
    r = cl.post(LOOKUP, content=b"{bad", headers={"X-Api-Key": "wrong", "Content-Type": "application/json",
                                                  "CF-Connecting-IP": "198.51.100.2"})
    assert (r.status_code, code(r)) == (400, "invalid_request")
    # 키 없음 + 없는 경로 → 404
    r = cl.get("/api/ext/nope", headers={"CF-Connecting-IP": "198.51.100.3"})
    assert (r.status_code, code(r)) == (404, "not_found")
    # 한도 초과 + 칸 틀림 → 429
    for _ in range(60):
        assert cl.get("/api/ext/menu", headers=H_LINKY).status_code == 200
    r = cl.post(LOOKUP, json={"zzz": 1}, headers=H_LINKY)
    assert (r.status_code, code(r)) == (429, "too_many_requests")
    # 맞는 키 + 칸 틀림(한도 안) → 400
    r = cl.post(LOOKUP, json={"name": " ", "email": "a@example.com"}, headers=H_CHARTY)
    assert (r.status_code, code(r)) == (400, "invalid_request")
    # IP 차단 중 + 맞는 키 → 429
    for _ in range(10):
        cl.get("/api/ext/menu", headers={"CF-Connecting-IP": IP})
    r = cl.get("/api/ext/menu", headers={**H_CHARTY, "CF-Connecting-IP": IP})
    assert (r.status_code, code(r)) == (429, "too_many_requests")


# ------------------------------------------------------------------ T26 호출 제한
def test_t26_rate_per_key(env):
    c, fake, cl, mono = env
    for _ in range(60):
        assert cl.get("/api/ext/menu", headers=H_LINKY).status_code == 200
    assert cl.get("/api/ext/menu", headers=H_LINKY).status_code == 429
    assert cl.get("/api/ext/menu", headers=H_LINKY).status_code == 429  # 막힌 요청은 세지 않는다
    assert cl.get("/api/ext/menu", headers=H_CHARTY).status_code == 200  # 다른 연동처는 따로
    mono[0] += 60.0
    assert cl.get("/api/ext/menu", headers=H_LINKY).status_code == 200
    blocked = [x for x in ext_calls(c) if x["status"] == 429]
    assert [(x["client"], x["outcome"]) for x in blocked] == [("linky", "too_many_requests")] * 2


def test_t26_401_not_counted_per_key(env):
    c, fake, cl, mono = env
    for i in range(70):  # 틀린 키 401 은 키당 카운터에 세지 않는다(IP 는 따로 · 매번 다른 IP)
        cl.get("/api/ext/menu", headers={"X-Api-Key": "wrong", "CF-Connecting-IP": f"198.51.100.{i}"})
    for _ in range(60):
        assert cl.get("/api/ext/menu", headers=H_LINKY).status_code == 200


# ------------------------------------------------------------------ T27 기록
def test_t27_ext_call_rows_and_privacy(env, caplog):
    c, fake, cl, mono = env
    caplog.set_level(logging.DEBUG)
    name, email = "가나다", "Secret.Person@Example.com"
    fake.visitors_page = {"count": 2, "data": [{"id": "v-1", "name": name, "email": email.lower()},
                                               {"id": "v-2", "name": name, "email": email}]}
    hdr = {**H_LINKY, "CF-Connecting-IP": IP}
    assert cl.get("/api/ext/menu", headers=hdr).status_code == 200
    assert cl.post(LOOKUP, json={"name": name, "email": email}, headers=hdr).status_code == 409
    fake.fail_paths["get-visitors"] = 503
    assert cl.post(LOOKUP, json={"name": name, "email": email}, headers=hdr).status_code == 502
    del fake.fail_paths["get-visitors"]
    assert cl.get("/api/ext/nope", headers=hdr).status_code == 404  # 맞는 키 + 없는 경로
    assert cl.get("/api/ext/customers/a@example.com", headers={**hdr, "CF-Connecting-IP": "198.51.100.9"}).status_code == 404
    assert cl.get("/api/ext/menu", headers={"X-Api-Key": LINKY[:-1] + "x", "CF-Connecting-IP": IP}).status_code == 401
    rows = ext_calls(c)
    assert [(x["client"], x["endpoint"], x["status"], x["outcome"]) for x in rows] == [
        ("linky", "GET /api/ext/menu", 200, "ok"),
        ("linky", "POST /api/ext/customers/lookup", 409, "customer_ambiguous"),
        ("linky", "POST /api/ext/customers/lookup", 502, "kos_unavailable"),
        (None, "GET (unknown)", 404, "not_found"),
        (None, "GET (unknown)", 404, "not_found"),  # 다른 IP
        (None, "GET /api/ext/menu", 401, "ext_unauthorized")]
    dump = repr(rows) + caplog.text
    for secret in (name, email, email.lower(), "a@example.com", LINKY, CHARTY, IP, "198.51.100.9"):
        assert secret not in dump, secret
    assert all(set(x) == {"id", "at", "client", "endpoint", "status", "outcome"} for x in rows)


def test_t27_clientless_collapsed_per_ip_minute(env):
    """연동처 없는 오류 응답(401 · 404 · 깨진 JSON 400 · 405) — 같은 IP · 같은 결과 1분 1줄(보정 1 N1)."""
    c, fake, cl, mono = env
    cases = [lambda h: cl.get("/api/ext/menu", headers=h),
             lambda h: cl.post(LOOKUP, content=b"{bad", headers={**h, "Content-Type": "application/json"}),
             lambda h: cl.get(LOOKUP, headers=h)]
    for n, call in enumerate(cases):
        ip = f"198.51.100.{n + 20}"
        for _ in range(5):
            call({"CF-Connecting-IP": ip})
        mono[0] += 1
    rows = ext_calls(c)
    assert [(x["client"], x["status"], x["outcome"]) for x in rows] == [
        (None, 401, "ext_unauthorized"), (None, 400, "invalid_request"), (None, 405, "http_error")]
    mono[0] += 60.0
    cl.get("/api/ext/menu", headers={"CF-Connecting-IP": "198.51.100.20"})
    assert len(ext_calls(c)) == 4


def test_t27_write_failure_keeps_response(env, monkeypatch):
    c, fake, cl, _ = env

    def boom(*a, **k):
        raise RuntimeError("db")

    monkeypatch.setattr(c.repo, "tx", boom)
    r = cl.get("/api/ext/customers/lookup", headers=H_LINKY)
    assert r.status_code == 405


# ------------------------------------------------------------------ T28 캐시 헤더
def test_t28_no_store(env):
    c, fake, cl, _ = env
    for r in (cl.get("/api/ext/menu", headers=H_LINKY), cl.get("/api/ext/menu"), cl.get("/api/ext/nope"),
              cl.post(LOOKUP, json={}, headers=H_LINKY)):
        assert r.headers["cache-control"] == "no-store"
    assert "cache-control" not in cl.get("/api/health").headers


# ------------------------------------------------------------------ T31 키 없는 거절 IP 제한
def test_t31_ip_block(env, caplog):
    c, fake, cl, mono = env
    caplog.set_level(logging.DEBUG)
    a = {"CF-Connecting-IP": IP}
    for i in range(10):  # 401 · 404 · 깨진 본문 400 · 405 섞어 10번
        [lambda: cl.get("/api/ext/menu", headers=a), lambda: cl.get("/api/ext/nope", headers=a),
         lambda: cl.post(LOOKUP, content=b"x", headers={**a, "Content-Type": "application/json"}),
         lambda: cl.get(LOOKUP, headers=a)][i % 4]()
    r = cl.get("/api/ext/menu", headers={**H_LINKY, **a})
    assert (r.status_code, code(r)) == (429, "too_many_requests")
    assert cl.get("/api/ext/menu", headers={**H_LINKY, "CF-Connecting-IP": "198.51.100.77"}).status_code == 200
    # CF-Connecting-IP 가 있으면 그 값으로 센다(X-Forwarded-For 는 뒤) — CF 가 다르면 열림 · XFF 만 같으면 같은 IP
    assert cl.get("/api/ext/menu", headers={**H_LINKY, "CF-Connecting-IP": "198.51.100.78",
                                            "X-Forwarded-For": IP}).status_code == 200
    assert cl.get("/api/ext/menu", headers={**H_LINKY, "X-Forwarded-For": IP}).status_code == 429
    mono[0] += 59.0
    assert cl.get("/api/ext/menu", headers={**H_LINKY, **a}).status_code == 429  # 막힌 요청은 세지 않음
    mono[0] += 1.5
    assert cl.get("/api/ext/menu", headers={**H_LINKY, **a}).status_code == 200
    rows = ext_calls(c)
    assert [x for x in rows if x["status"] == 429] and all(x["client"] is None for x in rows if x["status"] == 429)
    assert IP not in repr(rows) + caplog.text


def test_t31_valid_key_errors_not_counted(env):
    """연동처가 정해진 오류(400 칸 · 404 고객 없음)는 IP 카운트에 넣지 않는다."""
    c, fake, cl, _ = env
    fake.visitors_page = {"count": 0, "data": []}
    h = {**H_LINKY, "CF-Connecting-IP": IP}
    for _ in range(12):
        assert cl.post(LOOKUP, json={"name": "<이름>", "email": "a@example.com"}, headers=h).status_code == 404
    assert cl.get("/api/ext/menu", headers=h).status_code == 200


# ------------------------------------------------------------------ 수정 1 W5 동시 요청 · W6 처리 못한 예외
def test_w5_concurrent_requests_never_exceed_limit(env, monkeypatch):
    """150 동시 요청 · 카운터 안에 지연을 넣어도 200 은 정확히 60(카운터 = 이벤트 루프 한 스레드)."""
    import asyncio
    import time

    import httpx

    c, fake, cl, mono = env
    rate = c.ext.rate
    orig = rate._recent

    def slow(key):
        hits = orig(key)
        time.sleep(0.001)  # 끼어들 틈을 넓힌다
        return hits

    monkeypatch.setattr(rate, "_recent", slow)

    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=cl.app), base_url="http://t") as ac:
            return await asyncio.gather(*(ac.get("/api/ext/menu", headers=H_LINKY) for _ in range(150)))

    codes = [r.status_code for r in asyncio.run(main())]
    assert (codes.count(200), codes.count(429)) == (60, 90)


def test_w6_unhandled_error_logged_and_no_store(env, monkeypatch, caplog):
    c, fake, cl, _ = env

    def boom():
        raise RuntimeError("비밀 문구 a@example.com")

    monkeypatch.setattr(c.ext, "menu", boom)
    caplog.set_level(logging.DEBUG)
    r = cl.get("/api/ext/menu", headers=H_LINKY)
    assert r.status_code == 500 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"error": {"code": "internal_error", "message": "서버 오류가 났어요"}}
    assert [(x["client"], x["endpoint"], x["status"], x["outcome"]) for x in ext_calls(c)] == [
        ("linky", "GET /api/ext/menu", 500, "internal_error")]
    assert "비밀 문구" not in caplog.text and "a@example.com" not in caplog.text and "RuntimeError" in caplog.text
