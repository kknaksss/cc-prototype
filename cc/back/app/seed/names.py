"""이름 치환(DEC-002 D-09 · SPEC-001 §4.1-2).

- 고객마다 가짜 이름 하나(고객 id 로 결정적). KR 은 한글, 그 밖은 로마자 대문자. 캡처의 실제 고객 이름과 겹치면 다시 고른다
- 메모 본문 속 고객 · 동행인 이름(로마자 · 「이름 :」 줄 · 한글 음역)을 가짜 이름으로 바꾼다
- 직원 · 유입처 이름은 다른 날 고객과 같아도 바꾸지 않는다 → 한글 이름은 그날 고객 것만 치환한다
- 메모 속 전화번호는 010-****-**** 꼴로
"""

import hashlib
import re
from collections.abc import Iterable

KR_SURNAMES = list("김이박최정강조윤장임한오서신권황안송류홍")
KR_GIVEN = [
    "서연", "민준", "지우", "하은", "도윤", "수아", "예린", "지호", "유나", "시우", "다은", "현우", "채원", "준서",
    "소율", "은우", "지안", "하린", "태윤", "나은", "서진", "윤아", "가온", "도현", "세아", "주원", "라희", "건우",
]
ZH_SURNAMES = [
    "LIN", "WANG", "ZHANG", "LIU", "YANG", "ZHAO", "WU", "ZHOU", "XU", "MA", "ZHU", "GUO", "GAO", "LUO",
    "LIANG", "XIE", "SONG", "TANG", "FENG", "DENG", "CAO", "PENG", "ZENG", "XIAO", "LU", "PAN", "DU", "WEI",
]
ZH_SYLLABLES = [
    "MEI", "LING", "XIN", "TING", "JIA", "HUI", "AN", "QING", "FANG", "LAN", "NA", "JING", "XIAO", "RU",
    "SHAN", "YUN", "HAO", "MING", "ZHI", "LI", "XUE", "YING", "QIAN", "PEI", "WEN", "ROU", "SI", "YUE",
]
JP_SURNAMES = ["SATO", "SUZUKI", "TAKAHASHI", "TANAKA", "WATANABE", "ITO", "YAMAMOTO", "NAKAMURA", "KOBAYASHI", "KATO"]
JP_GIVEN = ["YUKI", "AOI", "HINA", "SAKURA", "MIO", "RIN", "YUI", "NANA", "EMI", "MAI", "SAKI", "MOMO"]
TH_GIVEN = ["ARIYA", "PIMCHANOK", "NARIN", "KANYA", "SUDA", "MALAI", "PRANEE", "SIRIPORN", "WANIDA", "RATANA"]
TH_SURNAMES = ["SRISUK", "CHAIYAPORN", "WONGSA", "BOONMA", "KAEWKAM", "THONGDEE", "SAELIM", "PHROMMA"]
EN_GIVEN = ["EMMA", "OLIVIA", "CHLOE", "SOPHIA", "MIA", "CLAIRE", "LUCY", "GRACE", "ANNA", "JULIA", "NORA", "ELLA"]
EN_SURNAMES = ["MILLER", "MARTIN", "BROWN", "DAVIS", "MOORE", "TAYLOR", "CLARK", "WALKER", "ADAMS", "BAKER"]

HANGUL = re.compile(r"[가-힣]")
LATIN_TOKEN = re.compile(r"[A-Za-z]+")
PREFIX = re.compile(r"^\s*[\[(][A-Za-z]{2}[\])]\s*")
NAME_SEP = r"[\s,\-.]*"

# 메모의 대문자 로마자 연속 중 이름이 아닌 것(시술 · 양식 낱말)
NON_NAME_TOKENS = {
    "OUT", "TIME", "ROOM", "NO", "BBL", "LDM", "CP", "IV", "BTX", "SV", "OK", "KJ", "CC", "DR", "ICU", "FLX",
    "SHOT", "UNIT", "PULSE", "CO", "TW", "CN", "HK", "JP", "KR", "US", "TH", "FR", "PH", "IN", "VIP", "SNS",
    "LED", "HB", "SC", "ECM", "SYR", "RE", "FACE", "PRP", "PDRN", "LINE", "ID", "TOX", "DNA", "AI",
}


def normalize(name: str) -> str:
    """대조용 — 접두([TW]) · 공백 · 쉼표 · 하이픈 · 점 제거, 대문자."""
    return re.sub(r"[\s,\-.·]", "", PREFIX.sub("", name or "")).upper()


def strip_prefix(name: str) -> str:
    return PREFIX.sub("", name or "").strip()


def _digest(key: str, salt: int) -> int:
    return int(hashlib.sha256(f"{key}:{salt}".encode()).hexdigest(), 16)


def _candidate(nationality: str, h: int) -> str:
    def pick(xs: list[str], k: int) -> str:
        return xs[(h >> (k * 8)) % len(xs)]

    if nationality == "KR":
        return pick(KR_SURNAMES, 0) + pick(KR_GIVEN, 1)
    if nationality in ("TW", "CN", "HK", ""):
        given = pick(ZH_SYLLABLES, 1) + ((" " + pick(ZH_SYLLABLES, 2)) if (h >> 40) % 3 else "")
        return f"{pick(ZH_SURNAMES, 0)} {given}"
    if nationality == "JP":
        return f"{pick(JP_SURNAMES, 0)} {pick(JP_GIVEN, 1)}"
    if nationality == "TH":
        return f"{pick(TH_GIVEN, 0)} {pick(TH_SURNAMES, 1)}"
    return f"{pick(EN_GIVEN, 0)} {pick(EN_SURNAMES, 1)}"


