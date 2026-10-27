"""여권 스캔 · 신분증 사진(SPEC-004 §6.16 · §7.3) — 다섯 역할 모두.

법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 열람은 Bearer 헤더만(쿠키 · `?token=` 없음 · api/deps.py) · 공개 URL 없음.
multipart 는 Content-Length 로 5MB 를 먼저 거르고, 메모리에서만 읽는다(임시 파일에 흘리지 않게 spool 한도를 올림).
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartParser

from app.api.deps import Actor, Ctr, require_real_board
from app.domain.errors import BadRequest
from app.schemas.actions import KosRetryResponse, PassportScanResponse
from app.service.id_photo import MAX_BYTES
from app.service.passport_scan import PhotoTooLarge

router = APIRouter(prefix="/api", tags=["photos"])
FORM_OVERHEAD = 64 * 1024  # 사진 밖 칸 · 경계 문자열
MultiPartParser.spool_max_size = MAX_BYTES + FORM_OVERHEAD  # 받은 사진을 디스크 임시 파일로 흘리지 않는다(§6.16 원본)


def _int(v: object, name: str) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(str(v))
    except ValueError:
        raise BadRequest("invalid_request", f"{name}: 정수여야 해요") from None


@router.post("/customers/{customer_id}/passport-scan", response_model=PassportScanResponse,
             dependencies=[Depends(require_real_board)])
async def passport_scan(customer_id: int, request: Request, c: Ctr, actor: Actor) -> PassportScanResponse:
    """multipart — fields(json) · photo(JPEG ≤ 5MB · manual=true 면 없어도 됨) · reservationId · displayRequestId? ·
    deviceId · manual."""
    size = request.headers.get("content-length")
    if size and size.isdigit() and int(size) > MAX_BYTES + FORM_OVERHEAD:
        raise PhotoTooLarge("photo_too_large", "사진이 5MB 를 넘어요")
    form = await request.form(max_files=1, max_fields=10)
    photo = form.get("photo")
    if photo is not None and not isinstance(photo, UploadFile):
        raise BadRequest("invalid_request", "photo: 사진 파일이어야 해요")
    data = await photo.read(MAX_BYTES + 1) if photo is not None else None  # 손 입력은 사진 없이도(service 가 판단)
    await form.close()
    out = await c.scan.save(actor, customer_id, fields=c.scan.parse_fields(form.get("fields")),  # type: ignore[arg-type]
                            photo=data, reservation_id=_int(form.get("reservationId"), "reservationId"),
                            display_request_id=_int(form.get("displayRequestId"), "displayRequestId"),
                            device_id=_int(form.get("deviceId"), "deviceId"),
                            manual=str(form.get("manual") or "").lower() in ("1", "true"))
    return PassportScanResponse.model_validate(out)


@router.get("/id-photos/{photo_id}")
def id_photo(photo_id: int, c: Ctr, actor: Actor) -> Response:
    """열람 — Bearer 헤더 로그인만 · 캐시 안 함 · 열 때마다 event_log(id_photo_view)."""
    return Response(c.photos.read(actor, photo_id), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})


@router.post("/id-photos/{photo_id}/kos-retry", response_model=KosRetryResponse, dependencies=[Depends(require_real_board)])
async def kos_retry(photo_id: int, c: Ctr, actor: Actor) -> KosRetryResponse:
    return KosRetryResponse(kos=await c.photos.retry(actor, photo_id))  # type: ignore[arg-type]
