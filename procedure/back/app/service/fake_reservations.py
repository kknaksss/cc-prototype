"""예약 현황 가짜 응답(SPEC-005 §7.1) — `PROC_FAKE_BOARD=1` 일 때 GET 넷이 이 값을 준다(front 단독 작업용).

이름 · 공지 · 직원 · 방 · 금액은 전부 지어낸 값이다(KOS 값 · 시안 실명 아님 — 「고객 A」 꼴). KOS id 없음.
장면(WORK-007 「가짜 응답」): 칸 13 + 「그룹 없음」 1 · 구역 2(켜진 구역 둘인 칸 1) · 상태 7종 + 부상태 · 꽉 찬 줄 1 ·
카드 수납 필요 1 · 귀가 대기 1 · 공지 1 · 원내 현황(두 구역) · 상세 = 예약마다(부도 · 이어 하기(방 고정) · 신분 칸 빔 포함).
날짜와 상관없이 같은 예약을 그 날짜에 놓는다(원내 현황은 오늘만).
"""

from datetime import date, datetime, timedelta

from app.domain.clock import KST, iso
from app.domain.errors import BadRequest, NotFound
from app.domain.reservation_rules import CLOSED_MAINS, at_hhmm, hhmm, parse_day, state_of
from app.schemas.reservations import (
    CustomerSearch,
    ReservationBoard,
    ReservationDetail,
    ReservationForm,
)

Z4, Z5 = 1, 2
ZONES = [{"zoneId": Z4, "title": "4층", "order": 1, "isDefault": True},
         {"zoneId": Z5, "title": "5층", "order": 2, "isDefault": False}]
ZONE_TITLE = {z["zoneId"]: z["title"] for z in ZONES}
BREAK = ("13:00", "14:00")
# (groupId, 제목, 간격, {구역: 정원}, 운영 (시작, 끝), 쉬는 시간 있음)
GROUPS = [
    (1, "국내", 30, {Z4: 3}, ("10:00", "20:00"), True),
    (2, "중화권", 30, {Z4: 3}, ("10:00", "20:00"), True),
    (3, "영미권", 30, {Z4: 3}, ("10:00", "20:00"), True),
    (4, "일본", 30, {Z4: 3}, ("10:00", "20:00"), True),
    (5, "동남아", 60, {Z4: 2}, ("10:00", "19:00"), False),
    (6, "제모", 15, {Z4: 3, Z5: 3}, ("10:00", "20:00"), True),
    (7, "리프팅", 60, {Z4: 2}, ("11:00", "20:00"), False),
    (8, "피부 관리", 30, {Z4: 3}, ("10:00", "18:00"), True),
    (9, "레이저", 30, {Z4: 3}, ("10:00", "20:00"), True),
    (10, "주사", 15, {Z4: 4}, ("10:00", "20:00"), True),
    (11, "재방문", 30, {Z4: 3}, ("12:00", "20:00"), False),
    (12, "VIP", 60, {}, ("10:00", "20:00"), False),  # 켜진 구역 없음 → 「- 명」
    (13, "기타", 30, {Z4: 3}, ("10:00", "20:00"), True),
]
AXIS = ("10:00", "20:00")

ROOMS = {Z4: [(1, "A-룸1"), (2, "A-룸2"), (3, "A-룸3"), (4, "A-룸4"), (5, "A-레이저실")],
         Z5: [(11, "B-룸1"), (12, "B-룸2")]}
DOCTORS = [(1, "원장 1"), (2, "원장 2"), (3, "원장 3")]
COUNSELORS = [(21, "상담사 1"), (22, "상담사 2"), (23, "상담사 3")]
SYSTEM = (30, "시스템")
STAFF = [SYSTEM, *DOCTORS, *COUNSELORS, (31, "데스크 1"), (32, "데스크 2")]
FUNNELS = [(1, "인스타그램"), (2, "지인 소개"), (3, "검색"), (4, "여행사"), (5, "기타")]