class FakeNames:
    """고객 id → 가짜 이름. 실제 이름(정규화)과 이미 쓴 가짜 이름은 피한다."""

    def __init__(self, real_names: Iterable[str]):
        self.real = {normalize(n) for n in real_names if n and normalize(n)}
        self.used: set[str] = set()
        self.by_key: dict[str, str] = {}

    def get(self, key: str, nationality: str) -> str:
        if key in self.by_key:
            return self.by_key[key]
        salt = 0
        while True:
            name = _candidate(nationality or "", _digest(key, salt))
            n = normalize(name)
            if n not in self.real and n not in self.used:
                break
            salt += 1
        self.used.add(n)
        self.by_key[key] = name
        return name


def latin_tokens(name: str) -> list[str]:
    return [t.upper() for t in LATIN_TOKEN.findall(strip_prefix(name))]


def latin_pattern(tokens: list[str]) -> re.Pattern:
    body = NAME_SEP.join(re.escape(t) for t in tokens)
    return re.compile(rf"(?<![A-Za-z]){body}(?![A-Za-z])", re.IGNORECASE)


def hangul_pattern(name: str) -> re.Pattern:
    chars = [ch for ch in name if not ch.isspace()]
    return re.compile(r"\s*".join(re.escape(ch) for ch in chars))


PHONE_PATTERNS = [
    re.compile(r"(?<![\d])\+?\d{1,3}[-\s]\d{2,4}[-\s]\d{3,4}[-\s]\d{4}(?!\d)"),
    re.compile(r"(?<![\d])\d{2,4}-\d{3,4}-\d{4}(?!\d)"),
    re.compile(r"(?<![\d.,])\d{10,12}(?![\d.,])"),
]
NAME_LINE = re.compile(r"(이름\s*:[ \t]*)([^\n]*?)(?=[ \t]*ROOM\b|[ \t]*$)", re.MULTILINE)
CAPS_RUN = re.compile(r"(?<![A-Za-z])[A-Z]{2,}(?:[ \t,\-]+[A-Z]{2,})+(?![A-Za-z])")


class Person:
    """치환 대상 고객 한 명 — 이름 꼴들."""

    def __init__(self, key: str, fake: str, names: Iterable[str], same_day: bool):
        self.key = key
        self.fake = fake
        self.same_day = same_day
        self.latin: list[list[str]] = []
        self.hangul: list[str] = []
        for n in names:
            if not n or not n.strip():
                continue
            if HANGUL.search(n):
                h = re.sub(r"\s+", " ", n.strip())
                if len(h.replace(" ", "")) >= 2:
                    self.hangul.append(h)
            else:
                toks = latin_tokens(n)
                if toks:
                    self.latin.append(toks)


class MemoScrubber:
    """메모 본문 치환기. 한 번 만들고 일정마다 `scrub(text, own)` 을 부른다."""

    def __init__(self, people: list[Person], fallback: FakeNames):
        self.people = people
        self.fallback = fallback
        self.name_tokens = {t for p in people for toks in p.latin for t in toks}
        rules: list[tuple[int, re.Pattern, Person]] = []
        for p in people:
            for toks in p.latin:
                # 한 낱말 로마자 이름은 오탐이 커서 4자 이상만
                if len(toks) >= 2 or len(toks[0]) >= 4:
                    rules.append((len("".join(toks)), latin_pattern(toks), p))
            if p.same_day:
                for h in p.hangul:
                    rules.append((len(h), hangul_pattern(h), p))
        rules.sort(key=lambda r: -r[0])
        self.rules = rules

    def scrub(self, text: str | None, own: Person) -> str:
        if not text:
            return text or ""
        slots: list[str] = []

        def hold(fake: str) -> str:
            slots.append(fake)
            return f"\x00{len(slots) - 1}\x00"

        out = text
        for _, pat, p in self.rules:
            out = pat.sub(lambda _m, p=p: hold(p.fake), out)
        # 「이름 :」 줄의 값 = 그 메모 주인
        out = NAME_LINE.sub(lambda m: m.group(1) + (hold(own.fake) if m.group(2).strip() and "\x00" not in m.group(2)
                                                     else m.group(2)), out)
        # 남은 대문자 로마자 연속 — 고객 이름 낱말로만 이뤄졌으면 동행인 이름으로 본다
        out = CAPS_RUN.sub(lambda m: self._caps(m.group(0), hold), out)
        for pat in PHONE_PATTERNS:
            out = pat.sub("010-****-****", out)
        return re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], out)

    def _caps(self, run: str, hold) -> str:
        toks = LATIN_TOKEN.findall(run)
        if any(t in NON_NAME_TOKENS for t in toks) or not all(t in self.name_tokens for t in toks):
            return run
        for p in self.people:
            for full in p.latin:
                for i in range(len(full) - len(toks) + 1):
                    if full[i:i + len(toks)] == toks:
                        return hold(p.fake)
        return hold(self.fallback.get("companion:" + normalize(run), "TW"))
