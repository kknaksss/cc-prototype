"""예약 현황 규칙(SPEC-005 §5) — HTTP · DB · KOS 를 모른다. 사본 · KOS 응답 값만 받아 계산한다."""

import math
from datetime import date, datetime, time, timedelta
from typing import Any

from app.domain.clock import KST, parse
from app.domain.errors import BadRequest

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# §5.1 — KOS flowStep → (main, sub)
FLOW_STATE: dict[str, tuple[str, str | None]] = {
    "RESERVED": ("reserved", None),
    "RECEPTION": ("reception", None),
    "CONSULTATION_WAITING": ("consultation", "waiting"),
    "CONSULTATION": ("consultation", "doing"),
    "PROCEDURE_WAITING": ("procedure", "waiting"),
    "PROCEDURE": ("procedure", "doing"),
    "PROCEDURE_DONE": ("home", "waiting"),
    "COMPLETED": ("home", "done"),
}
MAINS = ("reserved", "reception", "consultation", "procedure", "home", "canceled", "noshow")
CLOSED_MAINS = ("canceled", "noshow")
# §5.7 「사용 중」 · §6.4 원내 · §5.6 끝 단계 이후
BUSY_FLOWS = ("RECEPTION", "CONSULTATION_WAITING", "CONSULTATION", "PROCEDURE_WAITING", "PROCEDURE")
IN_CLINIC_FLOWS = (*BUSY_FLOWS, "PROCEDURE_DONE")
AFTER_END_FLOWS = ("CONSULTATION_WAITING", "CONSULTATION", "PROCEDURE_WAITING", "PROCEDURE", "PROCEDURE_DONE", "COMPLETED")
ROOM_TASK_TITLE = "방 배정"
NO_PROBLEM = ("없음", "아니오")  # §5.11 「확인 필요」 아님


def state_of(status: str | None, flow_step: str | None) -> tuple[str, str | None]:
    """2계층 상태(§5.1) — 취소 · 부도가 먼저, 아니면 flowStep. 모르는 단계 = 예약."""
    if status == "CANCELED":
        return "canceled", None
    if status == "NO_SHOW":
        return "noshow", None
    return FLOW_STATE.get(flow_step or "", ("reserved", None))


# ------------------------------------------------------------------ 날짜 · 시각
def parse_day(value: str | None, now: datetime) -> date:
    """`YYYY-MM-DD` → 날짜. 비면 오늘(KST) · 형식 오류 = 400."""
    if value is None or value == "":
        return now.astimezone(KST).date()
    try:
        if len(value) != 10:
            raise ValueError(value)
        return date.fromisoformat(value)
    except ValueError:
        raise BadRequest("invalid_request", "date: YYYY-MM-DD 꼴이어야 해요") from None


def parse_at(value: str, what: str = "start") -> datetime:
    """요청 ISO 시각 → aware(오프셋 없으면 KST 로 본다). 형식 오류 = 400."""
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise BadRequest("invalid_request", f"{what}: ISO 시각이어야 해요") from None
    return at if at.tzinfo else at.replace(tzinfo=KST)


def day_range(day: date) -> tuple[datetime, datetime]:
    """그 날짜 KST 00:00 ~ 다음날 00:00 — aware."""
    start = datetime.combine(day, time(0), tzinfo=KST)
    return start, start + timedelta(days=1)


def hhmm(at: datetime) -> str:
    return at.astimezone(KST).strftime("%H:%M")


def at_hhmm(day: date, value: str) -> datetime:
    """그 날짜(KST)의 `HH:MM` → aware datetime(`24:00` = 다음날 00:00)."""
    m = to_min(value)
    return datetime.combine(day, time(0), tzinfo=KST) + timedelta(minutes=m)


