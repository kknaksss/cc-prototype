"""설정 — env(.env) 로만 읽는다(SPEC-001 §8)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACK_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACK_DIR / ".env", extra="ignore")

    soniox_api_key: str = ""
    cc_capture_dir: str = ""  # 0.2.1 부터 시드는 시나리오 파일(CC_SCENARIO_DIR) — 캡처는 직접 읽지 않는다
    cc_back_port: int = 8600
    cc_db_path: str = "data/cc.db"
    cc_front_origin: str = "http://localhost:3600"
    cc_kos_staff_path: str = "data/kos-staff.json"
    cc_scenario_dir: str = "data/scenario"

    @property
    def db_path(self) -> Path:
        p = Path(self.cc_db_path)
        return p if p.is_absolute() else BACK_DIR / p

    @property
    def kos_staff_path(self) -> Path:
        p = Path(self.cc_kos_staff_path)
        return p if p.is_absolute() else BACK_DIR / p

    @property
    def scenario_dir(self) -> Path:
        p = Path(self.cc_scenario_dir)
        return p if p.is_absolute() else BACK_DIR / p

    @property
    def data_dir(self) -> Path:
        return self.db_path.parent

    @property
    def seed_path(self) -> Path:
        return self.data_dir / "seed.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
