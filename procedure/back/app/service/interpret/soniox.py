"""Soniox 실시간 STT · TTS WebSocket 연결(D-27 back 중계). 키는 Authorization 헤더로만 — 출력 · 로그 금지.

프로토콜: https://soniox.com/docs/api-reference/stt/websocket-api · https://soniox.com/docs/api-reference/tts/websocket-api
"""

import base64
import json
from collections.abc import AsyncIterator
from typing import Protocol

import websockets

STT_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
TTS_URL = "wss://tts-rt.soniox.com/tts-websocket"
STT_MODEL = "stt-rt-v5"
TTS_MODEL = "tts-rt-v2"
# 음색 하나 고정(D-17). 실물 확인: Jiwoo 가 ko · zh 둘 다 STT 왕복으로 원문 그대로 읽혔다
TTS_VOICE = "Jiwoo"
TTS_SAMPLE_RATE = 24000
STT_SAMPLE_RATE = 16000
CONNECT_TIMEOUT = 10


class SonioxError(Exception):
    """연결 실패 · Soniox 가 보낸 오류."""


def stt_config(lang: str) -> dict:
    return {
        "model": STT_MODEL,
        "audio_format": "pcm_s16le",
        "sample_rate": STT_SAMPLE_RATE,
        "num_channels": 1,
        "language_hints": ["ko", lang],
        "enable_endpoint_detection": True,
        "max_endpoint_delay_ms": 1000,
        "translation": {"type": "two_way", "language_a": "ko", "language_b": lang},
    }


def tts_config(stream_id: str, language: str) -> dict:
    return {
        "model": TTS_MODEL,
        "language": language,
        "voice": TTS_VOICE,
        "audio_format": "pcm_s16le",
        "sample_rate": TTS_SAMPLE_RATE,
        "stream_id": stream_id,
    }


def _check(msg: dict) -> dict:
    if msg.get("error_code") or msg.get("error_type"):
        raise SonioxError(f"{msg.get('error_type', 'error')}: {msg.get('error_message', '')}")
    return msg


class SttConn(Protocol):
    async def send_audio(self, chunk: bytes) -> None: ...
    async def keepalive(self) -> None: ...
    async def finalize(self) -> None: ...
    async def end(self) -> None: ...
    def messages(self) -> AsyncIterator[dict]: ...
    async def close(self) -> None: ...


class TtsConn(Protocol):
    def speak(self, stream_id: str, language: str, text: str) -> AsyncIterator[bytes]: ...
    async def keepalive(self) -> None: ...
    async def close(self) -> None: ...


class SonioxStt:
    def __init__(self, ws):
        self.ws = ws

    @classmethod
    async def open(cls, api_key: str, lang: str) -> "SonioxStt":
        ws = await websockets.connect(STT_URL, additional_headers={"Authorization": f"Bearer {api_key}"},
                                      open_timeout=CONNECT_TIMEOUT, max_size=None)
        await ws.send(json.dumps(stt_config(lang)))
        return cls(ws)

    async def send_audio(self, chunk: bytes) -> None:
        await self.ws.send(chunk)

    async def keepalive(self) -> None:
        await self.ws.send(json.dumps({"type": "keepalive"}))

    async def finalize(self) -> None:
        await self.ws.send(json.dumps({"type": "finalize"}))

    async def end(self) -> None:
        await self.ws.send("")  # 정상 종료 — 남은 토큰 · finished 를 받고 Soniox 가 닫는다

    async def messages(self) -> AsyncIterator[dict]:
        async for raw in self.ws:
            msg = _check(json.loads(raw))
            yield msg
            if msg.get("finished"):
                return

    async def close(self) -> None:
        await self.ws.close()


class SonioxTts:
    def __init__(self, ws):
        self.ws = ws

    @classmethod
    async def open(cls, api_key: str) -> "SonioxTts":
        ws = await websockets.connect(TTS_URL, additional_headers={"Authorization": f"Bearer {api_key}"},
                                      open_timeout=CONNECT_TIMEOUT, max_size=None)
        return cls(ws)

    async def speak(self, stream_id: str, language: str, text: str) -> AsyncIterator[bytes]:
        """스트림 하나(발화 하나) — 설정 + 전문(text_end) → 오디오 조각들. 한 연결에서 한 번에 하나씩 부른다."""
        await self.ws.send(json.dumps(tts_config(stream_id, language)))
        await self.ws.send(json.dumps({"text": text, "text_end": True, "stream_id": stream_id}))
        async for raw in self.ws:
            msg = _check(json.loads(raw))
            if msg.get("stream_id") not in (None, stream_id):
                continue
            if msg.get("audio"):
                yield base64.b64decode(msg["audio"])
            if msg.get("terminated"):
                return

    async def cancel(self, stream_id: str) -> None:
        await self.ws.send(json.dumps({"stream_id": stream_id, "cancel": True}))

    async def keepalive(self) -> None:
        await self.ws.send("{}")

    async def close(self) -> None:
        await self.ws.close()
