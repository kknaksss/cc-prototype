"""가짜 KOS — HAR · 공개 API 모양만 맞춘 값(id · 이름 · 키 전부 지어냄). httpx.MockTransport 로 붙인다."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Settings

OPEN = "https://open.fake.test"
INTERNAL = "https://internal.fake.test"
TENANT = "tenant-x"
ZONE = "zone-4"
ZONE2 = "zone-5"
SYSTEM = "sys-0"


def kos_settings(tmp_path, **kw) -> Settings:
    base = dict(_env_file=None, proc_db_path=str(tmp_path / "k.db"), kos_open_api_base=OPEN, kos_open_api_key="fake-key",
                kos_internal_api_base=INTERNAL, kos_tenant_id=TENANT, kos_system_email="sys@fake.test",
                kos_system_password="fake-pw", kos_zone_id=ZONE, kos_exclude_account_ids="anes-0")
    base.update(kw)
    return Settings(**base)


def task(seq, type_="PROCEDURE", status="NOT_STARTED", **kw):
    t = {"type": type_, "sequence": seq, "order": seq, "title": f"작업{seq}", "status": status, "paymentRequired": False,
         "assignees": [], "doctors": [], "room": None, "doctorCallDateTime": None, "completedDateTimeUtc": None,
         "roomAssignedDateTimeUtc": None, "doctorAssignedDateTimeUtc": None, "memo": "저장 안 함"}
    t.update(kw)
    return t


def schedule(n, flow="PROCEDURE_WAITING", room=True, procs=2, memo="메모"):
    tasks = [task(i + 1) for i in range(procs)]
    if room:
        tasks.append(task(procs + 1, "ETCETERA", "READY", title="방 배정",
                          room={"id": f"room-{n}", "zoneId": ZONE, "title": f"A-룸{n}", "order": n},
                          roomAssignedDateTimeUtc="2026-10-21T01:00:00Z"))
    return {"id": f"sch-{n}", "flowStep": flow, "flowStepUpdatedDateTimeUtc": "2026-10-21T01:00:00Z",
            "updatedDateTimeUtc": "2026-10-21T01:00:00Z", "orderMemo": memo, "zone": {"id": ZONE, "title": "4층"},
            "visitor": {"id": f"vis-{n}", "name": f"고객{n}", "phoneticName": None, "nationality": "KR", "isNew": True,
                        "chartNumber": f"C{n}", "phone": {"phoneNumber": "저장 안 함"}, "memo": "저장 안 함"},
            "tasks": tasks}


# ------------------------------------------------------------------ 예약 현황(SPEC-005) — 모양 = WP-KOS K1 실제
# 제출본 최상위 · 없음 400 + errorProperties · room:{id:""} · 밀리초 없는 시각 · 빈 칸 키 없음 · 구역 2
RESV_NAMES = {
    "get-zones", "get-reservation-groups", "get-codes", "get-etcetera-tasks", "get-schedules-for-reservation",
    "get-reservation-slots-by-groups", "get-notices", "get-purchase-summaries", "get-visitor", "get-visitors",
    "get-visitor-questionnaire", "get-questionnaire-submit", "get-schedules-by-visitor", "get-schedule-detail",
    "find-duplicated-visitor", "create-visitor", "reserve", "update-reservation", "cancel-reservation",
    "change-reservation-memo", "update-visitor-personal-information", "update-visitor-management-information",
    "recept", "add-flow-tasks", "change-content", "create-notice", "delete-notice",
    "get-questionnaire-agreements", "submit-visitor-questionnaire",  # 앱 문진(SPEC-004 §6.15)
    "generate-uploading-url", "register-visitor-images",  # 앱 여권 사진(SPEC-004 §6.16 ④-c)
    "get-visitor-images", "delete-visitor-images",  # 사진 삭제(E2E batch 3 #1)
}
DAY = datetime(2026, 10, 21, tzinfo=UTC)  # 시험 날짜(수요일) — KST 하루 = 전날 15:00Z ~ 15:00Z


def z(at: datetime) -> str:
    """KOS 가 주는 꼴 — 밀리초 없음(WP-KOS 주의 5)."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def kst(hh: int, mm: int = 0, day: datetime = DAY) -> datetime:
    return day.replace(hour=0, minute=0) + timedelta(hours=hh - 9, minutes=mm)


