"""리뷰 r1 처분(fix-decisions-r1) 시험 — F3 · W1 · W2 · W3/S5 · W6 · W7 · W10 · W11 · W12 · W13."""

import asyncio
import importlib
import logging
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient

from app.main import DropQueryString, create_app
from tests.conftest import ADMIN, make_settings
from tests.helpers import T0, seed_staff, seed_visit
from tests.test_kos_sync import env, run  # noqa: F401 — fixture 재사용


def op_states(c):
    with c.repo.tx() as tx:
        return [(o.path.rsplit("/", 1)[-1], o.status, o.attempts) for o in tx.ops()]


def boot(c):
    run(c.kos.startup())
    run(c.kos.tick())
    card = c.board.snapshot().cards[0]
    return card.visitId, [p.id for p in card.procedures if p.kind == "procedure"]


# ---------------------------------------------------------------- F3 접근 로그
def test_access_log_drops_query_string():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:1", "GET", "/api/board/stream?token=abc.def", "1.1", 200), None)
    assert DropQueryString().filter(rec)
    assert "token" not in rec.getMessage() and "/api/board/stream" in rec.getMessage()
    ws = logging.LogRecord("uvicorn.error", logging.INFO, "", 0, '%s - "WebSocket %s" %s',
                           ("127.0.0.1:1", "/api/interpret?token=abc.def", "[accepted]"), None)
    assert DropQueryString().filter(ws) and "token" not in ws.getMessage() and "/api/interpret" in ws.getMessage()


# ---------------------------------------------------------------- W12 팩토리
def test_main_import_does_not_build_app():
    mod = importlib.import_module("app.main")
    assert not hasattr(mod, "app")


