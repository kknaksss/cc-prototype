"""procedure 로 복사(SPEC-004 §4.1) — 원본 cc/back tests/test_interpret.py + §4.2 WS 토큰 인증.

통역 중계 — 발화 묶기 · side · 번체 · 오류 코드 · WS 흐름(가짜 Soniox). 실물 호출 없음."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.container import build_container
from app.main import create_app
from app.service.interpret.assembler import CaptionAssembler
from app.service.interpret.session import BadStart, InterpretSession, parse_start
from app.service.interpret.soniox import stt_config, tts_config
from tests.conftest import ADMIN, make_settings


def tk(text, final=True, status="original", lang="ko"):
    return {"text": text, "is_final": final, "translation_status": status, "language": lang}


# ── 발화 묶기 · side · 번체 ──


def test_groups_until_end_and_replaces_non_final():
    a = CaptionAssembler()
    caps, utts = a.feed([tk("안녕"), tk("하세", final=False)])
    assert caps == [{"type": "caption", "id": "u1", "side": "me", "original": "안녕하세", "translation": "", "final": False}]
    caps, utts = a.feed([tk("하세요"), tk("你好", status="translation", lang="zh"), tk("<end>", status="none", lang=None)])
    assert caps[-1] == {"type": "caption", "id": "u1", "side": "me", "original": "안녕하세요", "translation": "你好",
                        "final": True}
    assert [(u.id, u.text, u.language) for u in utts] == [("u1", "你好", "zh")]
    caps, _ = a.feed([tk("谢谢", lang="zh"), tk("감사", status="translation", lang="ko", final=False)])
    assert caps[0]["id"] == "u2" and caps[0]["side"] == "them"


def test_unchanged_caption_not_resent_and_empty_end_skipped():
    a = CaptionAssembler()
    assert a.feed([tk("<end>", status="none", lang=None)]) == ([], [])
    caps1, _ = a.feed([tk("네", final=False)])
    caps2, _ = a.feed([tk("네", final=False)])
    assert caps1 and caps2 == []


def test_traditional_only_for_chinese_caption_tts_stays_simplified():
    a = CaptionAssembler(traditional=True)
    caps, utts = a.feed([tk("麻醉药膏", lang="zh"), tk("마취 연고", status="translation", lang="ko"), tk("<end>", lang=None)])
    assert caps[-1]["original"] == "麻醉藥膏" and caps[-1]["translation"] == "마취 연고" and caps[-1]["side"] == "them"
    caps, utts = a.feed([tk("시간"), tk("时间", status="translation", lang="zh"), tk("<fin>", lang=None)])
    assert caps[-1]["translation"] == "時間"
    assert utts[0].text == "时间"  # TTS 에는 간체


def test_flush_closes_open_utterance():
    a = CaptionAssembler()
    a.feed([tk("잠깐"), tk("等一下", status="translation", lang="zh")])
    caps, utts = a.flush()
    assert caps[-1]["final"] is True and utts[0].text == "等一下"


# ── start 검사 · 설정 ──


@pytest.mark.parametrize("kind,value", [
    ("bytes", b"\x00"), ("text", "nope"), ("text", '{"type":"pause"}'), ("text", '{"type":"start","lang":"ko"}'),
    ("text", '{"type":"start","lang":"zh","traditional":"y"}'),
])
def test_bad_start(kind, value):
    with pytest.raises(BadStart):
        parse_start(kind, value)


def test_configs():
    c = stt_config("zh")
    assert c["audio_format"] == "pcm_s16le" and c["sample_rate"] == 16000 and c["num_channels"] == 1
    assert c["translation"] == {"type": "two_way", "language_a": "ko", "language_b": "zh"}
    t = tts_config("u1", "ko")
    assert t["model"] == "tts-rt-v2" and t["audio_format"] == "pcm_s16le" and t["sample_rate"] == 24000


# ── WS 흐름(가짜 Soniox) ──


class FakeStt:
    instances: list["FakeStt"] = []

    def __init__(self):
        self.q: asyncio.Queue = asyncio.Queue()
        self.audio = 0
        self.closed = False
        FakeStt.instances.append(self)

    async def send_audio(self, chunk):
        self.audio += len(chunk)
        if self.audio == len(chunk):  # 첫 조각에 발화 하나를 돌려준다
            self.q.put_nowait({"tokens": [tk("안녕", final=False)]})
            self.q.put_nowait({"tokens": [tk("안녕하세요"), tk("您好", status="translation", lang="zh"),
                                          tk("<end>", status="none", lang=None)]})

    async def keepalive(self):
        pass

    async def finalize(self):
        pass

    async def end(self):
        self.q.put_nowait({"tokens": [], "finished": True})

    async def messages(self):
        while True:
            m = await self.q.get()
            yield m
            if m.get("finished"):
                return

    async def close(self):
        self.closed = True


class FakeTts:
    instances: list["FakeTts"] = []

    def __init__(self):
        self.closed = False
        self.spoken: list[tuple[str, str]] = []
        FakeTts.instances.append(self)

    async def speak(self, stream_id, language, text):
        self.spoken.append((language, text))
        yield b"\x01\x02" * 10
        yield b"\x03\x04" * 10

    async def keepalive(self):
        pass

    async def close(self):
        self.closed = True


FRONT = "http://localhost:3600"


@pytest.fixture
def ws_app(tmp_path):
    def make(key="test-key", fail=False):
        settings = make_settings(tmp_path, soniox_api_key=key, proc_front_origin=FRONT)
        c = build_container(settings)

        async def open_stt(api_key, lang):
            if fail:
                raise OSError("down")
            return FakeStt()

        async def open_tts(api_key):
            return FakeTts()

        c.open_stt, c.open_tts = open_stt, open_tts
        FakeStt.instances.clear()
        FakeTts.instances.clear()
        client = TestClient(create_app(settings, c))
        client.token = client.post("/api/auth/login", json=ADMIN).json()["token"]
        client.bearer = {"Authorization": f"Bearer {client.token}"}
        return client

    return make


START = {"type": "start", "lang": "zh", "scheduleId": "s1", "traditional": True}


def test_full_flow(ws_app):
    client = ws_app()
    with client.websocket_connect("/api/interpret", headers={"origin": FRONT, **client.bearer}) as ws:
        ws.send_json(START)
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(b"\x00\x00" * 800)
        first = ws.receive_json()
        assert first["type"] == "caption" and first["final"] is False and first["side"] == "me"
        final = ws.receive_json()
        assert final == {"type": "caption", "id": "u1", "side": "me", "original": "안녕하세요", "translation": "您好",
                         "final": True}
        assert ws.receive_json() == {"type": "audio_start", "id": "u1", "sampleRate": 24000}
        audio = ws.receive_bytes() + ws.receive_bytes()
        assert len(audio) == 40
        assert ws.receive_json() == {"type": "audio_end", "id": "u1"}
        ws.send_json({"type": "pause"})
        ws.send_json({"type": "resume"})
        ws.send_json({"type": "stop"})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert FakeTts.instances[0].spoken == [("zh", "您好")]  # TTS 에는 간체
    assert FakeStt.instances[0].closed and FakeTts.instances[0].closed  # Soniox 연결 정리


def test_client_close_cleans_up():
    """브라우저가 stop 없이 닫아도 Soniox 두 연결을 닫는다(TTS 동시 한도 3)."""

    class Gone:
        def __init__(self):
            self.frames = [("text", json.dumps(START)), ("close", None)]
            self.sent: list = []

        async def receive(self):
            await asyncio.sleep(0)
            return self.frames.pop(0)

        async def send_json(self, data):
            self.sent.append(data)

        async def send_bytes(self, data):
            self.sent.append(data)

        async def close(self, code=1000):
            pass

    async def open_stt(k, lang):
        return FakeStt()

    async def open_tts(k):
        return FakeTts()

    FakeStt.instances.clear()
    FakeTts.instances.clear()
    client = Gone()
    asyncio.run(asyncio.wait_for(InterpretSession(client, "k", open_stt, open_tts).run(), 5))
    assert client.sent == [{"type": "ready"}]
    assert FakeStt.instances[0].closed and FakeTts.instances[0].closed


@pytest.mark.parametrize("key,fail,start,code", [
    ("", False, START, "no_api_key"),
    ("k", True, START, "soniox_unavailable"),
    ("k", False, {"type": "start", "lang": "xx"}, "bad_request"),
])
def test_error_codes(ws_app, key, fail, start, code):
    client = ws_app(key=key, fail=fail)
    with client.websocket_connect("/api/interpret", headers=client.bearer) as ws:
        ws.send_json(start)
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == code and msg["message"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_other_origin_rejected(ws_app):
    client = ws_app()
    headers = {"origin": "http://evil.example", **client.bearer}
    with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect("/api/interpret", headers=headers):
        pass
    assert e.value.code == 1008


# ── SPEC-004 §4.2: WS 토큰 인증(accept 전 검증 · 실패면 핸드셰이크 거절) ──


@pytest.mark.parametrize("headers,path", [
    ({}, "/api/interpret"),  # 토큰 없음
    ({"Authorization": "Bearer nope.sig"}, "/api/interpret"),  # 틀린 토큰
    ({}, "/api/interpret?token=nope.sig"),  # 틀린 쿼리 토큰
    ({"origin": FRONT}, "/api/interpret"),  # 허용 출처여도 토큰 없으면 거절
])
def test_ws_rejects_without_valid_token(ws_app, headers, path):
    client = ws_app()
    with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect(path, headers=headers):
        pass
    assert e.value.code == 1008
    assert FakeStt.instances == [] and FakeTts.instances == []  # Soniox 연결(키 소모) 없음


@pytest.mark.parametrize("how", ["header", "query", "header_with_front_origin"])
def test_ws_accepts_valid_token(ws_app, how):
    client = ws_app()
    if how == "query":
        path, headers = f"/api/interpret?token={client.token}", {}
    else:
        path, headers = "/api/interpret", dict(client.bearer)
        if how == "header_with_front_origin":
            headers["origin"] = FRONT
    with client.websocket_connect(path, headers=headers) as ws:  # Origin 없음(앱) + 토큰 = 통과
        ws.send_json(START)
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "stop"})


# ── fix1: zh · ja · th 문장 속 빈칸 ──


@pytest.mark.parametrize("lang,raw,want", [
    ("zh", "今天在治疗前 我会先涂麻醉膏 然后请您等大约20分钟。", "今天在治疗前我会先涂麻醉膏然后请您等大约20分钟。"),
    ("zh", "打 20 分钟 针", "打 20 分钟针"),  # 숫자 옆 빈칸은 둔다
    ("zh", "先做 BBL 然后", "先做 BBL 然后"),
    ("zh", "好的， 我知道了", "好的，我知道了"),  # 전각 구두점 옆
    ("ja", "こんにちは 今日は よろしく", "こんにちは今日はよろしく"),
    ("th", "สวัสดี ค่ะ", "สวัสดีค่ะ"),
    ("ko", "오늘 시술 전에", "오늘 시술 전에"),  # 한국어는 그대로
    ("en", "hello there", "hello there"),
])
def test_squeeze_spaces(lang, raw, want):
    from app.service.interpret.assembler import squeeze_spaces

    assert squeeze_spaces(raw, lang) == want


def test_squeeze_applies_to_caption_and_tts_and_traditional_order_independent():
    from app.service.interpret.assembler import squeeze_spaces
    from app.service.interpret.chinese import to_traditional

    a = CaptionAssembler(traditional=True)
    caps, utts = a.feed([tk("시간"), tk("治疗前", status="translation", lang="zh"), tk(" 我会", status="translation", lang="zh"),
                         tk("<end>", lang=None)])
    assert caps[-1]["translation"] == "治療前我會"
    assert utts[0].text == "治疗前我会"  # TTS 텍스트도 빈칸 없음 · 간체
    raw = "治疗前 我会先涂 麻醉膏"
    assert to_traditional(squeeze_spaces(raw, "zh")) == squeeze_spaces(to_traditional(raw), "zh")
