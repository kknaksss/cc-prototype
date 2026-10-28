"""웹 예약 상세 E2E batch 3 — #1 사진 삭제(ccc + KOS 이미지) · #2 유입 채널 KOS 쓰기 ·
#3 ~ #5 자동 저장 같은 값이면 KOS 안 부름."""


import pytest
from fastapi.testclient import TestClient

from app.domain.errors import BadRequest, Conflict
from app.main import create_app
from app.schemas.reservations import PersonalIn
from tests.fake_kos import visitor
from tests.resv_env import load, make_env, rid_of, run
from tests.test_push import tok

JPEG = b"\xff\xd8\xff\xe0" + b"TEST-PASSPORT-IMAGE" * 50 + b"\xff\xd9"
LOGINS = dict(ccc_coord_id="coord1", ccc_coord_password="pw-c", proc_session_secret="s", proc_bcrypt_rounds=4)
SCAN = {"passportNumber": "TZ0000001", "passportExpiryDate": "2031-05-06"}


@pytest.fixture
def env(tmp_path):
    c, fake, _ = make_env(tmp_path, proc_photo_dir=str(tmp_path / "photos"), **LOGINS)
    fake.visitors["vis-1"] = visitor("vis-1", name="고객이름", memo="특이 메모",
                                     visitorFunnel={"funnelCategoryId": "", "funnelId": "", "funnelDetail": ""})
    fake.add_resv("s1", "vis-1", flow="RESERVED", status="RESERVED", memo="예약 메모")
    load(c)
    with c.repo.tx() as tx:
        coord = tx.account("coord1")
        cid = tx.reservation(rid_of(c, "s1")).customer_id
    tab = c.devices.register(coord, tok("tab"), "데스크 패드", "tablet")
    client = TestClient(create_app(c.settings, container=c))
    login = client.post("/api/auth/login", json={"id": "coord1", "password": "pw-c"}).json()
    yield c, fake, client, {"Authorization": f"Bearer {login['token']}"}, coord, rid_of(c, "s1"), cid, tab, tmp_path / "photos"


def writes(fake, name):
    return [b for p, b in fake.calls if p.endswith("/" + name)]


def scan(c, coord, cid, rid, tab):
    return run(c.scan.save(coord, cid, fields=PersonalIn(**SCAN), photo=JPEG, reservation_id=rid, display_request_id=None,
                           device_id=tab, manual=False))


# ------------------------------------------------------------------ #1 사진 삭제
def test_photo_delete_ccc_and_kos(env):
    c, fake, client, auth, coord, rid, cid, tab, photos = env
    out = scan(c, coord, cid, rid, tab)
    with c.repo.tx() as tx:
        name = tx.id_photo(out["photoId"])["file_name"]
    assert (photos / name).exists() and run(c.resv.detail(rid)).customer.identity.status == "confirmed"
    r = client.delete(f"/api/id-photos/{out['photoId']}", headers=auth)
    assert r.status_code == 200 and r.json() == {"ok": True, "kos": "deleted"}
    assert fake.deleted_images == [["img-1"]]  # KOS 웹 [삭제]와 같은 길 · 그 사진 id
    assert writes(fake, "get-visitor-images")[-1] == {"visitorId": "vis-1", "deleted": False}
    assert not (photos / name).exists()
    with c.repo.tx() as tx:
        assert tx.id_photo(out["photoId"]) is None
        ev = tx.events("id_photo_delete")[-1]
    assert ev["payload"] == {"photoId": out["photoId"], "customerId": cid, "kos": "deleted"} and ev["actor"] == "coord1"
    ident = run(c.resv.detail(rid)).customer.identity
    assert (ident.status, ident.photoId, ident.photoKos) == ("unconfirmed", None, None)
    assert fake.visitors["vis-1"]["passportNumber"] == "TZ0000001"  # 자동 입력된 고객 값은 그대로
    assert client.delete(f"/api/id-photos/{out['photoId']}", headers=auth).status_code == 404


def test_photo_delete_kos_fail_keeps_ccc(env):
    c, fake, client, auth, coord, rid, cid, tab, photos = env
    out = scan(c, coord, cid, rid, tab)
    fake.resv_fail["delete-visitor-images"] = (400, {"className": "InvalidRequestException"})
    with pytest.raises(Conflict) as e:
        run(c.photos.delete(coord, out["photoId"]))
    assert e.value.code == "kos_rejected"
    with c.repo.tx() as tx:
        assert tx.id_photo(out["photoId"]) is not None and tx.last_identity_check(cid).status == "confirmed"
        assert tx.events("kos_rejected")[-1]["payload"]["op"] == "delete-visitor-images"


