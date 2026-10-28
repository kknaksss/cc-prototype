"""WORK-009 WP-BE5 — 여권 스캔 · 신분증 사진(SPEC-004 §6.16 · §7.3 · §8.6 「스캔」 · 「경로 수」). 가짜 KOS · 지어낸 바이트."""

import json
import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain.errors import Conflict
from app.main import create_app
from app.schemas.reservations import PersonalIn
from tests.fake_kos import visitor
from tests.resv_env import load, make_env, rid_of, run
from tests.test_push import tok

BACK = Path(__file__).resolve().parent.parent
JPEG = b"\xff\xd8\xff\xe0" + b"TEST-PASSPORT-IMAGE" * 50 + b"\xff\xd9"  # 지어낸 바이트(실제 신분증 아님)
LOGINS = dict(ccc_coord_id="coord1", ccc_coord_password="pw-c", ccc_admin_id="admin1", ccc_admin_password="pw-a",
              proc_session_secret="s", proc_bcrypt_rounds=4)
SCAN = {"passportSurname": "TESTER", "passportGivenNames": "ANNA", "passportNumber": "TZ0000001", "nationality": "TW",
        "dateOfBirth": "1990-01-02", "gender": "FEMALE", "passportExpiryDate": "2031-05-06"}


@pytest.fixture
def env(tmp_path):
    c, fake, _ = make_env(tmp_path, proc_photo_dir=str(tmp_path / "photos"), **LOGINS)
    fake.visitors["vis-1"] = visitor("vis-1", name="고객이름", nationality="JP", email="x@example.com")
    fake.add_resv("s1", "vis-1", flow="RESERVED", status="RESERVED")
    load(c)
    with c.repo.tx() as tx:
        acc = {a.login_id: a for a in tx.accounts()}
        cid = tx.reservation(rid_of(c, "s1")).customer_id
    coord = acc["coord1"]
    tab = c.devices.register(coord, tok("tab"), "데스크 패드", "tablet")
    yield c, fake, coord, rid_of(c, "s1"), cid, tab, tmp_path / "photos"


def scan(c, actor, cid, rid, tab, fields=SCAN, photo=JPEG, manual=False, display=None):
    return run(c.scan.save(actor, cid, fields=PersonalIn(**fields), photo=photo, reservation_id=rid,
                           display_request_id=display, device_id=tab, manual=manual))


def sent(fake, name):
    return [b for p, b in fake.calls if p.endswith("/" + name)]


def test_scan_personal_reread_all_keys_and_expiry(env):
    c, fake, coord, rid, cid, tab, photos = env
    before = len(sent(fake, "get-visitor"))
    out = scan(c, coord, cid, rid, tab)
    assert len(sent(fake, "get-visitor")) == before + 1  # 저장 직전 다시 읽기
    body = sent(fake, "update-visitor-personal-information")[-1]
    from app.service.reservations import PERSONAL_KEYS
    kept = {k for k in PERSONAL_KEYS if k in visitor("vis-1", name="고객이름", email="x@example.com")}
    assert set(body) == {"id"} | kept | set(SCAN)  # 다시 읽은 응답에 있는 키 전부 + 바뀐 칸(고정 수 아님)
    assert body["name"] == "고객이름"  # name 안 바뀜(D7-53)
    assert body["passportExpiryDate"] == "2031-05-06" and body["dateOfBirth"] == "1990-01-02 00:00:00.000Z"
    assert out == {"ok": True, "personal": "ok", "skipped": [], "photo": {"ccc": "ok", "kos": "ok"},
                   "photoId": out["photoId"]}


def test_scan_name_field_rejected():
    from app.domain.errors import BadRequest
    from app.service.passport_scan import PassportScanService
    with pytest.raises(BadRequest):
        PassportScanService.parse_fields(json.dumps({"name": "X"}))
    with pytest.raises(BadRequest):
        PassportScanService.parse_fields("not json")
    assert PassportScanService.parse_fields(json.dumps({"passportNumber": "A1"})).model_fields_set == {"passportNumber"}


