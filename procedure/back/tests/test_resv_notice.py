"""WORK-007 WP-FIX3 — 공지 [저장](SPEC-005 §5.15 · §7.5 · §8 공지 줄 · D-61).

KOS 본문 = `reservation-notice-report.md` 데모 실호출 모양(가짜 KOS 가 받은 본문을 본다).
"""

import pytest

from app.domain.errors import BadGateway, BadRequest, Conflict
from app.schemas.reservations import NoticeRequest
from tests.fake_kos import kst, z
from tests.resv_env import DAY, DESK, load, make_env, run

NEXT = "2026-10-22"  # 앞날(시험 오늘 = 2026-10-21 KST)


@pytest.fixture
def env(tmp_path):
    c, fake, mono = make_env(tmp_path)
    load(c)
    return c, fake, mono


def save(c, content, date=DAY, notice_id=None):
    return run(c.resv.notice(DESK, NoticeRequest(date=date, noticeId=notice_id, content=content)))


def writes(fake):
    return [(p.rsplit("/", 1)[-1], b) for p, b in fake.calls
            if p.rsplit("/", 1)[-1] in ("change-content", "create-notice", "delete-notice")]


def events(c):
    with c.repo.tx() as tx:
        return tx.events("notice_save")


def test_change_existing_rereads_and_keeps_untrimmed(env):
    c, fake, _ = env
    board = load(c)
    nid = board.notices[0].id
    fake.calls.clear()
    out = save(c, "  고친 공지\n둘째 줄  ", notice_id=nid)
    names = [p.rsplit("/", 1)[-1] for p, _ in fake.calls]
    assert names[0] == "get-notices"  # 저장 직전 다시 읽기(캐시 없음 · Q-139)
    assert writes(fake) == [("change-content", {"id": "ntc-1", "content": "  고친 공지\n둘째 줄  "})]
    assert out.notice is not None and out.notice.id == nid and out.notice.content == "  고친 공지\n둘째 줄  "
    assert "ntc" not in out.model_dump_json()  # 응답에 KOS id 없음(Q-143)
    ev = events(c)
    assert len(ev) == 1 and ev[0]["payload"] == {"date": DAY, "op": "change", "noticeId": nid, "requestedNoticeId": nid,
                                                 "length": 10}


def test_create_when_none_trims_and_uses_kst_midnight(env):
    c, fake, _ = env
    out = save(c, "  새 공지  ", date=NEXT)
    assert writes(fake) == [("create-notice", {"content": "새 공지", "releaseDateTimeUtc": "2026-10-21T15:00:00.000Z"})]
    assert out.notice is not None and out.notice.content == "새 공지" and out.notice.releasedAt.startswith(NEXT + "T00:00")
    assert [n.content for n in load(c, NEXT).notices] == ["새 공지"]
    p = events(c)[0]["payload"]
    assert p["op"] == "create" and p["noticeId"] == out.notice.id and p["requestedNoticeId"] is None  # 새 행 id(W2-2)


def test_create_decided_by_reread_not_by_cache(env):
    """화면이 본 뒤 다른 데스크가 먼저 만들었으면 — 둘째 create 대신 그 공지를 고친다(Q-139)."""
    c, fake, _ = env
    load(c, NEXT)
    fake.notices.append({"id": "ntc-other", "content": "먼저 쓴 공지", "releaseDateTimeUtc": "2026-10-21T15:00:00Z",
                         "deleted": False})
    save(c, "나중 저장", date=NEXT)
    assert writes(fake) == [("change-content", {"id": "ntc-other", "content": "나중 저장"})]


def test_empty_with_notice_deletes(env):
    c, fake, _ = env
    nid = load(c).notices[0].id
    out = save(c, "   \n ")
    assert writes(fake) == [("delete-notice", {"id": "ntc-1"})]
    assert out.notice is None and load(c).notices == []
    assert fake.notices[0]["deleted"] is True  # 소프트 삭제
    p = events(c)[0]["payload"]
    assert p["op"] == "delete" and p["noticeId"] == nid  # 지운 행 id(W2-2)


def test_empty_without_notice_calls_nothing(env):
    c, fake, _ = env
    fake.calls.clear()
    out = save(c, "", date=NEXT)
    assert out.notice is None and writes(fake) == [] and events(c) == []


