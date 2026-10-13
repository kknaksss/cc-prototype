"""시드 CLI — SPEC-001 §4.1 · §4.3.

  uv run python -m app.seed build [--date 2026-10-09] [--at 14:45]   캡처 → data/seed.json + DB
  uv run python -m app.seed save                                        지금 DB → data/seed.json (이전 것은 seed.<시각>.json)
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from app.config import get_settings
from app.container import build_container
from app.seed.build import AT_RE, DATE_RE, build_seed
from app.seed.capture import KST, Capture


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
    b = sub.add_parser("build", help="캡처에서 시드 만들기")
    b.add_argument("--date", default="2026-10-09")
    b.add_argument("--at", default="14:45")
    b.add_argument("--capture", default=None, help="기본: env CC_CAPTURE_DIR")
    sub.add_parser("save", help="지금 DB 상태를 시드로")
    args = p.parse_args(argv)

    settings = get_settings()
    c = build_container(settings)
    if args.cmd == "build":
        if not DATE_RE.match(args.date) or not AT_RE.match(args.at):
            p.error("--date YYYY-MM-DD · --at HH:MM")
        root = args.capture or settings.cc_capture_dir
        if not root:
            p.error("CC_CAPTURE_DIR 를 cc/back/.env 에 넣거나 --capture 로 주세요")
        snap, notes = build_seed(Capture(Path(root)), date.fromisoformat(args.date), args.at)
        old = _backup(settings.seed_path)
        _write(settings.seed_path, snap)
        c.board.load_snapshot(snap)
        st = snap["state"]
        here = [x for x in st["customers"] if not x["done"]]
        print(f"seed build {args.date} {args.at} → {settings.seed_path}" + (f" (이전 것: {old.name})" if old else ""))
        print(f"  일정 {len(st['resv'])} · 지금 내원 {len(here)} · 귀가 {len(st['customers']) - len(here)}"
              f" · 직원 {len(st['staff'])} · 완료 기록 {len(st['history'])}")
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