# 고객: id · 이름 · 발음 · 성별 · 국적 · 신규 · 차트 · 생년월일
CUSTOMERS = [
    (1, "고객 A", "コキャクA", "FEMALE", "JP", True, None, "1994-03-02"),
    (2, "고객 B", "고객비", "MALE", "KR", False, "C-0102", "1988-11-20"),
    (3, "CUSTOMER C", None, "FEMALE", "US", False, "C-0103", "1990-07-14"),
    (4, "顾客 D", "구커디", "FEMALE", "CN", True, None, "1999-01-30"),
    (5, "고객 E", "コキャクE", "MALE", "JP", False, "C-0105", None),
    (6, "고객 F", None, "GENDER_UNSPECIFIED", "TW", False, "C-0106", "1985-05-05"),
    (7, "고객 G", "コキャクG", "FEMALE", "JP", False, "C-0107", "1992-09-09"),
    (8, "CUSTOMER H", None, "MALE", "TH", True, None, "2000-02-29"),
    (9, "고객 I", "고객아이", "FEMALE", "KR", False, "C-0109", "1979-12-01"),
    (10, "고객 J", None, "FEMALE", "VN", True, None, "1996-06-06"),
    (11, "고객 K", "コキャクK", "FEMALE", "JP", False, "C-0111", "1991-04-04"),
    (12, "고객 L", None, "MALE", "ZZ", False, "C-0112", "1983-08-08"),
    (13, "고객 M", None, "FEMALE", None, True, None, None),
    (14, "고객 N", "コキャクN", "FEMALE", "JP", False, "C-0114", "1993-10-10"),
    (15, "고객 O", None, "MALE", "US", False, "C-0115", "1987-03-03"),
    (16, "고객 P", "고객피", "FEMALE", "KR", False, "C-0116", "1995-02-02"),
]
CUST = {c[0]: c for c in CUSTOMERS}
SEARCH_EXTRA = [(100 + i, f"고객 A{i:02d}", None, "FEMALE", "JP", False, f"C-{200 + i:04d}", "1990-01-01") for i in range(1, 25)]

# 예약: id · 고객 · 묶음[(그룹, 시작, 분)] · 구역 · KOS 상태 · 단계 · 상담 필요 · 방(작업에 붙은 방 id) · 수납 필요 수 · 메모
RESERVATIONS = [
    (1, 1, [(4, "10:00", 30)], Z4, "RESERVED", "RESERVED", True, None, 0, "날짜/지점/희망 시술/통역/특이사항"),
    (2, 2, [(1, "10:30", 30)], Z4, "RESERVED", "RESERVED", False, None, 0, None),          # 신분 칸 빔(내국인 주민번호)
    (3, 3, [(3, "11:00", 30)], Z4, "IN_PROGRESS", "RECEPTION", True, 3, 0, None),         # 이어 하기 · 방 고정
    (4, 4, [(2, "11:00", 30)], Z4, "IN_PROGRESS", "CONSULTATION_WAITING", True, 1, 0, None),
    (5, 5, [(4, "11:30", 30)], Z4, "IN_PROGRESS", "CONSULTATION", True, 2, 0, None),
    (6, 6, [(9, "12:00", 30)], Z4, "IN_PROGRESS", "PROCEDURE_WAITING", False, 5, 0, None),
    (7, 7, [(4, "12:00", 60), (10, "13:00", 15)], Z4, "IN_PROGRESS", "PROCEDURE", True, 4, 0, "두 묶음 예약"),
    (8, 8, [(13, "14:00", 30)], Z4, "IN_PROGRESS", "PROCEDURE_DONE", False, None, 1, None),  # 귀가 대기 · 수납 필요 1
    (9, 9, [(1, "15:00", 30)], Z4, "COMPLETED", "COMPLETED", False, None, 0, None),
    (10, 10, [(2, "15:00", 30)], Z4, "CANCELED", "RESERVED", True, None, 0, None),
    (11, 11, [(4, "15:30", 30)], Z4, "NO_SHOW", "RESERVED", True, None, 0, None),          # 부도 — 접수 가능
    (12, 12, [(6, "16:00", 15)], Z5, "RESERVED", "RESERVED", False, None, 0, None),        # 다른 구역
    (13, 13, [(6, "16:00", 15)], Z5, "IN_PROGRESS", "PROCEDURE_WAITING", False, 12, 0, None),  # 5층 원내(두 구역)
    (14, 14, [(99, "17:00", 30)], Z4, "RESERVED", "RESERVED", True, None, 0, None),         # 「그룹 없음」
    (15, 15, [(3, "18:00", 30)], Z4, "RESERVED", "RESERVED", True, None, 0, None),          # 18:00 영미권 꽉 참(3)
    (16, 16, [(3, "18:00", 30)], Z4, "RESERVED", "RESERVED", False, None, 0, None),
    (17, 1, [(3, "18:00", 30)], Z4, "RESERVED", "RESERVED", False, None, 0, None),
]
RESV = {r[0]: r for r in RESERVATIONS}

