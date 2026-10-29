"""WP-BE2 — 카드 드래그 순서(SPEC-003 0.4.0 §3.2 · §5.12 · §7.3 · §7.5): 저장 · 거르기 · 400 · 마지막 쓰기 · 로그 · SSE · 정렬."""

import asyncio
import json
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repository.db import SCHEMA, Database
from tests.conftest import ADMIN, make_settings
from tests.helpers import T0, seed_staff, seed_visit

URL = "/api/board/order"


@pytest.fixture
def three(ctr):
    """카드 3장(입실 1 → 2 → 3)."""
    seed_staff(ctr.repo)
    return [seed_visit(ctr.repo, n)["visit"] for n in (1, 2, 3)]


def order(ctr) -> list[int]:
    return [c.visitId for c in ctr.board.snapshot().cards]


def rows(ctr):
    with ctr.repo.tx() as tx:
        ev = tx.events("board_order")
        saved = tx.con.execute("SELECT * FROM board_order").fetchall()
        return ev, [dict(r) for r in saved], tx.ops()


def test_save_and_snapshot_follows(client, auth, ctr, three):
    a, b, c = three
    assert order(ctr) == [a, b, c]  # 순서 없음 = 입실순
    r = client.put(URL, json={"visitIds": [c, a, b]}, headers=auth)
    assert r.status_code == 200 and r.json() == {"ok": True, "visitIds": [c, a, b]}
    assert order(ctr) == [c, a, b]
    assert [x["visitId"] for x in client.get("/api/board", headers=auth).json()["cards"]] == [c, a, b]


def test_event_log_one_row_and_no_kos_op(client, auth, ctr, three):
    a, b, c = three
    client.put(URL, json={"visitIds": [b, a, c]}, headers=auth)
    ev, saved, ops = rows(ctr)
    assert len(ev) == 1 and ev[0]["actor"] == ADMIN["id"] and ev[0]["visit_id"] is None
    assert ev[0]["payload"] == {"day": "2026-10-21", "visitIds": [b, a, c]}
    assert len(saved) == 1 and saved[0]["day"] == "2026-10-21" and json.loads(saved[0]["visit_ids"]) == [b, a, c]
    assert saved[0]["updated_by"] == ADMIN["id"] and saved[0]["event_id"] == ev[0]["id"]
    assert ops == []  # KOS 반영 없음


def test_filters_unknown_home_and_gone_cards(client, auth, ctr, three):
    a, b, c = three
    home = seed_visit(ctr.repo, 4, flow="PROCEDURE_DONE")["visit"]
    gone = seed_visit(ctr.repo, 5)["visit"]
    lounge = seed_visit(ctr.repo, 6, room=False)["visit"]  # 방 없음 = 카드 아님
    with ctr.repo.tx() as tx:
        tx.update_visit(gone, present=False)  # 데스크 귀가 등으로 사라진 카드
    r = client.put(URL, json={"visitIds": [999, c, home, gone, lounge, b, a]}, headers=auth)
    assert r.status_code == 200 and r.json()["visitIds"] == [c, b, a]
    ev, saved, _ = rows(ctr)
    assert ev[0]["payload"]["visitIds"] == [c, b, a] and json.loads(saved[0]["visit_ids"]) == [c, b, a]


@pytest.mark.parametrize("body", [
    [1, 2],  # 객체 아님
    {},  # visitIds 없음
    {"visitIds": [1], "extra": 1},  # 그 밖 필드
    {"visitIds": 1},  # 배열 아님
    {"visitIds": ["3"]},  # StrictInt — 문자열
    {"visitIds": [3.0]},  # 실수
    {"visitIds": [True]},  # 불리언
    {"visitIds": [None]},
])
def test_bad_format_400(client, auth, ctr, three, body):
    before = ctr.hub.version
    r = client.put(URL, json=body, headers=auth)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    assert rows(ctr)[0] == [] and ctr.hub.version == before


def test_duplicate_id_400(client, auth, ctr, three):
    a, b, _ = three
    r = client.put(URL, json={"visitIds": [a, b, a]}, headers=auth)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    assert rows(ctr)[0] == []


