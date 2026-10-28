"""WORK-009 WP-BE4 — 문진 언어 표(SPEC-004 §6.15 ②). 불러오기 · 제출 · 이력은 고객 문진 웹(SPEC-006)으로 옮김 → test_app_qweb.py ·
unlock · 직원 문진 경로는 없앰(SPEC-006 §6.2)."""


import pytest

from app.domain import languages

LOGINS = dict(ccc_coord_id="coord1", ccc_coord_password="pw", ccc_admin_id="admin1", ccc_admin_password="pw",
              proc_session_secret="s", proc_bcrypt_rounds=4)


# ------------------------------------------------------------------ 언어 표(§6.15 ②)
@pytest.mark.parametrize("language,nationality,want", [
    ("zh-CN", "KR", ("zh-Hans", "kos_language")),
    ("zh-yue", None, ("zh-Hant", "kos_language")),
    ("", "TW", ("zh-Hant", "nationality")),
    ("", "HK", ("zh-Hant", "nationality")),
    ("", "VN", ("en", "default")),
    ("th", "TH", ("en", "kos_language")),  # th = 양식에 없음 → en
    ("", "TH", ("en", "nationality")),
    ("etc", "JP", ("ja", "nationality")),  # etc = 없음 → 국적
    ("ja", "CN", ("ja", "kos_language")),
    (None, None, ("en", "default")),
    ("id", None, ("id", "kos_language")),
])
def test_questionnaire_language_table(language, nationality, want):
    assert languages.resolve(language, nationality) == want


def test_questionnaire_language_options_and_agreement_keys():
    assert languages.FORM_LANGS == ("ko", "ja", "zh-Hans", "zh-Hant", "en", "id")
    assert languages.AGREEMENT_KEY == {"ja": "ja", "en": "en", "zh-Hans": "zh", "zh-Hant": "zh"}
