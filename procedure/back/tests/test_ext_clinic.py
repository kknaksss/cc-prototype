"""SPEC-008 0.4.0 · 0.4.3 §6.16 `GET /api/ext/clinic` · §6.17 `GET /api/ext/clinics/{clinicId}/staff` — T66 · T67."""

import pytest

from tests.ext_env import H_LINKY, make_ext_env
from tests.fake_kos import SYSTEM

TOKEN_CALLS = {"exchange-token", "sign-in", "get-user-account"}
HIDDEN = ("nursingInstitutionNumber", "companyRegistrationNumber", "businessLicenseImageUrl", "companyName",
          "representativeName", "websiteUrl", "taxBillEmail", "logoImageUrl", "representativeStampImageUrl",
          "hospitalMapImageUrl", "nationality", "languages", "qualifiedInvoiceIssuerNumber", "translsMap")


@pytest.fixture
def env(tmp_path):
    c, fake, cl = make_ext_env(tmp_path, menu=False)
    fake.hospital = {"data": {
        "nursingInstitutionNumber": "00000000", "companyRegistrationNumber": "", "businessLicenseImageUrl": "",
        "companyName": "", "hospitalName": "<병원>", "representativeName": "<대표>", "hospitalPhoneNumber": "",
        "addressContract": {"address": "", "detailedAddress": "", "zipCode": "", "translsMap": {}},
        "websiteUrl": "https://site.example.com", "taxBillEmail": "tax@example.com", "logoImageUrl": "",
        "representativeStampImageUrl": "", "hospitalMapImageUrl": "", "nationality": "KR", "languages": ["ko"],
        "qualifiedInvoiceIssuerNumber": "", "translsMap": {"hospitalName": {}}}}
    day = {"enabled": True, "startTime": "2026-08-10T01:00:00Z", "endTime": "2026-08-10T10:00:00Z",
           "breaktime": {"startTime": "", "endTime": ""}}
    fake.op_timetable = {"data": {d: dict(day) for d in ("monday", "tuesday", "wednesday", "thursday", "friday")}
                         | {"saturday": {**day, "breaktime": {"startTime": "2026-08-10T04:00:00Z",
                                                              "endTime": "2026-08-10T05:00:00Z"}},
                            "sunday": {"enabled": False, "startTime": "", "endTime": "", "breaktime": {}}}}
    fake.days_off = {"data": [
        {"id": "off-kos-id-1", "startDateTime": "2026-10-24T15:00:00Z", "endDateTime": "2026-10-25T15:00:00Z"},  # 하루
        {"id": "off-kos-id-2", "startDateTime": "2026-11-01T15:00:00Z", "endDateTime": "2026-11-04T15:00:00Z"}]}  # 사흘
    return c, fake, cl


def kos(fake, since=0):
    return [p.rsplit("/", 1)[-1] for p, _ in fake.calls[since:] if p.rsplit("/", 1)[-1] not in TOKEN_CALLS]


# ------------------------------------------------------------------ T66 병원 정보
def test_t66_clinic(env):
    c, fake, cl = env
    n = len(fake.calls)
    r = cl.get("/api/ext/clinic", headers=H_LINKY)
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == {"clinicId", "name", "phone", "address", "operatingHours", "daysOff"}
    assert d["clinicId"] == 1 and d["name"] == "<병원>" and d["phone"] is None and d["address"] is None
    for k in HIDDEN:
        assert k not in r.text
    for leak in ("<대표>", "00000000", "site.example.com", "tax@example.com", "off-kos-id"):
        assert leak not in r.text
    assert d["operatingHours"]["monday"] == {"enabled": True, "start": "10:00", "end": "19:00", "breakStart": None,
                                             "breakEnd": None}
    assert d["operatingHours"]["saturday"]["breakStart"] == "13:00" and d["operatingHours"]["sunday"]["enabled"] is False
    assert d["daysOff"] == [{"startDate": "2026-10-25", "endDate": "2026-10-25"},
                            {"startDate": "2026-11-02", "endDate": "2026-11-04"}]
    assert all(set(x) == {"startDate", "endDate"} for x in d["daysOff"])
    assert sorted(kos(fake, n)) == sorted(["get-hospital", "get-default-operation-timetable", "get-default-days-off"])
    body = [b for p, b in fake.calls[n:] if p.endswith("/get-default-days-off")][0]
    assert body == {"startDateTime": "2026-10-20T15:00:00.000Z", "endDateTime": "2027-01-19T15:00:00.000Z"}  # 오늘 ~ +90일 끝


