"""WORK-009 WP-BE4 — 문진(언어 표 · KOS 공개 양식 · 제출 · 이력) · unlock(SPEC-004 §6.15 · §3.3 · §8.6 「문진」)."""


import pytest
from fastapi.testclient import TestClient

from app.domain import languages
from app.domain.errors import BadGateway, BadRequest, Conflict, NotFound
from app.main import create_app
from tests.conftest import PW, make_settings
from tests.resv_env import load, make_env, rid_of, run
from tests.test_push import tok

LOGINS = dict(ccc_coord_id="coord1", ccc_coord_password="pw", ccc_admin_id="admin1", ccc_admin_password="pw",
              proc_session_secret="s", proc_bcrypt_rounds=4)


# ------------------------------------------------------------------ 언어 표(§6.15 ②)
@pytest.mark.parametrize("language,nationality,want", [
    ("zh-CN", "KR", ("zh-Hans", "kos_language")),
    ("zh-yue", None, ("zh-Hant", "kos_language")),
    ("", "TW", ("zh-Hant", "nationality")),
    ("", "HK", ("zh-Hant", "nationality")),
    ("", "VN", ("en", "default")),
    ("th", "TH", ("en", "kos_language")),  # th = 양식에 없음 → en
    ("", "TH", ("en", "nationality")),
    ("etc", "JP", ("ja", "nationality")),  # etc = 없음 → 국적
    ("ja", "CN", ("ja", "kos_language")),
    (None, None, ("en", "default")),
    ("id", None, ("id", "kos_language")),
])
def test_questionnaire_language_table(language, nationality, want):
    assert languages.resolve(language, nationality) == want


def test_questionnaire_language_options_and_agreement_keys():
    assert languages.FORM_LANGS == ("ko", "ja", "zh-Hans", "zh-Hant", "en", "id")
    assert languages.AGREEMENT_KEY == {"ja": "ja", "en": "en", "zh-Hans": "zh", "zh-Hant": "zh"}


# ------------------------------------------------------------------ 불러오기 · 제출(가짜 KOS)
@pytest.fixture
def env(tmp_path):
    c, fake, _ = make_env(tmp_path, **LOGINS)
    fake.visitors["vis-1"] = {**fake.visitors["vis-1"], "language": "zh-CN", "nationality": "TW",
                              "phoneNumber": {"countryCode": "82", "phoneNumber": "1012345678"}}
    fake.add_resv("s1", "vis-1", flow="RECEPTION", status="IN_PROGRESS")
    load(c)
    with c.repo.tx() as tx:
        acc = {a.login_id: a for a in tx.accounts()}
    coord, admin = acc["coord1"], acc["admin1"]
    tab = c.devices.register(coord, tok("tab"), "데스크 패드", "tablet")
    other = c.devices.register(admin, tok("adm"), None, "phone")
    yield c, fake, coord, rid_of(c, "s1"), tab, other


def body(**kw):
    b = {"language": "ja", "name": "고객 문진", "dateOfBirth": "19900102", "gender": "FEMALE",
         "phone": {"countryCode": "82", "phoneNumber": "01098765432"}, "address": "[ccc 시험] 주소", "addressDetail": "101",
         "agreements": [{"id": "ag-1", "type": "PERSONAL_INFORMATION", "required": True, "agreed": True}],
         "answers": [{"parentQuestionId": "q1", "parentQuestionTitle": "질문1", "id": "a1", "title": "아니오"},
                     {"parentQuestionId": "q2", "parentQuestionTitle": "질문2", "id": "a9", "title": "기타", "subText": "메모"}]}
    b.update(kw)
    return b


def history(c):
    with c.repo.db.connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM questionnaire_history ORDER BY id")]


def test_questionnaire_load_shape(env):
    c, fake, coord, rid, tab, other = env
    out = run(c.questionnaire.load(coord, rid, None, tab))
    assert out["language"] == {"code": "zh-Hans", "source": "kos_language", "options": list(languages.FORM_LANGS)}
    assert out["customerName"] == "고객" and out["reservationId"] == rid and out["todaySubmitted"] is False
    assert [p["id"] for p in out["form"]["pages"]] == ["p1", "p2"]
    assert out["agreements"][0]["type"] == "PERSONAL_INFORMATION"
    assert out["prefill"] == {"name": "고객", "phone": {"countryCode": "82", "phoneNumber": "1012345678"},
                              "address": "", "addressDetail": "", "dateOfBirth": "19900102", "gender": "FEMALE"}
    assert run(c.questionnaire.load(coord, rid, "id", tab))["language"]["code"] == "id"  # ?lang=
    assert run(c.questionnaire.load(coord, rid, "xx", None))["language"]["code"] == "zh-Hans"  # 모르는 값 = 무시
    with pytest.raises(NotFound) as e:  # 남의 계정 기기
        run(c.questionnaire.load(coord, rid, None, other))
    assert e.value.code == "device_not_found"
    with pytest.raises(NotFound):
        run(c.questionnaire.load(coord, 9999, None, None))


