import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.main import create_app
from app.seed.build import build_seed, load_scenario

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def accounts() -> list[dict]:
    """가짜 직원(시험 픽스처) — 실제 kos-staff.json 은 쓰지 않는다."""
    return json.loads((FIXTURES / "kos-staff.json").read_text())["data"]


@pytest.fixture(scope="session")
def scenario():
    return load_scenario(FIXTURES / "scenario")


@pytest.fixture(scope="session")
def seed(scenario, accounts):
    snap, _ = build_seed(scenario[0], scenario[1], accounts)
    return snap


@pytest.fixture
def container(tmp_path, seed):
    """사용자 E2E DB(data/cc.db · seed.json)는 쓰지 않는다 — 시험마다 임시 DB."""
    settings = Settings(cc_db_path=str(tmp_path / "cc.db"), cc_front_origin="http://localhost:3600")
    settings.seed_path.write_text(json.dumps(seed, ensure_ascii=False))
    c = build_container(settings)
    c.board.load_snapshot(seed)
    return c


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container.settings, container))