IN_CLINIC = ("RECEPTION", "CONSULTATION_WAITING", "CONSULTATION", "PROCEDURE_WAITING", "PROCEDURE", "PROCEDURE_DONE")
BUSY_FLOWS = ("RECEPTION", "CONSULTATION_WAITING", "CONSULTATION", "PROCEDURE_WAITING", "PROCEDURE")
GROUP = {g[0]: g for g in GROUPS}
ROOM_TITLE = {rid: t for rooms in ROOMS.values() for rid, t in rooms}
ROOM_ZONE = {rid: z for z, rooms in ROOMS.items() for rid, _ in rooms}


def _state(r) -> tuple[str, str | None]:
    return state_of(r[4], r[5])


def _minutes(value: str) -> int:
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def _hm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _open(g) -> list[dict]:
    start, end = g[4]
    if g[5]:
        return [{"start": start, "end": BREAK[0]}, {"start": BREAK[1], "end": end}]
    return [{"start": start, "end": end}]


def _lines(interval: int) -> list[str]:
    return [_hm(m) for m in range(_minutes(AXIS[0]), _minutes(AXIS[1]), interval)]


def _card_customer(cid: int) -> dict:
    c = CUST[cid]
    return {"customerId": c[0], "name": c[1], "phoneticName": c[2], "gender": c[3], "nationality": c[4], "isNew": c[5]}


def _amount(r) -> dict | None:
    if r[5] not in ("PROCEDURE_DONE", "COMPLETED", "PROCEDURE", "PROCEDURE_WAITING"):
        return None
    total = 1000 * (r[0] + 10)
    paid = total if r[8] == 0 and r[5] == "COMPLETED" else total // 2
    return {"total": total, "paid": paid, "currency": "KRW"}


def _count_at(group_id: int, zone_id: int, line: str, interval: int) -> int:
    lo, hi = _minutes(line), _minutes(line) + interval
    n = 0
    for r in RESERVATIONS:
        if _state(r)[0] in CLOSED_MAINS or r[3] != zone_id:
            continue
        n += sum(1 for g, s, _ in r[2] if g == group_id and lo <= _minutes(s) < hi)
    return n