def test_first_only_when_two(env):
    c, fake, _ = env
    fake.notices.append({"id": "ntc-2", "content": "둘째", "releaseDateTimeUtc": z(kst(10)), "deleted": False})
    save(c, "첫째 고침")
    assert writes(fake) == [("change-content", {"id": "ntc-1", "content": "첫째 고침"})]


def test_two_same_day_saves_the_one_screen_picked(env):
    """같은 날 둘 — 요청 noticeId(ccc 행 id)가 다시 읽은 목록에 있으면 그것을 고친다(추가 지시 1 W1)."""
    c, fake, _ = env
    fake.notices.append({"id": "ntc-2", "content": "둘째", "releaseDateTimeUtc": z(kst(10)), "deleted": False})
    second = next(n for n in load(c).notices if n.content == "둘째")
    out = save(c, "둘째 고침", notice_id=second.id)
    assert writes(fake) == [("change-content", {"id": "ntc-2", "content": "둘째 고침"})]
    assert out.notice is not None and out.notice.id == second.id and out.notice.content == "둘째 고침"
    assert events(c)[0]["payload"]["noticeId"] == second.id
    fake.notices[1]["deleted"] = True  # 고른 행이 KOS 에서 사라졌으면 → 첫 번째
    fake.calls.clear()
    save(c, "첫째로", notice_id=second.id)
    assert writes(fake) == [("change-content", {"id": "ntc-1", "content": "첫째로"})]


def test_past_date_409_without_kos(env):
    c, fake, _ = env
    fake.calls.clear()
    with pytest.raises(Conflict) as e:
        save(c, "x", date="2026-10-20")
    assert e.value.code == "notice_past_date" and fake.calls == []


def test_length_limit_is_trimmed_2000(env):
    c, fake, _ = env
    save(c, "  " + "가" * 2000 + "  ")  # trim 길이 2000 = 됨
    assert writes(fake)[-1][0] == "change-content"
    fake.calls.clear()
    with pytest.raises(BadRequest):
        save(c, "가" * 2001)
    assert fake.calls == []


@pytest.mark.parametrize("bad", ["", "2026-1-1", "x"])
def test_bad_date_400(env, bad):
    c, _, _ = env
    with pytest.raises(BadRequest):
        save(c, "x", date=bad)


def test_cache_cleared_after_save(env):
    c, fake, mono = env
    load(c)
    fake.notices[0]["content"] = "KOS 에서 바뀜"  # 캐시가 살아 있으면 안 보일 값
    assert run(c.resv.board(DAY)).notices[0].content == "공지 예시"  # 캐시(10초) 안
    save(c, "저장한 값")
    assert run(c.resv.board(DAY)).notices[0].content == "저장한 값"  # 저장 뒤 그 날짜를 다시 읽었다


def test_board_notice_editable(env):
    c, _, _ = env
    assert load(c).noticeEditable is True
    assert load(c, NEXT).noticeEditable is True
    assert load(c, "2026-10-20").noticeEditable is False


def test_kos_reject_409_and_unavailable_502(env):
    c, fake, _ = env
    fake.resv_fail["change-content"] = (400, {"className": "InvalidRequestException"})
    with pytest.raises(Conflict) as e:
        save(c, "x")
    assert e.value.code == "kos_rejected" and events(c) == []
    del fake.resv_fail["change-content"]
    fake.fail_paths["get-notices"] = 503
    with pytest.raises(BadGateway):
        save(c, "x")
    with c.repo.tx() as tx:
        ops = [e["payload"]["op"] for e in tx.events("kos_rejected")]
    assert ops == ["change-content", "get-notices"]


def test_http_401_400_502(client, auth):
    """HTTP 검사 순서(§7.1) — 401 → 400(모르는 필드) → KOS env 없음 502."""
    url = "/api/reservations/notice"
    assert client.put(url, json={"date": DAY, "content": "x"}).status_code == 401
    r = client.put(url, json={"date": DAY, "content": "x", "extra": 1}, headers=auth)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    r = client.put(url, json={"date": "2999-01-01", "noticeId": None, "content": "x"}, headers=auth)
    assert (r.status_code, r.json()["error"]["code"]) == (502, "kos_unavailable")
