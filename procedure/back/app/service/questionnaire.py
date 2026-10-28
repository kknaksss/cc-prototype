"""QR 문진 — 고객용(SPEC-004 §6.15 · §8.0 #16 ~ #20). KOS 공개 양식 · 약관 · 제출 · 제출 확인 + 내부 get-visitor(언어).

- 언어는 back 이 정한다(domain/languages.py) · 앱은 받은 번역 안에서 바꾼다(D7-46)
- 제출: 주민번호 · 발음 칸을 보내면 400 · visitorId 를 붙여 공개 submit · 성공하면 제출본을 다시 읽어
  questionnaire_history 1행(source = app_submit). 같은 제출본 read 행이 있으면 그 행을 고친다(r2)
- KOS 400 = 409 questionnaire_rejected · 그 밖 = 502 · 둘 다 event_log(kos_rejected)
- 제출은 KOS 고객의 성별 · 생년월일 · 주소 · 휴대폰 · 동의를 바꾼다(AK§5.3). 휴대폰은 KOS 가 맨 앞 0 을 뺀다 — 고치지 않는다
"""

import asyncio
import logging
from typing import Any

from app.domain import languages
from app.domain.clock import KST, Clock, parse
from app.domain.errors import BadGateway, BadRequest, Conflict, NotFound
from app.domain.models import Account
from app.kos.client import KosError
from app.repository.repo import Repository
from app.service import kos_errors
from app.service.devices import DeviceService
from app.service.reservations import PATH_Q_FORM, PATH_Q_SUBMIT, PATH_VISITOR, ReservationService

log = logging.getLogger("procedure.questionnaire")

PATH_AGREEMENTS = "visitor/open/v1/queries/get-questionnaire-agreements"
PATH_SUBMIT = "visitor/open/v1/commands/submit-visitor-questionnaire"
FORBIDDEN_FIELDS = ("registrationNumber", "phoneticName")  # 주민번호 칸 없음(D7-16 Q-152) · 발음은 KOS 고객 값을 바꾼다
FAILED = "제출하지 못했어요 · 직원에게 알려 주세요"


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


