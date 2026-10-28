"""고객 문진 웹(SPEC-006 · DEC-008) — 고객 자기 폰 · 로그인 대신 띄우기 요청 토큰.

KOS 공개 양식 · 약관 · 제출 · 제출 확인 + 내부 get-visitor.

- 「누가」 = 토큰의 띄우기 요청 행(`public_target`) — 예약 · 고객 id 를 입력으로 받지 않는다(§7.1)
- 언어는 back 이 정한다(domain/languages.py) · 고객은 받은 번역 안에서 바꾼다(D7-46)
- 제출: 주민번호 · 발음 칸 = 400 · visitorId 를 붙여 공개 submit · 제출본을 다시 읽어 questionnaire_history(source = web_submit ·
  같은 제출본 read 행이면 그 행을 고침) · 요청 done · KOS 400 = 409 questionnaire_rejected · 그 밖 502 · event_log(kos_rejected)
- 제출은 KOS 고객의 성별 · 생년월일 · 주소 · 휴대폰 · 동의를 바꾼다(AK§5.3). 휴대폰은 KOS 가 맨 앞 0 을 뗀다 — 고치지 않는다
- 나중에 KOS 없이(§9): 원천을 바꿀 자리 = `read_form` · `read_prefill` · `submit_answers` 세 함수(지금은 KOS 하나)
- 속도 제한 · 겹친 제출 잠금 = back 메모리(한 파드 · OQ-804). 토큰 · IP 는 로그 · event_log 에 남기지 않는다
"""

import asyncio
import hmac
import logging
import time
from datetime import timedelta
from typing import Any

from app.config import Settings
from app.domain import languages
from app.domain.clock import Clock, iso, kos_utc, parse
from app.domain.errors import BadGateway, BadRequest, Conflict, DomainError, Gone, NotFound, TooManyRequests
from app.domain.models import Customer, DisplayRequest
from app.kos.client import KosError
from app.repository.repo import Repository
from app.service import kos_errors
from app.service.display import qweb_token, token_hash
from app.service.reservations import PATH_Q_FORM, PATH_Q_SUBMIT, PATH_VISITOR, ReservationService

log = logging.getLogger("procedure.questionnaire")

PATH_AGREEMENTS = "visitor/open/v1/queries/get-questionnaire-agreements"
PATH_SUBMIT = "visitor/open/v1/commands/submit-visitor-questionnaire"
FORBIDDEN_FIELDS = ("registrationNumber", "phoneticName")  # 주민번호 칸 없음(D7-16 Q-152) · 발음은 KOS 고객 값을 바꾼다
FAILED = "제출하지 못했어요 · 직원에게 알려 주세요"
ACTOR = "customer"  # event_log actor(SPEC-006 §7.4)
FRESH_SEC = 60  # 제출 확인이 이번 제출인지 — 제출 시작보다 이만큼 앞이면 옛 제출본(KOS 는 첫 제출본을 준다 · Q-27)
WINDOW_SEC = 60.0
# (이름, 한도) — SPEC-006 §7.3 · 1분 창
LIMIT_GET_IP, LIMIT_POST_IP, LIMIT_BAD_IP, LIMIT_POST_TOKEN = 30, 5, 10, 3


def _obj(resp: dict[str, Any]) -> dict[str, Any]:
    """공개 응답 — `data` 로 감쌌으면 벗긴다(양식은 안 감쌈 · AK§4)."""
    data = resp.get("data")
    return data if isinstance(data, dict) else resp


def _list(resp: dict[str, Any], key: str) -> list[dict[str, Any]]:
    for v in (resp.get("data"), resp.get(key)):
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def _ymd(v: Any) -> str | None:
    """KOS 생년월일(`yyyy-MM-dd 00:00:00.000Z` 등) → 제출 꼴 `yyyyMMdd`."""
    if not isinstance(v, str) or len(v) < 10:
        return None
    return v[:10].replace("-", "")


