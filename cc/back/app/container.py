"""의존성 조립 — 앱 하나에 서비스 한 벌."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.config import Settings
from app.repository.db import Database
from app.repository.state_repo import StateRepository
from app.service.board_service import BoardService
from app.service.events import EventBus
from app.service.interpret.soniox import SonioxStt, SonioxTts, SttConn, TtsConn
from app.service.patient_service import PatientService
from app.service.staff_service import StaffService


@dataclass
class Container:
    settings: Settings
    bus: EventBus
    repo: StateRepository
    board: BoardService
    staff: StaffService
    patients: PatientService
    # 통역 — Soniox 연결 팩토리(시험에서 가짜로 바꾼다)
    open_stt: Callable[[str, str], Awaitable[SttConn]] = field(default=SonioxStt.open)
    open_tts: Callable[[str], Awaitable[TtsConn]] = field(default=SonioxTts.open)


def build_container(settings: Settings, bus: EventBus | None = None) -> Container:
    repo = StateRepository(Database(settings.db_path))
    bus = bus or EventBus()
    return Container(
        settings=settings,
        bus=bus,
        repo=repo,
        board=BoardService(repo, bus, settings.seed_path),
        staff=StaffService(repo),
        patients=PatientService(repo),
    )
