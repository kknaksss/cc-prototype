"""Soniox STT 토큰 → 발화 단위 자막(SPEC-001 §7.1 · interpret-ws-contract).

- 한 발화 = `<end>`(발화 끝 감지) 또는 `<fin>`(수동 확정) 토큰까지.
  실물 확인: 번역 토큰은 원문 토큰 사이사이에 오고 `<end>` 전에 끝난다
- 메시지마다 final 토큰은 쌓고, non-final 토큰은 그 메시지 것으로 갈아 끼운다(Soniox 실시간 규칙)
- side = 원문 언어가 ko 면 me, 아니면 them
- traditional 이면 자막의 중국어(원문 · 번역)만 번체로. TTS 로 보낼 번역문은 간체 그대로
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from app.service.interpret.chinese import to_traditional

END_TOKENS = {"<end>", "<fin>"}

# 띄어쓰기 없는 문자 — CJK 한자 · 가나 · 태국 문자 · 전각 구두점(CJK 기호 · 전각형)
_NO_SPACE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\u31f0-\u31ff\u0e00-\u0e7f\u3000-\u303f\uff00-\uffef"
_INNER_SPACE = re.compile(rf"(?<=[{_NO_SPACE}])[ \t\u3000]+(?=[{_NO_SPACE}])")
SQUEEZE_LANGS = {"zh", "ja", "th"}


def squeeze_spaces(text: str, lang: str | None) -> str:
    """zh · ja · th 문장 속, 양옆이 띄어쓰기 없는 문자인 빈칸만 지운다(영문 · 숫자 옆 빈칸은 둔다)."""
    return _INNER_SPACE.sub("", text) if lang in SQUEEZE_LANGS else text


@dataclass
class Utterance:
    """확정된 발화 — TTS 로 보낼 번역문(간체 원문 그대로)과 그 언어."""

    id: str
    text: str
    language: str | None


@dataclass
class _Current:
    final_o: list[str] = field(default_factory=list)
    final_t: list[str] = field(default_factory=list)
    nf_o: list[str] = field(default_factory=list)
    nf_t: list[str] = field(default_factory=list)
    o_langs: Counter = field(default_factory=Counter)
    t_langs: Counter = field(default_factory=Counter)

    def empty(self) -> bool:
        return not "".join(self.final_o + self.final_t + self.nf_o + self.nf_t).strip()


class CaptionAssembler:
    def __init__(self, traditional: bool = False):
        self.traditional = traditional
        self.n = 0
        self.cur = _Current()
        self.cur_id: str | None = None
        self.last_sent: dict | None = None

    def feed(self, tokens: list[dict]) -> tuple[list[dict], list[Utterance]]:
        """한 STT 메시지의 토큰들 → (보낼 caption 들, 확정된 발화들)."""
        captions: list[dict] = []
        done: list[Utterance] = []
        self.cur.nf_o, self.cur.nf_t = [], []
        for tk in tokens:
            text = tk.get("text", "")
            if text in END_TOKENS:
                if tk.get("is_final", True):
                    self._close(captions, done)
                continue
            is_tr = tk.get("translation_status") == "translation"
            lang = tk.get("language")
            if lang:
                (self.cur.t_langs if is_tr else self.cur.o_langs)[lang] += 1
            if tk.get("is_final"):
                (self.cur.final_t if is_tr else self.cur.final_o).append(text)
            else:
                (self.cur.nf_t if is_tr else self.cur.nf_o).append(text)
        if not self.cur.empty():
            cap = self._caption(final=False)
            if cap != self.last_sent:
                captions.append(cap)
                self.last_sent = cap
        return captions, done

    def flush(self) -> tuple[list[dict], list[Utterance]]:
        """연결을 끝낼 때 남은 발화를 확정한다."""
        captions: list[dict] = []
        done: list[Utterance] = []
        self.cur.nf_o, self.cur.nf_t = [], []
        self._close(captions, done)
        return captions, done

    # ──
    def _id(self) -> str:
        if self.cur_id is None:
            self.n += 1
            self.cur_id = f"u{self.n}"
        return self.cur_id

    def _langs(self) -> tuple[str | None, str | None]:
        o = self.cur.o_langs.most_common(1)[0][0] if self.cur.o_langs else None
        t = self.cur.t_langs.most_common(1)[0][0] if self.cur.t_langs else None
        return o, t

    def _side(self) -> str:
        o, t = self._langs()
        if o:
            return "me" if o == "ko" else "them"
        if t:  # 원문 언어 태그가 없으면 번역 언어의 반대편
            return "them" if t == "ko" else "me"
        return "me"

    def _show(self, text: str, lang: str | None) -> str:
        text = squeeze_spaces(text.strip(), lang)
        return to_traditional(text) if self.traditional and lang == "zh" else text

    def _caption(self, final: bool) -> dict:
        o, t = self._langs()
        original = "".join(self.cur.final_o + ([] if final else self.cur.nf_o))
        translation = "".join(self.cur.final_t + ([] if final else self.cur.nf_t))
        return {"type": "caption", "id": self._id(), "side": self._side(),
                "original": self._show(original, o), "translation": self._show(translation, t), "final": final}

    def _close(self, captions: list[dict], done: list[Utterance]) -> None:
        if self.cur.empty():
            self.cur, self.cur_id, self.last_sent = _Current(), None, None
            return
        cap = self._caption(final=True)
        captions.append(cap)
        _, t = self._langs()
        text = squeeze_spaces("".join(self.cur.final_t).strip(), t)
        if text:
            done.append(Utterance(id=cap["id"], text=text, language=t))
        self.cur, self.cur_id, self.last_sent = _Current(), None, None
