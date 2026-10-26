"""가짜 KOS — HAR · 공개 API 모양만 맞춘 값(id · 이름 · 키 전부 지어냄). httpx.MockTransport 로 붙인다."""

import json
from copy import deepcopy

import httpx

from app.config import Settings

OPEN = "https://open.fake.test"
INTERNAL = "https://internal.fake.test"
TENANT = "tenant-x"
ZONE = "zone-4"
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


class FakeKos:
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
            return httpx.Response(200, json={"data": deepcopy(self.rooms)})
        if name == "get-schedules-grouped-by-zone":
            return httpx.Response(200, json={"data": [{"zone": {"id": ZONE}, "schedules": deepcopy(self.schedules)}]})
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