def board(now: datetime, date_value: str | None) -> ReservationBoard:
    day = parse_day(date_value, now)
    today = now.astimezone(KST).date()

    def at(value: str) -> str:
        return iso(at_hhmm(day, value))

    columns, slots, rows = [], [], []
    for g in GROUPS:
        gid, title, interval, caps, _, _ = g
        resv = [r for r in RESERVATIONS if any(x[0] == gid for x in r[2])]
        columns.append({"groupId": gid, "title": title, "order": gid, "intervalMinutes": interval,
                        "count": sum(1 for r in resv if _state(r)[0] not in CLOSED_MAINS),
                        "capacities": [{"zoneId": z, "capacity": n} for z, n in caps.items()], "open": _open(g)})
        for line in _lines(interval):
            fulls = []
            for z, cap in caps.items():
                count = _count_at(gid, z, line, interval)
                fulls.append(count >= cap)
                slots.append({"groupId": gid, "zoneId": z, "start": at(line), "end": at(_hm(_minutes(line) + interval)),
                              "capacity": cap, "count": count, "full": count >= cap})
            rows.append({"groupId": gid, "start": at(line), "plusAllowed": any(not f for f in fulls)})
    lost = [r for r in RESERVATIONS if any(x[0] not in GROUP for x in r[2])]
    columns.append({"groupId": None, "title": "그룹 없음", "order": len(GROUPS) + 1, "intervalMinutes": 30,
                    "count": sum(1 for r in lost if _state(r)[0] not in CLOSED_MAINS), "capacities": [], "open": []})

    cards = []
    for r in RESERVATIONS:
        main, sub = _state(r)
        for i, (gid, start, minutes) in enumerate(r[2]):
            cards.append({"reservationId": r[0], "resourceIndex": i, "groupId": gid if gid in GROUP else None,
                          "zoneId": r[3], "start": at(start), "end": at(_hm(_minutes(start) + minutes)),
                          "customer": _card_customer(r[1]), "state": {"main": main, "sub": sub},
                          "paymentRequiredCount": r[8], "draggable": main in ("reserved", "reception")})
    order = {g[0]: g[0] for g in GROUPS}
    cards.sort(key=lambda c: (order.get(c["groupId"], 99), c["start"], c["reservationId"]))

    counts = {m: 0 for m in ("reserved", "reception", "consultation", "procedure", "home", "canceled", "noshow")}
    for r in RESERVATIONS:
        counts[_state(r)[0]] += 1
    counts["total"] = sum(1 for r in RESERVATIONS if _state(r)[0] not in CLOSED_MAINS)

    clinic = None
    if day == today:
        items = [r for r in RESERVATIONS if r[5] in IN_CLINIC and _state(r)[0] not in CLOSED_MAINS]
        items.sort(key=lambda r: (r[3], _minutes(r[2][0][1]), r[0]))
        ccounts = {"all": len(items), "reception": 0, "consultation": 0, "procedure": 0, "home": 0}
        for r in items:
            ccounts[_state(r)[0]] += 1
        clinic = {"counts": ccounts, "items": [{
            "reservationId": r[0], "zoneId": r[3],
            "customer": {"name": CUST[r[1]][1], "phoneticName": CUST[r[1]][2], "nationality": CUST[r[1]][4]},
            "state": dict(zip(("main", "sub"), _state(r), strict=True)),
            "receptionAt": at(_hm(_minutes(r[2][0][1]) - 10)), "paymentRequiredCount": r[8], "amount": _amount(r)}
            for r in items]}

    return ReservationBoard.model_validate({
        "date": day.isoformat(), "isToday": day == today, "now": iso(now),
        "sync": {"lastOkAt": iso(now - timedelta(seconds=4)), "lastError": None},
        "axis": {"start": AXIS[0], "end": AXIS[1]},
        "zones": ZONES, "columns": columns, "cards": cards, "slots": slots, "rows": rows, "counts": counts,
        "notices": [{"id": 1, "content": "공지 예시입니다.\n오후 2시 레이저실 점검이 있어요.", "releasedAt": at("09:30")}],
        "requests": [], "clinic": clinic,
    })


# ------------------------------------------------------------------ 상세(§7.3)
def _personal(c, *, empty_identity: bool) -> dict:
    foreign = c[4] != "KR"
    return {
        "name": c[1], "phoneticName": c[2], "gender": c[3], "dateOfBirth": c[7],
        "registrationNumber": None if (foreign or empty_identity) else "000000-0000000",
        "passportNumber": "X00000000" if foreign else None,
        "passportSurname": "CUSTOMER" if foreign else None, "passportGivenNames": None,
        "passportExpiryDate": "2030-01-01" if foreign else None, "foreignRegistrationNumber": None,
        "nationality": c[4], "language": "ja" if c[4] == "JP" else None,
        "phone": {"countryCode": "+81" if foreign else "+82", "number": "0000000000"}, "additionalPhone": None,
        "email": None, "sns": {"type": "line", "accountId": "example"} if foreign else None,
        "address": {"address": "주소 예시", "detailed": None, "zipCode": None} if not foreign else None,
    }