class QuestionnaireService:
    def __init__(self, repo: Repository, clock: Clock, resv: ReservationService, devices: DeviceService, display):
        self.repo = repo
        self.clock = clock
        self.resv = resv
        self.devices = devices
        self.display = display  # DisplayService — 제출 성공 = 띄우기 요청 done

    def _target(self, reservation_id: int):
        with self.repo.tx() as tx:
            r = tx.reservation(reservation_id)
            if r is None:
                raise NotFound("없는 예약이에요")
            cust = tx.customer(r.customer_id) if r.customer_id else None
        if cust is None:
            raise NotFound("고객이 없는 예약이에요")
        return r, cust

    # ------------------------------------------------------------------ ① 불러오기
    async def load(self, actor: Account, reservation_id: int, lang: str | None, device_id: int | None) -> dict[str, Any]:
        self.devices.check(actor, device_id)
        r, cust = self._target(reservation_id)
        client = self.resv.client()
        vid = cust.kos_id
        got = await asyncio.gather(client.internal(PATH_VISITOR, {"id": vid}), client.open(PATH_Q_FORM, {"visitorId": vid}),
                                   client.open(PATH_AGREEMENTS, {}), client.open(PATH_Q_SUBMIT, {"visitorId": vid}),
                                   return_exceptions=True)
        visitor_r, form_r, agree_r, submit_r = got
        for x in (form_r, agree_r):  # 양식 · 약관이 없으면 화면을 못 그린다
            if isinstance(x, BaseException):
                raise BadGateway("kos_unavailable", kos_errors.describe(x))
        visitor = _obj(visitor_r) if not isinstance(visitor_r, BaseException) else {}
        form = _obj(form_r)  # type: ignore[arg-type]
        code, source = languages.resolve(visitor.get("language"), visitor.get("nationality") or cust.nationality)
        if lang in languages.FORM_LANGS:
            code = lang  # 다시 부를 때 고른 언어(앱은 보통 받은 번역 안에서 바꾼다 · D7-46)
        submit = None if isinstance(submit_r, BaseException) else _obj(submit_r)
        submitted = parse((submit or {}).get("createdDateTimeUtc"))
        today = self.clock.now().astimezone(KST).date()
        phone = visitor.get("phoneNumber") if isinstance(visitor.get("phoneNumber"), dict) else {}
        addr = visitor.get("address") if isinstance(visitor.get("address"), dict) else {}
        return {
            "reservationId": r.id, "customerName": cust.name,
            "language": {"code": code, "source": source, "options": list(languages.FORM_LANGS)},
            "form": {"pages": [p for p in form.get("pages") or [] if isinstance(p, dict)]},
            "agreements": _list(agree_r, "agreements") or [a for a in form.get("agreements") or [] if isinstance(a, dict)],  # type: ignore[arg-type]
            "prefill": {"name": visitor.get("name") or form.get("name") or cust.name,
                        "phone": {"countryCode": phone.get("countryCode") or "", "phoneNumber": phone.get("phoneNumber") or ""},
                        "address": addr.get("address") or form.get("address") or "",
                        "addressDetail": addr.get("detailedAddress") or form.get("addressDetail") or "",
                        "dateOfBirth": _ymd(visitor.get("dateOfBirth")) or _ymd(form.get("dateOfBirth")),
                        "gender": visitor.get("gender") or form.get("gender")},
            "todaySubmitted": bool(submitted and submitted.astimezone(KST).date() == today),
        }

    # ------------------------------------------------------------------ ⑥ 제출
    async def submit(self, actor: Account, reservation_id: int, body: dict[str, Any], sent: set[str]) -> None:
        bad = [k for k in FORBIDDEN_FIELDS if k in sent]
        if bad:
            raise BadRequest("questionnaire_field", f"{', '.join(bad)}: 보낼 수 없는 칸이에요")
        device = self.devices.check(actor, body.get("deviceId"))
        r, cust = self._target(reservation_id)
        client = self.resv.client()
        payload = {k: v for k, v in body.items() if k not in ("deviceId", "displayRequestId", "language", *FORBIDDEN_FIELDS)}
        payload["visitorId"] = cust.kos_id
        try:
            await client.open(PATH_SUBMIT, payload)
        except Exception as err:
            with self.repo.tx() as tx:
                tx.add_event(self.clock.now(), actor.login_id, "kos_rejected", None,
                             {"reservationId": r.id, "customerId": cust.id, "op": "submit-visitor-questionnaire",
                              "httpStatus": getattr(err, "status", None), "kosError": kos_errors.describe(err)})
            log.warning("KOS 문진 제출 실패: %s", kos_errors.describe(err))
            if isinstance(err, KosError) and err.status == 400:
                raise Conflict("questionnaire_rejected", FAILED) from None
            raise BadGateway("kos_unavailable", FAILED) from None
        submitted, answers = None, []
        try:  # 제출 확인 — 실패해도 제출은 됐다(이력만 못 씀)
            sub = _obj(await client.open(PATH_Q_SUBMIT, {"visitorId": cust.kos_id}))
            submitted, answers = sub.get("createdDateTimeUtc"), sub.get("answers") or []
        except Exception as err:
            log.warning("KOS 제출 확인 실패: %s", kos_errors.describe(err))
        now = self.clock.now()
        with self.repo.tx() as tx:
            if isinstance(submitted, str) and submitted:
                tx.put_app_questionnaire(cust.id, r.id, submitted, answers, now, language=body.get("language"),
                                         device_id=device.id if device else None,
                                         display_request_id=body.get("displayRequestId"))
            self.display.finish(tx, actor, body.get("displayRequestId"))
            tx.add_event(now, actor.login_id, "questionnaire_submit", None,
                         {"reservationId": r.id, "customerId": cust.id, "language": body.get("language"),
                          "deviceId": device.id if device else None, "displayRequestId": body.get("displayRequestId")})
        self.resv.after_write(r.day)