def test_t66_address_and_empty(env):
    c, fake, cl = env
    fake.hospital["data"]["addressContract"] = {"address": "<주소>", "detailedAddress": "", "zipCode": "00000"}
    fake.hospital["data"]["hospitalPhoneNumber"] = "0200000000"
    fake.days_off = {"data": []}
    d = cl.get("/api/ext/clinic", headers=H_LINKY).json()
    assert d["address"] == {"address": "<주소>", "detailed": None, "zipCode": "00000"} and d["phone"] == "0200000000"
    assert d["daysOff"] == []


@pytest.mark.parametrize("fail", ["get-hospital", "get-default-operation-timetable", "get-default-days-off"])
def test_t66_any_failure_502_all_called(env, fail):
    c, fake, cl = env
    fake.fail_paths[fail] = 500
    n = len(fake.calls)
    r = cl.get("/api/ext/clinic", headers=H_LINKY)
    assert (r.status_code, r.json()["error"]["code"]) == (502, "kos_unavailable")
    assert len(kos(fake, n)) == 3  # 셋 동시에 나감


@pytest.mark.parametrize("bad", [{"hospital": {"data": []}}, {"days_off": {"data": {"x": 1}}},
                                 {"days_off": {"data": [{"id": "x"}]}}, {"op_timetable": {}}])
def test_t66_shape_502(env, bad):
    c, fake, cl = env
    for k, v in bad.items():
        setattr(fake, k, v)
    assert cl.get("/api/ext/clinic", headers=H_LINKY).status_code == 502


def test_t66_no_runtime_502(env):
    c, fake, cl = env
    c.kos = None
    assert cl.get("/api/ext/clinic", headers=H_LINKY).status_code == 502


# ------------------------------------------------------------------ T67 직원 목록
def internal(aid, name, role, active=True):
    return {"id": aid, "userId": f"u-{aid}", "email": f"{aid}@example.com", "name": name, "realName": f"<실명{aid}>",
            "roleId": "r-1", "roleName": role, "role": {"id": "r-1", "name": role, "roleTags": [1, 4]}, "activate": active,
            "createdAt": "", "updatedDateTimeUtc": "", "mfaMethods": [], "licenseNumber": "L-0"}


def test_t67_staff(env):
    c, fake, cl = env
    fake.internal_accounts = {"data": [internal("doc-a", "가 원장", "원장"), internal(SYSTEM, "시스템", "관리자"),
                                       internal("anes-0", "마취용", "원장"), internal("nurse-0", "간호", "간호팀", False),
                                       internal("new-1", "<새 직원>", "CS팀(콜센터)")]}
    n = len(fake.calls)
    r = cl.get("/api/ext/clinics/1/staff", headers=H_LINKY)
    assert r.status_code == 200, r.text
    assert kos(fake, n) == ["get-accounts"]
    assert [p for p, _ in fake.calls[n:] if p.endswith("/get-accounts")][0].endswith("/account/v2/queries/get-accounts")
    d = r.json()
    assert d["clinicId"] == 1 and [x["name"] for x in d["staff"]] == ["가 원장", "간호", "<새 직원>"]  # 시스템 · 제외 뺌
    doc, nurse, new = d["staff"]
    with c.repo.tx() as tx:
        copy = {x.kos_id: x for x in tx.staff()}
    assert doc == {"staffId": copy["doc-a"].id, "name": "가 원장", "roleName": "원장", "roleTags": ["DOCTOR"], "active": True}
    assert nurse["active"] is False and nurse["roleTags"] == ["NURSE"]
    assert new == {"staffId": None, "name": "<새 직원>", "roleName": "CS팀(콜센터)", "roleTags": [], "active": True}
    for leak in ("@example.com", "<실명", "u-doc-a", "doc-a", "L-0", "mfa", "roleId"):
        assert leak not in r.text


def test_t67_errors(env):
    c, fake, cl = env
    n = len(fake.calls)
    r = cl.get("/api/ext/clinics/2/staff", headers=H_LINKY)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "clinic_not_found") and kos(fake, n) == []
    assert cl.get("/api/ext/clinics/x/staff", headers=H_LINKY).status_code == 400
    fake.internal_accounts = {"data": {"x": 1}}
    assert cl.get("/api/ext/clinics/1/staff", headers=H_LINKY).status_code == 502
    fake.internal_accounts = None
    fake.fail_paths["get-accounts"] = 500
    assert cl.get("/api/ext/clinics/1/staff", headers=H_LINKY).status_code == 502