def _identity(c, personal: dict | None, confirmed: bool, now: datetime) -> dict:
    foreign = c[4] != "KR"
    if personal is None:
        fields = []
    elif foreign:
        fields = [{"key": "passportSurname", "label": "여권 영문명",
                   "filled": bool(personal["passportSurname"] or personal["passportGivenNames"])},
                  {"key": "dateOfBirth", "label": "생년월일", "filled": bool(personal["dateOfBirth"])},
                  {"key": "passportNumber", "label": "여권번호", "filled": bool(personal["passportNumber"])}]
    else:
        fields = [{"key": "dateOfBirth", "label": "생년월일", "filled": bool(personal["dateOfBirth"])},
                  {"key": "registrationNumber", "label": "주민등록번호", "filled": bool(personal["registrationNumber"])}]
    return {"status": "confirmed" if confirmed else "unconfirmed",
            "checkedAt": iso(now - timedelta(minutes=30)) if confirmed else None,
            "checkedBy": "데스크 1" if confirmed else None, "method": "web_manual" if confirmed else None,
            "kind": "foreign" if foreign else "domestic", "fields": fields,
            "complete": bool(fields) and all(f["filled"] for f in fields)}


HEALTH_Q = ["복용 중인 약", "알레르기", "임신 · 수유", "피부 질환", "최근 시술", "켈로이드", "기타 질환"]


def _health(rid: int, now: datetime) -> dict:
    if rid in (1, 12, 14):  # 제출본 없음
        return {"state": "none", "submittedAt": None, "needCount": 0, "items": [
            {"title": q, "answer": None, "memo": None, "needsCheck": False, "empty": True} for q in HEALTH_Q]}
    if rid == 16:  # KOS 읽기 실패
        return {"state": "error", "submittedAt": None, "needCount": 0, "items": []}
    items = []
    for i, q in enumerate(HEALTH_Q):
        if i == 1:
            items.append({"title": q, "answer": "있음 · 꽃가루", "memo": "봄철", "needsCheck": True, "empty": False})
        elif i == 6:
            items.append({"title": q, "answer": None, "memo": None, "needsCheck": False, "empty": True})
        else:
            items.append({"title": q, "answer": "없음" if i % 2 else "아니오", "memo": None, "needsCheck": False, "empty": False})
    return {"state": "ok", "submittedAt": iso(now - timedelta(days=1)), "needCount": 1, "items": items}


def _previous(c, day: date) -> list[dict]:
    if c[5]:  # 초진
        return []
    prev = day - timedelta(days=40)
    older = day - timedelta(days=120)
    return [
        {"date": prev.isoformat(), "start": iso(at_hhmm(prev, "14:00")), "result": "completed", "resultRaw": "COMPLETED",
         "zoneTitle": "4층", "groupTitle": "레이저", "reservationMemo": "지난 예약 메모 예시",
         "consultationMemo": "상담 메모 예시",
         "procedures": [{"title": "레이저 토닝", "status": "DONE", "doctors": ["원장 1"]},
                        {"title": "진정 관리", "status": "DONE", "doctors": []}]},
        {"date": older.isoformat(), "start": iso(at_hhmm(older, "11:00")), "result": "noshow", "resultRaw": "NO_SHOW",
         "zoneTitle": "4층", "groupTitle": "일본", "reservationMemo": None, "consultationMemo": None, "procedures": []},
    ]


