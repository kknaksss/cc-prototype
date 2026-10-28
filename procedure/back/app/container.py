"""의존성 조립 — 앱 하나에 서비스 한 벌."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.domain.clock import Clock, today_range_kst
from app.repository.db import Database
from app.repository.repo import Repository
from app.schemas.board import BoardSnapshot
from app.service.accounts import AccountService
from app.service.actions import ActionService
from app.service.auth import AuthService
from app.service.board_service import BoardService
from app.service.devices import DeviceService
from app.service.display import DisplayService
from app.service.fake_board import fake_snapshot
from app.service.id_photo import PhotoService
from app.service.interpret.soniox import SonioxStt, SonioxTts, SttConn, TtsConn
from app.service.notifications import NotificationService
from app.service.passport_scan import PassportScanService
from app.service.push import PushService
from app.service.questionnaire import QuestionnaireService
from app.service.reception import ReceptionService
from app.service.reservations import ReservationService
from app.service.stream import StreamHub


@dataclass
class Container:
    settings: Settings
    clock: Clock
    repo: Repository
    auth: AuthService
    board: BoardService
    actions: ActionService
    accounts: AccountService
    push: PushService
    devices: DeviceService
    notifications: NotificationService
    hub: StreamHub = field(init=False)
    display: Any = None  # DisplayService — 띄우기 요청(SPEC-004 §5-3)
    questionnaire: Any = None  # QuestionnaireService — 고객 문진 웹(SPEC-006)
    photos: Any = None  # PhotoService — 신분증 사진(SPEC-004 §6.16)
    scan: Any = None  # PassportScanService
    resv: Any = None  # ReservationService — 예약 현황(SPEC-005)
    reception: Any = None  # ReceptionService
    kos: Any = None  # app.kos.runtime.KosRuntime — KOS env 가 있을 때만
    # 통역 — Soniox 연결 팩토리(시험에서 가짜로 바꾼다 · SPEC-004 §4.1)
    open_stt: Callable[[str, str], Awaitable[SttConn]] = field(default=SonioxStt.open)
    open_tts: Callable[[str], Awaitable[TtsConn]] = field(default=SonioxTts.open)

    def __post_init__(self) -> None:
        self.hub = StreamHub(self.snapshot)
        # 새 알림 행 → 그 계정 스트림에만 `notification {unread}`(SPEC-004 §5-4 · §7.1)
        self.notifications.on_new = lambda account_id, unread: self.hub.send_to_account(
            account_id, "notification", {"unread": unread})

    def snapshot(self) -> BoardSnapshot:
        if self.settings.proc_fake_board:
            return fake_snapshot(self.clock.now())
        return self.board.snapshot()

    def changed(self) -> None:
        """ccc · KOS 상태가 바뀐 뒤 — SSE 발행 · 반영 루프 깨우기."""
        self.hub.publish()
        if self.kos is not None:
            self.kos.kick()

    def rollover(self) -> None:
        """날짜가 바뀌면(KST 00:00) 전날 조회된 카드를 내린다(리뷰 W11) — 오늘 조회되지 않은 visit 의 present 를 끈다."""
        start, _ = today_range_kst(self.clock.now())
        with self.repo.tx() as tx:
            dropped = tx.drop_visits_synced_before(start)
        if dropped:
            self.hub.publish()

    async def heartbeat(self, check_sec: float = 1.0) -> None:
        """조회 시간 · KOS 와 상관없이 KOS_POLL_SCHEDULE_SEC 마다 board 를 발행한다(경과 · 확인 필요 · 조회 시간 표시 갱신)."""
        interval = self.settings.kos_poll_schedule_sec
        while True:
            await asyncio.sleep(check_sec)
            try:
                self.rollover()
                if time.monotonic() - self.hub.last_publish >= interval:
                    self.hub.publish()
            except Exception:  # 발행 실패로 루프가 죽지 않게
                logging.getLogger("procedure").exception("board 발행 오류")

    def kos_tokens(self) -> tuple[bool, bool]:
        with self.repo.tx() as tx:
            return tx.token("open") is not None, tx.token("internal") is not None


def build_container(settings: Settings, clock: Clock | None = None) -> Container:
    clock = clock or Clock()
    repo = Repository(Database(settings.db_path))
    actions = ActionService(repo, clock)
    accounts = AccountService(repo, settings, clock)
    accounts.sync()  # 서버 시작 — admin · nurse · coordinator(env) · 지금 원장 · 상담사 목록의 doctor · counselor
    notifications = NotificationService(repo, clock)
    c = Container(settings=settings, clock=clock, repo=repo, auth=AuthService(settings, clock, repo, accounts),
                  board=BoardService(repo, clock, settings.poll_window), actions=actions, accounts=accounts,
                  push=PushService(repo, settings, clock=clock, notifications=notifications),
                  devices=DeviceService(repo, clock), notifications=notifications)
    actions.on_change = c.changed
    c.display = DisplayService(repo, clock, settings, c.devices)
    c.display.online = c.hub.online
    c.display.send = lambda device_id, data: c.hub.send_to_device(device_id, "display", data)
    c.display.push = lambda request_id: c.push.schedule_display(request_id)
    c.resv = ReservationService(settings, repo, clock, lambda: c.kos)
    c.resv.displays_of = c.display.of_reservation  # 상세 응답 displays[](§5-3 「닫기」)
    c.reception = ReceptionService(c.resv)
    c.questionnaire = QuestionnaireService(repo, clock, settings, c.resv, c.display)  # 고객 문진 웹(SPEC-006)
    c.photos = PhotoService(repo, clock, settings, c.resv.client)
    c.scan = PassportScanService(repo, c.resv, c.devices, c.photos, c.display)
    if not settings.proc_photo_dir:
        logging.getLogger("procedure").warning("PROC_PHOTO_DIR 가 비어 신분증 사진 저장을 끈다(스캔 = 고객 수정만)")
    c.reception.on_counselor_call = lambda rid, sid: c.push.schedule_counselor(rid, sid)  # KOS 200 + 커밋 뒤(§5-2)
    actions.on_call = c.push.schedule  # 호출이 생긴 뒤(커밋 뒤) 원장 호출 푸시
    if settings.kos_enabled:
        from app.kos.runtime import KosRuntime

        c.kos = KosRuntime(settings, repo, clock, c.hub.publish)
        c.kos.on_staff = accounts.sync  # 직원 조회(서버 시작 · 1시간)마다 원장 · 상담사 한 명당 계정
    return c
