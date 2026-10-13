"""메모 양식 파싱 — SPEC-001 0.1.0 §5.5 · 0.2.0 §3.4 · research-patient-detail-report §A.

원문은 고치지 않는다(자르기 · 고르기만). 앞뒤 공백 · 폭 없는 공백만 다듬는다. `**…**` 기호도 원문 그대로 둔다(굵게는 front).
값 없는 양식 줄(「고민:」 처럼 콜론 뒤가 빈 줄 · 「H)」 · 빈 번호 「1.」)은 숨긴다(0.2.0 §3.4).
"""

import re

ZW = re.compile(r"[​‌‍﻿]")
DIVIDER = re.compile(r"^\s*-{4,}\s*$")
TAG_LINE = re.compile(r"^\s*\[(특이사항|임플란트 여부|임플란트)\]\s*:?\s*(.*)$")
OUT_TIME = re.compile(r"OUT\s*TIME\s*:?\s*(.*)$", re.IGNORECASE)
NUMBERED = re.compile(r"^\s*([1-9]\d*)\s*[.)]")
EMPTY_VALUES = {"", "x", "X", "x .", "X .", "-"}
OUT_HINT = re.compile(r"(\d{1,2}\s*시[^\n]*아웃|아웃[^\n]*\d{1,2}\s*시|\d{1,2}\s*:\s*\d{2}\s*전)")
HISTORY_LINE = re.compile(r"^\s*(H\)|받은\s*시술\s*:)\s*(.*)$")
HISTORY_SENTENCE = re.compile(r"\d{1,2}\s*월[^\n]*하(심|셨)")


EMPTY_FORM = re.compile(r"^\s*(?:[^:：\n]{1,30}[:：]|[A-Za-z]\)|\d{1,2}\s*[.)])\s*$")


def is_empty_form(line: str) -> bool:
    return bool(EMPTY_FORM.match(line))


def drop_empty_form(lines: list[str]) -> list[str]:
    return [ln for ln in lines if not is_empty_form(ln)]


def clean(text: str | None) -> str:
    return ZW.sub("", text or "")


def lines_of(text: str | None) -> list[str]:
    return [ln.rstrip() for ln in clean(text).split("\n")]


def split_consult(text: str | None) -> tuple[list[str], list[str]]:
    """상담 메모 → (구분선 위, 구분선 아래 = 오더지 사본)."""
    ls = lines_of(text)
    for i, ln in enumerate(ls):
        if DIVIDER.match(ln):
            return ls[:i], ls[i + 1:]
    return ls, []


def leading_flag_lines(text: str | None) -> list[str]:
    """메모 맨 앞에 연달아 붙은 `**…**` · `★` 줄."""
    out = []
    for ln in lines_of(text):
        s = ln.strip()
        if s.startswith("**") or s.startswith("★"):
            out.append(s)
        elif out or s:
            break
    return out


def tag_blocks(ls: list[str]) -> list[tuple[str, str]]:
    """[특이사항] · [임플란트 여부] 값(같은 줄 + 이어지는 줄)."""
    out = []
    i = 0
    while i < len(ls):
        m = TAG_LINE.match(ls[i])
        if not m:
            i += 1
            continue
        tag = "임플란트" if m.group(1).startswith("임플란트") else "특이사항"
        parts = [m.group(2).strip()]
        j = i + 1
        while j < len(ls) and ls[j].strip() and not ls[j].strip().startswith("["):
            parts.append(ls[j].strip())
            j += 1
        value = " ".join(p for p in parts if p).strip()
        value = re.sub(r"^[oO]\s*\.\s*", "", value).strip()
        if value not in EMPTY_VALUES:
            out.append((tag, value))
        i = j
    return out


def out_time(order_memo: str | None, resv_memo: str | None) -> str | None:
    for ln in lines_of(order_memo):
        m = OUT_TIME.search(ln)
        if m:
            v = m.group(1).strip()
            if v not in EMPTY_VALUES:
                return v
            break
    for ln in leading_flag_lines(resv_memo) + lines_of(resv_memo)[:3]:
        if OUT_HINT.search(ln):
            return ln.strip().strip("*★ ").strip()
    return None


def order_lines(order_memo: str | None) -> tuple[list[str], str | None]:
    """② 오늘 오더 — 번호 줄 · `*` 한 개로 시작하는 지시 줄 · 마취 줄. (줄들, 접힘 때 보일 마취 줄)."""
    flags = set(leading_flag_lines(order_memo))
    out: list[str] = []
    anesthesia = None
    for ln in lines_of(order_memo):
        s = ln.strip()
        if not s or s in flags or OUT_TIME.search(s) or TAG_LINE.match(s) or is_empty_form(s):
            continue
        is_anes = "마취" in s
        if NUMBERED.match(s) or (s.startswith("*") and not s.startswith("**")) or is_anes:
            out.append(s)
            if is_anes and anesthesia is None:
                anesthesia = s
        elif out and not s.startswith(("0.", "[", "(")) and not NUMBERED.match(s) and out[-1].startswith("*"):
            out.append(s)  # `*` 지시 줄이 다음 줄로 이어진 경우
    return out, anesthesia


def consult_summary(consult_memo: str | None) -> list[str]:
    top, _ = split_consult(consult_memo)
    return [ln.strip() for ln in top if ln.strip() and ln.strip() != "[상담내용]" and not is_empty_form(ln)]


def other_clinic_history(consult_memo: str | None) -> list[str]:
    top = consult_summary(consult_memo)
    out = []
    for ln in top:
        m = HISTORY_LINE.match(ln)
        if m and m.group(2).strip() and m.group(2).strip() not in EMPTY_VALUES:
            out.append(ln)
    if not out:
        out = [ln for ln in top if HISTORY_SENTENCE.search(ln)]
    return out


def companions(resv_memo: str | None) -> str | None:
    for ln in lines_of(resv_memo):
        m = re.search(r"동행\s*\d+\s*명[^/\n]*", ln)
        if m:
            return m.group(0).strip()
    for ln in lines_of(resv_memo):
        s = ln.strip().lstrip("*").strip()
        if "동행" in s and len(s) <= 40:
            return s
    return None
