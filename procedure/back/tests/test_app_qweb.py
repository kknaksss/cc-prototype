"""WORK-010 WP-BE — 고객 문진 웹(SPEC-006 §10.1): 토큰 · 공개 GET · POST · 다시 띄우기 · pending · 상세 ·
속도 제한 · 로그 · 경로."""

import asyncio
import hashlib
import json
import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fake_kos import visitor
from tests.resv_env import T0, load, make_env, rid_of, run
from tests.test_push import tok

LOGINS = dict(ccc_coord_id="coord1", ccc_coord_password="pw-c", proc_session_secret="s", proc_bcrypt_rounds=4)
URL = "/api/public/questionnaire"


@pytest.fixture
def env(tmp_path):
    c, fake, _ = make_env(tmp_path, **LOGINS)
    fake.visitors["vis-1"] = visitor("vis-1", name="고객이름", language="zh-CN", nationality="TW",
                                     phoneNumber={"countryCode": "82", "phoneNumber": "1012345678"})
    fake.add_resv("s1", "vis-1", flow="RECEPTION", status="IN_PROGRESS")
    load(c)
    with c.repo.tx() as tx:
        coord = tx.account("coord1")
    client = TestClient(create_app(c.settings, container=c))  # lifespan 없음(조회 루프 안 띄움)
    login = client.post("/api/auth/login", json={"id": "coord1", "password": "pw-c"}).json()
    staff = {"Authorization": f"Bearer {login['token']}"}
    mono = [1000.0]
    c.questionnaire.rate.now_mono = lambda: mono[0]
    yield c, fake, client, coord, rid_of(c, "s1"), staff, mono


def new_q(c, coord, rid, device=None):
    out = c.display.create(coord, rid, "questionnaire", device)
    return out, out["qrUrl"].split("#", 1)[1]


def h(token):
    return {"X-Questionnaire-Token": token}


def body(**kw):
    b = {"language": "ja", "name": "고객 문진", "dateOfBirth": "19900102", "gender": "FEMALE",
         "phone": {"countryCode": "82", "phoneNumber": "01098765432"}, "address": "[ccc 시험] 주소", "addressDetail": "101",
         "agreements": [{"id": "ag-1", "type": "PERSONAL_INFORMATION", "required": True, "agreed": True}],
         "answers": [{"parentQuestionId": "q1", "parentQuestionTitle": "질문1", "id": "a1", "title": "아니오"}]}
    b.update(kw)
    return b


def disp(c, rid_):
    with c.repo.tx() as tx:
        return tx.display(rid_)


def history(c):
    with c.repo.db.connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM questionnaire_history ORDER BY id")]


def events(c, t):
    with c.repo.tx() as tx:
        return tx.events(t)


# ------------------------------------------------------------------ 토큰(§3.1)
def test_questionnaire_token_shape_and_hash_only(env):
    c, fake, client, coord, rid, staff, mono = env
    out, token = new_q(c, coord, rid)
    assert out["qrToken"] is None and out["qrUrl"] == f"http://localhost:3700/q#{token}" and len(token) == 43
    d = disp(c, out["id"])
    assert d.qr_nonce and len(d.qr_nonce) == 32 and c.display.token_of(d) == token  # 같은 행 다시 계산 = 같은 토큰
    with c.repo.db.connect() as con:
        row = dict(con.execute("SELECT * FROM display_request WHERE id = ?", (out["id"],)).fetchone())
    assert row["qr_token_hash"] == hashlib.sha256(token.encode()).hexdigest() and token not in json.dumps(row)
    scan = c.display.create(coord, rid, "scan", None)  # 스캔 종류 = 지금 그대로
    assert scan["qrToken"] and scan["qrUrl"] is None and disp(c, scan["id"]).qr_nonce is None


