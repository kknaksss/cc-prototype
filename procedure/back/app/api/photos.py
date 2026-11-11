"""여권 스캔 · 신분증 사진(SPEC-004 §6.16 · §7.3) — 다섯 역할 모두.

법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 열람은 Bearer 헤더만(쿠키 · `?token=` 없음 · api/deps.py) · 공개 URL 없음.
multipart 는 Content-Length 로 5MB 를 먼저 거르고, 메모리에서만 읽는다(임시 파일에 흘리지 않게 spool 한도를 올림).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import Response
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartParser

from app.api.deps import Actor, Ctr, require_real_board
from app.api.docs import FAKE_BOARD, INVALID, KOS_REJECTED, KOS_UNAVAILABLE, T_PHOTO, UNAUTHORIZED, binary, errors
from app.domain.errors import BadRequest
from app.schemas.actions import KosRetryResponse, PassportScanResponse, PhotoDeleteResponse
from app.service.id_photo import MAX_BYTES
from app.service.passport_scan import PhotoTooLarge

router = APIRouter(prefix="/api", tags=[T_PHOTO])
FORM_OVERHEAD = 64 * 1024  # 사진 밖 칸 · 경계 문자열
MultiPartParser.spool_max_size = MAX_BYTES + FORM_OVERHEAD  # 받은 사진을 디스크 임시 파일로 흘리지 않는다(§6.16 원본)
# ↑ 프로세스 전역 — 채팅 사진(api/chat.py · SPEC-007 §9)도 이 값을 쓴다. 바꾸면 여권 스캔 · 채팅 사진이 같이 바뀐다
# ↑ 채팅 동영상(api/chat.py · SPEC-007 §9.2)은 이 값보다 커서 Starlette 임시 파일로 흐른다 — 동영상 때문에 올리지 않는다


def _int(v: object, name: str) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(str(v))
    except ValueError:
        raise BadRequest("invalid_request", f"{name}: 정수여야 해요") from None


CustomerId = Annotated[int, Path(description="ccc 고객 id(예약 상세의 고객 id)")]
PhotoId = Annotated[int, Path(description="ccc 신분증 사진 id(여권 스캔 응답 `photoId`)")]
PHOTO_404 = (404, "photo_not_found", "사진 행이 없을 때")

SCAN_FORM = {
    "type": "object",
    "required": [],
    "properties": {
        "fields": {"type": "string", "description": (
            "바꿀 고객 칸 — JSON 객체 문자열. 키는 `passportSurname` · `passportGivenNames` · `passportNumber` · `nationality` · "
            "`dateOfBirth`(`YYYY-MM-DD`) · `gender` · `passportExpiryDate`(`YYYY-MM-DD`)만(그 밖 키 = 400). 값 = 문자열 또는 "
            "null(빈 값으로 지움). 보낸 키만 바꾼다. 생략 · `{}` = 고객 수정 없음. 이 칸은 1MB 까지")},
        "photo": {"type": "string", "format": "binary", "description": (
            "여권 사진 JPEG(5MB 이하 · 파일 1개). `manual` 이 true 가 아니면 필수. "
            "서버는 바이트를 그대로 저장한다(형식 검사 없음)")},
        "reservationId": {"type": "integer", "description": (
            "선택 — 이 스캔의 ccc 예약 id. 있는 예약인지 검사하지 않고 사진 행에 그대로 남긴다(없는 id 도 저장됨). "
            "ccc 사진을 저장했고(`PROC_PHOTO_DIR` 켜짐) 그 예약이 있고 KOS 일정 id 가 있을 때만 KOS 이미지를 그 예약 일정"
            "(`scheduleId`)에 붙인다 — 아니면 일정 없이 올린다")},
        "displayRequestId": {"type": "integer", "description": (
            "선택 — 이 스캔을 띄운 띄우기 요청 id. 저장이 성공하면 그 요청을 done 으로 닫는다 — 요청 종류(scan · "
            "questionnaire) · 예약이 이 스캔과 맞는지 검사하지 않는다. 없는 id · 이미 닫힌 요청이면 그대로 둔다(오류 없음). "
            "생략하면 어떤 요청도 닫지 않는다")},
        "deviceId": {"type": "integer", "description": (
            "선택 — 스캔한 자기 계정 기기 id(아니면 404 device_not_found). 신분 확인 기록에 기기 이름을 남긴다")},
        "manual": {"type": "string", "description": (
            "선택 — `true` · `1`(대소문자 무시)이면 손 입력: 사진 없이도 된다 · 신분 확인 방법 = app_manual. "
            "그 밖 · 생략 = 카메라 스캔(app_scan · 사진 필수)")},
    },
}


@router.post(
    "/customers/{customer_id}/passport-scan", response_model=PassportScanResponse,
    dependencies=[Depends(require_real_board)],
    summary="여권 스캔 저장 — 고객 칸 수정 + 사진 저장 · KOS 올리기",
    description="""