def detail(now: datetime, reservation_id: int) -> ReservationDetail:
    r = RESV.get(reservation_id)
    if r is None:
        raise NotFound("없는 예약이에요")
    rid, cid, resources, zone, status, flow, consult, room_id, pay, memo = r
    c = CUST[cid]
    day = now.astimezone(KST).date()
    main, sub = _state(r)
    g0, s0, m0 = resources[0]

    def at(value: str) -> str:
        return iso(at_hhmm(day, value))

    personal = None if rid == 17 else _personal(c, empty_identity=rid == 2)
    identity = _identity(c, personal, confirmed=rid in (3, 4, 5, 6), now=now)
    resume = flow == "RECEPTION"
    new = main in ("reserved", "noshow")
    receive_mode = "resume" if resume else ("new" if new else None)
    locked = resume and room_id is not None

    busy = {x[7] for x in RESERVATIONS if x[5] in BUSY_FLOWS and _state(x)[0] not in CLOSED_MAINS and x[7]}
    rooms = []
    if receive_mode:
        rooms = [{"roomId": i, "title": t, "busy": i in busy and i != room_id, "selected": i == room_id and locked}
                 for i, t in ROOMS[zone]]

    after = main not in ("reserved", "canceled", "noshow")
    flow_obj = None
    if after:
        cons = None
        if consult:
            cons_state = {"CONSULTATION_WAITING": "waiting", "CONSULTATION": "doing"}.get(flow, "none" if resume else "done")
            counselor = {"staffId": 21, "name": "상담사 1"} if flow in ("CONSULTATION", "PROCEDURE", "COMPLETED") else None
            cons = {"state": cons_state, "counselor": counselor,
                    "since": at(_hm(_minutes(s0) + 5)) if cons_state == "doing" else None,
                    "calledAt": at(_hm(_minutes(s0) + 2)) if counselor else None,
                    "calledBy": "데스크 1" if counselor else None}
        proc = {"PROCEDURE_WAITING": "waiting", "PROCEDURE": "doing", "PROCEDURE_DONE": "done", "COMPLETED": "done"}
        home = {"PROCEDURE_DONE": "waiting", "COMPLETED": "done"}
        flow_obj = {"receptionAt": at(_hm(_minutes(s0) - 10)), "roomTitle": ROOM_TITLE.get(room_id) if room_id else None,
                    "receptionBy": "데스크 1" if rid != 3 else None, "consultation": cons,
                    "stages": {"procedure": proc.get(flow, "none"), "home": home.get(flow, "none")}}

    settlement = None
    if main == "home":
        settlement = {"paymentRequiredCount": pay, "amount": _amount(r), "prescriptionCount": 1 if rid == 8 else 0,
                      "links": {"purchase": "about:blank#tab=purchase",
                                "prescription": "about:blank#tab=etceteraWork"}}

    counselors = []
    if flow_obj and flow_obj["consultation"] is not None:
        counselors = [{"staffId": 21, "name": "상담사 1", "busyRoom": "A-룸2"},
                      {"staffId": 22, "name": "상담사 2", "busyRoom": None},
                      {"staffId": 23, "name": "상담사 3", "busyRoom": None}]

    ident_ok = identity["complete"]
    can = {
        "cancel": main == "reserved",
        "editRoute": main in ("reserved", "noshow") and not c[5],  # 추가 지시 1 W4
        "receive": bool(resume or (new and ident_ok and personal is not None)),
        "callCounselor": flow in ("CONSULTATION_WAITING", "CONSULTATION"),
        "discharge": flow == "PROCEDURE_DONE" and pay == 0,
        "editMemo": main != "canceled" and flow != "COMPLETED",  # §5.14 · r1 W1
        "editPersonal": True, "editRemark": True,
        "confirmIdentity": identity["status"] == "unconfirmed",
        "unconfirmIdentity": identity["status"] == "confirmed" and not any(  # 고객 단위(r1 W4)
            x[1] == cid and _state(x)[0] not in ("reserved", "noshow", "canceled") for x in RESERVATIONS),
    }
    end = _hm(_minutes(resources[-1][1]) + resources[-1][2])
    return ReservationDetail.model_validate({
        "reservationId": rid, "day": day.isoformat(), "start": at(s0), "end": at(end),
        "groupTitle": GROUP[g0][1] if g0 in GROUP else None, "zoneId": zone, "zoneTitle": ZONE_TITLE[zone],
        "state": {"main": main, "sub": sub},
        "customer": {
            "customerId": cid, "name": c[1], "phoneticName": c[2], "gender": c[3], "nationality": c[4], "isNew": c[5],
            "chartNumber": c[6], "age": _age(c[7], day), "personal": personal,
            "personalError": "HTTP 500 InternalServerError" if personal is None else None,
            "remark": "고객 공통 메모 예시" if rid % 3 == 0 else None, "identity": identity},
        "reservation": {"consultationRequired": consult, "sedationRequired": rid % 4 == 0, "memo": memo,
                        "funnel": {"name": "인스타그램", "detail": "광고 보고 옴"} if rid % 2 else None,
                        "connectedChannel": None,
                        "counselor": {"staffId": 21, "name": "상담사 1"} if rid in (1, 5) else None,
                        "assignee": {"name": SYSTEM[1]}, "doctors": [{"name": "원장 1"}] if rid % 2 else [],
                        "desiredDischargeAt": at("17:30") if rid == 1 else None},
        "health": _health(rid, now), "previousVisits": _previous(c, day), "flow": flow_obj, "settlement": settlement,
        "rooms": rooms, "roomLocked": locked, "receiveMode": receive_mode, "counselors": counselors, "can": can,
    })