# ------------------------------------------------------------------ 공개 GET(§6.1)
def test_questionnaire_public_get(env):
    c, fake, client, coord, rid, staff, mono = env
    out, token = new_q(c, coord, rid)
    r = client.get(URL)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "q_token_missing")
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"  # 오류도
    r = client.get(URL, headers=h("x" * 43))
    assert (r.status_code, r.json()["error"]["code"]) == (404, "q_not_found")
    scan = c.display.create(coord, rid, "scan", None)
    assert client.get(URL, headers=h(scan["qrToken"])).status_code == 404  # 스캔 토큰 = 404
    r = client.get(URL, headers=h(token))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    j = r.json()
    assert set(j) == {"customerName", "language", "form", "agreements", "prefill", "fillUntil"}  # 허용 키만
    assert "reservationId" not in json.dumps(j) and "vis-1" not in json.dumps(j) and "customerId" not in json.dumps(j)
    assert j["customerName"] == "고객" and j["language"]["code"] == "zh-Hans" and j["language"]["source"] == "kos_language"
    assert j["prefill"]["phone"] == {"countryCode": "82", "phoneNumber": "1012345678"}  # KOS 값 그대로(앞 0 없음)
    assert j["fillUntil"] == "2026-10-21T12:00:00+09:00"  # 처음 연 때 + 60분
    d = disp(c, out["id"])
    assert d.status == "opened" and d.opened_at == T0
    c.clock.set(T0 + timedelta(minutes=5))
    again = client.get(URL, headers={**h(token), **staff})  # Authorization 을 실어도 결과 같음
    assert again.status_code == 200 and again.json()["fillUntil"] == j["fillUntil"]
    assert disp(c, out["id"]).opened_at == T0  # opened_at 그대로
    ev = [e["payload"] for e in events(c, "qweb_open")]
    assert ev == [{"requestId": out["id"], "reservationId": rid, "language": "zh-Hans", "first": True},
                  {"requestId": out["id"], "reservationId": rid, "language": "zh-Hans", "first": False}]
    assert all(e["actor"] == "customer" for e in events(c, "qweb_open"))
    assert client.get(URL + "?lang=id", headers=h(token)).json()["language"]["code"] == "id"


def test_questionnaire_public_get_expiry_and_close(env):
    c, fake, client, coord, rid, staff, mono = env
    late, t1 = new_q(c, coord, rid)
    c.clock.set(T0 + timedelta(minutes=10))  # 여는 시한 10분 지난 pending
    r = client.get(URL, headers=h(t1))
    assert (r.status_code, r.json()["error"]["code"]) == (410, "q_expired") and "requestId" not in r.json()["error"]
    c.clock.set(T0)
    opened, t2 = new_q(c, coord, rid)
    assert client.get(URL, headers=h(t2)).status_code == 200
    c.clock.set(T0 + timedelta(minutes=59))
    assert client.get(URL, headers=h(t2)).status_code == 200  # 쓰는 시한 안 = 다시 열림
    c.clock.set(T0 + timedelta(minutes=60))
    r = client.get(URL, headers=h(t2))
    assert (r.status_code, r.json()["error"]["code"]) == (410, "q_expired") and disp(c, opened["id"]).status == "expired"
    c.clock.set(T0 + timedelta(minutes=61))
    closed, t3 = new_q(c, coord, rid)
    client.post(f"/api/display-requests/{closed['id']}/close", json={"status": "canceled"}, headers=staff)
    r = client.get(URL, headers=h(t3))
    assert (r.status_code, r.json()["error"]["code"]) == (410, "q_canceled")


def test_questionnaire_redisplay_closes_pending_and_opened(env):
    c, fake, client, coord, rid, staff, mono = env
    a, ta = new_q(c, coord, rid)
    assert client.get(URL, headers=h(ta)).status_code == 200  # 고객이 엶 → opened
    b, tb = new_q(c, coord, rid)  # 같은 예약 새 요청 → 옛 opened 도 canceled
    assert disp(c, a["id"]).status == "canceled"
    c2, _ = new_q(c, coord, rid)
    assert disp(c, b["id"]).status == "canceled" and disp(c, c2["id"]).status == "pending"
    assert client.get(URL, headers=h(ta)).json()["error"]["code"] == "q_canceled"


