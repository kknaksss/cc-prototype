"""배포(DEC-003) — 평평한 이벤트 파일(Secret 마운트) · seed ensure · 헬스."""

import json
import shutil

from app.config import Settings
from app.container import build_container
from app.seed.__main__ import main as seed_main
from app.seed.build import load_scenario
from tests.conftest import FIXTURES


def test_flat_events_layout(tmp_path):
    """쿠버네티스 Secret 은 하위 폴더를 못 만든다 — `event-<id>.json` · `events.json` 도 읽는다."""
    shutil.copy(FIXTURES / "scenario" / "seed.json", tmp_path / "seed.json")
    ev = {f.stem: json.loads(f.read_text()) for f in (FIXTURES / "scenario" / "events").glob("*.json")}
    (tmp_path / "event-sch-1.json").write_text(json.dumps(ev["sch-1"]))
    (tmp_path / "events.json").write_text(json.dumps({"sch-4": ev["sch-4"]}))
    _, events = load_scenario(tmp_path)
    assert set(events) == {"sch-1", "sch-4"} and events == ev


def test_seed_ensure_builds_once(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "db" / "cc.db"))
    monkeypatch.setenv("CC_SCENARIO_DIR", str(FIXTURES / "scenario"))
    monkeypatch.setenv("CC_KOS_STAFF_PATH", str(FIXTURES / "kos-staff.json"))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert seed_main(["ensure"]) == 0  # 빈 DB → 시나리오로 build
        c = build_container(Settings())
        v = c.board.version()
        assert v > 0 and len(c.board.board()["resv"]) == 5 and (tmp_path / "db" / "seed.json").exists()
        assert seed_main(["ensure"]) == 0  # 이미 있음 → 건너뜀
        assert build_container(Settings()).board.version() == v
    finally:
        get_settings.cache_clear()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True
