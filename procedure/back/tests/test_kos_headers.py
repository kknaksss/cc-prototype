"""KOS 내부 API 요청 헤더 — 웹 클라이언트 User-Agent · Origin · kos-client-uri(2026-11-03 내부 403 `Unsupported client.`).

내부(sign-in · get-user-account · internal · send internal)엔 싣고, 공개 · presigned PUT 엔 싣지 않는다.
"""

import asyncio
from datetime import UTC, datetime

import pytest

from app.container import build_container
from app.domain.clock import Clock
from app.kos.client import WEB_USER_AGENT, KosClient
from tests.fake_kos import TENANT, FakeKos, kos_settings

WEB = "https://app.kos.test"
CHROME_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/150.0.0.0 Safari/537.36")


def run(coro):
    return asyncio.run(coro)


def client(tmp_path, **kw):
    fake = FakeKos()
    s = kos_settings(tmp_path, **kw)
    clock = Clock()
    clock.set(datetime(2026, 10, 21, 2, 0, tzinfo=UTC))
    c = build_container(s, clock)
    return KosClient(s, c.repo, clock, transport=fake.transport()), fake


def _exercise(kc):
    async def go():
        await kc.internal("schedule/zone/room/queries/get-rooms", {})
        await kc.send("internal", "account/queries/get-accounts", {})
        await kc.open("account/open/v1/queries/get-accounts", {})
        await kc.send("open", "account/open/v1/queries/get-accounts", {})
        await kc.put_presigned("https://s3.fake.test/bucket/a.jpg?X-Amz-Signature=sig", b"x", "image/jpeg")
        await kc.aclose()
    run(go())


def _by_kind(fake):
    internal = [(p, h) for p, h in fake.headers if p.startswith("internal.fake.test")]
    others = [(p, h) for p, h in fake.headers if not p.startswith("internal.fake.test")]
    return internal, others


def test_internal_requests_carry_web_client_headers(tmp_path):
    kc, fake = client(tmp_path, kos_web_base=WEB + "/")
    _exercise(kc)
    internal, others = _by_kind(fake)
    names = [p.rsplit("/", 1)[-1] for p, _ in internal]
    assert names == ["sign-in", "get-user-account", "get-rooms", "get-accounts"]
    assert WEB_USER_AGENT == CHROME_UA
    for _, h in internal:
        assert h["user-agent"] == CHROME_UA
        assert h["origin"] == WEB  # 끝 / 뗀 값
        assert h["kos-client-uri"] == f"{WEB}/{TENANT}/reservation/schedule/"
    # Authorization 과 합친다 — sign-in 만 토큰 없음
    assert "authorization" not in internal[0][1]
    assert all(h["authorization"].startswith("Bearer int-") for _, h in internal[1:])
    # 공개 · presigned PUT 엔 안 싣는다
    assert {p.split("/", 1)[0] for p, _ in others} == {"open.fake.test", "s3.fake.test"}
    for _, h in others:
        assert h.get("user-agent", "").startswith("python-httpx/")
        assert "origin" not in h and "kos-client-uri" not in h
    assert fake.uploads[0]["auth"] is None


def test_retry_after_401_keeps_headers(tmp_path):
    kc, fake = client(tmp_path, kos_web_base=WEB)
    async def go():
        await kc.internal_token()
        fake.expire_once.add("internal")  # 다음 내부 호출 1번 401 → 다시 받기 → 같은 요청
        await kc.internal("schedule/zone/room/queries/get-rooms", {})
        await kc.aclose()
    run(go())
    internal, _ = _by_kind(fake)
    assert [p.rsplit("/", 1)[-1] for p, _ in internal] == [
        "sign-in", "get-user-account", "get-rooms", "sign-in", "get-user-account", "get-rooms"]
    assert all(h["user-agent"] == CHROME_UA and h["origin"] == WEB for _, h in internal)


@pytest.mark.parametrize("web", ["", None])
def test_no_web_base_sends_user_agent_only(tmp_path, web):
    kw = {"kos_web_base": web} if web is not None else {}
    kc, fake = client(tmp_path, **kw)
    _exercise(kc)
    internal, _ = _by_kind(fake)
    assert len(internal) == 4
    for _, h in internal:
        assert h["user-agent"] == CHROME_UA
        assert "origin" not in h and "kos-client-uri" not in h