# ------------------------------------------------------------------ 공개 POST(§6.1 · §6.2 · §6.4)
def test_questionnaire_public_post(env):
    c, fake, client, coord, rid, staff, mono = env
    out, token = new_q(c, coord, rid)
    client.get(URL, headers=h(token))
    r = client.post(URL, json=body(), headers=h(token))
    assert r.status_code == 200 and r.json() == {"ok": True} and r.headers["cache-control"] == "no-store"
    assert fake.submitted[-1] == {**{k: v for k, v in body().items() if k != "language"}, "visitorId": "vis-1"}
    assert disp(c, out["id"]).status == "done"
    rows = history(c)
    assert len(rows) == 1 and (rows[0]["source"], rows[0]["language"], rows[0]["display_request_id"], rows[0]["device_id"],
                               rows[0]["reservation_id"]) == ("web_submit", "ja", out["id"], None, rid)
    ev = events(c, "questionnaire_submit")[-1]
    assert ev["actor"] == "customer" and ev["payload"] == {
        "reservationId": rid, "customerId": rows[0]["customer_id"], "language": "ja", "historyId": rows[0]["id"],
        "displayRequestId": out["id"], "channel": "web", "kosReadStale": False}
    r = client.post(URL, json=body(), headers=h(token))
    assert (r.status_code, r.json()["error"]["code"]) == (409, "q_submitted")
    assert client.get(URL, headers=h(token)).json()["error"]["code"] == "q_submitted"  # 다시 열기
    d = run(c.resv.detail(rid))  # 다음 상세 = 「제출됨」 · 읽기는 web_submit 행을 덮지 않는다
    assert [x.status for x in d.displays] == ["done"] and [r["source"] for r in history(c)] == ["web_submit"]


def test_questionnaire_public_post_fixes_read_row(env):
    c, fake, client, coord, rid, staff, mono = env
    out, token = new_q(c, coord, rid)
    with c.repo.tx() as tx:
        tx.add_questionnaire(tx.reservation(rid).customer_id, rid, fake.submit_at, [], c.clock.now())
    assert client.post(URL, json=body(), headers=h(token)).status_code == 200  # pending 에서 바로 제출도 됨
    rows = history(c)
    assert len(rows) == 1 and (rows[0]["source"], rows[0]["language"]) == ("web_submit", "ja")


@pytest.mark.parametrize("extra,code", [({"registrationNumber": "x"}, "questionnaire_field"),
                                        ({"phoneticName": "x"}, "questionnaire_field"),
                                        ({"deviceId": 1}, "invalid_request"),
                                        ({"displayRequestId": 1}, "invalid_request")])
def test_questionnaire_public_post_bad_fields(env, extra, code):
    c, fake, client, coord, rid, staff, mono = env
    _, token = new_q(c, coord, rid)
    r = client.post(URL, json=body(**extra), headers=h(token))
    assert (r.status_code, r.json()["error"]["code"]) == (400, code) and fake.submitted == []


def test_questionnaire_public_post_kos_rejected_and_fake_board(env):
    c, fake, client, coord, rid, staff, mono = env
    out, token = new_q(c, coord, rid)
    fake.resv_fail["submit-visitor-questionnaire"] = (400, {"className": "InvalidRequestException"})
    r = client.post(URL, json=body(), headers=h(token))
    assert (r.status_code, r.json()["error"]["code"]) == (409, "questionnaire_rejected")
    ev = events(c, "kos_rejected")[-1]
    assert ev["actor"] == "customer" and ev["payload"]["op"] == "submit-visitor-questionnaire"
    assert disp(c, out["id"]).status == "pending" and history(c) == []
    fake.resv_fail.pop("submit-visitor-questionnaire")
    c.settings.proc_fake_board = True
    r = client.post(URL, json=body(), headers=h(token))
    assert (r.status_code, r.json()["error"]["code"]) == (403, "fake_board")


def test_questionnaire_public_post_overlap_locked(env):
    """같은 링크로 겹친 두 POST — 하나 409 q_submitting · 하나 성공(요청 id 별 잠금)."""
    c, fake, client, coord, rid, staff, mono = env
    out, token = new_q(c, coord, rid)
    real = c.questionnaire.submit_answers

    async def slow(cust, payload):
        await asyncio.sleep(0.05)
        return await real(cust, payload)

    c.questionnaire.submit_answers = slow
    b = body()

    async def go():
        return await asyncio.gather(c.questionnaire.submit_public(token, b, set(b), "1.1.1.1"),
                                    c.questionnaire.submit_public(token, b, set(b), "1.1.1.1"), return_exceptions=True)

    res = asyncio.run(go())
    errs = [x for x in res if isinstance(x, Exception)]
    assert len(errs) == 1 and errs[0].code == "q_submitting" and len(fake.submitted) == 1