def test_scan_photo_kos_image_body(env):
    c, fake, coord, rid, cid, tab, photos = env
    out = scan(c, coord, cid, rid, tab)
    with c.repo.tx() as tx:
        row = tx.id_photo(out["photoId"])
    up = fake.uploads[-1]
    assert up["content"] == JPEG and up["contentType"] == "image/jpeg" and up["auth"] is None
    assert sent(fake, "generate-uploading-url")[-1] == {"fileName": row["file_name"]}
    reg = fake.registered[-1]["images"]
    assert len(reg) == 1 and set(reg[0]) == {"fileName", "visitorId", "source", "scheduleId", "shootingDateTimeUtc",
                                             "equipment", "memo"}
    assert reg[0]["scheduleId"] == "s1"  # 그 예약 일정(E2E batch 2 #5 — KOS 일정 「사진 · 펜차트」)
    assert "category" not in reg[0] and "path" not in reg[0]
    assert (reg[0]["fileName"], reg[0]["visitorId"], reg[0]["source"], reg[0]["memo"]) == (
        row["file_name"], "vis-1", "HOSPITAL", "ccc 여권 스캔")
    assert reg[0]["equipment"] == fake.equipment[0]  # get-codes 「태블릿」 객체 그대로(6키)
    assert reg[0]["shootingDateTimeUtc"].endswith("Z")
    assert (row["kos_status"], row["kos_error"], row["doc_type"]) == ("ok", None, "passport")


def test_scan_photo_file_ccc(env):
    c, fake, coord, rid, cid, tab, photos = env
    out = scan(c, coord, cid, rid, tab)
    files = list(photos.iterdir())
    assert len(files) == 1 and files[0].read_bytes() == JPEG
    assert re.fullmatch(r"[0-9a-f]{32}\.jpg", files[0].name)  # 무작위 · 고객 값 0
    with c.repo.db.connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM id_photo")]
    assert len(rows) == 1 and rows[0]["id"] == out["photoId"] and rows[0]["bytes"] == len(JPEG)
    assert rows[0]["customer_id"] == cid and rows[0]["reservation_id"] == rid and len(rows[0]["sha256"]) == 64


def test_scan_equipment_code_missing(env):
    c, fake, coord, rid, cid, tab, photos = env
    fake.equipment = [x for x in fake.equipment if x["name"] != "태블릿"]
    out = scan(c, coord, cid, rid, tab)
    assert out["photo"] == {"ccc": "ok", "kos": "failed"}
    assert sent(fake, "generate-uploading-url") == [] and fake.uploads == [] and fake.registered == []  # KOS 업로드 0
    with c.repo.tx() as tx:
        row = tx.id_photo(out["photoId"])
    assert (row["kos_status"], row["kos_error"]) == ("failed", "equipment_code_missing")


def test_scan_kos_personal_fail_saves_nothing(env):
    c, fake, coord, rid, cid, tab, photos = env
    fake.resv_fail["update-visitor-personal-information"] = (400, {"className": "InvalidRequestException"})
    with pytest.raises(Conflict) as e:
        scan(c, coord, cid, rid, tab)
    assert e.value.code == "kos_rejected"
    assert not photos.exists() or list(photos.iterdir()) == []
    with c.repo.db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM id_photo").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM identity_check").fetchone()[0] == 0
    assert fake.uploads == []


def test_scan_kos_photo_fail_then_retry(env):
    c, fake, coord, rid, cid, tab, photos = env
    fake.fail_paths["s3-put"] = 500
    out = scan(c, coord, cid, rid, tab)
    assert out["photo"] == {"ccc": "ok", "kos": "failed"} and out["personal"] == "ok"
    with c.repo.tx() as tx:
        row = tx.id_photo(out["photoId"])
        assert tx.last_identity_check(cid).status == "confirmed"  # 고객 수정 · ccc 사진 · 신분 확인은 남는다
    assert (row["kos_status"], row["kos_error"]) == ("failed", "HTTP 500 presigned-put")
    fake.fail_paths.pop("s3-put")
    assert run(c.photos.retry(coord, out["photoId"])) == "ok"
    with c.repo.tx() as tx:
        assert tx.id_photo(out["photoId"])["kos_status"] == "ok"
        assert tx.events("id_photo_kos_retry")[-1]["payload"] == {"photoId": out["photoId"], "kos": "ok"}
    assert run(c.photos.retry(coord, out["photoId"])) == "ok" and len(fake.registered) == 1  # 이미 ok = 그대로


def test_scan_photo_disabled(env, tmp_path):
    c, fake, coord, rid, cid, tab, photos = env
    c.settings.proc_photo_dir = ""
    out = scan(c, coord, cid, rid, tab)
    assert out["photo"] == {"ccc": "disabled", "kos": "skipped"} and out["photoId"] is None
    assert fake.uploads == [] and not photos.exists()
    with c.repo.tx() as tx:
        assert tx.last_identity_check(cid).method == "app_scan"