def _time(h: int) -> str:
    return f"2026-08-10T{h - 9:02d}:00:00Z"


def group(gid, title, order, interval, caps, brk=False, sunday=False):
    day = {"enabled": True, "startTime": _time(10), "endTime": _time(20),
           "breaktime": {"startTime": _time(13), "endTime": _time(14)} if brk else None}
    table = {d: deepcopy(day) for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday")}
    table["sunday"] = deepcopy(day) if sunday else {"enabled": False}
    return {"id": gid, "title": title, "memo": "", "startDate": "2026-01-01", "intervalMinutes": interval, "order": order,
            "intervalCapacities": [{"zoneId": zid, "enabled": cap is not None, "intervalCapacity": cap or 0}
                                   for zid, cap in caps.items()],
            "isDefault": False, "sameDayCloseBufferMinutes": 0, "operationTimetable": table}


def visitor(vid, name="고객", nationality="JP", **kw):
    """get-visitor data — 빈 칸은 키 자체가 없다(K1)."""
    v = {"id": vid, "name": name, "phoneticName": "コキャク", "gender": "FEMALE", "nationality": nationality,
         "language": "ja", "isNew": False, "chartNumber": f"C-{vid}", "dateOfBirth": "1990-01-02 00:00:00.000Z",
         "passportNumber": "X1234567", "passportSurname": "KOKYAKU",
         "address": {"address": "", "detailedAddress": "", "zipCode": ""}, "memo": "특이 메모",
         "visitorFunnel": {"funnelId": "", "funnelDetail": ""}, "aggrementPersonalInformation": False,
         "aggrementAdvertisements": False, "agreementInformationalNotification": True,
         "visitorType": {"id": "vt-1", "name": "기본"}, "visitorCategories": [], "doctor": {"id": "", "name": ""},
         "counselor": {"id": "", "name": ""}}
    v.update(kw)
    return {k: x for k, x in v.items() if x is not None}


def rtask(seq, type_="PROCEDURE", status="NOT_STARTED", room=None, paid=False, title=None, assigned=None):
    return {"type": type_, "sequence": seq, "title": title or f"시술{seq}", "status": status, "paymentRequired": paid,
            "room": room or {"id": "", "zoneId": "", "title": "", "order": 0},
            "roomAssignedDateTimeUtc": assigned, "doctors": []}


def resv(sid, vid="vis-1", *, grp="grp-1", start=None, minutes=30, flow="RESERVED", status="RESERVED", zone=ZONE,
         tasks=None, consult=True, name="고객", nationality="JP", is_new=False, gender="FEMALE", purchases=(), memo="예약 메모",
         resources=None, counselor=None):
    """get-schedules-for-reservation data[] 한 건."""
    start = start or kst(11)
    res = resources or [(grp, start, minutes)]
    occupied = [{"id": f"{sid}-r{i}", "type": "RESERVATION_GROUP",
                 "reservationTime": {"startDateTimeUtc": z(s), "endDateTimeUtc": z(s + timedelta(minutes=m))},
                 "reservationGroup": {"reservationGroupId": g, "zoneId": zone, "doctors": [{"id": "doc-a", "name": "가 원장"}]}}
                for i, (g, s, m) in enumerate(res)]
    return {"id": sid, "flowStep": flow, "flowStepUpdatedDateTimeUtc": z(start), "receptionDateTimeUtc": None,
            "updatedDateTimeUtc": z(start), "zone": {"id": zone, "title": "4층" if zone == ZONE else "미사용"},
            "visitor": {"id": vid, "name": name, "phoneticName": "コキャク", "gender": gender, "nationality": nationality,
                        "isNew": is_new, "chartNumber": None if is_new else f"C-{vid}"},
            "reservation": {"status": status, "consultationRequired": consult, "sedationRequired": False,
                            "counselor": counselor or {"id": "", "name": ""}, "doctor": {"id": "", "name": ""},
                            "reservationAssignee": {"id": SYSTEM, "name": "시스템"}, "reservationMemo": memo,
                            "funnel": {"funnelDetail": ""}, "connectedChannel": "", "reservationGroupId": res[0][0],
                            "startDateTime": z(start), "endDateTime": z(start + timedelta(minutes=minutes)), "zoneId": zone,
                            "requestedProcedures": []},
            "occupiedResources": occupied, "purchaseIds": list(purchases), "prescriptionIds": [], "tasks": tasks or []}


def _public(items):
    return [{k: v for k, v in deepcopy(x).items() if k != "listed"} for x in items]


class ResvFake:
    """FakeKos 의 예약 현황 몫 — 상태를 리스트 · dict 로 들고, 쓰기를 반영한다."""

    def __init__(self):
        self.zones = [{"id": ZONE, "title": "4층", "order": 1, "isDefault": True},
                      {"id": ZONE2, "title": "미사용", "order": 2, "isDefault": False}]
        self.groups = [group("grp-1", "일본", 1, 30, {ZONE: 3, ZONE2: None}, brk=True),
                       group("grp-2", "리프팅", 2, 60, {ZONE: 2, ZONE2: None}),
                       group("grp-3", "제모", 3, 15, {ZONE: 3, ZONE2: 3})]
        self.rooms2 = [{"id": "room-b1", "zoneId": ZONE2, "title": "B-룸1", "order": 1}]
        self.funnels = [{"id": "fn-1", "category": "FUNNEL", "name": "인스타그램", "order": 1, "closed": False, "default": False},
                        {"id": "fn-2", "category": "FUNNEL", "name": "닫힌 코드", "order": 2, "closed": True, "default": False}]
        self.etc_tasks = [{"id": "etc-room", "title": "방 배정", "deleted": False, "translsMap": {}},
                          {"id": "etc-other", "title": "시트팩", "deleted": False, "translsMap": {}}]
        self.resv: list[dict] = []
        self.history: list[dict] = []  # 다른 날 일정(이전 방문)
        self.notices = [{"id": "ntc-1", "content": "공지 예시", "releaseDateTimeUtc": z(kst(9)), "deleted": False}]
        self.visitors: dict[str, dict] = {"vis-1": visitor("vis-1")}
        self.form = {"name": "", "pages": [{"id": "p1", "title": "기본 정보", "questions": []},
                                           {"id": "p2", "title": "건강 정보", "questions": [
                                               {"questionId": f"q{i}", "title": f"질문{i}", "sequence": i, "answers": []}
                                               for i in range(1, 4)]}]}
        self.submits: dict[str, dict] = {}
        self.agreements = [{"id": "ag-1", "title": "개인정보 수집 동의", "link": "", "required": True,
                            "type": "PERSONAL_INFORMATION", "translsMap": {"title": {"translation": {"ja": "同意", "en": "Agree",
                                                                                                      "zh": "同意"}}}}]
        self.submitted: list[dict] = []  # 받은 문진 제출 본문
        # 이미지 장비 코드(WP-KOS K3 모양 · id 지어냄) · 받은 presigned PUT · 등록
        self.equipment = [{"id": "eq-1", "category": "IMAGE_EQUIPMENT", "name": "태블릿", "order": 0, "closed": False,
                           "default": False},
                          {"id": "eq-2", "category": "IMAGE_EQUIPMENT", "name": "DSLR", "order": 2, "closed": False,
                           "default": True}]
        self.image_categories = [{"id": "ic-1", "category": "IMAGE_CATEGORY", "name": "시술 전", "order": 0, "closed": False,
                                   "default": False},
                                  {"id": "ic-2", "category": "IMAGE_CATEGORY", "name": "시술 후", "order": -1, "closed": False,
                                   "default": False}]  # 데모 지점 꼴(「여권」 없음)
        self.uploads: list[dict] = []  # {url, content, contentType}
        self.registered: list[dict] = []
        self.images: list[dict] = []  # KOS 고객 이미지(등록 · 삭제 반영)
        self.deleted_images: list[list[str]] = []  # 받은 delete-visitor-images ids
        self.submit_at = "2026-10-21T02:05:00Z"  # 다음 제출본 createdDateTimeUtc
        self.keep_first_submit = False  # 실 KOS 꼴 — 다시 제출해도 제출본 읽기는 첫 제출본(데모 2026-10-28)
        self.purchases: dict[str, dict] = {}
        self.delay: dict[str, int] = {}  # 쓰기 이름 → 그 결과가 보이기까지 get-schedule-detail 읽기 수
        self._pending: list[list] = []  # [남은 읽기, 적용 함수]
        self.resv_fail: dict[str, tuple[int, dict]] = {}  # 이름 → (상태, 본문) — 한 번만이 아니라 계속
        self._new = 0

    def _resv_sch(self, sid):
        return next((x for x in self.resv if x["id"] == sid), None)

    def add_resv(self, *a, **kw) -> dict:
        x = resv(*a, **kw)
        self.resv.append(x)
        return x

    def _later(self, name, fn) -> None:
        n = self.delay.get(name, 0)
        if n <= 0:
            fn()
        else:
            self._pending.append([n, fn])

    def _tick_reads(self) -> None:
        for item in list(self._pending):
            item[0] -= 1
            if item[0] <= 0:
                item[1]()
                self._pending.remove(item)

    def resv_handle(self, name, body, kind):  # noqa: C901 — 가짜 KOS 분기
        if name in self.resv_fail:
            status, payload = self.resv_fail[name]
            return httpx.Response(status, json=payload)
        ok = httpx.Response(200, json={})
        if name == "get-zones":
            return httpx.Response(200, json={"data": deepcopy(self.zones)})
        if name == "get-reservation-groups":
            return httpx.Response(200, json={"data": deepcopy(self.groups)})
        if name == "get-codes":
            codes = {"FUNNEL": self.funnels, "IMAGE_EQUIPMENT": self.equipment,
                     "IMAGE_CATEGORY": self.image_categories}.get(body.get("category"), [])
            return httpx.Response(200, json={"data": deepcopy(codes)})
        if name == "generate-uploading-url":
            return httpx.Response(200, json={"data": f"https://s3.fake.test/bucket/{body['fileName']}?X-Amz-Signature=sig"})
        if name == "register-visitor-images":
            self.registered.append(deepcopy(body))
            for img in body["images"]:
                self.images.append({"id": f"img-{len(self.images) + 1}", "visitorId": img["visitorId"],
                                    "scheduleId": img.get("scheduleId", ""), "fileName": img["fileName"], "deleted": False})
            return ok
        if name == "get-visitor-images":
            out = [deepcopy(x) for x in self.images if x["visitorId"] == body.get("visitorId")
                   and ("scheduleId" not in body or x["scheduleId"] == body["scheduleId"])
                   and (body.get("deleted") is None or x["deleted"] == body["deleted"])]
            return httpx.Response(200, json={"data": out})
        if name == "delete-visitor-images":
            self.deleted_images.append(list(body.get("ids") or []))
            for x in self.images:
                if x["id"] in (body.get("ids") or []):
                    x["deleted"] = True
            return ok
        if name == "get-etcetera-tasks":
            return httpx.Response(200, json={"data": deepcopy(self.etc_tasks)})
        if name == "get-schedules-for-reservation":
            lo = datetime.fromisoformat(body["baseDateUtc"].replace("Z", "+00:00"))
            hi = lo + timedelta(days=1)
            out = [x for x in self.resv if x.get("listed", True) and lo <= _start(x) < hi]
            return httpx.Response(200, json={"data": _public(out)})
        if name == "get-reservation-slots-by-groups":
            return httpx.Response(200, json={"data": self._slots(body)})
        if name == "get-notices":
            lo, hi = _rng(body)
            return httpx.Response(200, json={"data": [deepcopy(n) for n in self.notices
                                                      if not (n["deleted"] and body.get("deleted") is False)
                                                      and lo <= datetime.fromisoformat(n["releaseDateTimeUtc"]
                                                                                     .replace("Z", "+00:00")) < hi]})
        if name == "get-purchase-summaries":
            return httpx.Response(200, json={"data": [deepcopy(self.purchases[i]) for i in body["purchaseIds"]
                                                      if i in self.purchases]})
        if name == "get-visitor":
            v = self.visitors.get(body.get("id"))
            return httpx.Response(200, json={"data": deepcopy(v)}) if v else httpx.Response(
                400, json={"className": "InvalidRequestException", "errorProperties": [{"key": "id", "reason": "NotFound"}]})
        if name == "get-visitors":
            q = (body.get("visitorName") or "").lower()
            found = [v for v in self.visitors.values() if q in v["name"].lower()]
            if body.get("chartNumber"):
                found = [v for v in found if v.get("chartNumber") == body["chartNumber"]]
            page, size = body.get("indexOfPage", 0), body.get("countInPage", 20)
            return httpx.Response(200, json={"data": deepcopy(found[page * size:(page + 1) * size]), "count": len(found)})
        if name == "get-visitor-questionnaire":
            return httpx.Response(200, json=deepcopy(self.form))
        if name == "get-questionnaire-agreements":
            return httpx.Response(200, json={"data": deepcopy(self.agreements)})
        if name == "submit-visitor-questionnaire":  # 공개 제출 — 고객 값을 바꾼다(AK§5.3 · 휴대폰 맨 앞 0 뺌)
            self.submitted.append(deepcopy(body))
            v = self.visitors[body["visitorId"]]
            d = body["dateOfBirth"]
            v.update({"gender": body["gender"], "dateOfBirth": f"{d[:4]}-{d[4:6]}-{d[6:]} 00:00:00.000Z",
                      "phoneNumber": {"countryCode": body["phone"]["countryCode"],
                                      "phoneNumber": body["phone"]["phoneNumber"].lstrip("0")},
                      "address": {"address": body.get("address", ""), "detailedAddress": body.get("addressDetail", ""),
                                  "zipCode": ""}})
            if self.keep_first_submit and body["visitorId"] in self.submits:
                return httpx.Response(200, json={"questionnaireId": f"qn-{len(self.submitted)}"})
            self.submits[body["visitorId"]] = {
                "createdDateTimeUtc": self.submit_at, "visitorName": body["name"],
                "answers": [{"seq": "", "questionId": a["parentQuestionId"], "questionTitle": a["parentQuestionTitle"],
                             "answerId": a["id"], "answerTitle": a["title"], "memo": a.get("inputText") or a.get("subText")}
                            for a in body["answers"]]}
            return httpx.Response(200, json={"questionnaireId": f"qn-{len(self.submitted)}"})
        if name == "get-questionnaire-submit":
            sub = self.submits.get(body.get("visitorId"))
            if sub is None:
                return httpx.Response(400, json={"className": "com.x.InvalidRequestException", "message": "x",
                                                 "errorProperties": [{"key": "visitorId", "reason": "NotFound", "value": "v"}]})
            return httpx.Response(200, json=deepcopy(sub))
        if name == "get-schedules-by-visitor":
            vid = body.get("visitorId")
            out = [x for x in [*self.resv, *self.history] if x["visitor"]["id"] == vid]
            return httpx.Response(200, json={"data": _public(out)})
        if name == "get-schedule-detail":
            self._tick_reads()
            x = self._resv_sch(body.get("scheduleId"))
            return httpx.Response(200, json={"data": _public([x])[0]}) if x else httpx.Response(  # 실 KOS = 404(b2 #2)
                404, json={"className": "com.x.NotFoundException"})
        if name == "find-duplicated-visitor":
            for v in self.visitors.values():
                if v["name"] == body.get("name") and body.get("birthDateUtc") and v.get("dateOfBirth"):
                    return httpx.Response(200, json={"data": deepcopy(v)})
            return ok
        if name == "create-visitor":
            self._new += 1
            vid = f"vis-new-{self._new}"
            v = {k: x for k, x in body.items() if x not in (None, "")}
            self.visitors[vid] = {"id": vid, "isNew": True, **v}
            return httpx.Response(200, json={"data": {"id": vid}})
        if name == "reserve":
            return self._reserve(body)
        if name in ("change-content", "create-notice", "delete-notice"):
            return self._notice(name, body)
        sch = self._resv_sch(body.get("scheduleId") or body.get("id"))
        if name in ("update-visitor-personal-information", "update-visitor-management-information"):
            v = self.visitors[body["id"]]
            v.update({k: x for k, x in body.items() if k != "id"})
            return ok
        if sch is None:
            return httpx.Response(400, json={"className": "InvalidRequestException"})
        if name == "update-reservation":
            self._update(sch, body)
        elif name == "cancel-reservation":
            sch["reservation"]["status"] = body["reason"]
        elif name == "change-reservation-memo":
            sch["reservation"]["reservationMemo"] = body["memo"]
        elif name == "recept":
            def f():
                sch["flowStep"] = "RECEPTION"
                sch["reservation"]["status"] = "IN_PROGRESS"
                sch["receptionDateTimeUtc"] = z(kst(11))
            self._later(name, f)
        elif name == "add-flow-tasks":
            def f():
                for t in body["tasks"]:
                    seq = max([x["sequence"] for x in sch["tasks"]] or [0]) + 1
                    sch["tasks"].append(rtask(seq, "ETCETERA", title=t["title"]))
            self._later(name, f)
        elif name == "change-tasks-room":
            room = next(r for r in [*self.rooms, *self.rooms2] if r["id"] == body["roomId"])

            def f():
                for t in sch["tasks"]:
                    if t["sequence"] in body["sequences"]:
                        t["room"] = deepcopy(room)
                        t["status"] = "READY"
                        t["roomAssignedDateTimeUtc"] = z(kst(11, 1))
            self._later(name, f)
        elif name == "change-flow-step":
            if body["step"] == "COMPLETED" and any(t["paymentRequired"] and t["status"] != "CANCELED" for t in sch["tasks"]):
                return httpx.Response(400, json={"className": "InvalidRequestException"})

            def f():
                sch["flowStep"] = body["step"]
                if body["step"] == "COMPLETED":
                    sch["reservation"]["status"] = "COMPLETED"
            self._later(name, f)
        return ok

    def _notice(self, name, body):
        """공지 쓰기(notice 리포트 §1 · §2 — 데모 실호출 모양). 지우기 = 소프트 삭제 · 빈 고치기는 거절."""
        if name == "create-notice":
            self._new += 1
            n = {"id": f"ntc-new-{self._new}", "content": body["content"],
                 "releaseDateTimeUtc": body["releaseDateTimeUtc"].replace(".000Z", "Z"), "deleted": False}
            self.notices.append(n)
            return httpx.Response(200, json={"data": deepcopy(n)})
        n = next((x for x in self.notices if x["id"] == body.get("id") and not x["deleted"]), None)
        if n is None or (name == "change-content" and not (body.get("content") or "").strip()):
            return httpx.Response(400, json={"className": "InvalidRequestException",
                                             "errorProperties": [{"key": "content" if n else "id", "reason": "NotAvailable"}]})
        if name == "change-content":
            n["content"] = body["content"]
        else:
            n["deleted"] = True
        return httpx.Response(200, json={})

    def _reserve(self, body):
        self._new += 1
        sid = f"rsv-new-{self._new}"
        v = self.visitors[body["visitorId"]]
        o = body["occupiedResources"][0]
        start = datetime.fromisoformat(o["reservationTime"]["startDateTimeUtc"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(o["reservationTime"]["endDateTimeUtc"].replace("Z", "+00:00"))
        x = resv(sid, v["id"], grp=o["reservationGroup"]["reservationGroupId"], start=start,
                 minutes=int((end - start).total_seconds() // 60), zone=body["zoneId"], name=v["name"],
                 nationality=v.get("nationality"), is_new=bool(v.get("isNew")), consult=body.get("consultationRequired", False),
                 memo=body.get("reservationMemo"))
        x["occupiedResources"][0]["id"] = o["id"]
        x["occupiedResources"][0]["reservationGroup"]["doctors"] = o["reservationGroup"]["doctors"]
        x["reservation"].update({"sedationRequired": body.get("sedationRequired", False),
                                 "counselor": body.get("counselor") or {"id": "", "name": ""},
                                 "reservationAssignee": body["reservationAssignee"],
                                 "funnel": body.get("funnel") or {"funnelDetail": ""}})
        if body.get("desiredDischargeDateTimeUtc"):
            x["reservation"]["desiredDischargeDateTimeUtc"] = body["desiredDischargeDateTimeUtc"]
        self.resv.append(x)
        return httpx.Response(200, json={"scheduleId": sid})

    def _update(self, sch, body):
        if "occupiedResources" in body:
            items = body["occupiedResources"]["items"]
            sch["occupiedResources"] = [{**o, "reservationTime": {
                k: z(datetime.fromisoformat(v.replace("Z", "+00:00"))) for k, v in o["reservationTime"].items()}}
                for o in deepcopy(items)]
            sch["reservation"]["reservationGroupId"] = items[0]["reservationGroup"]["reservationGroupId"]
        if "consultationRequired" in body:
            sch["reservation"]["consultationRequired"] = body["consultationRequired"]
        if "counselor" in body:
            sch["reservation"]["counselor"] = body["counselor"]

    def _slots(self, body):
        lo, hi = _rng(body)
        out = []
        for g in self.groups:
            if g["id"] not in body["reservationGroupIds"]:
                continue
            for cap in g["intervalCapacities"]:
                if not cap["enabled"]:
                    continue
                slots = []
                t = kst(10, day=lo + timedelta(hours=9))
                while t < kst(20, day=lo + timedelta(hours=9)):
                    e = t + timedelta(minutes=g["intervalMinutes"])
                    n = sum(1 for x in self.resv for o in x["occupiedResources"]
                            if x["reservation"]["status"] not in ("CANCELED", "NO_SHOW")
                            and o["reservationGroup"]["reservationGroupId"] == g["id"]
                            and o["reservationGroup"]["zoneId"] == cap["zoneId"]
                            and t <= _parse(o["reservationTime"]["startDateTimeUtc"]) < e)
                    slots.append({"reservationGroupId": g["id"], "zone": {"id": cap["zoneId"], "name": ""},
                                  "startDateTimeUtc": z(t), "endDateTimeUtc": z(e), "capacity": cap["intervalCapacity"],
                                  "reservationCount": n})
                    t = e
                out.append({"reservationGroupId": g["id"], "zoneId": cap["zoneId"], "slots": slots})
        return out


def _parse(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def _start(x) -> datetime:
    return min(_parse(o["reservationTime"]["startDateTimeUtc"]) for o in x["occupiedResources"])


def _rng(body):
    return _parse(body["startDateTimeUtc"]), _parse(body["endDateTimeUtc"])


class FakeKos(ResvFake):
    def __init__(self):
        self.accounts = [
            {"id": "doc-a", "name": "가 원장", "roleTags": ["DOCTOR"], "activate": True},
            {"id": "doc-b", "name": "나 원장", "roleTags": ["DOCTOR"], "activate": True},
            {"id": SYSTEM, "name": "시스템", "roleTags": ["DOCTOR", "ADMIN"], "activate": True},
            {"id": "anes-0", "name": "마취용", "roleTags": ["DOCTOR"], "activate": True},
            {"id": "nurse-0", "name": "간호", "roleTags": ["NURSE"], "activate": True},
        ]
        self.rooms = [{"id": f"room-{i}", "zoneId": ZONE, "title": f"A-룸{i}", "order": i} for i in range(1, 4)]
        self.schedules = [schedule(1)]
        self.calls: list[tuple[str, dict]] = []  # (경로, 본문)
        self.apply_writes = True  # 쓰기를 일정에 반영하나
        self.fail_paths: dict[str, int] = {}  # 경로 끝 → 돌려줄 상태 코드
        self.expire_once: set[str] = set()  # "open" / "internal" — 다음 호출 1번 401
        self.tokens_issued = {"open": 0, "internal": 0}
        ResvFake.__init__(self)

    def rooms_on_procedures(self) -> "FakeKos":
        """시술 작업에도 카드 방이 이미 들어가 있는 상태(호출 전 방 넣기 op 이 confirmed 로 건너뛰어진다)."""
        for sch in self.schedules:
            room = next((t["room"] for t in sch["tasks"] if t["type"] == "ETCETERA" and t.get("room")), None)
            for t in sch["tasks"]:
                if t["type"] == "PROCEDURE" and room:
                    t["room"] = deepcopy(room)
        return self

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def paths(self) -> list[str]:
        return [p.rsplit("/", 1)[-1] for p, _ in self.calls]

    def _sch(self, sid):
        return next(s for s in self.schedules if s["id"] == sid)

    def handle(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.url.host == "s3.fake.test":  # presigned PUT(인증 헤더 없음)
            self.uploads.append({"url": str(req.url), "content": req.content, "contentType": req.headers.get("content-type"),
                                 "auth": req.headers.get("authorization")})
            return httpx.Response(self.fail_paths.get("s3-put", 200))
        body = json.loads(req.content or b"{}")
        self.calls.append((path, body))
        name = path.rsplit("/", 1)[-1]
        if name in self.fail_paths:
            return httpx.Response(self.fail_paths[name], json={"className": "FakeError", "message": "x"})
        if name == "exchange-token":
            self.tokens_issued["open"] += 1
            return httpx.Response(200, json={"token": f"open-{self.tokens_issued['open']}"})
        if name == "sign-in":
            self.tokens_issued["internal"] += 1
            return httpx.Response(200, json={"data": {"id": "user-0", "token": f"int-{self.tokens_issued['internal']}"},
                                             "tokenExpiredDateTimeUtc": "2026-10-22T00:00:00Z"})
        kind = "open" if req.url.host == "open.fake.test" else "internal"
        auth = req.headers.get("authorization", "")
        if kind in self.expire_once:
            self.expire_once.discard(kind)
            return httpx.Response(401, json={})
        if kind == "internal" and not (auth.startswith("Bearer int-") and path.startswith(f"/tenants/{TENANT}/")):
            return httpx.Response(401, json={})
        if kind == "open" and not auth.startswith("open-"):
            return httpx.Response(401, json={})
        if name == "get-user-account":
            return httpx.Response(200, json={"data": {"id": SYSTEM, "name": "시스템"}})
        if name == "get-accounts":
            return httpx.Response(200, json={"data": deepcopy(self.accounts)})
        if name == "get-rooms":
            return httpx.Response(200, json={"data": deepcopy(self.rooms2 if body.get("zoneId") == ZONE2 else self.rooms)})
        if name == "get-schedules-grouped-by-zone":
            today = [x for x in self.resv if (x.get("zone") or {}).get("id") == ZONE and x.get("listed", True)]
            return httpx.Response(200, json={"data": [{"zone": {"id": ZONE},
                                                       "schedules": deepcopy(self.schedules) + _public(today)}]})
        if name in RESV_NAMES or (name in ("change-flow-step", "change-tasks-room")
                                  and self._resv_sch(body.get("scheduleId") or body.get("id"))):
            return self.resv_handle(name, body, kind)
        reject = self._reject(name, body)  # 실 KOS 에서 본 400(2026-10-21 데모 실호출)
        if reject:
            return httpx.Response(400, json={"className": "InvalidRequestException", "message": reject})
        if self.apply_writes:
            self._write(name, body)
        return httpx.Response(200, json={})

    def _reject(self, name: str, body: dict) -> str | None:
        sch = self._sch(body.get("scheduleId"))
        if name == "change-flow-step" and sch["flowStep"] == body.get("step"):
            return "같은 단계"
        if name == "call-tasks-doctors" and sch["flowStep"] == "PROCEDURE_DONE":
            return "귀가 대기 일정 호출"
        if name == "call-tasks-doctors" and any(not t.get("room") for t in sch["tasks"] if t["sequence"] in body["sequences"]):
            return "roomId NotFound"  # 2026-10-21 사용자 E2E — 방 없는 시술 작업 호출
        return None

    def _write(self, name: str, body: dict) -> None:
        sch = self._sch(body.get("scheduleId"))
        if name == "change-flow-step":
            sch["flowStep"] = body["step"]
            return
        tasks = [t for t in sch["tasks"] if t["sequence"] in body.get("sequences", [])]
        for t in tasks:
            if name == "cancel-flow-tasks":
                t["status"] = "CANCELED"
            elif name == "change-tasks-room":
                t["room"] = deepcopy(next(r for r in self.rooms if r["id"] == body["roomId"]))
            elif name == "change-tasks-assignees":
                t["assignees"] = [{"id": i, "name": ""} for i in body["assigneeIds"]]
            elif name == "call-tasks-doctors":
                t["status"] = "WAITING"
            elif name == "change-tasks-doctors":
                t["doctors"] = [{"id": i, "name": ""} for i in body["doctorIds"]]
                t["status"] = "READY"
            elif name == "change-tasks-complete" and body.get("complete") is False:  # 완료 풀기 — 실 KOS = READY(WP-KOS K2)
                t["status"] = "READY"
                t["completedDateTimeUtc"] = None
            elif name == "change-tasks-complete":
                t["status"] = "DONE"
                t["completedDateTimeUtc"] = "2026-10-21T02:30:00Z"