def _age(birth: str | None, day: date) -> int | None:
    if not birth:
        return None
    b = date.fromisoformat(birth)
    return day.year - b.year - ((day.month, day.day) < (b.month, b.day))


# ------------------------------------------------------------------ 등록 모달 · 검색(§7.4)
def form(now: datetime, date_value: str | None, group_id: int | None, start: str | None) -> ReservationForm:
    parse_day(date_value, now)
    caps = GROUP[group_id][3] if group_id in GROUP else None
    zones = []
    for z in ZONES:
        available = True
        if caps is not None:
            available = z["zoneId"] in caps
            if available and start:
                line = _start_hhmm(start)
                available = _count_at(group_id, z["zoneId"], line, GROUP[group_id][2]) < caps[z["zoneId"]]
        zones.append({"zoneId": z["zoneId"], "title": z["title"], "available": available})
    default = next((z["zoneId"] for z in zones if z["available"]), None)
    return ReservationForm.model_validate({
        "staff": [{"staffId": i, "name": n} for i, n in STAFF], "defaultAssigneeStaffId": SYSTEM[0],
        "doctors": [{"staffId": i, "name": n} for i, n in DOCTORS],
        "counselors": [{"staffId": i, "name": n} for i, n in COUNSELORS],
        "funnels": [{"funnelId": i, "name": n} for i, n in FUNNELS], "zones": zones, "defaultZoneId": default})


def _start_hhmm(value: str) -> str:
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        raise BadRequest("invalid_request", "start: ISO 시각이어야 해요") from None
    return hhmm(at if at.tzinfo else at.replace(tzinfo=KST))


def search(name: str | None, phone: str | None, birth: str | None, chart: str | None, page: int) -> CustomerSearch:
    if not any(v and v.strip() for v in (name, phone, birth, chart)):
        raise BadRequest("invalid_request", "검색 조건을 하나 이상 넣어 주세요")
    if page < 1:
        raise BadRequest("invalid_request", "page: 1 이상이어야 해요")
    found = [c for c in (*CUSTOMERS, *SEARCH_EXTRA)
             if (not name or name.strip().lower() in c[1].lower())
             and (not chart or (c[6] or "") == chart.strip())
             and (not birth or c[7] == birth.strip())]
    items = [{"customerId": c[0], "chartNumber": c[6], "name": c[1], "phoneticName": c[2], "dateOfBirth": c[7],
              "nationality": c[4], "isNew": c[5]} for c in found[(page - 1) * 20: page * 20]]
    return CustomerSearch.model_validate({"items": items, "total": len(found), "page": page, "pageSize": 20})
