"""고객 문진 웹 공개 API(SPEC-006 §6.1) — 로그인 없음 · 토큰 = 헤더 `X-Questionnaire-Token`.

법적 검토 필요: 고객 공개 웹 문진 — 개인정보(이름 · 생년월일 · 성별 · 휴대폰 · 주소 · 건강 답) 수집 · 동의 · 보관 · 링크 노출

- `Authorization` 을 보지 않는다(deps.Actor 안 씀 — 직원 토큰이 실려도 직원 권한으로 바뀌지 않음)
- 토큰은 경로 · 쿼리에 싣지 않는다(접근 로그) · 로그에 토큰 · 헤더 값 0
- 응답 = 허용 키 모델(extra 금지) · `Cache-Control: no-store` · `Referrer-Policy: no-referrer`(main 미들웨어 — 오류 응답 포함)
"""

from fastapi import APIRouter, Header, Query, Request

from app.api.deps import Ctr
from app.api.docs import INVALID, T_PUBLIC, errors
from app.domain.errors import Forbidden
from app.schemas.actions import OkResponse, PublicQuestionnaireForm, PublicQuestionnaireSubmit

router = APIRouter(prefix="/api/public", tags=[T_PUBLIC])
PREFIX = "/api/public"


def client_ip(request: Request) -> str:
    """속도 제한 키 — 운영 = Cloudflare 엣지 → Tunnel(cloudflared) → ingress-nginx → 파드(infra CLAUDE.md ⑨).

    ingress-nginx 의 X-Forwarded-For 는 cloudflared 파드 주소가 되므로 **Cloudflare 가 넣는 `CF-Connecting-IP` 를 먼저** ·
    없으면(로컬 · LAN) X-Forwarded-For 첫 값 · 그다음 소켓 주소. 메모리 카운터에만 쓰고 DB · 로그에 남기지 않는다.
    """
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf
    xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if xff:
        return xff
    return request.client.host if request.client else "-"


TOKEN_DESC = ("고객 문진 웹 링크의 토큰 — 링크 `…/q#<토큰>` 의 `#` 뒤 값(43자). 경로 · 쿼리가 아니라 이 헤더로만 받는다. "
              "없으면 400 q_token_missing")

COMMON = """
**로그인 없음** — `Authorization` 을 보지 않는다(직원 토큰이 실려도 직원 권한이 되지 않는다). 「누구의 문진인가」는 헤더
`X-Questionnaire-Token` 의 토큰이 정한다(직원이 `POST /api/display-requests`(kind=questionnaire)로 만든 링크의 토큰).
예약 · 고객 · KOS id 는 응답에 없다.

- 응답(오류 포함)마다 `Cache-Control: no-store` · `Referrer-Policy: no-referrer`.
- **속도 제한**(서버 메모리 · 1분 창 · 넘으면 `429 too_many_requests`): IP 당 GET 30번 · POST 5번 · 같은 토큰 POST 3번.
  IP 당 틀린 · 지난 토큰(404 · 410)이 최근 60초 안에 10번 이상이면 그 IP 의 GET · POST 를 막는다(고정 1분이 아니라 미끄러지는
  창 — 최근 60초 안의 횟수가 10 밑으로 내려가는 순간 다시 열린다 · 막힌 요청은 횟수에 더하지 않는다).
  IP = `CF-Connecting-IP` → `X-Forwarded-For` 첫 값 → 소켓 주소 순(카운터에만 쓰고 저장하지 않음).
- 링크 상태: 없는 · 틀린 토큰 `404 q_not_found` · 여는 시한(만든 뒤 env `PROC_DISPLAY_TTL_MIN` · 기본 10분) 또는 쓰는 시한
  (처음 연 뒤 env `PROC_QWEB_FILL_MIN` · 기본 60분)이 지남 `410 q_expired` · 링크 요청이 `canceled` 로 닫힘 `410 q_canceled`
  (같은 예약에 새 문진 링크가 만들어졌거나 · 직원이 `POST /api/display-requests/{id}/close` 로 canceled 닫음) · 링크 요청이
  `done` 으로 닫힘 `409 q_submitted`(제출 성공 · 직원이 close 로 done 닫음 · 여권 스캔 저장의 `displayRequestId` 로 닫힘).
  이 오류 본문에는 `requestId` 를 싣지 않는다(`code` · `message` 만).
- 거절은 event_log `qweb_denied`(`reason` = not_found · expired · canceled · submitted · submitting · rate. not_found · rate 가
  아니면 `requestId` 도 남긴다 · 같은 IP 같은 이유는 1분에 1줄 · IP · 토큰은 남기지 않음).
"""

TOKEN_ERRORS = (
    (400, "q_token_missing", "`X-Questionnaire-Token` 헤더가 없거나 빈 값일 때"),
    (404, "q_not_found", "토큰에 맞는 문진 링크가 없거나 · 토큰이 틀리거나 · 링크의 고객이 없을 때"),
    (409, "q_submitted", "링크 요청이 done 으로 닫혔을 때(제출 성공 · 직원 close done · 여권 스캔 `displayRequestId`)"),
    (410, "q_expired", "여는 시한 또는 쓰는 시한(`fillUntil`)이 지났을 때"),
    (410, "q_canceled", "링크 요청이 canceled 로 닫혔을 때(같은 예약에 새 문진 링크 · 직원 close canceled)"),
    (429, "too_many_requests", "속도 제한을 넘었을 때(IP · 토큰 · 틀린 토큰 횟수)"),
)