def test_scan_identity_event_display(env):
    c, fake, coord, rid, cid, tab, photos = env
    q = c.display.create(coord, rid, "scan", tab)
    out = scan(c, coord, cid, rid, tab, display=q["id"], manual=True)
    with c.repo.tx() as tx:
        ic = tx.last_identity_check(cid)
        ev = tx.events("passport_scan")[-1]["payload"]
        assert tx.display(q["id"]).status == "done"
    assert (ic.status, ic.method, ic.device, ic.photo_id, ic.actor) == ("confirmed", "app_manual", "데스크 패드",
                                                                        out["photoId"], "coord1")
    assert ev == {"customerId": cid, "fields": sorted(SCAN), "photoId": out["photoId"],
                  "kos": {"personal": "ok", "photo": "ok"}, "manual": True}
    assert "TZ0000001" not in json.dumps(ev)  # 값 없음
    d = run(c.resv.detail(rid))
    assert (d.customer.identity.method, d.customer.identity.device, d.customer.identity.photoId) == (
        "app_manual", "데스크 패드", out["photoId"])
    assert [(x.kind, x.status, x.deviceName) for x in d.displays] == [("scan", "done", "데스크 패드")]


def test_scan_logs_no_values(env, caplog):
    c, fake, coord, rid, cid, tab, photos = env
    fake.fail_paths["s3-put"] = 500
    with caplog.at_level(logging.DEBUG):
        scan(c, coord, cid, rid, tab)
    text = caplog.text
    assert "TZ0000001" not in text and "TESTER" not in text and "X-Amz-Signature" not in text and "s3.fake.test" not in text


# ------------------------------------------------------------------ API — multipart · 413 · Bearer 열람
@pytest.fixture
def api(env):
    c, fake, coord, rid, cid, tab, photos = env
    client = TestClient(create_app(c.settings, container=c))  # lifespan 없음(조회 루프 안 띄움)
    token = client.post("/api/auth/login", json={"id": "coord1", "password": "pw-c"}).json()["token"]
    return client, {"Authorization": f"Bearer {token}"}, env


def post_scan(client, auth, cid, rid, tab, photo=JPEG, fields=SCAN, **extra):
    data = {"fields": json.dumps(fields), "reservationId": str(rid), "deviceId": str(tab), **extra}
    return client.post(f"/api/customers/{cid}/passport-scan", data=data, files={"photo": ("p.jpg", photo, "image/jpeg")},
                       headers=auth)


def test_scan_api_and_photo_view_bearer(api):
    client, auth, (c, fake, coord, rid, cid, tab, photos) = api
    r = post_scan(client, auth, cid, rid, tab)
    assert r.status_code == 200, r.json()
    pid = r.json()["photoId"]
    assert r.json()["photo"] == {"ccc": "ok", "kos": "ok"}
    v = client.get(f"/api/id-photos/{pid}", headers=auth)
    assert v.status_code == 200 and v.content == JPEG and v.headers["content-type"] == "image/jpeg"
    assert v.headers["cache-control"] == "no-store"
    token = auth["Authorization"].removeprefix("Bearer ")
    assert client.get(f"/api/id-photos/{pid}").status_code == 401
    assert client.get(f"/api/id-photos/{pid}?token={token}").status_code == 401  # 쿼리 토큰 안 받음
    assert client.get("/api/id-photos/999", headers=auth).status_code == 404
    with c.repo.tx() as tx:
        assert tx.events("id_photo_view")[-1]["payload"] == {"photoId": pid, "customerId": cid}
    r = client.post(f"/api/id-photos/{pid}/kos-retry", headers=auth)
    assert r.json() == {"ok": True, "kos": "ok"}


def test_scan_api_too_large_and_bad_input(api):
    client, auth, (c, fake, coord, rid, cid, tab, photos) = api
    r = post_scan(client, auth, cid, rid, tab, photo=b"\xff" * (5 * 1024 * 1024 + 1))
    assert (r.status_code, r.json()["error"]["code"]) == (413, "photo_too_large")
    assert fake.uploads == [] and sent(fake, "update-visitor-personal-information") == []
    r = post_scan(client, auth, cid, rid, tab, fields={"name": "X"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    r = client.post(f"/api/customers/{cid}/passport-scan", data={"fields": "{}"}, headers=auth)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    with c.repo.tx() as tx:
        other = tx.account("admin1")
    foreign = c.devices.register(other, tok("adm"), None, None)
    r = post_scan(client, auth, cid, rid, foreign)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "device_not_found")


def test_scan_photo_view_disabled(api):
    client, auth, (c, fake, coord, rid, cid, tab, photos) = api
    pid = post_scan(client, auth, cid, rid, tab).json()["photoId"]
    c.settings.proc_photo_dir = ""
    r = client.get(f"/api/id-photos/{pid}", headers=auth)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "photo_disabled")


# ------------------------------------------------------------------ grep(§8.6 · WORK-009 BE5 완료 조건)
def test_scan_repo_has_no_kos_code_ids_and_legal_notes():
    app_files = list((BACK / "app").rglob("*.py"))
    text = "\n".join(f.read_text() for f in app_files)
    assert not re.search(r"\b[0-9a-f]{24}\b", text)  # KOS id(24자 16진) 0
    assert text.count("법적 검토 필요") >= 3
    assert "EQUIPMENT_NAME = \"태블릿\"" in text


