"""고객 문진 웹 공개 API(SPEC-006 §6.1) — 로그인 없음 · 토큰 = 헤더 `X-Questionnaire-Token`.

법적 검토 필요: 고객 공개 웹 문진 — 개인정보(이름 · 생년월일 · 성별 · 휴대폰 · 주소 · 건강 답) 수집 · 동의 · 보관 · 링크 노출

- `Authorization` 을 보지 않는다(deps.Actor 안 씀 — 직원 토큰이 실려도 직원 권한으로 바뀌지 않음)
- 토큰은 경로 · 쿼리에 싣지 않는다(접근 로그) · 로그에 토큰 · 헤더 값 0
- 응답 = 허용 키 모델(extra 금지) · `Cache-Control: no-store` · `Referrer-Policy: no-referrer`(main 미들웨어 — 오류 응답 포함)
"""

from fastapi import APIRouter, Header, Request

from app.api.deps import Ctr
from app.domain.errors import Forbidden
from app.schemas.actions import OkResponse, PublicQuestionnaireForm, PublicQuestionnaireSubmit

router = APIRouter(prefix="/api/public", tags=["public"])
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


@router.get("/questionnaire", response_model=PublicQuestionnaireForm)
async def load(request: Request, c: Ctr, lang: str | None = None,
               token: str | None = Header(default=None, alias="X-Questionnaire-Token")) -> PublicQuestionnaireForm:
    """첫 성공 = 요청 opened · 응답 = 그 고객 이름 · 언어 · 양식 · 약관 · 미리 채움 · fillUntil(예약 · 고객 id 없음)."""
    return PublicQuestionnaireForm.model_validate(await c.questionnaire.load_public(token, lang, client_ip(request)))


@router.post("/questionnaire", response_model=OkResponse)
async def submit(body: PublicQuestionnaireSubmit, request: Request, c: Ctr,
                 token: str | None = Header(default=None, alias="X-Questionnaire-Token")) -> OkResponse:
    if c.settings.proc_fake_board:  # 가짜 판 = 제출 막음(require_real_board 와 같은 뜻 · 로그인 없이)
        raise Forbidden("fake_board", "가짜 스냅샷(PROC_FAKE_BOARD) 중에는 조작할 수 없어요")
    await c.questionnaire.submit_public(token, body.model_dump(exclude_unset=True), body.model_fields_set,
                                        client_ip(request))
    return OkResponse()
