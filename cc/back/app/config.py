"""설정 — env(.env) 로만 읽는다(SPEC-001 §8)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACK_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACK_DIR / ".env", extra="ignore")

    soniox_api_key: str = ""
    cc_capture_dir: str = ""
    cc_back_port: int = 8600
    cc_db_path: str = "data/cc.db"
    cc_front_origin: str = "http://localhost:3600"

    @property
    def db_path(self) -> Path:
        p = Path(self.cc_db_path)
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