def to_min(value: str) -> int:
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def from_min(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def kst_min(at: datetime, day: date) -> int:
    """그 날짜 KST 00:00 부터 몇 분(다른 날이면 범위 밖 값)."""
    return int((at - day_range(day)[0]).total_seconds() // 60)


# ------------------------------------------------------------------ §5.2 칸 · 축
def day_table(timetable: dict[str, Any], day: date) -> dict[str, Any]:
    t = timetable.get(WEEKDAYS[day.weekday()]) or {}
    return t if t.get("enabled") and t.get("start") and t.get("end") else {}


def open_spans(timetable: dict[str, Any], day: date) -> list[tuple[str, str]]:
    """운영 구간(쉬는 시간 뺀 조각) — 그 요일이 꺼졌으면 []."""
    t = day_table(timetable, day)
    if not t:
        return []
    start, end = t["start"], t["end"]
    bs, be = t.get("breakStart"), t.get("breakEnd")
    if bs and be and to_min(start) < to_min(bs) < to_min(be) <= to_min(end):
        return [x for x in ((start, bs), (be, end)) if to_min(x[0]) < to_min(x[1])]
    return [(start, end)]


def axis(timetables: list[dict[str, Any]], day: date, card_spans: list[tuple[int, int]]) -> tuple[str, str] | None:
    """세로축 = 켜진 그룹 운영 시간의 합 + 축 밖 카드까지 늘림(30분 단위). 둘 다 없으면 None(운영 안 하는 날)."""
    lo, hi = None, None
    for tt in timetables:
        t = day_table(tt, day)
        if t:
            lo = to_min(t["start"]) if lo is None else min(lo, to_min(t["start"]))
            hi = to_min(t["end"]) if hi is None else max(hi, to_min(t["end"]))
    for s, e in card_spans:
        s, e = max(0, s), min(24 * 60, e)
        lo = (s // 30) * 30 if lo is None else min(lo, (s // 30) * 30)
        hi = math.ceil(e / 30) * 30 if hi is None else max(hi, math.ceil(e / 30) * 30)
    if lo is None or hi is None or lo >= hi:
        return None
    return from_min(lo), from_min(hi)


def lines(ax: tuple[str, str] | None, interval: int) -> list[int]:
    """칸 줄 시작(분) — 축 시작을 그 칸 간격으로 내린 곳부터(자정 기준 경계와 같다 · r1 W2)."""
    if ax is None or interval <= 0:
        return []
    a0 = to_min(ax[0])
    return list(range(a0 - a0 % interval, to_min(ax[1]), interval))


def capacity_label(caps: list[tuple[str, int]]) -> str:
    """칸 머리 정원 글자(§5.2) — 구역 하나 = 「3명」 · 둘 이상 = 「4층 3 · 미사용 3명」 · 없음 = 「- 명」.

    front 가 `capacities` 로 그린다 — 이 함수는 시험 · 기준용.
    """
    if not caps:
        return "- 명"
    if len(caps) == 1:
        return f"{caps[0][1]}명"
    return " · ".join(f"{t} {n}" for t, n in caps) + "명"


# ------------------------------------------------------------------ §5.4 정원
def is_full(capacity: int | None, count: int | None) -> bool:
    return capacity is not None and count is not None and count >= capacity


def plus_allowed(fulls: list[bool]) -> bool:
    """[+] = 그 줄 켜진 구역 중 하나라도 자리 있음. 켜진 구역이 없으면 등록할 구역이 없다 → 없음."""
    return any(not f for f in fulls)


def draggable(main: str) -> bool:
    return main in ("reserved", "reception")


# ------------------------------------------------------------------ §5.9 수납 필요 · 금액
def is_room_task(task: dict[str, Any], called_seqs: set[int]) -> bool:
    """「방 배정」(SPEC-003 판정 — `domain/rules.py` `Rules.is_room_task` 와 같은 식): ETCETERA · 방 붙음 · ccc 호출 기록 없음.

    called_seqs = 시술 현황 사본에서 `visit.kos_id = reservation.kos_id` 인 visit 의 호출된 procedure `kos_sequence` —
    visit · procedure 행이 없으면 빈 집합(호출 0).
    """
    return task.get("type") == "ETCETERA" and bool(task.get("roomKosId")) and task.get("sequence") not in called_seqs


def payment_required_count(tasks: list[dict[str, Any]], called_seqs: set[int]) -> int:
    return sum(1 for t in tasks if t.get("paymentRequired") and t.get("status") != "CANCELED"
               and not is_room_task(t, called_seqs))


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _int_if(v: float) -> int | float:
    return int(v) if float(v).is_integer() else v


def purchase_amount(summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """전체 = items[].priceV2.amount.value 합 · 결제 = APPROVED 이고 canceledRefId 없는 거래 price.value 합(OQ-726)."""
    if not summaries:
        return None
    total = paid = 0.0
    currency = None
    for p in summaries:
        for it in p.get("items") or []:
            amount = ((it.get("priceV2") or {}).get("amount") or {}) if isinstance(it, dict) else {}
            total += _num(amount.get("value"))
            currency = currency or amount.get("currency") or (it.get("price") or {}).get("currency")
        for tr in p.get("transactions") or []:
            if isinstance(tr, dict) and tr.get("status") == "APPROVED" and not tr.get("canceledRefId"):
                paid += _num((tr.get("price") or {}).get("value"))
                currency = currency or (tr.get("price") or {}).get("currency")
    return {"total": _int_if(total), "paid": _int_if(paid), "currency": currency}


def sum_amounts(parts: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    got = [p for p in parts if p]
    if not got:
        return None
    return {"total": _int_if(sum(_num(p["total"]) for p in got)), "paid": _int_if(sum(_num(p["paid"]) for p in got)),
            "currency": next((p["currency"] for p in got if p.get("currency")), None)}


# ------------------------------------------------------------------ §5.12 신분 칸
def blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def identity_fields(visitor: dict[str, Any] | None) -> tuple[str, list[dict[str, Any]], bool]:
    """KOS get-visitor → (kind, fields[{key,label,filled}], complete). 키 = KOS 키(추가 지시 1 W5). 모르면 ([] · False)."""
    nationality = (visitor or {}).get("nationality")
    foreign = blank(nationality) or nationality != "KR"
    kind = "foreign" if foreign else "domestic"
    if visitor is None:
        return kind, [], False
    if foreign:
        fields = [{"key": "passportSurname", "label": "여권 영문명",
                   "filled": not (blank(visitor.get("passportSurname")) and blank(visitor.get("passportGivenNames")))},
                  {"key": "dateOfBirth", "label": "생년월일", "filled": not blank(visitor.get("dateOfBirth"))},
                  {"key": "passportNumber", "label": "여권번호", "filled": not blank(visitor.get("passportNumber"))}]
    else:
        fields = [{"key": "dateOfBirth", "label": "생년월일", "filled": not blank(visitor.get("dateOfBirth"))},
                  {"key": "registrationNumber", "label": "주민등록번호", "filled": not blank(visitor.get("registrationNumber"))}]
    return kind, fields, all(f["filled"] for f in fields)


# ------------------------------------------------------------------ §5.5 신규 구분
def identifiable(name: str | None, *, phone: dict | None, sns: dict | None, email: str | None, passport: str | None,
                 birth: str | None) -> bool:
    """이름 + (연락처(국가번호 + 번호) · SNS(종류 + ID) · 이메일 · 여권번호 · 생년월일 중 하나 이상)(D-17)."""
    if blank(name):
        return False
    has_phone = bool(phone) and not blank(phone.get("countryCode")) and not blank(phone.get("number"))
    has_sns = bool(sns) and not blank(sns.get("type")) and not blank(sns.get("accountId"))
    return has_phone or has_sns or not blank(email) or not blank(passport) or not blank(birth)


# ------------------------------------------------------------------ §5.6 접수 갈래 · §5.14 버튼
def receive_mode(main: str, flow_step: str | None) -> str | None:
    """§5.6 두 갈래 — 새 접수 = 예약 · 부도 / 이어 하기 = RECEPTION(방 유무 무관) / 그 밖 = None."""
    if main == "reception":
        return "resume"
    if main in ("reserved", "noshow"):
        return "new"
    return None


def is_reception_room_task(task: dict[str, Any]) -> bool:
    """§5.6 「제목 판정」 — ETCETERA · 제목 「방 배정」 · 취소 아님(묶음이 만든 · 쓸 작업)."""
    return task.get("type") == "ETCETERA" and (task.get("title") or "").strip() == ROOM_TASK_TITLE \
        and task.get("status") != "CANCELED"


def reception_room_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """쓸 「방 배정」 = 안 취소된 「방 배정」 중 가장 큰 sequence."""
    cands = [t for t in tasks if is_reception_room_task(t)]
    return max(cands, key=lambda t: t.get("sequence") or 0) if cands else None


def can(main: str, flow_step: str | None, *, is_new: bool, identity_complete: bool, personal_ok: bool,
        payment_required: int, identity_confirmed: bool, identity_locked: bool = False) -> dict[str, bool]:
    mode = receive_mode(main, flow_step)
    return {
        "cancel": main == "reserved",
        "editRoute": main in ("reserved", "noshow") and not is_new,  # 추가 지시 1 W4 — 부도도 연다
        "receive": mode == "resume" or (mode == "new" and personal_ok and identity_complete),
        "callCounselor": flow_step in ("CONSULTATION_WAITING", "CONSULTATION") and main not in CLOSED_MAINS,
        "discharge": flow_step == "PROCEDURE_DONE" and main not in CLOSED_MAINS and payment_required == 0,
        "editMemo": main != "canceled" and flow_step != "COMPLETED",  # §5.14 — 부도는 연다(추가 지시 1 W4 · r1 W1)
        "editPersonal": True,
        "editRemark": True,
        "confirmIdentity": not identity_confirmed,
        "unconfirmIdentity": identity_confirmed and not identity_locked,  # 고객 단위 — 409 identity_locked 와 같은 식(r1 W4)
    }


# ------------------------------------------------------------------ §5.11 건강 정보
def health_items(form: dict[str, Any] | None, submit: dict[str, Any] | None) -> list[dict[str, Any]]:
    """문진 양식 「건강 정보」 쪽 질문 × 제출본 답."""
    pages = (form or {}).get("pages") or []
    page = next((p for p in pages if isinstance(p, dict) and (p.get("title") or "").strip() == "건강 정보"), None)
    questions = sorted((q for q in (page or {}).get("questions") or [] if isinstance(q, dict)),
                       key=lambda q: q.get("sequence") or 0)
    answers = [a for a in (submit or {}).get("answers") or [] if isinstance(a, dict)]
    out = []
    for q in questions:
        mine = sorted((a for a in answers if a.get("questionId") == q.get("questionId")), key=lambda a: a.get("seq") or 0)
        titles = [(a.get("answerTitle") or "").strip() for a in mine if not blank(a.get("answerTitle"))]
        memos = [a["memo"].strip() for a in mine if isinstance(a.get("memo"), str) and a["memo"].strip()]
        empty = not titles and not memos
        out.append({"title": q.get("title") or "", "answer": " · ".join(titles) or None, "memo": " · ".join(memos) or None,
                    "needsCheck": not empty and not (titles and all(t in NO_PROBLEM for t in titles)), "empty": empty})
    return out


# ------------------------------------------------------------------ §5.13 이전 방문
PREV_RESULT = {"COMPLETED": "completed", "NO_SHOW": "noshow", "CANCELED": "canceled"}


def schedule_start(sch: dict[str, Any]) -> datetime | None:
    starts = [parse(((r or {}).get("reservationTime") or {}).get("startDateTimeUtc"))
              for r in sch.get("occupiedResources") or [] if isinstance(r, dict)]
    starts = [s for s in starts if s]
    return min(starts) if starts else parse((sch.get("reservation") or {}).get("startDateTime"))


def age_on(birth: str | None, day: date) -> int | None:
    if blank(birth):
        return None
    try:
        b = date.fromisoformat(str(birth)[:10])
    except ValueError:
        return None
    return day.year - b.year - ((day.month, day.day) < (b.month, b.day))
