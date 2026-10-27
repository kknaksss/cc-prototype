"""여권 스캔 저장(SPEC-004 §6.16 ④ · D7-17 ~ D7-20 · D7-48 ~ D7-56).

순서: 기기 확인 → 5MB → ④-a 고객 수정(SPEC-005 §5.13 함수 그대로 — 저장 직전 다시 읽고 있는 키 전부 + 바뀐 칸) →
실패면 아무것도 저장 안 함(사진도) → ④-b ccc 사진 → ④-c KOS 사진(실패해도 앞은 남김) → ④-d 신분 확인 · 이벤트 · 띄우기 done.
법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 사진 바이트는 메모리에서 바로 저장소로(로그 · 임시 파일 없음).
"""

import json
from typing import Any

from pydantic import ValidationError

from app.domain.errors import BadRequest, DomainError, NotFound
from app.domain.models import Account
from app.repository.repo import Repository
from app.schemas.reservations import PersonalIn
from app.service.devices import DeviceService
from app.service.id_photo import MAX_BYTES, PhotoService
from app.service.reservations import ReservationService

SCAN_FIELDS = ("passportSurname", "passportGivenNames", "passportNumber", "nationality", "dateOfBirth", "gender",
               "passportExpiryDate")  # name(카드 이름) 칸 없음(D7-53)


class PhotoTooLarge(DomainError):
    status = 413


class PassportScanService:
    def __init__(self, repo: Repository, resv: ReservationService, devices: DeviceService, photos: PhotoService, display):
        self.repo = repo
        self.resv = resv
        self.devices = devices
        self.photos = photos
        self.display = display

    @staticmethod
    def parse_fields(raw: str | None) -> PersonalIn:
        try:
            fields = json.loads(raw or "{}")
        except ValueError:
            raise BadRequest("invalid_request", "fields: JSON 이어야 해요") from None
        if not isinstance(fields, dict):
            raise BadRequest("invalid_request", "fields: 객체여야 해요")
        bad = sorted(set(fields) - set(SCAN_FIELDS))
        if bad:
            raise BadRequest("invalid_request", f"fields: 바꿀 수 없는 칸 {', '.join(bad)}")
        try:
            return PersonalIn(**fields)
        except ValidationError:
            raise BadRequest("invalid_request", "fields: 값 형식이 맞지 않아요") from None

    async def save(self, actor: Account, customer_id: int, *, fields: PersonalIn, photo: bytes | None,
                   reservation_id: int | None, display_request_id: int | None, device_id: int | None,
                   manual: bool) -> dict[str, Any]:
        device = self.devices.check(actor, device_id)
        if photo and len(photo) > MAX_BYTES:
            raise PhotoTooLarge("photo_too_large", "사진이 5MB 를 넘어요")
        if not photo and not manual:  # 카메라 길(app_scan) = 사진 필수 · 손 입력(app_manual) = 사진 없어도 됨(리뷰 r1 FAIL-2)
            raise BadRequest("invalid_request", "photo: 사진 파일이 필요해요")
        with self.repo.tx() as tx:
            cust = tx.customer(customer_id)
        if cust is None:
            raise NotFound("없는 고객이에요")
        changed = sorted(fields.model_fields_set)
        if changed:  # ④-a — 실패(409 · 502)면 여기서 끝(사진 · 신분 확인 0)
            await self.resv.personal(actor, customer_id, fields)
        photo_id = self.photos.save(actor, customer_id, reservation_id, photo) if photo else None  # ④-b
        kos = "skipped"
        if photo and photo_id is not None:
            kos = await self.photos.upload(photo_id, cust.kos_id, photo)  # ④-c
        now = self.resv.clock.now()
        with self.repo.tx() as tx:  # ④-d
            ev = tx.add_event(now, actor.login_id, "passport_scan", None,
                              {"customerId": customer_id, "fields": changed, "photoId": photo_id,
                               "kos": {"personal": "ok", "photo": kos if photo else None}, "manual": manual})
            tx.add_identity_check(customer_id, "confirmed", now, actor.login_id, ev,
                                  method="app_manual" if manual else "app_scan",
                                  device=device.name if device else None, photo_id=photo_id)
            self.display.finish(tx, actor, display_request_id)
        result = {"ccc": "ok" if photo_id is not None else "disabled", "kos": kos} if photo else None  # 손 입력 사진 없음 = null
        return {"ok": True, "personal": "ok", "skipped": [], "photo": result, "photoId": photo_id}
