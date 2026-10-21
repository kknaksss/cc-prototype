"""설정 — env 로만 읽는다(SPEC-003 §2.3). 값은 `procedure/.env` 또는 `procedure/back/.env`(둘 다 gitignore)."""

from datetime import time
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACK_DIR = Path(__file__).resolve().parent.parent
FEATURE_DIR = BACK_DIR.parent


class Settings(BaseSettings):
    # 뒤에 오는 파일이 앞을 덮는다. 실제 환경변수가 둘보다 우선한다
    model_config = SettingsConfigDict(env_file=(FEATURE_DIR / ".env", BACK_DIR / ".env"), extra="ignore", env_ignore_empty=True)

    # KOS — 데모 지점만(D-06). 운영 명동점 키 금지
    kos_open_api_base: str = ""
    kos_open_api_key: str = ""
    kos_internal_api_base: str = ""
    kos_tenant_id: str = ""
    kos_system_email: str = ""
    kos_system_password: str = ""
    kos_zone_id: str = ""
    kos_exclude_account_ids: str = ""
    kos_poll_schedule_sec: float = 10
    kos_poll_master_sec: float = 3600
    kos_poll_window: str = "09:00-21:00"

    # ccc 계정(SPEC-004 §2.3) — 비면 그 계정 · 카드를 만들지 않는다
    ccc_admin_id: str = ""
    ccc_doctor_id: str = ""
    ccc_doctor_password: str = ""
    ccc_nurse_password: str = ""
    proc_bcrypt_rounds: int = 12  # 비밀번호 해시 비용(시험은 낮춘다)
    ccc_doctor_kos_account_id: str = ""  # PoC 의사 카드에 연결할 KOS 데모 지점 실제 원장(getAccounts id)
    ccc_nurse_id: str = ""
    ccc_nurse_name: str = ""
    # 원장 호출 푸시(SPEC-004 §5-1 · APNs 직접) — 하나라도 비면 발송을 끈다. 키 파일은 레포 밖
    apns_key_path: str = ""
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_bundle_id: str = ""
    apns_env: str = "production"  # sandbox | production
    # 통역(SPEC-004 §4)
    soniox_api_key: str = ""
    proc_interpret_origin: str = ""  # 브라우저 WS 허용 출처 — 비면 PROC_FRONT_ORIGIN
    ccc_admin_password: str = ""
    proc_session_secret: str = ""
    proc_session_hours: float = 12
    proc_db_path: str = "data/procedure.db"
    proc_back_port: int = 8700
    proc_front_origin: str = "http://localhost:3700"
    # 개발용 — 1 이면 GET /api/board · /stream 이 WP1 가짜 스냅샷을 준다(front 단독 작업용). 기본 0
    proc_fake_board: bool = False

    @property
    def db_path(self) -> Path:
        p = Path(self.proc_db_path)
        return p if p.is_absolute() else BACK_DIR / p

    @property
    def exclude_account_ids(self) -> set[str]:
        return {x.strip() for x in self.kos_exclude_account_ids.split(",") if x.strip()}

    @property
    def poll_window(self) -> tuple[time, time]:
        start, end = self.kos_poll_window.split("-")
        return time.fromisoformat(start.strip()), time.fromisoformat(end.strip())

    @property
    def apns_enabled(self) -> bool:
        return all((self.apns_key_path, self.apns_key_id, self.apns_team_id, self.apns_bundle_id,
                    self.apns_env in ("sandbox", "production")))

    @property
    def kos_enabled(self) -> bool:
        """KOS 연동에 필요한 값이 다 있나 — 하나라도 비면 조회 · 반영 루프를 띄우지 않는다."""
        return all((self.kos_open_api_base, self.kos_open_api_key, self.kos_internal_api_base, self.kos_tenant_id,
                    self.kos_system_email, self.kos_system_password, self.kos_zone_id))


@lru_cache
def get_settings() -> Settings:
    return Settings()