# ---------------------------------------------------------------- W13 가짜 스냅샷 중 조작 막힘
def test_fake_board_blocks_actions(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, proc_fake_board=True))) as client:
        tok = client.post("/api/auth/login", json=ADMIN).json()["token"]
        r = client.post("/api/visits/101/anesthesia/start", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "fake_board"
        body = client.get("/api/board", headers={"Authorization": f"Bearer {tok}"}).json()
        assert body["limits"] == {"callMin": 5, "anesMin": 20}


# ---------------------------------------------------------------- S5 limits · 마취 long · 10초 상시 발행
def test_limits_and_anes_long_even_when_need_is_home(ctr):
    s = seed_staff(ctr.repo)
    v = seed_visit(ctr.repo, 1, procs=1, doctors={1: [s["A"]]})
    ctr.actions.anesthesia_start("t", v["visit"])
    ctr.actions.start("t", v["procs"][0])
    ctr.actions.finish("t", v["procs"][0])
    snap = ctr.board.snapshot()
    assert snap.limits.callMin == 5 and snap.limits.anesMin == 20
    assert snap.cards[0].anesthesia.long is False
    ctr.clock.set(T0 + timedelta(minutes=20))
    card = ctr.board.snapshot().cards[0]
    assert card.need.why == "home" and card.anesthesia.long is True  # need 우선순위와 따로


def test_heartbeat_publishes_without_kos(tmp_path):
    from app.container import build_container

    c = build_container(make_settings(tmp_path, kos_poll_schedule_sec=0.05))

    async def go():
        v0 = c.hub.version
        task = asyncio.create_task(c.heartbeat(check_sec=0.01))
        await asyncio.sleep(0.2)
        task.cancel()
        return c.hub.version - v0

    assert run(go()) >= 2


# ---------------------------------------------------------------- W11 날짜가 바뀌면 전날 카드 내림
def test_rollover_drops_yesterdays_cards(ctr):
    seed_staff(ctr.repo)
    v1 = seed_visit(ctr.repo, 1)
    v2 = seed_visit(ctr.repo, 2)
    with ctr.repo.tx() as tx:
        tx.update_visit(v1["visit"], synced_at=T0 - timedelta(days=1))  # 어제 조회
        tx.update_visit(v2["visit"], synced_at=T0)  # 오늘 조회
    ctr.rollover()
    assert [c.visitId for c in ctr.board.snapshot().cards] == [v2["visit"]]


# ---------------------------------------------------------------- W7 시스템 계정 id 모르면 원장 목록 유지
def test_doctor_flags_kept_when_system_unknown(ctr):
    seed_staff(ctr.repo)
    before = {d.id for d in ctr.board.snapshot().doctors}
    with ctr.repo.tx() as tx:
        tx.upsert("staff", "doc-new", {"name": "새 원장", "role_tags": ["DOCTOR"], "active": True})
        tx.set_doctor_flags(None, set())
    assert {d.id for d in ctr.board.snapshot().doctors} == before  # 시스템 계정이 끼어들지 않음


# ---------------------------------------------------------------- W1 failed 뒤 KOS 값 · 실패 표시 유지
def test_failed_follows_kos_and_keeps_failed_mark(env):  # noqa: F811
    c, fake = env
    vid, (p1, p2) = boot(c)
    doc_a = next(d.id for d in c.board.snapshot().doctors if d.name == "가 원장")
    with c.repo.tx() as tx:
        tx.update_procedure(p1, doctor_staff_ids=[doc_a])
        tx.update_procedure(p2, doctor_staff_ids=[doc_a])
    fake.schedules[0]["tasks"][0]["doctors"] = [{"id": "doc-a", "name": ""}]
    fake.schedules[0]["tasks"][1]["doctors"] = [{"id": "doc-a", "name": ""}]
    c.actions.start("t", p1)
    run(c.kos.flush())
    run(c.kos.tick())  # flow-step confirmed
    fake.fail_paths = {"change-tasks-complete": 500}
    c.actions.finish("t", p1)
    assert {p.id: p.state for p in c.board.snapshot().cards[0].procedures}[p1] == "done"
    for _ in range(3):
        run(c.kos.tick())
    assert op_states(c)[-1] == ("change-tasks-complete", "failed", 3)
    run(c.kos.tick())  # 실패 뒤 첫 조회 — 보호가 풀려 KOS 값으로 덮인다
    card = c.board.snapshot().cards[0]
    assert {p.id: p.state for p in card.procedures}[p1] == "doing"  # KOS 값(완료 아님)으로 돌아감
    assert card.kos.status == "failed"
    c.actions.start("t", p2)  # 새 op 없음(첫 시작 아님) → 여전히 실패 표시
    assert c.board.snapshot().cards[0].kos.status == "failed"
    fake.fail_paths = {}
    c.actions.finish("t", p1)  # 다시 [종료] → 새 op confirmed 되면 실패 표시가 걷힌다
    run(c.kos.flush())
    run(c.kos.tick())
    assert c.board.snapshot().cards[0].kos.status == "ok"


# ---------------------------------------------------------------- W10 실 KOS 400 흉내
def test_same_step_flow_400_then_confirmed_by_kos_value(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = boot(c)
    doc_a = next(d.id for d in c.board.snapshot().doctors if d.name == "가 원장")
    with c.repo.tx() as tx:
        tx.update_procedure(p1, doctor_staff_ids=[doc_a])
    fake.schedules[0]["tasks"][0]["doctors"] = [{"id": "doc-a", "name": ""}]
    fake.schedules[0]["flowStep"] = "PROCEDURE"  # 조회 사이에 KOS 쪽이 먼저 진행으로 감
    c.actions.start("t", p1)  # ccc 는 아직 대기 → 첫 [시작] → flow-step PROCEDURE
    run(c.kos.flush())
    assert op_states(c)[0] == ("change-flow-step", "pending", 1)  # 400 같은 단계
    run(c.kos.tick())
    assert op_states(c)[0][1] == "confirmed"  # KOS 가 이미 그 단계 → 확인
    assert c.board.snapshot().cards[0].kos.status == "ok"


def test_call_on_home_schedule_400_fails(env):  # noqa: F811
    c, fake = env
    fake.rooms_on_procedures()  # 방은 이미 들어가 있음 — 이 시험은 귀가 대기 일정 호출 400 만 본다
    vid, (p1, _) = boot(c)
    c.actions.create_call("t", vid, [p1], "all", None)
    fake.schedules[0]["flowStep"] = "PROCEDURE_DONE"  # KOS 쪽이 귀가 대기로
    run(c.kos.flush())  # assignees 200
    for _ in range(4):
        run(c.kos.tick())
    assert op_states(c) == [("change-tasks-room", "confirmed", 0), ("change-tasks-assignees", "confirmed", 0),
                            ("call-tasks-doctors", "failed", 3)]
    with c.repo.tx() as tx:
        assert tx.events("kos_failed")[0]["payload"]["error"] == "HTTP 400 InvalidRequestException"


# ---------------------------------------------------------------- W6 KosError 아닌 예외
def test_non_kos_errors_reach_sync_state_and_op_failure(env):  # noqa: F811
    c, fake = env
    vid, (p1, _) = boot(c)
    fake.schedules[0]["tasks"][0]["sequence"] = "x"  # 모양이 다른 응답 → ValueError
    run(c.kos.tick())
    assert c.board.snapshot().sync.lastError == "ValueError"
    fake.schedules[0]["tasks"][0]["sequence"] = 1

    async def boom(*_a, **_k):
        raise RuntimeError("본문 · 토큰이 들어 있을 수 있는 메시지")

    c.kos.client.send = boom
    c.actions.create_call("t", vid, [p1], "all", None)
    run(c.kos.flush())
    with c.repo.tx() as tx:
        op = tx.ops()[0]
    assert (op.status, op.attempts, op.last_error) == ("pending", 1, "RuntimeError")


def test_non_json_2xx_is_sync_failure(env):  # noqa: F811
    c, fake = env
    run(c.kos.startup())
    run(c.kos.tick())
    before = c.board.snapshot()
    assert len(before.cards) == 1
    orig = fake.handle
    for bad in (httpx.Response(200, content=b"not json"), httpx.Response(200, json={"items": []})):
        def handle(req, bad=bad):
            if req.url.path.endswith("get-schedules-grouped-by-zone"):
                return bad
            return orig(req)

        c.kos.client.http._transport = httpx.MockTransport(handle)
        assert run(c.kos.tick()) == {"error": 1}
        snap = c.board.snapshot()
        # 동기화 실패: 카드 유지 · lastError 기록 · 마지막 성공 시각 그대로
        assert len(snap.cards) == 1 and snap.sync.lastError == "일정 응답 형식"
        assert snap.sync.lastOkAt == before.sync.lastOkAt