def test_questionnaire_submit_body_history_display(env):
    c, fake, coord, rid, tab, other = env
    q = c.display.create(coord, rid, "questionnaire", tab)
    run(c.questionnaire.submit(coord, rid, {**body(), "deviceId": tab, "displayRequestId": q["id"]},
                               {"language", "deviceId", "displayRequestId"}))
    sent = fake.submitted[-1]
    want = {k: v for k, v in body().items() if k != "language"}
    assert sent == {**want, "visitorId": "vis-1"}  # 받은 값 + visitorId · 언어 · 기기 · 요청 id 는 안 보냄
    rows = history(c)
    assert len(rows) == 1 and (rows[0]["source"], rows[0]["language"], rows[0]["device_id"], rows[0]["display_request_id"]) == (
        "app_submit", "ja", tab, q["id"])
    assert rows[0]["kos_submitted_at"] == fake.submit_at
    with c.repo.tx() as tx:
        assert tx.display(q["id"]).status == "done"
        ev = tx.events("questionnaire_submit")[-1]["payload"]
    assert ev == {"reservationId": rid, "customerId": rows[0]["customer_id"], "language": "ja", "deviceId": tab,
                  "displayRequestId": q["id"]}
    after = run(c.questionnaire.load(coord, rid, None, tab))
    assert after["todaySubmitted"] is True
    assert after["prefill"]["phone"] == {"countryCode": "82", "phoneNumber": "1098765432"}  # KOS 가 앞 0 을 뺀 값이 맞는 값


def test_questionnaire_submit_updates_read_row(env):
    """웹 상세 폴링이 먼저 같은 제출본을 read 로 넣었으면 그 행을 app_submit 으로(행 1 · r2) · 읽기가 뒤에 와도 그대로."""
    c, fake, coord, rid, tab, other = env
    with c.repo.tx() as tx:
        cust = tx.reservation(rid).customer_id
        tx.add_questionnaire(cust, rid, fake.submit_at, [], c.clock.now())
    run(c.questionnaire.submit(coord, rid, body(), {"language"}))
    rows = history(c)
    assert len(rows) == 1 and (rows[0]["source"], rows[0]["language"], rows[0]["device_id"]) == ("app_submit", "ja", None)
    run(c.resv.detail(rid))  # 읽기(§5.11) — INSERT OR IGNORE
    rows = history(c)
    assert len(rows) == 1 and rows[0]["source"] == "app_submit" and rows[0]["language"] == "ja"


def test_questionnaire_read_after_submit_keeps_app_row(env):
    c, fake, coord, rid, tab, other = env
    run(c.questionnaire.submit(coord, rid, body(), {"language"}))
    run(c.resv.detail(rid))
    assert [r["source"] for r in history(c)] == ["app_submit"]


@pytest.mark.parametrize("field", ["registrationNumber", "phoneticName"])
def test_questionnaire_forbidden_fields(env, field):
    c, fake, coord, rid, tab, other = env
    with pytest.raises(BadRequest) as e:
        run(c.questionnaire.submit(coord, rid, {**body(), field: "x"}, {"language", field}))
    assert e.value.code == "questionnaire_field" and fake.submitted == []


def test_questionnaire_kos_rejected(env):
    c, fake, coord, rid, tab, other = env
    q = c.display.create(coord, rid, "questionnaire", tab)
    fake.resv_fail["submit-visitor-questionnaire"] = (400, {"className": "InvalidRequestException"})
    with pytest.raises(Conflict) as e:
        run(c.questionnaire.submit(coord, rid, {**body(), "displayRequestId": q["id"]}, {"language", "displayRequestId"}))
    assert (e.value.code, e.value.message) == ("questionnaire_rejected", "제출하지 못했어요 · 직원에게 알려 주세요")
    fake.resv_fail["submit-visitor-questionnaire"] = (500, {})
    with pytest.raises(BadGateway):
        run(c.questionnaire.submit(coord, rid, body(), {"language"}))
    with c.repo.tx() as tx:
        assert len(tx.events("kos_rejected")) == 2 and tx.display(q["id"]).status == "pending"
    assert history(c) == []


