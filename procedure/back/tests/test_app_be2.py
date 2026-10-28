"""WORK-009 WP-BE2 — 상담사 호출 푸시(SPEC-004 §5-2 · §8.6 「상담사 호출 푸시」). 가짜 KOS · 가짜 APNs."""

import asyncio
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.domain.errors import Conflict
from app.push.apns import ApnsClient
from app.service.push import PushService
from tests.fake_kos import ZONE, rtask
from tests.resv_env import DESK, load, make_env, rid_of, run
from tests.test_push import FakeApns, tok

ROOM1 = {"id": "room-1", "zoneId": ZONE, "title": "A-룸1", "order": 1}
LOGINS = dict(ccc_admin_id="admin1", ccc_admin_password="pw", ccc_coord_id="coord1", ccc_coord_password="pw",
              ccc_counselor_id="counsel1", ccc_counselor_password="pw", ccc_counselor_kos_account_id="cs-1",
              proc_session_secret="s", proc_bcrypt_rounds=4)


def _key(tmp_path) -> str:
    path = tmp_path / "AuthKey_TEST.p8"
    path.write_bytes(ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return str(path)


def _setup(c):
    with c.repo.tx() as tx:
        for kos, name in (("cs-1", "상담사 1"), ("cs-2", "상담사 2")):
            tx.upsert("staff", kos, {"name": name, "role_tags": ["COUNSELOR"], "active": True})
    c.accounts.sync()
    with c.repo.tx() as tx:
        acc = {a.login_id: a for a in tx.accounts() if a.active}
        for login, a in acc.items():  # 계정마다 기기 1대(의사 · 관리자 · 코디 · 상담사)
            tx.put_device(a.id, tok(login), c.clock.now())
        sid = {s.kos_id: s.id for s in tx.staff()}
    return acc, sid


@pytest.fixture
def env(tmp_path):
    c, fake, _ = make_env(tmp_path, apns_key_path=_key(tmp_path), apns_key_id="KEYID00001", apns_team_id="TEAMID0001",
                          apns_bundle_id="com.example.procedure", apns_env="sandbox", **LOGINS)
    apns = FakeApns()
    c.push = PushService(c.repo, c.settings, client=ApnsClient(c.settings, transport=httpx.MockTransport(apns.handle)),
                         clock=c.clock, notifications=c.notifications)
    acc, sid = _setup(c)
    pressed = []
    c.reception.on_counselor_call = lambda rid, s: pressed.append((rid, s))  # 발송은 시험이 notify_counselor 로
    yield c, fake, apns, acc, sid, pressed


def add(c, fake, sid_, vid="vis-1", room=True, **kw):
    tasks = [rtask(1, "ETCETERA", "READY", room=ROOM1, title="방 배정")] if room else []
    fake.add_resv(sid_, vid, flow="CONSULTATION_WAITING", status="IN_PROGRESS", tasks=tasks, name="고객이름", **kw)
    load(c)
    return rid_of(c, sid_)


def notes(c):
    with c.repo.db.connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM notification ORDER BY id")]


def test_counselor_push_only_after_kos_200(env):
    c, fake, apns, acc, sid, pressed = env
    rid = add(c, fake, "s1")
    run(c.reception.counselor_call(DESK, rid, sid["cs-1"]))
    run(c.reception.counselor_call(DESK, rid, sid["cs-1"]))  # 다시 누름 = 다시
    run(c.reception.counselor_call(DESK, rid, sid["cs-2"]))  # 다른 상담사 = 그 상담사
    assert pressed == [(rid, sid["cs-1"]), (rid, sid["cs-1"]), (rid, sid["cs-2"])]
    fake.resv_fail["update-reservation"] = (400, {"className": "InvalidRequestException"})
    with pytest.raises(Conflict):
        run(c.reception.counselor_call(DESK, rid, sid["cs-1"]))
    assert len(pressed) == 3  # KOS 거절 = 0
    with pytest.raises(Conflict):  # 상담사 아님 = 0
        run(c.reception.counselor_call(DESK, rid, sid["doc-a"]))
    assert len(pressed) == 3


def test_counselor_push_recipient_content_payload(env):
    c, fake, apns, acc, sid, pressed = env
    rid = add(c, fake, "s1")
    out = asyncio.run(c.push.notify_counselor(rid, sid["cs-1"]))
    assert out == {"sent": 1, "failed": 0, "removed": 0}
    assert apns.tokens() == [tok("counsel1")]  # 그 상담사만 — 관리자 · 코디 · 의사 · 다른 상담사 0
    p = apns.requests[0]["payload"]
    assert p == {"aps": {"alert": {"title": "상담사 호출", "body": "A-룸1 · 상담 대기"}, "sound": "default"},
                 "kind": "counselor_call", "reservationId": rid}
    assert "category" not in p["aps"] and "고객이름" not in json.dumps(p, ensure_ascii=False)
    with c.repo.tx() as tx:
        logs = tx.push_logs()
    n = notes(c)
    assert len(n) == 1 and (n[0]["kind"], n[0]["reservation_id"], n[0]["call_id"]) == ("counselor_call", rid, None)
    assert [(x["kind"], x["reservation_id"], x["notification_id"], x["call_id"], x["status"]) for x in logs] == [
        ("counselor_call", rid, n[0]["id"], None, "sent")]

    apns.requests.clear()  # 다른 상담사로 바꿈 = 새 상담사만(앞 상담사 0 · 계정 행 내부 login_id · 기기 있음)
    asyncio.run(c.push.notify_counselor(rid, sid["cs-2"]))
    assert apns.tokens() == [tok(f"counselor-{sid['cs-2']}")]


def test_counselor_push_body_without_room(env):
    c, fake, apns, acc, sid, pressed = env
    rid = add(c, fake, "s2", "vis-2", room=False)
    asyncio.run(c.push.notify_counselor(rid, sid["cs-1"]))
    assert apns.requests[0]["payload"]["aps"]["alert"]["body"] == "상담 대기"


def test_counselor_push_setting_off(env):
    c, fake, apns, acc, sid, pressed = env
    rid = add(c, fake, "s1")
    with c.repo.tx() as tx:
        tx.put_notification_setting(acc["counsel1"].id, "counselor_call", False, c.clock.now())
    assert asyncio.run(c.push.notify_counselor(rid, sid["cs-1"]))["sent"] == 0
    with c.repo.tx() as tx:
        assert tx.push_logs() == []
    assert apns.requests == [] and notes(c) == []


def test_counselor_push_inactive_or_no_device(env):
    c, fake, apns, acc, sid, pressed = env
    rid = add(c, fake, "s1")
    with c.repo.tx() as tx:
        tx.delete_device(tok("counsel1"))
    asyncio.run(c.push.notify_counselor(rid, sid["cs-1"]))
    assert apns.requests == [] and [x["account_id"] for x in notes(c)] == [acc["counsel1"].id]  # 기기 없음 = 행만
    with c.repo.tx() as tx:
        tx.update_account(acc["counsel1"].id, c.clock.now(), active=False)
    asyncio.run(c.push.notify_counselor(rid, sid["cs-1"]))
    assert len(notes(c)) == 1  # 비활성 = 0


def test_counselor_call_wired_to_push_without_key(tmp_path):
    """컨테이너 연결 — 키 없음 = 알림 행 + push_log skipped_no_key(동기)."""
    c, fake, _ = make_env(tmp_path, **LOGINS)
    acc, sid = _setup(c)
    rid = add(c, fake, "s1")
    run(c.reception.counselor_call(DESK, rid, sid["cs-1"]))
    with c.repo.tx() as tx:
        logs = tx.push_logs()
    assert [(x["kind"], x["status"], x["account_id"]) for x in logs] == [
        ("counselor_call", "skipped_no_key", acc["counsel1"].id)]
    assert [(x["kind"], x["account_id"]) for x in notes(c)] == [("counselor_call", acc["counsel1"].id)]
    listing = c.notifications.listing(acc["counsel1"])
    assert listing["unread"] == 1 and listing["items"][0]["target"] == {"reservationId": rid}