앱에서 여권을 스캔(또는 손 입력)한 결과를 저장한다. 본문 = `multipart/form-data`(칸은 아래 요청 본문). 다섯 역할 모두.

**순서**
1. 검사(이 순서로 · 앞에서 걸리면 뒤는 안 봄): `Content-Length` 가 5MB + 64KB 초과 → `413`(본문을 읽기 전) → multipart 읽기
   실패 → `400 http_error` → `photo` 가 파일이 아님 → `400 invalid_request` → `fields` 형식 → `400 invalid_request` →
   정수 칸(`reservationId` · `displayRequestId` · `deviceId`) → `400 invalid_request` → 기기(`deviceId`) → `404 device_not_found`
   → 사진 5MB 초과 → `413` → 사진 없음(손 입력 아님) → `400 invalid_request` → 고객 없음 → `404 not_found` → 날짜 칸
   형식(고객 수정 단계 · KOS 부르기 전) → `400 invalid_request`.
2. **고객 수정**(`fields` 에 키가 있을 때) — KOS 고객을 다시 읽고(`get-visitor`) 개인 정보 묶음 전체 + 바뀐 칸으로
   **KOS `update-visitor-personal-information`**(다시 읽은 값과 같으면 KOS 를 부르지 않음). 실패(409 · 502)면 여기서 끝 —
   사진 · 신분 확인 아무것도 저장 안 함.
3. **ccc 사진** — env `PROC_PHOTO_DIR` 에 무작위 이름으로 저장 + 사진 행(폴더가 비면 저장 안 함 · `photo.ccc`=disabled).
4. **KOS 사진** — 공개 `generate-uploading-url` → 업로드 → 공개 `register-visitor-images`(장비 코드 「태블릿」 필요).
   실패해도 앞 단계는 남는다(`photo.kos`=failed → `kos-retry`).
5. 신분 확인 = 확인 완료(방법 app_scan | app_manual) · event_log `passport_scan` · `displayRequestId` 를 보냈을 때만 그 요청
   done(종류 · 예약 검사 없음 · 없거나 이미 닫혔으면 그대로). 보내지 않으면 띄우기 요청은 열린 채로 남는다.

- KOS 쓰기는 동기(응답 전에 끝남). SSE · 푸시 없음.
- 반복 호출 = 매번 새 사진 행 · 새 신분 확인 행(멱등 아님).
- 법적 검토 대상(신분증 이미지) — 사진은 메모리에서 바로 저장소로(임시 파일 없음).
""",
    openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": SCAN_FORM}}}},
    responses=errors(
        (400, "invalid_request", "`fields` 가 JSON 객체가 아니거나 · 바꿀 수 없는 키가 있거나 · 값 형식이 틀리거나 · "
                                 "(날짜 `YYYY-MM-DD`) · "
                                 "`photo` 가 파일이 아니거나 · 사진 없이 `manual` 이 아니거나 · 정수 칸이 정수가 아닐 때"),
        INVALID,
        (400, "http_error", "multipart 를 읽지 못할 때(파일 2개 이상 · 칸 10개 초과 · 사진 밖 칸이 1MB 초과 등)"),
        UNAUTHORIZED, FAKE_BOARD,
        (404, "device_not_found", "`deviceId` 가 없거나 다른 계정의 기기일 때"),
        (404, "not_found", "고객이 없을 때"),
        (413, "photo_too_large", "사진(또는 본문)이 5MB 를 넘을 때"),
        KOS_REJECTED, KOS_UNAVAILABLE,
    ),
)
async def passport_scan(customer_id: CustomerId, request: Request, c: Ctr, actor: Actor) -> PassportScanResponse:
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


@router.get(
    "/id-photos/{photo_id}",
    summary="신분증 사진 열람 — JPEG",
    description="""
