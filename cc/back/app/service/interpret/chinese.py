"""간체 → 번체(자막 전용, SPEC-001 §7.2 · D-17).

실물 확인(2026-10-13): Soniox zh 전사 · 번역은 간체로 나온다(광둥어 발화도). TTS 는 번체를 넣어도 오류 없이 읽지만
발음이 깨진다 → TTS 에는 간체, 화면 자막만 번체. 대만 글꼴(s2tw) 하나로 TW · HK 둘 다 처리한다.
"""

from functools import lru_cache

from opencc import OpenCC


@lru_cache(maxsize=1)
def _converter() -> OpenCC:
    return OpenCC("s2tw")


def to_traditional(text: str) -> str:
    return _converter().convert(text) if text else text
