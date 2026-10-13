"""§11-8 — 조작 함수마다 `kos api 연동 필요` 주석, KOS 호출 코드 0."""

import inspect
import re
from pathlib import Path

from app.domain import board as B

MARK = "## ============kos api 연동 필요 ========================"
APP = Path(__file__).resolve().parent.parent / "app"


def test_every_operation_has_kos_comment():
    with_mark = [f.__name__ for f in B.OPERATIONS if MARK in inspect.getsource(f)]
    assert len(B.OPERATIONS) == 13
    assert with_mark == [f.__name__ for f in B.OPERATIONS]
    # 조작 함수 = board.py 에서 Op 을 돌려주는 공개 함수 전부
    ops = [n for n, f in inspect.getmembers(B, inspect.isfunction)
           if f.__module__ == B.__name__ and "-> Op" in inspect.getsource(f).split("\n", 1)[0]]
    assert sorted(ops) == sorted(f.__name__ for f in B.OPERATIONS)


def test_no_kos_call_code():
    hits = []
    for p in APP.rglob("*.py"):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"kos-solution\.com|open-api\.kos|api\.kos|exchange-token|/commands/|/queries/", code):
                hits.append(f"{p.relative_to(APP)}:{i}: {line.strip()}")
    assert hits == []
    # HTTP 클라이언트는 통역(Soniox) 모듈에만
    for p in APP.rglob("*.py"):
        src = p.read_text()
        if re.search(r"^\s*(import|from)\s+(httpx|requests|urllib|aiohttp|websockets)\b", src, re.M):
            assert "interpret" in p.parts, p