ccc 에 저장한 여권 사진 원본(JPEG 바이트)을 준다. 다섯 역할 모두. **`Authorization: Bearer` 헤더로만** 열린다
(쿠키 · `?token=` 없음 · 공개 URL 없음).

- 응답 헤더 `Cache-Control: no-store` · `Content-Disposition: inline`.
- 열 때마다 event_log `id_photo_view`(누가 · 어느 사진). 가짜 스냅샷 모드에서도 열린다.
""",
    responses={**binary("image/jpeg", "여권 사진 원본 JPEG 바이트"), **errors(
        INVALID, UNAUTHORIZED,
        (404, "photo_not_found", "사진 행이 없거나 저장소에 파일이 없을 때"),
        (409, "photo_disabled", "env `PROC_PHOTO_DIR` 가 비어 사진 저장이 꺼져 있을 때"),
    )},
)
def id_photo(photo_id: PhotoId, c: Ctr, actor: Actor) -> Response:
    """열람 — Bearer 헤더 로그인만 · 캐시 안 함 · 열 때마다 event_log(id_photo_view)."""
    return Response(c.photos.read(actor, photo_id), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})


@router.post(
    "/id-photos/{photo_id}/kos-retry", response_model=KosRetryResponse, dependencies=[Depends(require_real_board)],
    summary="사진 KOS 다시 올리기",
    description="""
ccc 에 저장된 사진 파일로 KOS 고객 이미지 올리기만 다시 한다(공개 `generate-uploading-url` → 업로드 →
`register-visitor-images`). 다섯 역할 모두.

- 이미 KOS 올리기가 ok 인 사진 = 아무것도 안 하고 `ok`(멱등).
- 올리기 실패는 오류가 아니라 응답 `kos`=failed(사진 행에 실패 기록). 시도할 때마다 event_log `id_photo_kos_retry`.
- SSE · 푸시 없음.
""",
    responses=errors(
        INVALID, UNAUTHORIZED, FAKE_BOARD,
        (404, "photo_not_found", "사진 행이 없거나 저장소에 파일이 없을 때"),
        (404, "not_found", "사진의 고객이 없을 때"),
        (409, "photo_disabled", "env `PROC_PHOTO_DIR` 가 비어 사진 저장이 꺼져 있을 때"),
    ),
)
async def kos_retry(photo_id: PhotoId, c: Ctr, actor: Actor) -> KosRetryResponse:
    return KosRetryResponse(kos=await c.photos.retry(actor, photo_id))  # type: ignore[arg-type]


@router.delete(
    "/id-photos/{photo_id}", response_model=PhotoDeleteResponse, dependencies=[Depends(require_real_board)],
    summary="신분증 사진 삭제 — KOS 이미지 · ccc 파일",
    description="""
사진을 지운다. 다섯 역할 모두.

1. **KOS** — 사진 행의 KOS 상태가 `skipped` 가 아니면(`ok` 뿐 아니라 올리기 실패 `failed` 도) 내부 `get-visitor-images` 에서
   같은 파일 이름의 이미지를 찾아 내부 `delete-visitor-images`. 못 찾으면 `not_found` 로 두고 계속. **KOS 오류면 409 · 502 이고
   ccc 는 그대로**(event_log `kos_rejected` — `failed` 사진도 KOS 를 부르므로 이 오류가 날 수 있다). 사진의 고객 행이 ccc 에
   없으면 KOS 단계를 조용히 건너뛴다(`kos`=skipped).
2. **ccc** — 파일 · 사진 행 삭제. 그 고객의 마지막 신분 확인이 이 사진으로 한 「확인 완료」면 「미확인」 1행을 더한다.
   고객 값(여권 번호 등)은 그대로. event_log `id_photo_delete`.

- 반복: 두 번째는 사진 행이 없어 `404 photo_not_found`. SSE · 푸시 없음.
""",
    responses=errors(INVALID, UNAUTHORIZED, FAKE_BOARD, PHOTO_404, KOS_REJECTED, KOS_UNAVAILABLE),
)
async def delete_photo(photo_id: PhotoId, c: Ctr, actor: Actor) -> PhotoDeleteResponse:
    """[삭제](E2E batch 3 #1) — KOS 이미지 먼저 지우고(실패면 409 · 502 · ccc 그대로) ccc 파일 · 행 · 신분 확인(→ 미확인)."""
    return PhotoDeleteResponse(kos=await c.photos.delete(actor, photo_id))  # type: ignore[arg-type]
