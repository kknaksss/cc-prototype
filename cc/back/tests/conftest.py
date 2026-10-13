import json
import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.main import create_app
from app.seed.build import build_seed
from app.seed.capture import Capture


def _capture_dir() -> str:
    return os.environ.get("CC_CAPTURE_DIR") or Settings().cc_capture_dir


@pytest.fixture(scope="session")
def capture() -> Capture:
    root = _capture_dir()
    if not root or not Path(root).is_dir():
        pytest.skip("CC_CAPTURE_DIR 가 없어 캡처 기반 시험을 건너뜀")
    return Capture(Path(root))


@pytest.fixture(scope="session")
def seed(capture):
    snap, notes = build_seed(capture, date(2026, 10, 9), "14:45")
    return snap


@pytest.fixture
def container(tmp_path, seed):
    settings = Settings(cc_db_path=str(tmp_path / "cc.db"), cc_capture_dir="", cc_front_origin="http://localhost:3600")
    settings.seed_path.write_text(json.dumps(seed, ensure_ascii=False))
    c = build_container(settings)
    c.board.load_snapshot(seed)
    return c


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container.settings, container))