@router.get(
    "/questionnaire", response_model=PublicQuestionnaireForm,
    summary="공개 문진 불러오기 — 양식 · 약관 · 미리 채움",
    description=COMMON + """
고객 폰에서 문진 화면을 그릴 것을 준다 — 고객 이름 · 언어 · KOS 양식 · KOS 약관 · 미리 채움 · 제출 시한.

- **KOS 읽기**: 공개 `getVisitorQuestionnaire`(양식) · `get-questionnaire-agreements`(약관) — 둘 중 하나라도 실패하면
  `502 kos_unavailable`. 내부 `get-visitor`(언어 근거 · 미리 채움) — 실패해도 열고 미리 채움은 비운다(이름만 ccc 사본).
- **언어**: KOS 고객 언어 → 국적 대응표 → `en` 순으로 고르고, 양식 번역 6개(`ko · ja · zh-Hans · zh-Hant · en · id`)에 없으면
  `en`. 쿼리 `lang` 이 그 6개 중 하나면 그 값으로 바꾼다(그 밖 값은 무시).
- **부작용**: 첫 성공(링크가 pending)이면 링크 상태 = opened(쓰는 시한 시작) · 매번 event_log `qweb_open`. KOS 쓰기 없음.
- 반복 = 같은 내용(첫 연 시각 · `fillUntil` 은 그대로).
""",
    responses=errors(
        *TOKEN_ERRORS,
        (502, "kos_unavailable", "KOS 양식 · 약관을 읽지 못했을 때(KOS 연동 없음 포함)"),
    ),
)
async def load(request: Request, c: Ctr,
               lang: str | None = Query(None, description=(
                   "선택 — 화면 언어 `ko` · `ja` · `zh-Hans` · `zh-Hant` · `en` · `id` 중 하나. "
                   "그 밖 값 · 생략 = 서버가 고른 언어")),
               token: str | None = Header(default=None, alias="X-Questionnaire-Token", description=TOKEN_DESC),
               ) -> PublicQuestionnaireForm:
    """첫 성공 = 요청 opened · 응답 = 그 고객 이름 · 언어 · 양식 · 약관 · 미리 채움 · fillUntil(예약 · 고객 id 없음)."""
    return PublicQuestionnaireForm.model_validate(await c.questionnaire.load_public(token, lang, client_ip(request)))


@router.post(
    "/questionnaire", response_model=OkResponse,
    summary="공개 문진 제출",
    description=COMMON + """
고객이 쓴 문진을 KOS 에 제출한다. 가짜 스냅샷 모드(env `PROC_FAKE_BOARD`)면 `403 fake_board`(로그인 없이도 같은 규칙).

- 본문 **최상위**에 정의 밖 키가 있으면 `400 invalid_request`. `answers[]` · `agreements[]` 항목 안의 정의 밖 키는 검사하지
  않고 그대로 KOS 로 넘긴다. `registrationNumber` · `phoneticName` 은 보내기만 해도(null 이라도)
  `400 questionnaire_field`.
- **KOS 쓰기**: 공개 `submit-visitor-questionnaire`(본문에서 `language` 를 뺀 나머지 + visitorId) — KOS 고객의 성별 · 생년월일 ·
  주소 · 휴대폰 · 동의를 바꾼다(휴대폰 맨 앞 0 은 KOS 가 뗀다). KOS 가 400 이면 `409 questionnaire_rejected` · 그 밖 실패
  (KOS 연동 없음 포함)는 `502 kos_unavailable`(둘 다 message 「제출하지 못했어요 · 직원에게 알려 주세요」 ·
  event_log `kos_rejected`).
- 성공 뒤: KOS 제출본을 다시 읽어 ccc 문진 이력에 저장(다시 읽은 것이 이번 제출이 아니면 보낸 답으로) · 링크 상태 done ·
  event_log `questionnaire_submit`. SSE · 푸시 없음.
- 같은 링크로 겹친 제출 = 뒤엣것 `409 q_submitting`. 끝난 뒤 다시 제출 = `409 q_submitted`(1회).
""",
    responses=errors(
        INVALID,
        (400, "questionnaire_field", "`registrationNumber` · `phoneticName` 키를 보냈을 때"),
        (403, "fake_board", "서버가 가짜 스냅샷 모드(env `PROC_FAKE_BOARD`)일 때 — 제출을 막는다"),
        *TOKEN_ERRORS,
        (409, "q_submitting", "같은 링크의 앞 제출이 아직 처리 중일 때"),
        (409, "questionnaire_rejected", "KOS 가 제출을 400 으로 거절했을 때"),
        (502, "kos_unavailable", "KOS 제출이 400 밖의 이유로 실패했을 때(네트워크 · 5xx · 그 밖 4xx · KOS 연동 없음)"),
    ),
)
async def submit(body: PublicQuestionnaireSubmit, request: Request, c: Ctr,
                 token: str | None = Header(default=None, alias="X-Questionnaire-Token", description=TOKEN_DESC),
                 ) -> OkResponse:
    if c.settings.proc_fake_board:  # 가짜 판 = 제출 막음(require_real_board 와 같은 뜻 · 로그인 없이)
        raise Forbidden("fake_board", "가짜 스냅샷(PROC_FAKE_BOARD) 중에는 조작할 수 없어요")
    await c.questionnaire.submit_public(token, body.model_dump(exclude_unset=True), body.model_fields_set,
                                        client_ip(request))
    return OkResponse()
