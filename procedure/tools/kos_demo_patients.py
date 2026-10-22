#!/usr/bin/env python3
"""KOS 데모 지점에 그날 데모 환자(예약) 채우기 · 보기 · 지우기 — 시술 현황판 데모 준비용.

    python3 procedure/tools/kos_demo_patients.py create --date 2026-10-22 [--per-slot 2] [--groups 국내,중화권]
                                                        [--dry-run] [--out FILE]
    python3 procedure/tools/kos_demo_patients.py list   --date 2026-10-22 [--out FILE]
    python3 procedure/tools/kos_demo_patients.py delete --date 2026-10-22 [--yes] [--out FILE]

안전(스킬 `.claude/skills/kos-demo-patients/SKILL.md`):
- env = procedure/.env 의 KOS_OPEN_API_BASE · KOS_OPEN_API_KEY · KOS_ZONE_ID. **데모 테넌트에서만** — 직원 목록에 데모 표식
  계정(KOS-DEMO)이 없으면 운영으로 보고 멈춘다. 키 · 토큰 값은 출력하지 않는다
- 우리가 만든 것 = 예약 메모가 `[ccc 데모 <날짜>]` 로 시작하는 예약. list · delete 는 그것만 본다(기존 일정 손대지 않음)
- 이름은 아래 목록의 가상 이름(국적별 흔한 형태 · 실존 인물 아님) · 연락처 없음
- 한계: 공개 API 로는 예약까지만(재내원 · 접수 · 수납 · 시술 작업 · 방 배정은 KOS 화면에서)

stdlib 만 쓴다(back 가상환경 없이 python3 로 실행).
"""

import argparse
import collections
import itertools
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
UTC = UTC
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
DEMO_MARK_ACCOUNT = "KOS-DEMO"  # 데모 테넌트에만 있는 직원 이름(운영엔 없음 — kos-demo-api.md §1.2)

# 4층 예약 그룹(국적 칸) → 넣을 국적(돌려가며). 시술 칸(리프팅 · 레이저 …)은 쓰지 않는다
GROUP_NATS = {
    "국내": ["KR"],
    "중화권": ["CN", "TW"],
    "영미권": ["US", "GB", "AU", "CA"],
    "일본": ["JP"],
    "기타": ["TH", "VN"],
}

# 가상 이름 재료 — (성, 이름, 조합 방식). 조합으로 만든 흔한 형태일 뿐 특정 인물이 아니다
NAME_POOL = {
    "KR": (["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"],
           ["서연", "민준", "지우", "하준", "수아", "도윤", "지민", "예준", "하은", "주원", "유나", "시우"], "joined"),
    "CN": (["王", "李", "张", "刘", "陈", "杨", "赵", "黄"], ["芳", "伟", "静", "磊", "敏", "强", "丽", "军"], "joined"),
    "TW": (["林", "陳", "黃", "張", "吳", "蔡", "許", "鄭"],
           ["怡君", "冠宇", "詩涵", "家豪", "雅婷", "承恩", "佩珊", "宗翰"], "joined"),
    "JP": (["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村"],
           ["花子", "健太", "美咲", "翔", "由美", "大輔", "陽菜", "蓮"], "family_first"),
    "EN": (["Johnson", "Smith", "Davis", "Miller", "Brown", "Wilson", "Taylor", "Clark"],
           ["Emily", "Michael", "Sarah", "David", "Jessica", "Daniel", "Olivia", "James"], "given_first"),
    "TH": (["Boonmee", "Srisuk", "Chaiyo", "Kaewmanee", "Rattana", "Thongdee"],
           ["Siriporn", "Anan", "Malee", "Somsak", "Ploy", "Niran"], "given_first"),
    "VN": (["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ"], ["Thị Lan", "Văn Minh", "Thu Hà", "Quốc Bảo", "Mai Anh", "Đức Huy"],
           "family_first"),
}
NAME_KEY = {"US": "EN", "GB": "EN", "AU": "EN", "CA": "EN"}

FLOW_STEPS = ["RESERVED", "RECEPTION", "CONSULTATION_WAITING", "CONSULTATION", "PROCEDURE_WAITING", "PROCEDURE",
              "PROCEDURE_DONE", "COMPLETED"]


def mark(day: date) -> str:
    return f"[ccc 데모 {day.isoformat()}]"


