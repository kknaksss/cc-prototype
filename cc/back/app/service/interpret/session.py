"""통역 세션 하나 — 브라우저 WS ↔ Soniox STT(two_way) · TTS 중계(SPEC-001 §7 · interpret-ws-contract).

브라우저 → back: start(첫 프레임) · PCM s16le 16kHz mono 바이너리 · pause/resume · stop
back → 브라우저: ready · caption · audio_start · PCM 바이너리 · audio_end · error
끝나면(닫기 · stop · 오류) Soniox 두 연결을 반드시 닫는다(TTS 동시 한도 3).
"""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.service.interpret.assembler import CaptionAssembler, Utterance
from app.service.interpret.soniox import TTS_SAMPLE_RATE, SonioxError, SttConn, TtsConn

log = logging.getLogger(__name__)

# SPEC-001 §7.2 — 모달에서 고를 수 있는 언어
LANGS = {"zh", "en", "ja", "th", "fr", "es", "tl", "hi"}
START_TIMEOUT = 10.0
STOP_DRAIN = 3.0
KEEPALIVE_EVERY = 10.0
TTS_KEEPALIVE_EVERY = 20.0


class BadStart(Exception):
    pass


class Client(Protocol):
    async def receive(self) -> tuple[str, str | bytes | None]: ...  # ("text"|"bytes"|"close", 값)
    async def send_json(self, data: dict) -> None: ...
    async def send_bytes(self, data: bytes) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


OpenStt = Callable[[str, str], Awaitable[SttConn]]
OpenTts = Callable[[str], Awaitable[TtsConn]]


def parse_start(kind: str, value) -> dict:
    if kind != "text":
        raise BadStart("첫 프레임은 start 텍스트여야 해요")
    try:
        msg = json.loads(value)
    except (TypeError, ValueError) as e:
        raise BadStart("start 가 JSON 이 아니에요") from e
    if not isinstance(msg, dict) or msg.get("type") != "start":
        raise BadStart("첫 프레임은 {type: start} 여야 해요")
    lang = msg.get("lang")
    if lang not in LANGS:
        raise BadStart(f"지원하지 않는 언어예요: {lang!r} (가능: {', '.join(sorted(LANGS))})")
    trad = msg.get("traditional", False)
    if not isinstance(trad, bool):
        raise BadStart("traditional 은 true/false 여야 해요")
    return {"lang": lang, "traditional": trad, "scheduleId": msg.get("scheduleId")}