def submitted_answers(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """보낸 답 → KOS 제출본 answers 꼴({seq, questionId, questionTitle, answerId, answerTitle, memo} · AK§5.2)."""
    return [{"seq": "", "questionId": a.get("parentQuestionId"), "questionTitle": a.get("parentQuestionTitle"),
             "answerId": a.get("id"), "answerTitle": a.get("title"), "memo": a.get("inputText") or a.get("subText")}
            for a in answers if isinstance(a, dict)]


class RateLimiter:
    """메모리 1분 창 카운터(SPEC-006 §7.3) — 키 = (이름, IP 또는 토큰 해시). DB · 로그에 남기지 않는다."""

    def __init__(self) -> None:
        self.now_mono = time.monotonic  # 시험이 바꾼다
        self._hits: dict[tuple[str, str], list[float]] = {}

    def _recent(self, key: tuple[str, str]) -> list[float]:
        now = self.now_mono()
        hits = [t for t in self._hits.get(key, []) if now - t < WINDOW_SEC]
        self._hits[key] = hits
        return hits

    def full(self, key: tuple[str, str], limit: int) -> bool:
        return len(self._recent(key)) >= limit

    def add(self, key: tuple[str, str]) -> None:
        self._recent(key).append(self.now_mono())

    def take(self, key: tuple[str, str], limit: int) -> bool:
        """한 번 쓰기 — 한도에 닿아 있으면 False(세지 않음)."""
        if self.full(key, limit):
            return False
        self.add(key)
        return True


class QuestionnaireService:
    def __init__(self, repo: Repository, clock: Clock, settings: Settings, resv: ReservationService, display):
        self.repo = repo
        self.clock = clock
        self.s = settings
        self.resv = resv
        self.display = display  # DisplayService — 상태 · 만료 규칙
        self.rate = RateLimiter()
        self._locks: dict[int, asyncio.Lock] = {}
        self._denied: dict[tuple[str, str], float] = {}  # (IP, 이유) → 마지막 qweb_denied(1분에 1행)

    # ------------------------------------------------------------------ 「누가」 = 토큰(§6.1)
    def public_target(self, token: str | None) -> DisplayRequest:
        """토큰 → 문진 종류 띄우기 요청. 없음 400 · 못 찾음 404 · 지남 · 닫힘 410 · 제출됨 409."""
        if not token:
            raise BadRequest("q_token_missing", "링크가 올바르지 않아요")
        self.display.expire()  # 만료를 먼저 커밋(§6.1)
        with self.repo.tx() as tx:
            d = tx.display_by_hash(token_hash(token))
        if d is None or d.kind != "questionnaire" or not d.qr_nonce or not hmac.compare_digest(
                qweb_token(self.s.proc_session_secret, d.id, d.qr_nonce), token):
            raise NotFound("링크가 올바르지 않아요", "q_not_found")
        if d.status == "expired":
            raise Gone("q_expired", "QR 유효 시간이 지났어요", requestId=d.id)
        if d.status == "canceled":
            raise Gone("q_canceled", "새 QR 이 만들어졌어요", requestId=d.id)
        if d.status == "done":
            raise Conflict("q_submitted", "이미 제출했어요", requestId=d.id)
        return d

    def _customer(self, d: DisplayRequest) -> Customer:
        with self.repo.tx() as tx:
            cust = tx.customer(d.customer_id) if d.customer_id else None
        if cust is None:
            raise NotFound("링크가 올바르지 않아요", "q_not_found")
        return cust

    # ------------------------------------------------------------------ 원천 세 함수(§9 — 지금 KOS)
    async def read_form(self, cust: Customer) -> tuple[list[dict], list[dict]]:
        """(양식 pages, 약관) — KOS 공개 getVisitorQuestionnaire · getQuestionnaireAgreements."""
        client = self.resv.client()
        form_r, agree_r = await asyncio.gather(client.open(PATH_Q_FORM, {"visitorId": cust.kos_id}),
                                               client.open(PATH_AGREEMENTS, {}), return_exceptions=True)
        for x in (form_r, agree_r):  # 양식 · 약관이 없으면 화면을 못 그린다
            if isinstance(x, BaseException):
                raise BadGateway("kos_unavailable", kos_errors.describe(x))
        form = _obj(form_r)  # type: ignore[arg-type]
        agreements = _list(agree_r, "agreements") or [a for a in form.get("agreements") or [] if isinstance(a, dict)]  # type: ignore[arg-type]
        return [p for p in form.get("pages") or [] if isinstance(p, dict)], agreements

    async def read_prefill(self, cust: Customer) -> tuple[dict[str, Any], dict[str, Any]]:
        """(언어 근거 값, 미리 채움) — KOS 내부 get-visitor. 실패면 빈 미리 채움(이름만 ccc 사본)."""
        # 법적 검토 필요: 고객 공개 웹 문진 — 링크를 가진 사람이 미리 채운 개인정보를 본다(OQ-807 · PoC = 보임)
        try:
            visitor = _obj(await self.resv.client().internal(PATH_VISITOR, {"id": cust.kos_id}))
        except Exception as e:  # noqa: BLE001 — 언어 · 미리 채움 없이도 문진은 연다
            log.warning("KOS 고객 읽기 실패: %s", kos_errors.describe(e))
            visitor = {}
        phone = visitor.get("phoneNumber") if isinstance(visitor.get("phoneNumber"), dict) else {}
        addr = visitor.get("address") if isinstance(visitor.get("address"), dict) else {}
        prefill = {"name": visitor.get("name") or cust.name,
                   "phone": {"countryCode": phone.get("countryCode") or "", "phoneNumber": phone.get("phoneNumber") or ""},
                   "address": addr.get("address") or "", "addressDetail": addr.get("detailedAddress") or "",
                   "dateOfBirth": _ymd(visitor.get("dateOfBirth")), "gender": visitor.get("gender")}
        return {"language": visitor.get("language"), "nationality": visitor.get("nationality") or cust.nationality}, prefill

    async def submit_answers(self, cust: Customer, payload: dict[str, Any]) -> tuple[str | None, list]:
        """KOS 공개 submit → 제출본 다시 읽기 — (제출 시각, 답). 제출 실패는 KosError 그대로 올린다."""
        client = self.resv.client()
        await client.open(PATH_SUBMIT, {**payload, "visitorId": cust.kos_id})
        try:  # 제출 확인 — 실패해도 제출은 됐다(이력만 못 씀)
            sub = _obj(await client.open(PATH_Q_SUBMIT, {"visitorId": cust.kos_id}))
            return sub.get("createdDateTimeUtc"), sub.get("answers") or []
        except Exception as err:  # noqa: BLE001
            log.warning("KOS 제출 확인 실패: %s", kos_errors.describe(err))
            return None, []

    # ------------------------------------------------------------------ ① 불러오기
    async def load_for(self, d: DisplayRequest, lang: str | None) -> dict[str, Any]:
        cust = self._customer(d)
        (pages, agreements), (basis, prefill) = await asyncio.gather(self.read_form(cust), self.read_prefill(cust))
        code, source = languages.resolve(basis.get("language"), basis.get("nationality"))
        if lang in languages.FORM_LANGS:
            code = lang
        now = self.clock.now()
        first = d.status == "pending"
        with self.repo.tx() as tx:
            if first:  # 첫 성공 = 고객이 엶(§3.2)
                tx.update_display(d.id, status="opened", opened_at=now)
                d.opened_at = now
            tx.add_event(now, ACTOR, "qweb_open", None,
                         {"requestId": d.id, "reservationId": d.reservation_id, "language": code, "first": first})
        fill_until = (d.opened_at or now) + timedelta(minutes=self.s.proc_qweb_fill_min)
        return {"customerName": cust.name,
                "language": {"code": code, "source": source, "options": list(languages.FORM_LANGS)},
                "form": {"pages": pages}, "agreements": agreements, "prefill": prefill, "fillUntil": iso(fill_until)}

    # ------------------------------------------------------------------ ⑥ 제출
    async def submit_for(self, d: DisplayRequest, body: dict[str, Any], sent: set[str]) -> None:
        bad = [k for k in FORBIDDEN_FIELDS if k in sent]
        if bad:
            raise BadRequest("questionnaire_field", f"{', '.join(bad)}: 보낼 수 없는 칸이에요")
        cust = self._customer(d)
        payload = {k: v for k, v in body.items() if k not in ("language", *FORBIDDEN_FIELDS)}
        started = self.clock.now()
        try:
            submitted, answers = await self.submit_answers(cust, payload)
        except Exception as err:
            with self.repo.tx() as tx:
                tx.add_event(self.clock.now(), ACTOR, "kos_rejected", None,
                             {"reservationId": d.reservation_id, "customerId": cust.id, "op": "submit-visitor-questionnaire",
                              "httpStatus": getattr(err, "status", None), "kosError": kos_errors.describe(err)})
            log.warning("KOS 문진 제출 실패: %s · request=%d", kos_errors.describe(err), d.id)
            if isinstance(err, KosError) and err.status == 400:
                raise Conflict("questionnaire_rejected", FAILED) from None
            raise BadGateway("kos_unavailable", FAILED) from None
        now = self.clock.now()
        read_at = parse(submitted) if isinstance(submitted, str) else None
        stale = read_at is None or read_at < started - timedelta(seconds=FRESH_SEC)
        if stale:  # KOS 제출 확인이 이번 제출이 아님 → 받은 답을 KOS 제출본 꼴로 ccc 에(상세 「건강 정보」가 쓴다)
            log.info("KOS 제출 확인이 이번 제출이 아님(옛 제출본) — ccc 제출본으로 기록 · request=%d", d.id)
            submitted, answers = kos_utc(now), submitted_answers(payload.get("answers") or [])
        with self.repo.tx() as tx:
            history = tx.put_app_questionnaire(cust.id, d.reservation_id, submitted, answers, now,
                                               language=body.get("language"), device_id=None,
                                               display_request_id=d.id, source="web_submit")
            tx.update_display(d.id, status="done", closed_at=now)
            tx.add_event(now, ACTOR, "questionnaire_submit", None,
                         {"reservationId": d.reservation_id, "customerId": cust.id, "language": body.get("language"),
                          "historyId": history, "displayRequestId": d.id, "channel": "web", "kosReadStale": stale})
        with self.repo.tx() as tx:
            r = tx.reservation(d.reservation_id)
        self.resv.after_write(r.day if r else None)

    # ------------------------------------------------------------------ 공개 길(속도 제한 · 잠금 · 거절 기록)
    async def load_public(self, token: str | None, lang: str | None, ip: str) -> dict[str, Any]:
        self._gate(("get", ip), LIMIT_GET_IP, ip)
        d = self._target_or_deny(token, ip)
        return await self.load_for(d, lang)

    async def submit_public(self, token: str | None, body: dict[str, Any], sent: set[str], ip: str) -> None:
        self._gate(("post", ip), LIMIT_POST_IP, ip)
        if token and not self.rate.take(("post_token", token_hash(token)), LIMIT_POST_TOKEN):
            self._deny(ip, "rate", None)
            raise TooManyRequests("too_many_requests", "잠시 뒤 다시 시도해 주세요")
        d = self._target_or_deny(token, ip)
        lock = self._locks.setdefault(d.id, asyncio.Lock())
        if lock.locked():  # 같은 링크로 겹친 제출 — 뒤엣것(§3.3)
            self._deny(ip, "submitting", d.id)
            raise Conflict("q_submitting", "제출 중이에요")
        async with lock:
            d = self._target_or_deny(token, ip)  # 앞 제출이 끝났으면 409 q_submitted
            await self.submit_for(d, body, sent)

    def _gate(self, key: tuple[str, str], limit: int, ip: str) -> None:
        if self.rate.full(("bad", ip), LIMIT_BAD_IP) or not self.rate.take(key, limit):
            self._deny(ip, "rate", None)
            raise TooManyRequests("too_many_requests", "잠시 뒤 다시 시도해 주세요")

    def _target_or_deny(self, token: str | None, ip: str) -> DisplayRequest:
        try:
            return self.public_target(token)
        except DomainError as e:
            reasons = {"q_not_found": "not_found", "q_expired": "expired", "q_canceled": "canceled",
                       "q_submitted": "submitted"}
            if e.status in (404, 410):  # 틀린 · 지난 토큰 = 토큰 맞히기 카운터
                self.rate.add(("bad", ip))
            if e.code in reasons:
                self._deny(ip, reasons[e.code], e.extra.get("requestId"))
                e.extra.pop("requestId", None)  # 응답 본문엔 싣지 않는다
            raise

    def _deny(self, ip: str, reason: str, request_id: int | None) -> None:
        """qweb_denied — 같은 IP 같은 이유는 1분에 1행 · IP · 토큰은 남기지 않는다."""
        now = self.rate.now_mono()
        last = self._denied.get((ip, reason))
        if last is not None and now - last < WINDOW_SEC:
            return
        self._denied[(ip, reason)] = now
        payload: dict[str, Any] = {"reason": reason}
        if request_id is not None and reason != "not_found":
            payload["requestId"] = request_id
        with self.repo.tx() as tx:
            tx.add_event(self.clock.now(), ACTOR, "qweb_denied", None, payload)