def test_questionnaire_api_forbidden_field_and_device(tmp_path):
    """API — 주민번호 · 발음 = 400(KOS 부르기 전) · 남의 deviceId = 404."""
    s = make_settings(tmp_path, ccc_admin_id="admin1", ccc_coord_id="coord1")
    with TestClient(create_app(s)) as client:
        token = client.post("/api/auth/login", json={"id": "admin1", "password": PW["admin"]}).json()["token"]
        a = {"Authorization": f"Bearer {token}"}
        r = client.post("/api/questionnaires/1", json={**body(), "registrationNumber": "x"}, headers=a)
        assert (r.status_code, r.json()["error"]["code"]) == (400, "questionnaire_field")
        r = client.post("/api/questionnaires/1", json={**body(), "dateOfBirth": "1990-01-02"}, headers=a)
        assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
        r = client.get("/api/questionnaires/1?deviceId=77", headers=a)
        assert (r.status_code, r.json()["error"]["code"]) == (404, "device_not_found")


# ------------------------------------------------------------------ unlock(§3.3 r2 · D7-71)
@pytest.fixture
def api(tmp_path):
    s = make_settings(tmp_path, ccc_coord_id="coord1", ccc_admin_id="admin1")
    with TestClient(create_app(s)) as client:
        c = client.app.state.container
        mono = [1000.0]
        c.auth.now_mono = lambda: mono[0]
        a = {"Authorization": "Bearer " + client.post("/api/auth/login",
                                                      json={"id": "coord1", "password": PW["coordinator"]}).json()["token"]}
        adm = {"Authorization": "Bearer " + client.post("/api/auth/login",
                                                        json={"id": "admin1", "password": PW["admin"]}).json()["token"]}
        tab = client.post("/api/devices", json={"token": tok("tab")}, headers=a).json()["deviceId"]
        phone = client.post("/api/devices", json={"token": tok("phone")}, headers=a).json()["deviceId"]
        foreign = client.post("/api/devices", json={"token": tok("adm")}, headers=adm).json()["deviceId"]
        yield client, a, tab, phone, foreign, mono


def unlock(client, a, pw, device=None):
    return client.post("/api/auth/unlock", json={"password": pw, **({"deviceId": device} if device else {})}, headers=a)


def test_unlock_ok_and_wrong(api):
    client, a, tab, phone, foreign, mono = api
    assert unlock(client, a, PW["coordinator"], tab).json() == {"ok": True}
    r = unlock(client, a, "nope", tab)
    assert (r.status_code, r.json()["error"]) == (401, {"code": "invalid_credentials",
                                                       "message": "아이디 또는 비밀번호가 맞지 않아요"})
    r = unlock(client, a, PW["coordinator"], foreign)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "device_not_found")
    assert client.post("/api/auth/unlock", json={"password": PW["coordinator"]}).status_code == 401  # 토큰 필수
    assert client.post("/api/auth/unlock", json={}, headers=a).status_code == 400


def test_unlock_lock_per_device(api):
    client, a, tab, phone, foreign, mono = api
    for _ in range(5):
        assert unlock(client, a, "nope", tab).status_code == 401
    r = unlock(client, a, PW["coordinator"], tab)  # 맞아도 1분은 429
    assert (r.status_code, r.json()["error"]) == (429, {"code": "too_many_attempts",
                                                       "message": "여러 번 틀렸어요. 1분 뒤 다시 시도해 주세요"})
    assert unlock(client, a, PW["coordinator"], phone).status_code == 200  # 다른 기기 그대로
    assert unlock(client, a, PW["coordinator"]).status_code == 200  # 「기기 없음」 칸 따로
    r = client.post("/api/auth/login", json={"id": "coord1", "password": PW["coordinator"]})
    assert r.status_code == 200  # 로그인(코디 아이디)은 안 잠김
    mono[0] += 61
    assert unlock(client, a, PW["coordinator"], tab).status_code == 200  # 1분 뒤 풀림


def test_unlock_no_device_slot(api):
    client, a, tab, phone, foreign, mono = api
    for _ in range(5):
        unlock(client, a, "nope")
    assert unlock(client, a, PW["coordinator"]).status_code == 429
    assert unlock(client, a, PW["coordinator"], tab).status_code == 200


def test_unlock_success_clears_count(api):
    client, a, tab, phone, foreign, mono = api
    for _ in range(4):
        unlock(client, a, "nope", tab)
    assert unlock(client, a, PW["coordinator"], tab).status_code == 200
    for _ in range(4):
        unlock(client, a, "nope", tab)
    assert unlock(client, a, PW["coordinator"], tab).status_code == 200  # 성공이 0 으로 지움
