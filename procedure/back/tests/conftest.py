import os

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

PW = {"admin": "pw-admin", "doctor": "pw-doctor", "nurse": "pw-nurse", "coordinator": "pw-coord"}  # 시험 전용 비밀번호
ADMIN = {"id": "tester", "password": PW["admin"]}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """셸의 KOS_* · CCC_* · PROC_* · NEXT_PUBLIC_* 가 시험 결과를 바꾸지 않게(리뷰 W12)."""
    for key in list(os.environ):
        if key.startswith(("KOS_", "CCC_", "PROC_", "NEXT_PUBLIC_")):
            monkeypatch.delenv(key)


def make_settings(tmp_path, **kw) -> Settings:
    base = dict(_env_file=None, ccc_admin_id=ADMIN["id"], ccc_admin_password=PW["admin"], ccc_doctor_password=PW["doctor"],
                ccc_nurse_password=PW["nurse"], ccc_coord_password=PW["coordinator"], proc_bcrypt_rounds=4,
                proc_session_secret="test-secret", proc_db_path=str(tmp_path / "t.db"))
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def token(client) -> str:
    return client.post("/api/auth/login", json=ADMIN).json()["token"]


@pytest.fixture
def auth(token) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ctr(client):
    from app.domain.clock import Clock
    from tests.helpers import T0

    c = client.app.state.container
    c.clock.set(T0) if isinstance(c.clock, Clock) else None
    return c