def test_photo_delete_not_on_kos_and_later_manual_confirm(env):
    c, fake, client, auth, coord, rid, cid, tab, photos = env
    fake.fail_paths["s3-put"] = 500  # KOS 올리기 실패 — KOS 에 이미지 없음
    out = scan(c, coord, cid, rid, tab)
    c.resv.identity(coord, cid, "confirmed")  # 뒤에 웹에서 다시 확인 = 이 사진으로 한 확인이 아님
    assert run(c.photos.delete(coord, out["photoId"])) == "not_found" and fake.deleted_images == []
    with c.repo.tx() as tx:
        assert tx.last_identity_check(cid).status == "confirmed"  # 그대로


# ------------------------------------------------------------------ #2 유입 채널
def test_funnel_detail_and_write(env):
    c, fake, client, auth, coord, rid, cid, tab, photos = env
    d = run(c.resv.detail(rid))
    with c.repo.tx() as tx:
        codes = {f.kos_id: f.id for f in tx.funnel_codes()}
    assert d.customer.funnel is None and [(x.funnelId, x.name) for x in d.funnelCodes] == [(codes["fn-1"], "인스타그램")]
    r = client.put(f"/api/customers/{cid}/funnel", json={"funnelId": codes["fn-1"]}, headers=auth)
    assert r.status_code == 200
    body = writes(fake, "update-visitor-management-information")[-1]
    assert body["visitorFunnel"] == {"funnelCategoryId": "", "funnelId": "fn-1", "funnelDetail": ""}
    assert body["memo"] == "특이 메모" and body["visitorType"] == {"id": "vt-1", "name": "기본"}  # 묶음 그대로
    assert "visitorCategories" not in body  # 빈 배열은 뺀다(remark 와 같은 규칙)
    f = run(c.resv.detail(rid)).customer.funnel
    assert (f.funnelId, f.name, f.detail) == (codes["fn-1"], "인스타그램", None)
    n = len(writes(fake, "update-visitor-management-information"))
    client.put(f"/api/customers/{cid}/funnel", json={"funnelId": codes["fn-1"]}, headers=auth)
    assert len(writes(fake, "update-visitor-management-information")) == n  # 같은 값 = KOS 안 부름
    client.put(f"/api/customers/{cid}/funnel", json={"funnelId": codes["fn-1"], "funnelDetail": " 지인 소개 "}, headers=auth)
    assert writes(fake, "update-visitor-management-information")[-1]["visitorFunnel"]["funnelDetail"] == "지인 소개"
    r = client.put(f"/api/customers/{cid}/funnel", json={"funnelId": codes["fn-2"]}, headers=auth)  # 닫힌 코드
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    client.put(f"/api/customers/{cid}/funnel", json={"funnelId": None}, headers=auth)  # 비움(설명은 그대로)
    assert writes(fake, "update-visitor-management-information")[-1]["visitorFunnel"] == {
        "funnelCategoryId": "", "funnelId": "", "funnelDetail": "지인 소개"}
    with c.repo.tx() as tx:
        assert tx.events("visitor_funnel")[-1]["payload"] == {"customerId": cid, "funnelId": None}
    with pytest.raises(BadRequest):
        run(c.resv.funnel(coord, cid, 99999, None, False))


# ------------------------------------------------------------------ #3 ~ #5 같은 값이면 KOS 안 부름(자동 저장)
def test_autosave_same_value_skips_kos(env):
    c, fake, client, auth, coord, rid, cid, tab, photos = env
    run(c.resv.remark(coord, cid, "특이 메모"))
    run(c.resv.memo(coord, rid, "예약 메모"))
    run(c.resv.personal(coord, cid, PersonalIn(passportNumber="X1234567", gender="FEMALE")))  # 지금 KOS 값과 같음
    assert writes(fake, "update-visitor-management-information") == []
    assert writes(fake, "change-reservation-memo") == []
    assert writes(fake, "update-visitor-personal-information") == []
    before = len(writes(fake, "get-visitor"))
    run(c.resv.remark(coord, cid, "새 메모"))
    run(c.resv.memo(coord, rid, "새 예약 메모"))
    run(c.resv.personal(coord, cid, PersonalIn(passportNumber="X7654321")))
    assert len(writes(fake, "get-visitor")) >= before + 2  # 직전 다시 읽기 그대로
    assert writes(fake, "update-visitor-management-information")[-1]["memo"] == "새 메모"
    assert writes(fake, "change-reservation-memo")[-1]["memo"] == "새 예약 메모"
    assert writes(fake, "update-visitor-personal-information")[-1]["passportNumber"] == "X7654321"