# ------------------------------------------------------------------ pending · 상세 · claim(§6.6)
def test_display_questionnaire_pending_detail_claim(env):
    c, fake, client, coord, rid, staff, mono = env
    dev = c.devices.register(coord, tok("pad"), "데스크 패드", "tablet", "IFV-1")
    out, token = new_q(c, coord, rid, dev)
    got = client.get(f"/api/display-requests/pending?deviceId={dev}", headers=staff).json()["items"]
    assert [(x["requestId"], x["status"], x["qrUrl"]) for x in got] == [(out["id"], "pending", out["qrUrl"])]
    assert disp(c, out["id"]).status == "pending"  # 돌려줘도 그대로
    d = run(c.resv.detail(rid))
    assert [(x.qrUrl, x.openedAt) for x in d.displays] == [(out["qrUrl"], None)]
    client.get(URL, headers=h(token))
    d = run(c.resv.detail(rid))
    assert [(x.status, x.qrUrl, x.openedAt) for x in d.displays] == [("opened", None, "2026-10-21T11:00:00+09:00")]
    got = client.get(f"/api/display-requests/pending?deviceId={dev}", headers=staff).json()["items"]
    assert [(x["status"], x["qrUrl"]) for x in got] == [("opened", None)]  # 고객이 연 뒤 = 링크 없음
    r = client.post("/api/display-requests/claim", json={"qrToken": token}, headers=staff)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "display_not_found")  # 문진 QR 은 claim 길 아님
    r = client.post("/api/display-requests", json={"reservationId": rid, "kind": "questionnaire"}, headers=staff)
    assert r.json()["qrToken"] is None and r.json()["qrUrl"].startswith("http://localhost:3700/q#")


# ------------------------------------------------------------------ 속도 제한(§7.3)
def test_questionnaire_rate_get_ip(env):
    c, fake, client, coord, rid, staff, mono = env
    _, token = new_q(c, coord, rid)
    for _ in range(30):
        assert client.get(URL, headers=h(token)).status_code == 200
    r = client.get(URL, headers=h(token))
    assert (r.status_code, r.json()["error"]["code"]) == (429, "too_many_requests")
    assert client.get(URL, headers={**h(token), "CF-Connecting-IP": "203.0.113.9"}).status_code == 200  # 다른 IP
    assert client.get(f"/api/reservations/{rid}", headers=staff).status_code == 200  # 직원 API 는 안 걸림
    mono[0] += 61
    assert client.get(URL, headers=h(token)).status_code == 200  # 1분 뒤 풀림


def test_questionnaire_rate_bad_tokens(env):
    c, fake, client, coord, rid, staff, mono = env
    _, token = new_q(c, coord, rid)
    for _ in range(10):
        assert client.get(URL, headers=h("x" * 43)).status_code == 404
    assert client.get(URL, headers=h(token)).status_code == 429  # 토큰 맞히기 막기 — 맞는 토큰도 1분
    denied = [e["payload"] for e in events(c, "qweb_denied")]
    assert denied == [{"reason": "not_found"}, {"reason": "rate"}]  # 같은 IP 같은 이유 = 1분에 1행 · requestId 없음
    mono[0] += 61
    assert client.get(URL, headers=h(token)).status_code == 200


def test_questionnaire_rate_post_ip_and_token(env):
    c, fake, client, coord, rid, staff, mono = env
    tokens = [new_q(c, coord, rid)[1] for _ in range(1)]
    for i in range(3):  # 같은 토큰 POST 1분 3회(400 도 센다)
        r = client.post(URL, json=body(registrationNumber="x"), headers=h(tokens[0]))
        assert r.status_code == 400, i
    r = client.post(URL, json=body(), headers=h(tokens[0]))
    assert (r.status_code, r.json()["error"]["code"]) == (429, "too_many_requests")
    ip = {"CF-Connecting-IP": "198.51.100.7"}
    for i in range(5):  # 같은 IP POST 1분 5회
        client.post(URL, json=body(registrationNumber="x"), headers={**h(f"t{i}"), **ip})
    assert client.post(URL, json=body(), headers={**h("t9"), **ip}).status_code == 429


