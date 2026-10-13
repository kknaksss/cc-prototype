"""시드 CLI — SPEC-001 0.2.1 §0-a · §6.

  uv run python -m app.seed build [--date 2026-10-09]   시나리오(data/scenario) + KOS 직원 저장본 → 개원 전 data/seed.json + DB
  uv run python -m app.seed save                        지금 DB → data/seed.json (이전 것은 seed.<시각>.json)
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.container import build_container
from app.seed.build import DATE_RE, build_seed, load_scenario
from app.seed.capture import KST


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    dst = path.with_name(f"seed.{stamp}.json")
    path.rename(dst)
    return dst


def _write(path: Path, snap: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.seed")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="시나리오 파일에서 개원 전 시드 만들기")
    b.add_argument("--date", default=None, help="주면 시나리오 날짜와 같은지 확인")
    b.add_argument("--scenario", default=None, help="기본: env CC_SCENARIO_DIR(data/scenario)")
    sub.add_parser("save", help="지금 DB 상태를 시드로")
    args = p.parse_args(argv)

    settings = get_settings()
    c = build_container(settings)
    if args.cmd == "build":
        if args.date and not re.match(DATE_RE, args.date):
            p.error("--date YYYY-MM-DD")
        root = Path(args.scenario) if args.scenario else settings.scenario_dir
        try:
            scenario, events = load_scenario(root)
        except FileNotFoundError as e:
            p.error(f"{e} — 시나리오 대기(CC_SCENARIO_DIR)")
        if args.date and scenario.get("date") != args.date:
            p.error(f"시나리오 날짜({scenario.get('date')})가 --date({args.date})와 달라요")
        staff_path = settings.kos_staff_path
        if not staff_path.exists():
            p.error(f"직원 원천(KOS getAccounts 저장본)이 없어요: {staff_path} — CC_KOS_STAFF_PATH")
        accounts = json.loads(staff_path.read_text()).get("data", [])
        snap, notes = build_seed(scenario, events, accounts)
        old = _backup(settings.seed_path)
        _write(settings.seed_path, snap)
        c.board.load_snapshot(snap)
        st = snap["state"]
        roles: dict[str, int] = {}
        for s in st["staff"]:
            roles[s["role"]] = roles.get(s["role"], 0) + 1
        print(f"seed build {scenario['date']}(개원 전 · 시나리오 {root})")
        print(f"  → {settings.seed_path}" + (f" (이전 것: {old.name})" if old else ""))
        print(f"  예약 {len(st['resv'])}(취소 {sum(r['st'] == 'canceled' for r in st['resv'])}) · 직원 {len(st['staff'])} "
              + " · ".join(f"{k} {v}" for k, v in roles.items()))
        print(f"  이벤트 {len(snap['reference']['events'])}개")
        for n in notes:
            print("  ! " + n)
    else:
        snap = c.board.snapshot()
        old = _backup(settings.seed_path)
        _write(settings.seed_path, snap)
        print(f"seed save → {settings.seed_path}" + (f" (이전 것: {old.name})" if old else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