def test_scan_detail_photo_kos(env):
    """추가 1 — 상세 customer.identity.photoKos = id_photo.kos_status · 사진 없으면 null."""
    c, fake, coord, rid, cid, tab, photos = env
    assert run(c.resv.detail(rid)).customer.identity.photoKos is None  # 확인 기록 없음
    c.resv.identity(coord, cid, "confirmed")  # 웹 수동 확인 = 사진 없음
    assert run(c.resv.detail(rid)).customer.identity.photoKos is None
    fake.fail_paths["s3-put"] = 500
    out = scan(c, coord, cid, rid, tab)
    assert run(c.resv.detail(rid)).customer.identity.photoKos == "failed"
    fake.fail_paths.pop("s3-put")
    run(c.photos.retry(coord, out["photoId"]))
    assert run(c.resv.detail(rid)).customer.identity.photoKos == "ok"
    with c.repo.tx() as tx:
        tx.update_id_photo(out["photoId"], kos_status="skipped")
    assert run(c.resv.detail(rid)).customer.identity.photoKos == "skipped"


def test_scan_manual_without_photo(env):
    """리뷰 r1 FAIL-2 — 손 입력은 사진 없이 저장(app_manual · photo null · ccc · KOS 사진 0) · 카메라 길은 사진 필수."""
    from app.domain.errors import BadRequest

    c, fake, coord, rid, cid, tab, photos = env
    out = scan(c, coord, cid, rid, tab, photo=None, manual=True)
    assert out == {"ok": True, "personal": "ok", "skipped": [], "photo": None, "photoId": None}
    assert sent(fake, "update-visitor-personal-information")  # 고객 수정은 됨
    assert fake.uploads == [] and sent(fake, "generate-uploading-url") == [] and not photos.exists()
    with c.repo.tx() as tx:
        ic = tx.last_identity_check(cid)
        ev = tx.events("passport_scan")[-1]["payload"]
    assert (ic.status, ic.method, ic.photo_id) == ("confirmed", "app_manual", None)
    assert ev["photoId"] is None and ev["kos"] == {"personal": "ok", "photo": None}
    assert run(c.resv.detail(rid)).customer.identity.photoKos is None
    with pytest.raises(BadRequest):
        scan(c, coord, cid, rid, tab, photo=None, manual=False)


def test_scan_api_manual_without_photo(api):
    client, auth, (c, fake, coord, rid, cid, tab, photos) = api
    data = {"fields": json.dumps(SCAN), "reservationId": str(rid), "deviceId": str(tab), "manual": "true"}
    r = client.post(f"/api/customers/{cid}/passport-scan", data=data, headers=auth)
    assert r.status_code == 200 and r.json()["photo"] is None and r.json()["photoId"] is None
    r = client.post(f"/api/customers/{cid}/passport-scan", data={**data, "manual": "false"}, headers=auth)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")


def test_scan_photo_kos_schedule_id(env):
    """E2E batch 2 #5 — 예약 없는 스캔 = scheduleId 없음 · kos-retry 도 그 사진의 예약 일정을 싣는다."""
    c, fake, coord, rid, cid, tab, photos = env
    scan(c, coord, cid, None, tab)
    assert "scheduleId" not in fake.registered[-1]["images"][0]
    fake.fail_paths["s3-put"] = 500
    out = scan(c, coord, cid, rid, tab)
    fake.fail_paths.pop("s3-put")
    assert run(c.photos.retry(coord, out["photoId"])) == "ok"
    assert fake.registered[-1]["images"][0]["scheduleId"] == "s1"


def test_scan_photo_kos_category_passport(env):
    """여권 사진 분류 — get-codes{IMAGE_CATEGORY} 에 이름 「여권」 이 있으면 그 객체 그대로 · 없으면(데모) category 키 없음."""
    c, fake, coord, rid, cid, tab, photos = env
    scan(c, coord, cid, rid, tab)
    assert "category" not in fake.registered[-1]["images"][0]
    assert {"category": "IMAGE_CATEGORY"} in sent(fake, "get-codes")
    passport = {"id": "ic-9", "category": "IMAGE_CATEGORY", "name": "여권", "order": 2, "closed": False, "default": False}
    fake.image_categories.append(passport)  # 운영 지점 꼴
    scan(c, coord, cid, rid, tab)
    img = fake.registered[-1]["images"][0]
    assert img["category"] == passport and img["scheduleId"] == "s1" and img["equipment"]["name"] == "태블릿"