# ------------------------------------------------------------------ 로그 · 경로
def test_questionnaire_logs_have_no_token(env, caplog):
    c, fake, client, coord, rid, staff, mono = env
    with caplog.at_level(logging.DEBUG):
        out, token = new_q(c, coord, rid)
        client.get(URL, headers=h(token))
        fake.resv_fail["submit-visitor-questionnaire"] = (500, {})
        client.post(URL, json=body(), headers=h(token))
        client.get(URL, headers=h("x" * 43))
    assert token not in caplog.text
    with c.repo.tx() as tx:
        assert token not in json.dumps(tx.events(), ensure_ascii=False)


def test_questionnaire_staff_routes_gone(env):
    c, fake, client, coord, rid, staff, mono = env
    assert client.get(f"/api/questionnaires/{rid}", headers=staff).status_code == 404
    assert client.post(f"/api/questionnaires/{rid}", json=body(), headers=staff).status_code == 404
    assert client.post("/api/auth/unlock", json={"password": "pw-c"}, headers=staff).status_code == 404


# ------------------------------------------------------------------ 건강 정보 반영(제출 직후 상세 — 2026-10-28 실 back 확인)
def test_questionnaire_health_items_real_page_title():
    from app.domain.reservation_rules import health_items

    form = {"pages": [{"title": "건강 정보 >> 안전한 시술을 위해 건강 상태를 자세히 알려주세요.\n부작용과 …",
                       "questions": [{"questionId": "7", "title": "복용 약물", "sequence": 1}]}]}
    sub = {"answers": [{"questionId": "7", "answerTitle": "아스피린", "memo": None}]}
    assert [(i["title"], i["answer"], i["needsCheck"]) for i in health_items(form, sub)] == [("복용 약물", "아스피린", True)]


def test_questionnaire_health_after_resubmit_when_kos_keeps_first(env):
    """실 KOS 꼴 — 다시 제출해도 제출본 읽기가 첫 제출본(어제) → 상세 「건강 정보」 = 방금 낸 답 · 제출 시각 · 이력 새 행."""
    c, fake, client, coord, rid, staff, mono = env
    fake.form["pages"][1]["title"] = "건강 정보 >> 안전한 시술을 위해 건강 상태를 자세히 알려주세요."
    fake.keep_first_submit = True
    fake.submits["vis-1"] = {"createdDateTimeUtc": "2026-10-20T01:00:00Z", "visitorName": "고객",
                             "answers": [{"seq": "", "questionId": "q1", "questionTitle": "질문1", "answerId": "a0",
                                          "answerTitle": "없음", "memo": None}]}
    before = run(c.resv.detail(rid)).health
    assert before.submittedAt == "2026-10-20T10:00:00+09:00" and [i.answer for i in before.items][0] == "없음"
    _, token = new_q(c, coord, rid)
    answers = [{"parentQuestionId": "q1", "parentQuestionTitle": "질문1", "id": "a5", "title": "있음", "subText": "알레르기"},
               {"parentQuestionId": "q2", "parentQuestionTitle": "질문2", "id": "a6", "title": "없음"}]
    assert client.post(URL, json=body(answers=answers), headers=h(token)).status_code == 200
    after = run(c.resv.detail(rid)).health
    assert after.state == "ok" and after.submittedAt == "2026-10-21T11:00:00+09:00"  # 방금(T0) — 어제 값 아님
    got = {i.title: (i.answer, i.memo, i.needsCheck) for i in after.items}
    assert got["질문1"] == ("있음", "알레르기", True) and got["질문2"] == ("없음", None, False) and after.needCount == 1
    rows = history(c)
    assert [(r["source"], r["kos_submitted_at"]) for r in rows] == [
        ("read", "2026-10-20T01:00:00Z"), ("web_submit", "2026-10-21T02:00:00.000Z")]  # 옛 행 그대로 · 새 행
    assert events(c, "questionnaire_submit")[-1]["payload"]["kosReadStale"] is True
    assert run(c.resv.detail(rid)).health.submittedAt == "2026-10-21T11:00:00+09:00"  # 다시 불러도 그대로
    fake.keep_first_submit = False  # 뒤에 KOS 가 더 새 제출본을 주면(예: KOS 웹 제출) 그것이 이긴다
    fake.submits["vis-1"] = {"createdDateTimeUtc": "2026-10-21T03:00:00Z", "answers": []}
    assert run(c.resv.detail(rid)).health.submittedAt == "2026-10-21T12:00:00+09:00"
