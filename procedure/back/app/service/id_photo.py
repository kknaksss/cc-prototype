"""신분증(여권) 사진 — ccc 저장소(`PROC_PHOTO_DIR`) · KOS 이미지 올리기 · 열람(SPEC-004 §6.16 ④-b · ④-c · §7.3 · §7.4).

법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 이 파일 전체(저장 · KOS 올리기 · 열람 · 보관 기간).
여권만(D7-51) · 가리지 않음(D7-19).
"""

import hashlib
import logging
import secrets
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.clock import Clock, kos_utc
from app.domain.errors import Conflict, NotFound
from app.domain.models import Account
from app.repository.repo import Repository
from app.service import kos_errors

log = logging.getLogger("procedure.photo")

# 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 종류 = 여권 고정(주민번호 있는 신분증이면 마스킹 자리 · D7-51)
DOC_TYPE = "passport"
EQUIPMENT_CATEGORY = "IMAGE_EQUIPMENT"
EQUIPMENT_NAME = "태블릿"  # 코드 id 는 지점마다 다르다 — 이름으로 업로드 때마다 찾는다(레포 · env 에 id 없음 · Q-155)
MEMO = "ccc 여권 스캔"
PATH_CODES = "meta/codes/v1/queries/get-codes"
PATH_UPLOAD_URL = "image/open/v1/commands/generate-uploading-url"
PATH_REGISTER = "image/open/v1/commands/register-visitor-images"
MAX_BYTES = 5 * 1024 * 1024


class PhotoService:
    def __init__(self, repo: Repository, clock: Clock, settings: Settings, client):
        self.repo = repo
        self.clock = clock
        self.s = settings
        self._client = client  # () → KosClient(없으면 502)

    @property
    def folder(self) -> Path | None:
        return Path(self.s.proc_photo_dir) if self.s.proc_photo_dir else None

    def save(self, actor: Account, customer_id: int, reservation_id: int | None, data: bytes) -> int | None:
        """④-b — 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 볼륨 암호화 없음(D7-68 · OQ-626).

        `PROC_PHOTO_DIR/<무작위>.jpg` 에 바로 쓴다(임시 파일 없음 · 이름에 고객 정보 없음) + id_photo 1행. 폴더가 비면 None.
        """
        folder = self.folder
        if folder is None:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{secrets.token_hex(16)}.jpg"
        (folder / name).write_bytes(data)
        with self.repo.tx() as tx:
            return tx.add_id_photo(customer_id=customer_id, reservation_id=reservation_id, doc_type=DOC_TYPE,
                                   file_name=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                   kos_status="skipped", created_by=actor.login_id, created_at=self.clock.now())

    async def upload(self, photo_id: int, visitor_kos_id: str, data: bytes) -> str:
        """④-c — 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — KOS 고객 이미지로 올린다(KOS 보관 기간은 KOS 규칙).

        공개 generate-uploading-url → presigned PUT → 공개 register-visitor-images.
        `scheduleId` = 그 스캔의 예약 일정(KOS 일정 상세 「사진 · 펜차트」 탭이 `get-visitor-images{visitorId, scheduleId}` 로
        읽는다 — KOS 자체 여권 스캔도 싣는다 · E2E batch 2 #5) · 예약이 없으면 뺀다. category · path 는 안 보냄(지점 분류 없음).
        장비 = 내부 get-codes 의 「태블릿」 코드 객체 그대로 · 못 찾으면 올리지 않고 failed(equipment_code_missing).
        결과 ok | failed 를 id_photo 에 적고 돌려준다. 실패해도 고객 수정 · ccc 사진은 남는다.
        """
        with self.repo.tx() as tx:
            row = tx.id_photo(photo_id)
            resv = tx.reservation(row["reservation_id"]) if row and row["reservation_id"] else None
        assert row is not None
        schedule = {"scheduleId": resv.kos_id} if resv is not None and resv.kos_id else {}
        status, error = "failed", None
        try:
            client = self._client()
            codes = await client.internal(PATH_CODES, {"category": EQUIPMENT_CATEGORY})
            equipment = next((x for x in codes.get("data") or [] if isinstance(x, dict)
                              and x.get("category") == EQUIPMENT_CATEGORY and x.get("name") == EQUIPMENT_NAME), None)
            if equipment is None:
                error = "equipment_code_missing"
                log.warning("KOS 이미지 올리기 건너뜀 — 장비 코드 「%s」 없음", EQUIPMENT_NAME)
            else:
                url = (await client.open(PATH_UPLOAD_URL, {"fileName": row["file_name"]})).get("data")
                if not isinstance(url, str) or not url:
                    raise ValueError("generate-uploading-url: url 없음")
                await client.put_presigned(url, data, "image/jpeg")
                await client.open(PATH_REGISTER, {"images": [{
                    "fileName": row["file_name"], "visitorId": visitor_kos_id, "source": "HOSPITAL", **schedule,
                    "shootingDateTimeUtc": kos_utc(self.clock.now()), "equipment": equipment, "memo": MEMO}]})
                status = "ok"
        except Exception as e:  # 상태 · 이름만(URL · 본문 없음)
            error = kos_errors.describe(e)[:80]
            log.warning("KOS 이미지 올리기 실패: %s", error)
        with self.repo.tx() as tx:
            tx.update_id_photo(photo_id, kos_status=status, kos_error=error if status != "ok" else None)
        return status

    def read(self, actor: Account, photo_id: int) -> bytes:
        """§7.3 열람 — 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 보관 기간: 지우지 않음(PoC · D7-55).

        Bearer 헤더 로그인만(쿠키 · 쿼리 토큰 없음 — api/deps.py) · 열 때마다 event_log(id_photo_view).
        """
        row = self._row(photo_id)
        folder = self.folder
        if folder is None:
            raise Conflict("photo_disabled", "사진 저장이 꺼져 있어요")
        path = folder / row["file_name"]
        if not path.is_file():
            raise NotFound("사진 파일이 없어요", "photo_not_found")
        with self.repo.tx() as tx:
            tx.add_event(self.clock.now(), actor.login_id, "id_photo_view", None,
                         {"photoId": photo_id, "customerId": row["customer_id"]})
        return path.read_bytes()

    async def retry(self, actor: Account, photo_id: int) -> str:
        """[사진 다시 올리기] — ccc 파일로 KOS 올리기만 다시(D7-56). 이미 ok 면 그대로."""
        row = self._row(photo_id)
        if row["kos_status"] == "ok":
            return "ok"
        data = self.read_file(row)
        with self.repo.tx() as tx:
            cust = tx.customer(row["customer_id"])
        if cust is None:
            raise NotFound("없는 고객이에요")
        status = await self.upload(photo_id, cust.kos_id, data)
        with self.repo.tx() as tx:
            tx.add_event(self.clock.now(), actor.login_id, "id_photo_kos_retry", None, {"photoId": photo_id, "kos": status})
        return status

    def read_file(self, row: dict[str, Any]) -> bytes:
        folder = self.folder
        if folder is None:
            raise Conflict("photo_disabled", "사진 저장이 꺼져 있어요")
        path = folder / row["file_name"]
        if not path.is_file():
            raise NotFound("사진 파일이 없어요", "photo_not_found")
        return path.read_bytes()

    def _row(self, photo_id: int) -> dict[str, Any]:
        with self.repo.tx() as tx:
            row = tx.id_photo(photo_id)
        if row is None:
            raise NotFound("없는 사진이에요", "photo_not_found")
        return row