def test_duplicate_unknown_id_still_400(client, auth, ctr, three):
    """같은 id 두 번은 거르기 전에 본다(없는 id 여도 형식 오류)."""
    r = client.put(URL, json={"visitIds": [999, 999]}, headers=auth)
    assert r.status_code == 400


def test_empty_list_clears_order(client, auth, ctr, three):
    a, b, c = three
    client.put(URL, json={"visitIds": [c, b, a]}, headers=auth)
    r = client.put(URL, json={"visitIds": []}, headers=auth)
    assert r.json() == {"ok": True, "visitIds": []}
    assert order(ctr) == [a, b, c]


def test_last_write_wins(client, auth, ctr, three):
    a, b, c = three
    client.put(URL, json={"visitIds": [c, b, a]}, headers=auth)
    client.put(URL, json={"visitIds": [b, a]}, headers=auth)  # 뒤 사람 목록에 c 없음 → 목록 밖(맨 뒤 · 입실순)
    assert order(ctr) == [b, a, c]
    ev, saved, _ = rows(ctr)
    assert len(ev) == 2 and len(saved) == 1


def test_publishes_one_board_after_save(client, auth, ctr, three):
    a, b, c = three
    hub = ctr.hub

    async def run():
        gen = hub.frames(ping_sec=5)
        first = json.loads((await gen.__anext__()).split("data: ", 1)[1])
        assert [x["visitId"] for x in first["cards"]] == [a, b, c]
        kept = ctr.actions.board_order("tester", [c, b, a])
        assert kept == [c, b, a]
        nxt = json.loads((await asyncio.wait_for(gen.__anext__(), 1)).split("data: ", 1)[1])
        assert nxt["version"] == first["version"] + 1 and [x["visitId"] for x in nxt["cards"]] == [c, b, a]
        with pytest.raises(TimeoutError):  # 1개만
            await asyncio.wait_for(gen.__anext__(), 0.1)
        await gen.aclose()

    asyncio.run(run())


def test_http_save_publishes_once(client, auth, ctr, three):
    before = ctr.hub.version
    assert client.put(URL, json={"visitIds": three[::-1]}, headers=auth).status_code == 200
    assert ctr.hub.version == before + 1


def test_requires_login(client, ctr, three):
    r = client.put(URL, json={"visitIds": three})
    assert (r.status_code, r.json()["error"]["code"]) == (401, "unauthorized")
    assert client.put(URL, json=[1], headers={"Authorization": "Bearer nope.sig"}).status_code == 401  # 401 이 400 보다 먼저
    assert rows(ctr)[0] == []


def test_fake_board_403(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, proc_fake_board=True))) as client:
        tok = client.post("/api/auth/login", json=ADMIN).json()["token"]
        r = client.put(URL, json={"visitIds": [101, 102]}, headers={"Authorization": f"Bearer {tok}"})
        assert (r.status_code, r.json()["error"]["code"]) == (403, "fake_board")
        assert client.put(URL, json={"visitIds": [101]}).status_code == 401  # 401 이 403 보다 먼저


def test_cors_allows_put(client):
    r = client.options(URL, headers={"Origin": "http://localhost:3700", "Access-Control-Request-Method": "PUT"})
    assert r.status_code == 200 and "PUT" in r.headers["access-control-allow-methods"]


