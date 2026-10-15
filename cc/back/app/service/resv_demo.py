"""예약관리 데모 값 — 시안 「Ceramique 예약관리 v1」 샘플 그대로(전부 가짜, 실제 고객 값 아님).

링키가 보낼 요청을 데모 버튼이 대신 만든다(SPEC-002 §3.2). 날짜는 받은 날 기준 오프셋 —
시안 기준일 10-14 에서 10-16 · 10-17 · 10-17 이었으므로 +2 · +3 · +3 일.
"""

from datetime import datetime, timedelta

from app.seed.capture import KST

# [링키 예약 요청 생성] 을 누를 때마다 차례로 하나씩. 다 쓰면 처음부터.
SAMPLES = [
    {"customer": {"name": "[TW] LIN YA CHEN", "reading": "린야천", "chart": "No.9041", "nat": "대만", "natCode": "TW",
                  "sex": "여성", "birth": "1991.03.08 (만 35세)", "phone": "+886 900 000 000",
                  "zone": "3층 / 중화권", "isNew": True},
     "days": 2, "time": "14:00", "proc": "울쎄라피 프라임 300shot", "lang": "중국어"},
    {"customer": {"name": "[JP] TANAKA YUKI", "reading": "다나카 유키", "chart": "No.9058", "nat": "일본", "natCode": "JP",
                  "sex": "여성", "birth": "1988.11.23 (만 37세)", "phone": "+81 90 0000 0000",
                  "zone": "3층 / 일본", "isNew": False},
     "days": 3, "time": "10:00", "proc": "리쥬란 힐러 2cc", "lang": "일본어"},
    {"customer": {"name": "[HK] CHAN MEI LING", "reading": "찬메이링", "chart": "No.9063", "nat": "홍콩", "natCode": "HK",
                  "sex": "여성", "birth": "1995.07.19 (만 31세)", "phone": "+852 9000 0000",
                  "zone": "3층 / 중화권", "isNew": True},
     "days": 3, "time": "15:00", "proc": "써마지 FLX 900shot", "lang": "중국어"},
]
LAST_VISIT_RETURNING = "2026.08.21"  # 시안 스크린샷 「최근방문일」(재내원) — 가짜

# [링키 수정 요청 생성] 새 시간 — 시안 값. 변경 요청 반영 = 14:30, 고객 시간 변경 = 16:30.
# 이전 시간과 같으면(같은 묶음을 두 번 수정) 이전 시간 + 1시간.
MODIFY_TIME = {"change_request": "14:30", "customer": "16:30"}


def _kst(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, KST)


def add_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    x = (h * 60 + m + minutes) % (24 * 60)
    return f"{x // 60:02d}:{x % 60:02d}"


def sample(n: int, now_ms: int) -> dict:
    """n 번째 요청(0부터)의 고객 · 일시 · 시술 · 통역."""
    s = SAMPLES[n % len(SAMPLES)]
    return {"customer": dict(s["customer"]), "date": (_kst(now_ms) + timedelta(days=s["days"])).date().isoformat(),
            "time": s["time"], "proc": s["proc"], "lang": s["lang"]}


def modify_time(reason: str, old: str) -> str:
    new = MODIFY_TIME[reason]
    return new if new != old else add_minutes(old, 60)


def memo(row: dict, at_ms: int) -> str:
    """예약 메모(자동 작성) — 시안 `memoOf` 형식: `26.10.14/링키 본사/<시술>/<언어> 통역 필요` + 수정이면 한 줄."""
    text = f"{_kst(at_ms):%y.%m.%d}/링키 본사/{row['proc']}/{row['lang']} 통역 필요"
    before = row.get("before")
    if before is not None:
        text += f"\n*예약 시간 변경 {before['time']} → {row['time']}" if "time" in before else "\n*예약 수정"
    return text


def snapshot(row: dict, at_ms: int) -> dict:
    """「KOS 등록 화면」 값 — 시안 스크린샷 모달(KOS 예약 카드) · 미리보기 표 칸."""
    c = row["customer"]
    return {
        "kind": "modify" if row["kind"] == "modify" else "register",
        "at": at_ms,
        "name": c["name"], "reading": c["reading"], "chart": c["chart"],
        "nat": c["nat"], "natCode": c["natCode"], "sex": c["sex"], "isNew": c["isNew"],
        "visitType": "신규 환자" if c["isNew"] else "재내원",
        "birth": c["birth"], "phone": c["phone"],
        "lastVisit": "없음" if c["isNew"] else LAST_VISIT_RETURNING,
        "source": "본사(링키)",
        "date": row["date"], "time": row["time"], "endTime": add_minutes(row["time"], 30),
        "floor": c["zone"].split(" / ")[0], "zone": c["zone"],
        "proc": row["proc"], "lang": row["lang"], "interpret": f"{row['lang']} 통역 필요",
        "memo": memo(row, at_ms),
    }