def utc(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def kst_hm(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(KST).strftime("%H:%M")


# ---------------------------------------------------------------- KOS 공개 API
class Kos:
    def __init__(self, env_path: Path):
        env = {}
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.removeprefix("export ").split("=", 1)
                    env[k.strip()] = v.strip().strip("\"'")
        self.base = env.get("KOS_OPEN_API_BASE", "").rstrip("/")
        self.key = env.get("KOS_OPEN_API_KEY", "")
        self.zone_id = env.get("KOS_ZONE_ID", "")
        if not (self.base and self.key and self.zone_id):
            sys.exit(f"멈춤: {env_path} 에 KOS_OPEN_API_BASE · KOS_OPEN_API_KEY · KOS_ZONE_ID 가 필요해요")
        self._token: str | None = None

    def post(self, path: str, body: dict, auth: bool = True) -> dict:
        headers = {"Content-Type": "application/json"}
        if auth:
            if self._token is None:
                self._token = self.post("/open/authorization/commands/exchange-token", {"key": self.key}, auth=False)["token"]
            headers["Authorization"] = self._token
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:  # 본문 · 토큰은 싣지 않고 상태 · 오류 이름만
            try:
                name = json.loads(e.read()).get("className", "")
            except ValueError:
                name = ""
            return {"__error": f"HTTP {e.code} {name}".strip()}

    def ensure_demo_tenant(self) -> None:
        """데모 테넌트인가 — 직원 목록에 데모 표식 계정이 없으면 운영으로 보고 멈춘다."""
        accounts = self.post("/account/open/v1/queries/get-accounts", {}).get("data") or []
        if not any((a.get("name") or "") == DEMO_MARK_ACCOUNT for a in accounts):
            sys.exit("멈춤: 데모 테넌트가 아니에요(데모 표식 계정 없음) — 운영 키로 보이면 절대 쓰지 마세요")

    def groups(self) -> dict[str, str]:
        """국적 칸 이름 → 예약 그룹 id(4층에서 켜진 것만)."""
        out = {}
        for g in self.post("/schedule/open/v1/queries/get-reservation-groups", {}).get("data") or []:
            on = any(c.get("enabled") and c.get("zoneId") == self.zone_id for c in g.get("intervalCapacities") or [])
            if g.get("title") in GROUP_NATS and on:
                out[g["title"]] = g["id"]
        return out

    def capacity(self) -> dict[str, int]:
        out = {}
        for g in self.post("/schedule/open/v1/queries/get-reservation-groups", {}).get("data") or []:
            for c in g.get("intervalCapacities") or []:
                if c.get("enabled") and c.get("zoneId") == self.zone_id:
                    out[g.get("id")] = int(c.get("intervalCapacity") or 0)
        return out

    def open_slots(self, day: date) -> list[datetime]:
        """그날(KST) 예약 가능한 슬롯 시작 시각 — 기본 예약 규칙의 슬롯 그대로."""
        start = datetime(day.year, day.month, day.day, tzinfo=KST)
        resp = self.post("/schedule/open/v1/queries/get-reservation-time-slots",
                         {"dateTimeRangeUtc": {"startDateTimeUtc": utc(start), "endDateTimeUtc": utc(start + timedelta(days=1))}})
        out = []
        for s in resp.get("data") or []:
            if s.get("available"):
                out.append(datetime.fromisoformat(s["dateTimeRangeUtc"]["startDateTimeUtc"].replace("Z", "+00:00")))
        return sorted(out)

    def schedules(self, day: date) -> list[dict]:
        """그날 4층 일정 전부(단계 8개 · 예약 시작 시각 기준)."""
        start = datetime(day.year, day.month, day.day, tzinfo=KST)
        seen, out = set(), []
        for step in FLOW_STEPS:
            resp = self.post("/schedule/open/v1/queries/get-schedules-by-flow-step",
                             {"flowStep": step, "reservationStartDateTimeUtcFrom": utc(start),
                              "reservationStartDateTimeUtcTo": utc(start + timedelta(days=1))})
            if "__error" in resp:
                sys.exit(f"멈춤: 일정 조회 실패({resp['__error']})")
            for s in resp.get("data") or []:
                if s.get("id") not in seen and (s.get("zone") or {}).get("id") in (self.zone_id, None):
                    seen.add(s.get("id"))
                    out.append(s)
        return out


def ours(schedules: list[dict], day: date) -> list[dict]:
    """우리가 만든 데모 예약 = 예약 메모가 [ccc 데모 <날짜>] 로 시작 · 취소되지 않은 것."""
    tag = mark(day)
    return [s for s in schedules if ((s.get("reservation") or {}).get("reservationMemo") or "").startswith(tag)
            and (s.get("reservation") or {}).get("status") != "CANCELED"]


def row(s: dict, group_title: dict[str, str]) -> dict:
    r = s.get("reservation") or {}
    v = s.get("visitor") or {}
    return {"scheduleId": s.get("id"), "slot": kst_hm(r.get("startDateTime") or "1970-01-01T00:00:00Z"),
            "group": group_title.get(r.get("reservationGroupId"), "?"), "nat": v.get("nationality"), "name": v.get("name"),
            "flowStep": s.get("flowStep"), "status": r.get("status")}


def names(taken: set[str]):
    """국적별 가상 이름 생성기 — 그날 이미 쓴 이름은 건너뛴다."""
    def gen(key: str):
        sur, given, mode = NAME_POOL[key]
        for i in itertools.count():
            s, g = sur[i % len(sur)], given[(i + i // len(sur)) % len(given)]
            n = {"joined": s + g, "family_first": f"{s} {g}", "given_first": f"{g} {s}"}[mode]
            if n not in taken:
                taken.add(n)
                yield n
            if i > len(sur) * len(given) * 2:
                raise SystemExit(f"멈춤: {key} 가상 이름이 모자라요 — NAME_POOL 을 늘리세요")
    return {k: gen(k) for k in NAME_POOL}


def write_out(path: str | None, title: str, rows: list[dict]) -> None:
    if not path:
        return
    lines = [f"# {title}", "", "| 그룹 | 시간(KST) | 국적 | 이름(가상) | 상태 | scheduleId |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r.get("group", ""), r.get("slot", ""))):
        lines.append(f"| {r.get('group')} | {r.get('slot')} | {r.get('nat')} | {r.get('name')} | {r.get('status', '')} | "
                     f"`{r.get('scheduleId') or '-'}` |")
    Path(path).write_text("\n".join(lines) + "\n")
    print(f"기록: {path}")


# ---------------------------------------------------------------- 하위 명령
def cmd_list(kos: Kos, args) -> list[dict]:
    groups = kos.groups()
    title = {v: k for k, v in groups.items()}
    rows = [row(s, title) for s in ours(kos.schedules(args.date), args.date)]
    by = collections.Counter(r["group"] for r in rows)
    print(f"{args.date} 데모 예약 {len(rows)}건 — " + " · ".join(f"{g} {by[g]}" for g in GROUP_NATS if by[g]) +
          (f" · 그 밖 {sum(v for k, v in by.items() if k not in GROUP_NATS)}" if any(k not in GROUP_NATS for k in by) else ""))
    write_out(getattr(args, "out", None), f"데모 예약 {args.date}", rows)
    return rows


def cmd_create(kos: Kos, args) -> None:
    groups = kos.groups()
    want = [g.strip() for g in args.groups.split(",")] if args.groups else list(GROUP_NATS)
    missing = [g for g in want if g not in groups]
    if missing:
        sys.exit(f"멈춤: 4층에 없는(또는 꺼진) 국적 칸 — {missing}")
    title = {v: k for k, v in groups.items()}
    cap = kos.capacity()
    slots = kos.open_slots(args.date)
    every = kos.schedules(args.date)
    mine = ours(every, args.date)
    all_cnt, our_cnt = collections.Counter(), collections.Counter()
    for s in every:
        r = s.get("reservation") or {}
        if r.get("status") != "CANCELED" and r.get("reservationGroupId") in title:
            all_cnt[(r["reservationGroupId"], kst_hm(r.get("startDateTime")))] += 1
    for s in mine:
        r = s["reservation"]
        if r.get("reservationGroupId") in title:
            our_cnt[(r["reservationGroupId"], kst_hm(r.get("startDateTime")))] += 1
    gen = names({(s.get("visitor") or {}).get("name") or "" for s in mine})

    plan = []
    for g in want:
        gid, nats = groups[g], GROUP_NATS[g]
        for si, t0 in enumerate(slots):
            hm = t0.astimezone(KST).strftime("%H:%M")
            need = max(0, args.per_slot - our_cnt[(gid, hm)])
            room = max(0, cap.get(gid, 0) - all_cnt[(gid, hm)])  # 정원 초과 금지(다른 예약 포함)
            for j in range(min(need, room)):
                nat = nats[(si * args.per_slot + our_cnt[(gid, hm)] + j) % len(nats)]
                plan.append({"group": g, "gid": gid, "slot": hm, "start": t0, "nat": nat,
                             "name": next(gen[NAME_KEY.get(nat, nat)])})
    by = collections.Counter(p["group"] for p in plan)
    print(f"{args.date} 계획 {len(plan)}건(슬롯 {len(slots)} · 칸당 {args.per_slot}명 · 이미 우리 것 {len(mine)}) — "
          + (" · ".join(f"{g} {by[g]}" for g in want) if plan else "더 만들 것 없음"))
    if args.dry_run or not plan:
        write_out(args.out, f"데모 예약 계획 {args.date}(dry-run)", plan)
        return
    made = []
    for p in plan:
        body = {"visitorName": p["name"], "visitorNationality": p["nat"], "zoneId": kos.zone_id,
                "reservationMemo": f"{mark(args.date)} 시술 현황판 데모용 가상 고객",
                "occupiedResources": [{"startDateTimeUtc": utc(p["start"]),
                                       "endDateTimeUtc": utc(p["start"] + timedelta(minutes=30)),
                                       "reservationGroup": {"reservationGroupId": p["gid"], "zoneId": kos.zone_id}}]}
        resp = kos.post("/schedule/open/v2/commands/reserve", body)
        made.append({**{k: v for k, v in p.items() if k in ("group", "slot", "nat", "name")},
                     "scheduleId": resp.get("scheduleId"), "status": resp.get("__error") or "RESERVED"})
        if not made[-1]["scheduleId"]:
            print(f"  실패 {p['group']} {p['slot']} {p['nat']}: {resp.get('__error')}")
        time.sleep(0.25)
    print(f"만듦 {sum(1 for m in made if m['scheduleId'])} · 실패 {sum(1 for m in made if not m['scheduleId'])}")
    write_out(args.out, f"데모 예약 생성 {args.date}", made)


def cmd_delete(kos: Kos, args) -> None:
    rows = cmd_list(kos, argparse.Namespace(date=args.date, out=None))
    targets = [r for r in rows if r["status"] == "RESERVED"]
    moved = [r for r in rows if r["status"] != "RESERVED"]
    if moved:
        print(f"  예약 상태가 아닌 {len(moved)}건(접수 이후로 진행)은 건너뜀 — KOS 화면에서 정리")
    if not targets:
        print("지울 것 없음")
        return
    if not args.yes and input(f"{args.date} 데모 예약 {len(targets)}건을 취소할까요? [y/N] ").strip().lower() != "y":
        print("취소 안 함")
        return
    done = []
    for r in targets:
        resp = kos.post("/schedule/open/v1/commands/cancel-reservation", {"scheduleId": r["scheduleId"], "reason": "CANCELED"})
        done.append({**r, "status": resp.get("__error") or "CANCELED"})
        time.sleep(0.2)
    print(f"취소 {sum(1 for d in done if d['status'] == 'CANCELED')} · 실패 {sum(1 for d in done if d['status'] != 'CANCELED')}")
    write_out(args.out, f"데모 예약 취소 {args.date}", done)


def main() -> None:
    ap = argparse.ArgumentParser(description="KOS 데모 지점 데모 환자(예약) 채우기 · 보기 · 지우기")
    ap.add_argument("--env", default=str(ENV_PATH), help="env 파일(기본 procedure/.env)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    day = {"type": date.fromisoformat, "required": True, "help": "날짜(KST) YYYY-MM-DD"}
    c = sub.add_parser("create", help="국적 칸마다 슬롯당 N명")
    c.add_argument("--date", **day)
    c.add_argument("--per-slot", type=int, default=2)
    c.add_argument("--groups", help=f"쉼표로(기본 전부: {','.join(GROUP_NATS)})")
    c.add_argument("--dry-run", action="store_true", help="계획만 출력")
    c.add_argument("--out", help="결과 기록 파일(markdown)")
    lst = sub.add_parser("list", help="그날 우리가 만든 데모 예약")
    lst.add_argument("--date", **day)
    lst.add_argument("--out")
    d = sub.add_parser("delete", help="그날 우리가 만든 데모 예약(예약 상태) 취소")
    d.add_argument("--date", **day)
    d.add_argument("--yes", action="store_true", help="확인 묻지 않음")
    d.add_argument("--out")
    args = ap.parse_args()
    kos = Kos(Path(args.env))
    kos.ensure_demo_tenant()
    {"create": cmd_create, "list": cmd_list, "delete": cmd_delete}[args.cmd](kos, args)


if __name__ == "__main__":
    main()