# ------------------------------------------------------------------ 스냅샷 정렬(§5.12)
def test_sort_list_then_rest_by_in_at_then_home(client, auth, ctr):
    seed_staff(ctr.repo)
    v = {n: seed_visit(ctr.repo, n)["visit"] for n in (1, 2, 3, 4, 5)}
    client.put(URL, json={"visitIds": [v[4], v[2]]}, headers=auth)
    # ① 목록 4 · 2 → ② 목록 밖 입실순 1 · 3 · 5
    assert order(ctr) == [v[4], v[2], v[1], v[3], v[5]]
    # 목록 안 카드가 귀가 대기 → ③ 맨 뒤(귀가 대기 시각 순) · 목록 자리는 무시
    with ctr.repo.tx() as tx:
        tx.update_visit(v[4], flow_step="PROCEDURE_DONE", flow_step_at=T0 + timedelta(minutes=30))
        tx.update_visit(v[1], flow_step="PROCEDURE_DONE", flow_step_at=T0 + timedelta(minutes=20))
    assert order(ctr) == [v[2], v[3], v[5], v[1], v[4]]
    # 새 카드 → 귀가 대기 아닌 카드들 맨 뒤(목록 밖 입실순)
    new = seed_visit(ctr.repo, 6)["visit"]
    assert order(ctr) == [v[2], v[3], v[5], new, v[1], v[4]]
    # 목록 안 카드가 사라지면 그냥 건너뛴다
    with ctr.repo.tx() as tx:
        tx.update_visit(v[2], present=False)
    assert order(ctr) == [v[3], v[5], new, v[1], v[4]]


def test_in_at_tie_breaks_by_visit_id(ctr):
    seed_staff(ctr.repo)
    a, b = seed_visit(ctr.repo, 1)["visit"], seed_visit(ctr.repo, 2)["visit"]
    with ctr.repo.tx() as tx:
        tx.update_visit(a, room_assigned_at=T0)
        tx.update_visit(b, room_assigned_at=T0)
    assert order(ctr) == sorted([a, b])


def test_next_day_has_no_order(client, auth, ctr, three):
    a, b, c = three
    client.put(URL, json={"visitIds": [c, b, a]}, headers=auth)
    ctr.clock.set(T0 + timedelta(hours=13))  # KST 다음날 00:00
    assert order(ctr) == [a, b, c]  # 새 날 = 순서 없음(전날 행은 읽지 않는다)
    with ctr.repo.tx() as tx:
        assert tx.board_order("2026-10-21") == [c, b, a] and tx.board_order("2026-10-22") == []
    client.put(URL, json={"visitIds": [b, a, c]}, headers=auth)  # 새 날 순서는 새 행
    with ctr.repo.tx() as tx:
        assert tx.board_order("2026-10-22") == [b, a, c] and tx.board_order("2026-10-21") == [c, b, a]


def test_kst_day_boundary(client, auth, ctr, three):
    """오늘 = KST — UTC 15:00 직전은 같은 날, 15:00 부터 다음 날."""
    a, b, c = three
    ctr.clock.set(T0 + timedelta(hours=12, minutes=59))  # KST 23:59
    client.put(URL, json={"visitIds": [c, b, a]}, headers=auth)
    with ctr.repo.tx() as tx:
        assert tx.board_order("2026-10-21") == [c, b, a]


# ------------------------------------------------------------------ 옛 스키마 DB(r2)
def test_old_schema_db_keeps_rows(tmp_path):
    """0.3.0 SCHEMA(board_order 없음)로 만든 SQLite 파일 + visit 행 1 → 지금 초기화 → board_order 생김 · visit 행 남음."""
    head, sep, tail = SCHEMA.partition("CREATE TABLE IF NOT EXISTS board_order")
    assert sep and "CREATE TABLE" not in tail  # board_order 가 마지막 표 — 그 앞이 0.3.0 SCHEMA
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(head)
    con.execute("INSERT INTO visit (kos_id, flow_step) VALUES ('sch-old', 'PROCEDURE_WAITING')")
    con.commit()
    assert "board_order" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    con.close()

    db = Database(path)
    with db.connect() as con:
        tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        visits = [dict(r) for r in con.execute("SELECT kos_id, flow_step FROM visit")]
        cols = [r["name"] for r in con.execute("PRAGMA table_info(board_order)")]
    assert "board_order" in tables
    assert cols == ["day", "visit_ids", "updated_at", "updated_by", "event_id"]
    assert visits == [{"kos_id": "sch-old", "flow_step": "PROCEDURE_WAITING"}]


