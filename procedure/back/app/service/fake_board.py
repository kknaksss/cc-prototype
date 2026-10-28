"""WP1 가짜 스냅샷 — 계약(§7.2) 모양을 보여 주는 값. `PROC_FAKE_BOARD=1` 일 때만 쓴다(front 단독 작업용).

이름 · 방 · 메모는 전부 지어낸 값이다(KOS 값 아님). 시각은 호출한 때(now) 기준으로 만든다.
시안 장면: board · memo-expanded · call-modal(-specific) · all-done · panel-doctors · panel-customers 를 한 화면에 담는다.
"""

from datetime import datetime, timedelta

from app.domain.clock import iso
from app.schemas.board import BoardSnapshot

LONG_MEMO = (
    "왼쪽 볼 색소 위주로 진행. 지난번 시술 후 홍조가 있었으니 출력 낮춰서 시작. 마취크림 30분 이상. "
    "시술 후 진정관리 포함, 귀가 전 주의사항 안내 필요. 통역 필요 시 데스크 호출."
)


def fake_snapshot(now: datetime) -> BoardSnapshot:
    def ago(minutes: float) -> str:
        return iso(now - timedelta(minutes=minutes))

    doctors = [
        {"id": 1, "name": "가 원장", "busy": False, "busyRoom": None},
        {"id": 2, "name": "나 원장", "busy": False, "busyRoom": None},
        {"id": 3, "name": "다 원장", "busy": True, "busyRoom": "A-룸3"},
        {"id": 4, "name": "라 원장", "busy": False, "busyRoom": None},
    ]

    def room(i: int, title: str) -> dict:
        return {"id": i, "title": title, "order": i}

    def cust(name: str, phon: str | None, nat: str, new: bool, chart: str) -> dict:
        return {"name": name, "phoneticName": phon, "nationality": nat, "isNew": new, "chartNumber": chart}

    def anes(running: float | None = None, last: int | None = None, home: bool = False) -> dict:
        return {
            "runningSince": ago(running) if running is not None else None,
            "lastMinutes": last,
            "long": running is not None and running >= 20,
            "canStart": running is None and not home,
            "canEnd": running is not None and not home,
        }

    def proc(pid: int, seq: int, title: str, state: str, *, doctor: dict | None = None, call: dict | None = None,
             started: float | None = None, completed: float | None = None, home: bool = False) -> dict:
        accepted = call is None or call.get("acceptedBy") is not None
        can_start = state == "wait" and not home and (accepted if call else doctor is not None)
        return {
            "id": pid, "kind": "procedure", "sequence": seq, "title": title, "state": state,
            "kosStatus": {"done": "DONE", "doing": "READY"}.get(state, "WAITING" if call else "NOT_STARTED"),
            "startedAt": ago(started) if started is not None else None,
            "completedAt": ago(completed) if completed is not None else None,
            "doctor": doctor, "call": call,
            "pickable": state == "wait" and not home,
            "canStart": can_start, "canFinish": state == "doing", "isRoomTask": False,
            # 되돌리기 아이콘 예시(지어낸 값 · §5.13) — 진행 줄 · ccc [시작] 있는 완료 줄 · 귀가 대기 카드는 false
            "canUndoStart": state == "doing" and not home,
            "canUndoFinish": state == "done" and started is not None and not home,
        }

    def call(cid: int, kind: str, created: float, target: int | None = None, by: int | None = None,
             at: float | None = None) -> dict:
        return {"id": cid, "kind": kind, "targetDoctorId": target, "createdAt": ago(created),
                "acceptedBy": by, "acceptedAt": ago(at) if at is not None else None}

    ok = {"status": "ok", "failed": []}
    d1, d2, d3 = ({"id": d["id"], "name": d["name"]} for d in doctors[:3])
    c_all = call(11, "all", 7)
    c_one = call(12, "one", 2, target=2)
    c_acc = call(10, "all", 15, by=1, at=12)

    cards = [
        {  # 시술 대기 · 전체 호출 7분 미수락 → 확인 필요(call) · 수납 필요 · 긴 메모
            "visitId": 101, "room": room(1, "A-룸1"), "inAt": ago(25), "homeAt": None,
            "customer": cust("홍길동", "ホンギルドン", "JP", True, "F-0001"),
            "state": "waiting", "paymentRequired": True, "orderMemo": LONG_MEMO,
            "anesthesia": anes(),
            "procedures": [
                proc(1001, 1, "레이저 토닝", "wait", call=c_all),
                proc(1002, 2, "슈링크 300샷", "wait", call=c_all),
                proc(1003, 3, "진정관리", "wait"),
                {**proc(1004, 4, "시트팩", "wait"), "kind": "etc"},  # 방 없는 ETCETERA = 같은 시술 줄(2026-10-25)
                {**proc(1005, 5, "방 배정", "wait"), "kind": "etc", "kosStatus": "READY", "pickable": False,
                 "canStart": False, "isRoomTask": True},  # 「방 배정」 — 실리지만 front 가 숨긴다
            ],
            "canCall": True, "canHome": False,
            "need": {"why": "call", "since": c_all["createdAt"], "limitMin": 5},
            "kos": {"status": "pending", "failed": []},
        },
        {  # 시술 대기 · 마취 22분 → 확인 필요(anes) · 지정 호출 + 수락됨 섞임
            "visitId": 102, "room": room(2, "A-룸2"), "inAt": ago(40), "homeAt": None,
            "customer": cust("김철수", None, "KR", False, "F-0002"),
            "state": "waiting", "paymentRequired": False, "orderMemo": "울쎄라 300샷 · 턱선 위주",
            "anesthesia": anes(running=22),
            "procedures": [
                proc(1011, 1, "울쎄라 300샷", "wait", doctor=d1, call=c_acc),
                proc(1012, 2, "리쥬란 힐러", "wait", call=c_one),
                proc(1013, 3, "스킨부스터", "wait", doctor=d2),
            ],
            "canCall": True, "canHome": False,
            "need": {"why": "anes", "since": ago(22), "limitMin": 20},
            "kos": ok,
        },
        {  # 시술 진행 · 완료 1 · 진행 1 · 담당의 미정 1
            "visitId": 103, "room": room(3, "A-룸3"), "inAt": ago(55), "homeAt": None,
            "customer": cust("(TW) CHEN WANLING ALEXANDRA", "첸 완링 알렉산드라 테스트 발음", "TW", True, "F-0003"),
            "state": "doing", "paymentRequired": False, "orderMemo": None,
            "anesthesia": anes(last=18),
            "procedures": [
                proc(1021, 1, "보톡스 사각턱", "done", doctor=d3, started=30, completed=20),
                proc(1022, 2, "필러 코", "doing", doctor=d3, started=10),
                proc(1023, 3, "LDM", "wait"),
            ],
            "canCall": True, "canHome": False, "need": None,
            "kos": {"status": "failed", "failed": [{"op": "change-tasks-complete", "error": "HTTP 500"}]},
        },
        {  # 시술 전부 완료 · 귀가 대기 전 → 확인 필요(home) · [귀가 대기]
            "visitId": 104, "room": room(4, "A-룸4"), "inAt": ago(80), "homeAt": None,
            "customer": cust("이영희", None, "KR", False, "F-0004"),
            "state": "doing", "paymentRequired": False, "orderMemo": "아쿠아필 · 진정",
            "anesthesia": anes(last=25),
            "procedures": [
                proc(1031, 1, "아쿠아필", "done", doctor=d2, started=50, completed=40),
                proc(1032, 2, "진정관리", "done", doctor=d2, started=38, completed=6),
            ],
            "canCall": False, "canHome": True,
            "need": {"why": "home", "since": ago(6), "limitMin": 0},
            "kos": ok,
        },
        {  # 귀가 대기 — 흐리게 맨 뒤
            "visitId": 105, "room": room(5, "A-룸5"), "inAt": ago(120), "homeAt": ago(3),
            "customer": cust("SMITH JOHN", None, "US", True, "F-0005"),
            "state": "home", "paymentRequired": False, "orderMemo": None,
            "anesthesia": anes(home=True),
            "procedures": [proc(1041, 1, "레이저 토닝", "done", doctor=d1, started=70, completed=50, home=True)],
            "canCall": False, "canHome": False, "need": None, "kos": ok,
        },
    ]
    calls = [
        {"callId": 11, "visitId": 101, "room": room(1, "A-룸1"), "customer": {"name": "홍길동", "nationality": "JP"},
         "kind": "all", "targetDoctorId": None, "createdAt": c_all["createdAt"],
         "procedures": [{"id": 1001, "title": "레이저 토닝"}, {"id": 1002, "title": "슈링크 300샷"}]},
        {"callId": 12, "visitId": 102, "room": room(2, "A-룸2"), "customer": {"name": "김철수", "nationality": "KR"},
         "kind": "one", "targetDoctorId": 2, "createdAt": c_one["createdAt"],
         "procedures": [{"id": 1012, "title": "리쥬란 힐러"}]},
    ]
    return BoardSnapshot.model_validate({
        "now": iso(now),
        "sync": {"lastOkAt": ago(0.1), "lastError": None, "inWindow": True},
        "doctors": sorted(doctors, key=lambda d: d["busy"]),
        "counts": {"all": 5, "need": 3, "waiting": 2, "anes": 1, "call": 2, "doing": 2},
        "limits": {"callMin": 5, "anesMin": 20},
        "cards": cards,
        "calls": calls,
        "recentAccepts": [{"at": ago(12), "room": "A-룸2", "doctorName": "가 원장", "count": 1}],
    })