class InterpretSession:
    def __init__(self, client: Client, api_key: str, open_stt: OpenStt, open_tts: OpenTts):
        self.client = client
        self.api_key = api_key
        self.open_stt = open_stt
        self.open_tts = open_tts
        self.stt: SttConn | None = None
        self.tts: TtsConn | None = None
        self.paused = False
        self.stopping = False
        self.closed = False
        self.speaking = False
        self.last_audio = time.monotonic()
        self.last_tts = time.monotonic()
        self.queue: asyncio.Queue[Utterance] = asyncio.Queue()
        self._send_lock = asyncio.Lock()

    async def _send(self, data: dict | bytes) -> None:
        if self.closed:
            return
        async with self._send_lock:
            if isinstance(data, bytes):
                await self.client.send_bytes(data)
            else:
                await self.client.send_json(data)

    async def _error(self, code: str, message: str) -> None:
        with contextlib.suppress(Exception):
            await self._send({"type": "error", "code": code, "message": message})

    async def run(self) -> None:
        try:
            try:
                kind, value = await asyncio.wait_for(self.client.receive(), START_TIMEOUT)
                if kind == "close":
                    return
                start = parse_start(kind, value)
            except (BadStart, TimeoutError) as e:
                await self._error("bad_request", str(e) or "start 를 받지 못했어요")
                return
            if not self.api_key:
                await self._error("no_api_key", "SONIOX_API_KEY 가 cc/back/.env 에 없어요")
                return
            try:
                self.stt = await self.open_stt(self.api_key, start["lang"])
                self.tts = await self.open_tts(self.api_key)
            except Exception as e:  # 연결 실패 · 인증 실패
                log.warning("soniox connect failed: %s", type(e).__name__)
                await self._error("soniox_unavailable", "통역 서버(Soniox)에 연결하지 못했어요")
                return
            await self._send({"type": "ready"})
            await self._pump(CaptionAssembler(traditional=start["traditional"]))
        finally:
            await self._cleanup()

    async def _pump(self, asm: CaptionAssembler) -> None:
        reader = asyncio.create_task(self._client_reader())
        stt = asyncio.create_task(self._stt_reader(asm))
        tts = asyncio.create_task(self._tts_worker())
        keep = asyncio.create_task(self._keepalive())
        try:
            done, _ = await asyncio.wait({reader, stt, tts}, return_when=asyncio.FIRST_COMPLETED)
            if reader in done and self.stopping and not stt.done():
                # stop — Soniox 가 남은 토큰을 내고 finished 할 때까지 잠깐 기다린다
                with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(stt), STOP_DRAIN)
            for t in (reader, stt, tts):
                if t.done() and not t.cancelled() and t.exception():
                    raise t.exception()
        except SonioxError as e:
            log.warning("soniox error: %s", e)
            await self._error("soniox_unavailable", "통역 서버(Soniox) 오류로 끊겼어요")
        except Exception as e:
            log.warning("interpret relay error: %s", type(e).__name__)
            await self._error("soniox_unavailable", "통역 중계가 끊겼어요")
        finally:
            for t in (reader, stt, tts, keep):
                t.cancel()
            await asyncio.gather(reader, stt, tts, keep, return_exceptions=True)

    async def _client_reader(self) -> None:
        while True:
            kind, value = await self.client.receive()
            if kind == "close":
                self.closed = True
                return
            if kind == "bytes":
                if not self.paused and value:
                    await self.stt.send_audio(value)
                    self.last_audio = time.monotonic()
                continue
            try:
                msg = json.loads(value)
            except (TypeError, ValueError):
                await self._error("bad_request", "알 수 없는 텍스트 프레임이에요")
                continue
            typ = msg.get("type") if isinstance(msg, dict) else None
            if typ == "pause":
                if not self.paused:
                    self.paused = True
                    await self.stt.finalize()  # 말하던 것을 확정해 자막 · 음성으로 내보낸다
            elif typ == "resume":
                self.paused = False
            elif typ == "stop":
                self.stopping = True
                await self.stt.end()
                return
            else:
                await self._error("bad_request", f"알 수 없는 type: {typ!r}")

    async def _stt_reader(self, asm: CaptionAssembler) -> None:
        async for msg in self.stt.messages():
            captions, utts = asm.feed(msg.get("tokens") or [])
            await self._emit(captions, utts)
        captions, utts = asm.flush()
        await self._emit(captions, utts)
        if not self.stopping and not self.closed:
            raise SonioxError("STT 연결이 끝났어요")

    async def _emit(self, captions: list[dict], utts: list[Utterance]) -> None:
        for c in captions:
            await self._send(c)
        for u in utts:
            if u.language and not self.stopping:
                self.queue.put_nowait(u)

    async def _tts_worker(self) -> None:
        while True:
            u = await self.queue.get()
            self.speaking = True
            try:
                await self._send({"type": "audio_start", "id": u.id, "sampleRate": TTS_SAMPLE_RATE})
                async for chunk in self.tts.speak(u.id, u.language, u.text):
                    await self._send(chunk)
                await self._send({"type": "audio_end", "id": u.id})
            finally:
                self.speaking = False
                self.last_tts = time.monotonic()

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(KEEPALIVE_EVERY)
            now = time.monotonic()
            with contextlib.suppress(Exception):
                if now - self.last_audio >= KEEPALIVE_EVERY:
                    await self.stt.keepalive()  # 멈춤 중에도 40초 idle 로 끊기지 않게
                if not self.speaking and now - self.last_tts >= TTS_KEEPALIVE_EVERY:
                    await self.tts.keepalive()
                    self.last_tts = now

    async def _cleanup(self) -> None:
        for conn in (self.stt, self.tts):
            if conn is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(conn.close(), 3)
        self.stt = self.tts = None
        if not self.closed:
            self.closed = True
            with contextlib.suppress(Exception):
                await self.client.close()