# ------------------------------------------------------------------ 경로 수(§7.4)
# 앱 다음 판 새 HTTP 14(SPEC-004 0.4.1 §7.3 · SPEC-006 §6.7)
APP_ROUTES = {("GET", "/api/notifications"), ("POST", "/api/notifications/read"), ("GET", "/api/me/notification-settings"),
              ("PUT", "/api/me/notification-settings"), ("GET", "/api/devices/targets"), ("POST", "/api/display-requests"),
              ("GET", "/api/display-requests/pending"), ("POST", "/api/display-requests/claim"),
              ("POST", "/api/display-requests/{request_id}/close"), ("GET", "/api/public/questionnaire"),
              ("POST", "/api/public/questionnaire"), ("DELETE", "/api/id-photos/{photo_id}"),
              ("PUT", "/api/customers/{customer_id}/funnel"),
              ("POST", "/api/customers/{customer_id}/passport-scan"), ("GET", "/api/id-photos/{photo_id}"),
              ("POST", "/api/id-photos/{photo_id}/kos-retry")}

# 직원 채팅 HTTP 18(SPEC-007 §6.2 · §6.4 — 1판 14 + r3 수정 · 동영상 올리기 · 열기 · 썸네일 4)
CHAT_ROUTES = {("GET", "/api/chat/people"), ("GET", "/api/chat/rooms"), ("POST", "/api/chat/rooms/direct"),
               ("POST", "/api/chat/rooms"), ("POST", "/api/chat/rooms/{room_id}/members"),
               ("POST", "/api/chat/rooms/{room_id}/leave"), ("POST", "/api/chat/rooms/{room_id}/hide"),
               ("PUT", "/api/chat/rooms/{room_id}/mute"), ("GET", "/api/chat/rooms/{room_id}/messages"),
               ("POST", "/api/chat/rooms/{room_id}/messages"), ("DELETE", "/api/chat/messages/{message_id}"),
               ("POST", "/api/chat/rooms/{room_id}/read"), ("POST", "/api/chat/photos"), ("GET", "/api/chat/photos/{photo_id}"),
               ("PATCH", "/api/chat/messages/{message_id}"), ("POST", "/api/chat/videos"),
               ("GET", "/api/chat/videos/{video_id}"), ("GET", "/api/chat/videos/{video_id}/thumbnail")}


def test_route_count_69(client):
    """back 경로 69 = HTTP 68 + 통역 WS 1 — 51(아래) + 직원 채팅 HTTP 18(SPEC-007 §6.4 · 1판 14 + r3 4).

    51 = HTTP 50 + 통역 WS 1 — 앞 판 35(SPEC-005 §7.6 · 시술 현황 19 + 예약 현황 HTTP 16)
    + 앱 다음 판 새 HTTP 16(띄우기 5 · 스캔 · 사진 3 · 알림 4 · 고객 문진 웹 공개 2 — SPEC-006 §6.7:
    직원 문진 2 · unlock 1 없앰 · 공개 GET · POST 더함 · E2E batch 3: 사진 삭제 · 유입 채널 2)."""
    from app.api import interpret

    http = {(m.upper(), p) for p, ops in client.app.openapi()["paths"].items() for m in ops}
    ws = [r.path for r in interpret.router.routes if type(r).__name__ == "APIWebSocketRoute"]
    assert ("PUT", URL) in http and ws == ["/api/interpret"]
    assert {("POST", "/api/procedures/{procedure_id}/undo-start"), ("POST", "/api/procedures/{procedure_id}/undo-finish")} <= http
    assert ("PUT", "/api/reservations/notice") in http
    assert len([x for x in http - APP_ROUTES if "/reservations" in x[1] or "/customers" in x[1]]) == 16
    assert len(APP_ROUTES) == 16 and APP_ROUTES <= http
    gone = {("GET", "/api/questionnaires/{reservation_id}"), ("POST", "/api/questionnaires/{reservation_id}"),
            ("POST", "/api/auth/unlock")}
    assert not gone & http
    assert len(CHAT_ROUTES) == 18 and CHAT_ROUTES <= http
    assert len([x for x in http if x[1].startswith("/api/chat")]) == 18
    assert len(http - CHAT_ROUTES) + len(ws) == 51, sorted(http)
    assert len(http) + len(ws) == 69, sorted(http)
