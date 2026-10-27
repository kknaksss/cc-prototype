"""문진 언어 표(SPEC-004 §6.15 ② · D7-15 · D7-16) — 한 곳.

출처: KOS 웹앱 `reservation-client` · `purchase-client` 의 언어 결정 규칙(JS) — `orchestration/work/overall-board/
app-kos-report.md` §3.2 ~ §3.4. normalize(고객 language) → 없으면 국적 대응표 → 없으면 en → 양식 번역 6개에 없으면 en.
"""

# 양식(getVisitorQuestionnaire) 번역이 있는 6개 — 언어 칩 순서(AK§4)
FORM_LANGS = ("ko", "ja", "zh-Hans", "zh-Hant", "en", "id")
DEFAULT = "en"
# KOS 문서 언어 enum(17) — normalize 결과가 여기 없으면 없음(etc 등)
DOC_LANGS = frozenset(("ko", "ja", "zh-Hans", "zh-Hant", "en", "th", "es", "ru", "fr", "id", "ms", "vi", "mn", "uz", "nl",
                       "de", "pt"))
_NORMALIZE = {"zh-CN": "zh-Hans", "zh-yue": "zh-Hant"}
# fromNationality — KOS 웹앱 표 그대로(그 밖 나라 = 없음)
NATIONALITY = {"KR": "ko", "JP": "ja", "CN": "zh-Hans", "TW": "zh-Hant", "HK": "zh-Hant", "MO": "zh-Hant", "TH": "th",
               "ID": "id", "ES": "es", "RU": "ru", "FR": "fr", "DE": "de", "PT": "pt", "BR": "pt", "US": "en", "GB": "en",
               "AU": "en", "NZ": "en"}
# 동의 약관 번역 키(ja · en · zh — 간체 · 번체 구분 없음 · AK§3.4) — 그 밖은 원문
AGREEMENT_KEY = {"ja": "ja", "en": "en", "zh-Hans": "zh", "zh-Hant": "zh"}


def normalize(language: str | None) -> str | None:
    v = (language or "").strip()
    v = _NORMALIZE.get(v, v)
    return v if v in DOC_LANGS else None


def from_nationality(nationality: str | None) -> str | None:
    return NATIONALITY.get((nationality or "").strip().upper())


def resolve(language: str | None, nationality: str | None) -> tuple[str, str]:
    """(양식 언어, source) — source = kos_language | nationality | default."""
    picked, source = normalize(language), "kos_language"
    if picked is None:
        picked, source = from_nationality(nationality), "nationality"
    if picked is None:
        picked, source = DEFAULT, "default"
    return (picked if picked in FORM_LANGS else DEFAULT), source
